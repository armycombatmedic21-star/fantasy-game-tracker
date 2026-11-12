"""Win % spread check for the consensus engine (Nov 11 2026, Wes: "better win % for this weekend, don't wait a week").

The app widens each player's simulated range by his position's factor (fgt_model.SPREAD_POS, used by the app's
stretch()). Those factors were fit on Nov 9 to the OLD model. This re-fits them to projections like the new engine's:
Sleeper's projected stats for past weeks (Sleeper keeps them), run through our converter exactly like the engine,
compared with what each player really scored in this league's scoring (nflverse stats + play-by-play: yardage tiers per
game, TD points by length, INT -1, fumbles lost -1, 2-pt +2, return TDs 6; K by FG distance; DST points-allowed tiers,
sacks, INT, fumble recoveries, return TDs, safeties).

Per position: factor = sqrt(variance of real misses / average simulated variance). 1.0 = our simulated range is already
right; above 1 = real results spread wider than the simulation (needs widening).
Usage: python3 model/calib_spread.py --weeks 4-9 (needs internet to Sleeper; runs in GitHub Actions)
"""
import argparse, json, os, sys
import numpy as np
import polars as pl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nflreadpy as nfl
import fgt_model as M
import fetch_sources as S

TDL = lambda y: 12 if y >= 60 else 10 if y >= 50 else 8 if y >= 40 else 6


def tier1(y, T):
    return float(M.tier(np.array([float(y)]), T)[0])


def actuals(week, ps, pbp, sched):
    """(fold name, team, pos) -> real league points; ("DST", team) -> real D/ST points."""
    w = pbp.filter(pl.col("week") == week)
    tdp = {}
    for r in w.filter(pl.col("pass_touchdown") == 1).iter_rows(named=True):
        pts = TDL(r["yards_gained"] or 0)
        for pid in (r["passer_player_id"], r["receiver_player_id"]):
            if pid:
                tdp[pid] = tdp.get(pid, 0) + pts
    for r in w.filter(pl.col("rush_touchdown") == 1).iter_rows(named=True):
        if r["rusher_player_id"]:
            tdp[r["rusher_player_id"]] = tdp.get(r["rusher_player_id"], 0) + TDL(r["yards_gained"] or 0)
    out = {}
    g = lambda r, c: (r.get(c) or 0)
    for r in ps.filter(pl.col("week") == week).iter_rows(named=True):
        pos = "RB" if r["position"] == "FB" else r["position"]
        tm = M.ALIAS.get(r["team"], r["team"])
        if pos in ("QB", "RB", "WR", "TE"):
            p = tier1(g(r, "rushing_yards"), M.SKILL_TIERS) + tier1(g(r, "receiving_yards"), M.SKILL_TIERS)
            if pos == "QB" or g(r, "passing_yards") >= 75:
                p += tier1(g(r, "passing_yards"), M.PASS_TIERS)
            p += tdp.get(r["player_id"], 0) - g(r, "passing_interceptions")
            p -= g(r, "rushing_fumbles_lost") + g(r, "receiving_fumbles_lost") + g(r, "sack_fumbles_lost")
            p += 2 * (g(r, "passing_2pt_conversions") + g(r, "rushing_2pt_conversions") + g(r, "receiving_2pt_conversions"))
            p += 6 * g(r, "special_teams_tds")
        elif pos == "K":
            p = (3 * (g(r, "fg_made_0_19") + g(r, "fg_made_20_29") + g(r, "fg_made_30_39")) + 4 * g(r, "fg_made_40_49")
                 + 5 * (g(r, "fg_made_50_59") + g(r, "fg_made_60_")) + g(r, "pat_made"))
        else:
            continue
        out[(M.fold(r["player_display_name"]), tm, pos)] = p
    s = sched.filter((pl.col("week") == week) & (pl.col("game_type") == "REG"))
    for r in s.iter_rows(named=True):
        if r["home_score"] is None:
            continue
        for tm, opp_pts in ((r["home_team"], r["away_score"]), (r["away_team"], r["home_score"])):
            d = w.filter(pl.col("defteam") == tm)
            pa = opp_pts
            pa_pts = 15 if pa <= 0 else 9 if pa <= 7 else 6 if pa <= 17 else 3 if pa <= 24 else 0 if pa <= 29 else -3
            sk = int(d.filter(pl.col("sack") == 1).height)
            it = int(d.filter(pl.col("interception") == 1).height)
            fr = int(d.filter(pl.col("fumble_lost") == 1).height)
            sf = int(d.filter(pl.col("safety") == 1).height)
            rtd = int(w.filter((pl.col("return_touchdown") == 1) & (pl.col("td_team") == tm)).height)
            out[("DST", M.ALIAS.get(tm, tm))] = pa_pts + sk + it + fr + 2 * sf + 6 * rtd
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", default="4-9")
    ap.add_argument("--min", type=float, default=3.0)
    a = ap.parse_args()
    lo, hi = (int(x) for x in a.weeks.split("-"))
    ps = nfl.load_player_stats([M.SEASON]).filter(pl.col("season_type") == "REG")
    pbp = nfl.load_pbp([M.SEASON]).filter(pl.col("season_type") == "REG")
    sched = nfl.load_schedules([M.SEASON])
    rng = np.random.default_rng(5)
    rows = {p: [] for p in ("QB", "RB", "WR", "TE", "K", "DST")}
    unmatched = 0
    for wk in range(lo, hi + 1):
        act = actuals(wk, ps, pbp, sched)
        by_name = {}
        for k in act:
            if k[0] != "DST":
                by_name.setdefault((k[0], k[2]), []).append(k)
        recs, info = S.fetch_sleeper(wk)
        for r in recs:
            pos, tm = r["pos"], M.ALIAS.get(r["team"], r["team"])
            key = ("DST", tm) if pos == "DST" else (M.fold(r["name"]), tm, pos)
            if key not in act and pos != "DST":
                same = by_name.get((key[0], pos), [])
                key = same[0] if len(same) == 1 else None
            if key is None or key not in act:
                unmatched += 1
                continue
            summ = M.consensus_rec(pos, {"sleeper": r["stats"]}, "", 1.0, [])
            if pos != "DST" and summ["m"] < a.min:
                continue
            c = summ["c"]
            sim = M.sim_player(rng, pos, c, 1.0, 4000)
            if pos != "DST":
                sim = np.round(sim)
            rows[pos].append((float(sim.mean()), float(sim.var()), float(np.percentile(sim, 20)), float(np.percentile(sim, 80)),
                              float(act[key]), sim))
        print(f"week {wk}: sleeper {sum(info.values())} rows; unmatched so far {unmatched}")
    rep = {}
    for pos, rs in rows.items():
        if not rs:
            continue
        mu = np.array([r[0] for r in rs]); v = np.array([r[1] for r in rs]); y = np.array([r[4] for r in rs])
        err = y - mu
        k_var = float(np.sqrt(err.var() / v.mean()))
        k_mse = float(np.sqrt((err ** 2).mean() / v.mean()))

        def cover(k):
            n = 0
            for (m_, v_, p20, p80, yy, sim) in rs:
                s2 = m_ + k * (sim - m_)
                n += np.percentile(s2, 20) <= yy <= np.percentile(s2, 80)
            return round(n / len(rs), 3)
        rep[pos] = {"n": len(rs), "bias": round(float(err.mean()), 2), "mae": round(float(np.abs(err).mean()), 2),
                    "sim_sd": round(float(np.sqrt(v.mean())), 2), "real_sd": round(float(err.std()), 2),
                    "k_var": round(k_var, 3), "k_mse": round(k_mse, 3), "current": M.SPREAD_POS.get(pos),
                    "cover60_at_1": cover(1.0), "cover60_at_current": cover(M.SPREAD_POS.get(pos, 1.1)), "cover60_at_kvar": cover(k_var)}
    print("RESULT " + json.dumps({"weeks": a.weeks, "min_proj": a.min, "unmatched": unmatched, "by_pos": rep}))


if __name__ == "__main__":
    main()
