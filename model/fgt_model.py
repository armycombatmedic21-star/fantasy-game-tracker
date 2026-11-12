"""Fantasy Game Tracker — Prediction Engine, pregame model.

Exact port of Drop 1 Appendix A (fantasy_model.py, Grandpa project, Nov 6 2026), run for every
fantasy-relevant NFL player (bench included), plus all 32 defenses. Instead of shipping 20,000
simulations per player, it writes each player's DISTRIBUTION PARAMETERS to projections.json; the app
re-simulates them (same distributions) for live win %, in-game updating (Drop 1 §5) and playoff odds.
It also writes a summary (mean, 20th/80th pct) and a "neutral" mean/sd per player for future weeks.

Usage: python3 model/fgt_model.py [--week N] [--fp fp.json] [--overrides overrides.json] [--out projections.json]
Needs: pip install --break-system-packages nflreadpy polars numpy

fp.json (optional, FantasyPros consensus RAW stats from the laptop):
  {"source": "...", "at": "...", "players": [{"name","pos","team","pyd","ptd","ints","ryd","rtd","cyd","ctd"}]}
overrides.json (optional, each one sourced):
  [{"name","team"?, "play_prob"?, "usage_mult"?, "weeks"?, "mix"?: [{"p":0.7,"weeks":[...]}], "source"}]
"""
import argparse, datetime, json, re, sys
import numpy as np
import polars as pl
import nflreadpy as nfl

SEASON = 2026
N = 20000
SKILL_TIERS = [(200, 15), (150, 12), (100, 10), (50, 6), (25, 3)]
PASS_TIERS = [(400, 15), (350, 12), (300, 10), (226, 7), (150, 5), (75, 3)]
TD_LEN_PTS = np.array([6, 8, 10, 12])
TD_LEN_P = {"rush": [0.930, 0.029, 0.015, 0.026], "rec": [0.893, 0.048, 0.022, 0.037], "pass": [0.893, 0.048, 0.022, 0.037]}
ALIAS = {"LAR": "LA", "JAC": "JAX", "WSH": "WAS", "LVR": "LV", "OAK": "LV", "SD": "LAC", "STL": "LA", "ARZ": "ARI", "GNB": "GB",
         "KAN": "KC", "NWE": "NE", "NOR": "NO", "SFO": "SF", "TAM": "TB"}
TD_PER_POINT = 0.105
DEF_K = 0.25
ENV_K = 0.5
CV = {"RB": (0.55, 0.85), "WR": (1.0, 0.80), "TE": (1.0, 0.80)}
PRIOR = {"ypc": (4.2, 20), "ypt": {"RB": (5.5, 15), "WR": (7.6, 25), "TE": (6.6, 25)}}
QB_RY = (2.89, 0.8718)
PARTIAL_FRAC = 0.6
STALE_GAP = 2
OUTLIER_PCT, OUTLIER_ABS = 0.40, 3.0
WINDOW = {"WR": 5}
# Nov 11 2026 (Wes approved): QB pass yards from the season average of his full games with this team, not the
# weighted last 3. Backtest: pass-yds MAE 56.3 vs 62.7 (2025, n=369) and 60.3 vs 65.6 (2026, n=143).
# A hand-picked override window ("weeks"/"mix") still wins.
QB_PY_SEASON = True
FP_BLEND = 0.5
# How much wider than the raw simulation the app makes each range (v1.3.6, Nov 9 2026 league backtest, Wks 2-9):
# SPREAD_POS: each still-to-play player's own range, by position (1,287 rostered player-games vs CBS official points).
# SPREAD_RHO: small same-week correlation; only matters while several players are left (full team ~1.3x, 1 player = his own).
# SPREAD_K: future weeks (playoff odds) only. Checked with model/calibrate.py (pregame) and model/calibrate_live.py (live).
SPREAD_POS = {"QB": 1.10, "RB": 1.15, "WR": 1.13, "TE": 1.12, "K": 1.18, "DST": 1.08}
SPREAD_RHO = 0.06
SPREAD_K = 1.35
RNG = np.random.default_rng(7)
FP_STATS = {"matched": 0}
FP_RAW = {}   # (name, team, pos) -> FantasyPros raw stats, for rookies with no NFL games yet
FP_STD = {}   # (name, team, pos) -> FantasyPros' own standard-scoring points (scorecard only, never used in projections)


def score_fields(rec, fpp, own, prob, name, tm, pos):
    """Projection scorecard (Nov 10 2026): keep FantasyPros alone (in league scoring), our model alone, and FantasyPros'
    own standard points next to the blended projection, so each can be graded against the real results."""
    rec["fp"], rec["own"] = round(fpp * prob, 2), round(float(own), 2)
    v = FP_STD.get((norm_name(name), tm, pos))
    if v is not None:
        rec["fps"] = round(v, 2)


def norm_name(n):
    """Same as the app's normName()."""
    s = str(n or "").lower()
    s = re.sub(r"[‘’'`.]", "", s).replace("-", " ")
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", " ", s)
    s = re.sub(r"[^a-z ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def shrink(x, k=0.5):
    return 1 + k * (x - 1)


def tier(yds, tiers):
    out = np.zeros_like(yds, dtype=float)
    for thr, pts in reversed(tiers):
        out = np.where(yds >= thr, pts, out)
    return out


# ---------- simulation from parameters (the app's Web Worker mirrors these exactly) ----------
def sim_yds(rng, mean, cv, n):
    if mean <= 0.5:
        return np.zeros(n)
    k = 1 / cv ** 2
    return rng.gamma(k, mean / k, n)


def sim_td_pts(rng, lam, kind, n):
    if lam <= 0:
        return np.zeros(n)
    c = rng.poisson(lam, n)
    tot = np.zeros(n)
    for i in range(c.max()):
        tot += (c > i) * rng.choice(TD_LEN_PTS, n, p=TD_LEN_P[kind])
    return tot


def sim_comp(rng, pos, c, prob, n):
    if pos == "K":
        m = c["km"] * prob
        return np.clip(rng.normal(m, 0.45 * m, n), 0, None) if m > 0 else np.zeros(n)
    if pos == "DST":
        # fr / td / sf come from the consensus sources when present (Nov 11 2026); old fixed rates otherwise
        pa = np.clip(np.round(rng.normal(c["oi"], 9.5, n)), 0, None)
        pa_pts = np.select([pa == 0, pa <= 7, pa <= 17, pa <= 24, pa <= 29], [15, 9, 6, 3, 0], -3)
        return (pa_pts + rng.poisson(c["sk"], n) + rng.poisson(c["in"], n) + rng.poisson(c.get("fr", 0.6), n)
                + 6 * rng.poisson(c.get("td", 0.13), n) + 2 * rng.poisson(c.get("sf", 0.03), n))
    played = rng.random(n) < prob
    fl = rng.poisson(c["fl"], n) if c.get("fl") else 0      # fumbles lost, -1 each (consensus players only)
    if pos == "QB":
        py = np.clip(rng.normal(c["py"], c["ps"], n), 0, None)
        s = (tier(py, PASS_TIERS) + sim_td_pts(rng, c["pt"], "pass", n) - rng.poisson(c["it"], n)
             + tier(sim_yds(rng, c["ry"], 0.9, n), SKILL_TIERS) + sim_td_pts(rng, c["rt"], "rush", n)) - fl
        return s * played
    s = (tier(sim_yds(rng, c["ry"], c["rv"], n), SKILL_TIERS) + tier(sim_yds(rng, c["cy"], c["cv"], n), SKILL_TIERS)
         + sim_td_pts(rng, c["rt"], "rush", n) + sim_td_pts(rng, c["ct"], "rec", n)) - fl
    return s * played


def sim_player(rng, pos, comps, prob, n=N):
    if len(comps) == 1:
        return sim_comp(rng, pos, comps[0], prob, n)
    pick = rng.choice(len(comps), n, p=[c["w"] for c in comps])
    out = np.zeros(n)
    for i, c in enumerate(comps):
        out = np.where(pick == i, sim_comp(rng, pos, c, prob, n), out)
    return out


# ---------- data (Appendix A) ----------
SNAPS = {}


def load(season, before_week):
    global SNAPS
    ps = nfl.load_player_stats([season]).filter((pl.col("season_type") == "REG") & (pl.col("week") < before_week))
    num = ["carries", "rushing_yards", "rushing_tds", "targets", "receptions", "receiving_yards", "receiving_tds",
           "attempts", "passing_yards", "passing_tds", "passing_interceptions", "sacks_suffered"]
    ps = ps.with_columns([pl.col(c).fill_null(0) for c in num])
    ps = ps.with_columns(((pl.col("rushing_yards") + pl.col("receiving_yards")) / 10
                          + 6 * (pl.col("rushing_tds") + pl.col("receiving_tds"))).alias("fpts"))
    pbp = nfl.load_pbp([season]).filter((pl.col("season_type") == "REG") & (pl.col("week") < before_week))
    try:
        sc = nfl.load_snap_counts([season]).filter(pl.col("week") < before_week)
        SNAPS = {(r["player"], ALIAS.get(r["team"], r["team"]), r["week"]): (r["offense_pct"] or 0) * (100 if (r["offense_pct"] or 0) <= 1 else 1)
                 for r in sc.iter_rows(named=True)}
    except Exception:
        SNAPS = {}
    return ps, pbp


def week_lines(sched, week):
    s = sched.filter((pl.col("week") == week) & (pl.col("game_type") == "REG"))
    implied, opp, wx, home, playing = {}, {}, {}, {}, set()
    for r in s.iter_rows(named=True):
        h, a = r["home_team"], r["away_team"]
        playing.update([h, a])
        opp[h], opp[a] = a, h
        home[h], home[a] = True, False
        if r["total_line"] is None or r["spread_line"] is None:
            continue
        t, sp = r["total_line"], r["spread_line"]
        implied[h], implied[a] = t / 2 + sp / 2, t / 2 - sp / 2
        note = ""
        if (r["roof"] or "") in ("outdoors", "open"):
            if (r["wind"] or 0) >= 15: note += f"wind {r['wind']} mph "
            if r["temp"] is not None and r["temp"] <= 32: note += f"{r['temp']}F "
        wx[h] = wx[a] = note.strip()
    return implied, opp, wx, home, playing


def week_injuries(season, week):
    try:
        inj = nfl.load_injuries([season]).filter(pl.col("week") == week)
    except Exception:
        return {}
    out = {}
    for r in inj.iter_rows(named=True):
        out[r["gsis_id"]] = (r["report_status"], (r["practice_status"] or "").replace(" Participation in Practice", "")
                             .replace("Did Not Participate In Practice", "DNP"), r["report_primary_injury"] or r["practice_primary_injury"])
    return out


def team_context(ps, pbp):
    team = ps.group_by(["team", "week"]).agg(
        pl.col("carries").sum().alias("t_car"), pl.col("targets").sum().alias("t_tgt"),
        pl.col("rushing_tds").sum().alias("t_rtd"), pl.col("receiving_tds").sum().alias("t_ptd"))
    tds = team.group_by("team").agg(pl.col("t_rtd").sum(), pl.col("t_ptd").sum())
    rush_frac = {r["team"]: (r["t_rtd"] + 3) / (r["t_rtd"] + r["t_ptd"] + 8) for r in tds.iter_rows(named=True)}
    gl = (pbp.filter((pl.col("rush_attempt") == 1) & (pl.col("yardline_100") <= 10))
          .group_by(["posteam", "week", "rusher_player_id"]).len().rename({"len": "gl_car"}))
    rz = (pbp.filter((pl.col("pass_attempt") == 1) & (pl.col("yardline_100") <= 20) & pl.col("receiver_player_id").is_not_null())
          .group_by(["posteam", "week", "receiver_player_id"]).len().rename({"len": "rz_tgt"}))
    pts = (pbp.group_by(["game_id", "posteam"]).agg(pl.col("posteam_score_post").max())
           .drop_nulls().group_by("posteam").agg(pl.col("posteam_score_post").mean().alias("ppg")))
    ppg = {r["posteam"]: r["ppg"] for r in pts.iter_rows(named=True)}
    return team, rush_frac, gl, rz, ppg


def defense_ratios(ps):
    pos_pts = (ps.filter(pl.col("position").is_in(["RB", "WR", "TE"]))
               .group_by(["opponent_team", "week", "position"]).agg(pl.col("fpts").sum()))
    by_def = pos_pts.group_by(["opponent_team", "position"]).agg(pl.col("fpts").mean().alias("allowed"))
    lg = by_def.group_by("position").agg(pl.col("allowed").mean().alias("lg"))
    by_def = by_def.join(lg, on="position").with_columns((pl.col("allowed") / pl.col("lg")).alias("ratio"))
    qb = (ps.filter(pl.col("position") == "QB").group_by(["opponent_team", "week"])
          .agg((pl.col("passing_yards").sum() / 25 + 4 * pl.col("passing_tds").sum()).alias("q")))
    qb = qb.group_by("opponent_team").agg(pl.col("q").mean())
    lgq = qb["q"].mean()
    out = {(r["opponent_team"], r["position"]): r["ratio"] for r in by_def.iter_rows(named=True)}
    for r in qb.iter_rows(named=True):
        out[(r["opponent_team"], "QB")] = r["q"] / lgq
    return out


def league_pts_rows(me, pos):
    out = []
    for r in me.iter_rows(named=True):
        p = (float(tier(np.array([float(r["rushing_yards"])]), SKILL_TIERS)[0]) + float(tier(np.array([float(r["receiving_yards"])]), SKILL_TIERS)[0])
             + 6 * (r["rushing_tds"] + r["receiving_tds"]))
        if pos == "QB":
            p += float(tier(np.array([float(r["passing_yards"])]), PASS_TIERS)[0]) + 6 * r["passing_tds"] - r["passing_interceptions"]
        out.append(p)
    return out


def k_pts_rows(me):
    out = []
    for r in me.iter_rows(named=True):
        g = lambda c: (r.get(c) or 0)
        out.append(3 * (g("fg_made_0_19") + g("fg_made_20_29") + g("fg_made_30_39")) + 4 * g("fg_made_40_49")
                   + 5 * (g("fg_made_50_59") + g("fg_made_60_")) + g("pat_made"))
    return out


def partial_weeks(me, name, team):
    snaps = {w: SNAPS.get((name, team, w)) for w in me["week"].to_list()}
    vals = [v for v in snaps.values() if v is not None]
    if len(vals) < 3:
        return set()
    med = float(np.median(vals))
    return {w for w, v in snaps.items() if v is not None and v < PARTIAL_FRAC * med}


def fp_to_league(pos, pyd=0, ptd=0, ints=0, ryd=0, rtd=0, cyd=0, ctd=0, n=20000):
    rng = np.random.default_rng(11)
    cvr, cvc = CV.get(pos, CV["WR"]) if pos != "QB" else (0.9, 0.8)
    s = (tier(sim_yds(rng, ryd, cvr if pos == "RB" else 0.9, n), SKILL_TIERS) + tier(sim_yds(rng, cyd, cvc, n), SKILL_TIERS)
         + sim_td_pts(rng, rtd, "rush", n) + sim_td_pts(rng, ctd, "rec", n))
    if pos == "QB":
        py = np.clip(rng.normal(pyd, 0.28 * pyd + 20, n), 0, None)
        s += tier(py, PASS_TIERS) + sim_td_pts(rng, ptd, "pass", n) - rng.poisson(ints, n)
    return float(s.mean())


def target_week(sched):
    reg = sched.filter(pl.col("game_type") == "REG")
    open_ = reg.filter(pl.col("result").is_null())
    return int(open_["week"].min()) if open_.height else int(reg["week"].max())


# ---------- players with no game yet this season (back from injury, new signing, late-season rookie) ----------
# Without this they had no projection at all and the app counted them as 0 (Josh Jacobs Wk 7, McManus Wk 7,
# Grupe Wk 6 in our league). Source: last season's per-game averages, with this week's Vegas total and matchup;
# rookies with no NFL games use FantasyPros' raw stats when FantasyPros has them. Only players on an NFL roster
# as active (nflverse weekly rosters) are added.
DEPTH_MAX = {"QB": 1, "RB": 2, "WR": 3, "TE": 2, "K": 1}   # deepest depth-chart spot that still gets a projection


def no_games_yet(week, first_day, have_keys, have_pids, implied, opp_of, playing, inj, ppg, lg_ppg, dratio, fp_lookup):
    try:
        ro = nfl.load_rosters_weekly([SEASON]).filter((pl.col("week") <= week) & pl.col("position").is_in(["QB", "RB", "WR", "TE", "K", "FB"]))
        ro = ro.sort("week").group_by("gsis_id").agg(pl.col("full_name").last(), pl.col("team").last(), pl.col("position").last(),
                                                     pl.col("status").last(), pl.col("week").max().alias("rw"))
        prev = nfl.load_player_stats([SEASON - 1]).filter(pl.col("season_type") == "REG")
    except Exception:
        return []
    # depth chart as of the week's first game (latest snapshot per team): backups who haven't played stay out
    rank = {}
    try:
        dc = nfl.load_depth_charts([SEASON]).filter(pl.col("pos_abb").is_in(["QB", "RB", "WR", "TE", "PK"]) & (pl.col("dt").str.slice(0, 10) <= first_day))
        last = dc.group_by("team").agg(pl.col("dt").max().alias("mx"))
        dc = dc.join(last, on="team").filter(pl.col("dt") == pl.col("mx"))
        for r in dc.iter_rows(named=True):
            if r["gsis_id"]:
                rank[r["gsis_id"]] = min(rank.get(r["gsis_id"], 99), r["pos_rank"] or 99)
    except Exception:
        rank = None
    num = ["carries", "rushing_yards", "rushing_tds", "receiving_yards", "receiving_tds", "passing_yards", "passing_tds", "passing_interceptions"]
    prev = prev.with_columns([pl.col(c).fill_null(0) for c in num])
    out = []
    for r in ro.iter_rows(named=True):
        pid, name = r["gsis_id"], r["full_name"] or ""
        tm, pos = ALIAS.get(r["team"], r["team"]), ("RB" if r["position"] == "FB" else r["position"])
        if not pid or not name or r["status"] != "ACT" or pid in have_pids or (norm_name(name) + "|" + tm) in have_keys:
            continue
        if rank is not None and rank.get(pid, 99) > DEPTH_MAX.get(pos, 1) and not (pos == "K" and pid not in rank):
            continue
        me = prev.filter(pl.col("player_id") == pid)
        fpp = fp_lookup(name, tm, pos) if fp_lookup else None
        if me.height == 0 and fpp is None:
            continue
        status = inj.get(pid)
        prob = {"Out": 0.0, "Doubtful": 0.25, "Questionable": 0.75}.get(status[0], 1.0) if status else 1.0
        rec = {"k": norm_name(name) + "|" + tm, "n": name, "t": tm, "p": pos, "o": opp_of.get(tm), "pp": round(prob, 2)}
        if status:
            rec.update({"inj": status[0] or "", "pr": status[1] or "", "ij": status[2] or ""})
        imp, opp = implied.get(tm), opp_of.get(tm)
        flags = ["NO 2026 GAMES YET: based on %s" % ("last season" if me.height else "FantasyPros only")]

        def comps_for(imp_, opp_):
            env = shrink((imp_ / ppg.get(tm, imp_)) if imp_ else 1.0, ENV_K)
            m = shrink(dratio.get((opp_, pos), 1.0), DEF_K) if opp_ else 1.0
            if pos == "K":
                hist = k_pts_rows(me)
                vegas = (imp_ or lg_ppg) * 0.36
                return {"km": round(0.5 * vegas + 0.5 * float(np.mean(hist)) if len(hist) >= 3 else vegas, 3)}
            if me.height:
                g = lambda c: float(me[c].mean())
                py, pt, it, qry, qrt = g("passing_yards"), g("passing_tds"), g("passing_interceptions"), g("rushing_yards"), g("rushing_tds")
                ry, rt, cy, ct = g("rushing_yards"), g("rushing_tds"), g("receiving_yards"), g("receiving_tds")
            else:   # rookie with no NFL games: FantasyPros raw stats (already this week's matchup)
                st = fpp_raw
                py, pt, it, qry, qrt = st["pyd"], st["ptd"], st["ints"], st["ryd"], st["rtd"]
                ry, rt, cy, ct = st["ryd"], st["rtd"], st["cyd"], st["ctd"]
                env, m = 1.0, 1.0
            if pos == "QB":
                pm = py * env * m
                return {"py": round(pm, 2), "ps": round(0.28 * pm + 20, 2), "pt": round(pt * env * m, 4), "it": round(it, 4),
                        "ry": round(QB_RY[0] + QB_RY[1] * qry, 2), "rt": round(qrt, 4)}
            cv_r, cv_c = CV.get(pos, CV["WR"])
            return {"ry": round(ry * env * m, 2), "rv": cv_r, "cy": round(cy * env * m, 2), "cv": cv_c,
                    "rt": round(rt * env * m, 4), "ct": round(ct * env * m, 4)}
        fpp_raw = FP_RAW.get((norm_name(name), tm, pos)) if me.height == 0 else None
        if me.height == 0 and pos == "K":
            continue
        if me.height == 0 and not fpp_raw:
            continue
        nc = comps_for(ppg.get(tm, lg_ppg), None)
        nsim = np.round(sim_comp(RNG, pos, nc, 1.0, N))
        rec["nm"], rec["ns"] = round(float(nsim.mean()), 2), round(float(nsim.std()), 2)
        if tm not in playing or imp is None:
            rec.update({"bye": tm not in playing, "m": 0, "lo": 0, "hi": 0, "c": [], "f": flags + ["NO GAME / LINE"]})
            out.append(rec); continue
        c = comps_for(imp, opp)
        c["w"] = 1
        sim = np.round(sim_player(RNG, pos, [c], prob))
        basis = ("last season per-game averages" if me.height else "FantasyPros raw stats") + f" (no 2026 games yet); vs {opp}"
        scale = 1.0
        if fpp is not None and me.height and FP_BLEND > 0 and sim.mean() > 0:
            FP_STATS["matched"] += 1
            scale = ((1 - FP_BLEND) * sim.mean() + FP_BLEND * fpp * prob) / sim.mean()
            basis += f"; FantasyPros blended {FP_BLEND:.0%}"
            score_fields(rec, fpp, sim.mean(), prob, name, tm, pos)
        rec.update(summ(sim, [c], scale, basis, flags))
        out.append(rec)
    return out


# ---------- the model ----------
def build(week, fp_file=None, ov_file=None, src_file=None):
    sched = nfl.load_schedules([SEASON])
    ps, pbp = load(SEASON, week)
    implied, opp_of, wx, home_of, playing = week_lines(sched, week)
    inj = week_injuries(SEASON, week)
    team, rush_frac, gl, rz, ppg = team_context(ps, pbp)
    dratio = defense_ratios(ps)
    lg_ppg = float(np.mean(list(ppg.values()))) if ppg else 22.0
    # Nov 10 2026 (Wes): betting lines often aren't posted yet early in the week. A team that has a game but no line
    # gets its own scoring average as its implied total (same as the neutral projection) instead of a 0 projection.
    no_line = sorted(t for t in playing if t not in implied)
    for t in no_line:
        implied[t] = ppg.get(t, lg_ppg)
    no_line_al = set(no_line) | {ALIAS.get(t, t) for t in no_line}
    qbs = ps.filter(pl.col("attempts") > 0)
    g = qbs.group_by(["team", "opponent_team", "week"]).agg(pl.col("sacks_suffered").sum().alias("sk"), pl.col("passing_interceptions").sum().alias("int"))
    def_rates = {r["opponent_team"]: (r["sk"], r["int"]) for r in g.group_by("opponent_team").agg(pl.col("sk").mean(), pl.col("int").mean()).iter_rows(named=True)}
    off_rates = {r["team"]: (r["sk"], r["int"]) for r in g.group_by("team").agg(pl.col("sk").mean(), pl.col("int").mean()).iter_rows(named=True)}

    # FantasyPros raw stats -> league points. Matched by name + team (+ position); name alone only when unique.
    fp, fp_by_name = {}, {}
    FP_RAW.clear()
    FP_STD.clear()
    if fp_file:
        fj = json.load(open(fp_file))
        for p in fj.get("players", []):
            v = fp_to_league(p["pos"], *(p.get(k, 0) or 0 for k in ("pyd", "ptd", "ints", "ryd", "rtd", "cyd", "ctd")))
            nn, tm_ = norm_name(p["name"]), ALIAS.get((p.get("team") or "").upper(), (p.get("team") or "").upper())
            fp[(nn, tm_, p["pos"])] = v
            FP_RAW[(nn, tm_, p["pos"])] = {k: float(p.get(k, 0) or 0) for k in ("pyd", "ptd", "ints", "ryd", "rtd", "cyd", "ctd")}
            if p.get("std") is not None:
                FP_STD[(nn, tm_, p["pos"])] = float(p["std"])
            fp_by_name.setdefault((nn, p["pos"]), []).append(v)
    FP_STATS["matched"] = 0

    def fp_lookup(name, tm_, pos_):
        nn = norm_name(name)
        if (nn, tm_, pos_) in fp:
            return fp[(nn, tm_, pos_)]
        same = fp_by_name.get((nn, pos_), [])
        return same[0] if len(same) == 1 else None
    ovr = {}
    if ov_file:
        for o in json.load(open(ov_file)):
            ovr[norm_name(o["name"])] = o

    # current team = team in his latest game; stats with that team only (as Appendix A)
    latest = ps.sort("week").group_by("player_id").agg(pl.col("team").last(), pl.col("position").last(), pl.col("player_display_name").last(), pl.col("week").max().alias("lastwk"))
    players = []
    for r in latest.iter_rows(named=True):
        pos = "RB" if r["position"] == "FB" else r["position"]
        if pos not in ("QB", "RB", "WR", "TE", "K"):
            continue
        players.append({"pid": r["player_id"], "name": r["player_display_name"], "team": ALIAS.get(r["team"], r["team"]), "pos": pos})

    out, wr1 = [], {}
    for p in players:
        pos, tm, pid = p["pos"], p["team"], p["pid"]
        me = ps.filter((pl.col("player_id") == pid) & (pl.col("team") == tm)).sort("week")
        if me.height == 0:
            continue
        o = ovr.get(norm_name(p["name"]), {})
        if o.get("team") and ALIAS.get(o["team"], o["team"]) != tm:
            o = {}
        has_game = tm in playing
        imp = implied.get(tm)
        opp = opp_of.get(tm)
        status = inj.get(pid)
        prob = o.get("play_prob", 1.0)
        if status and "play_prob" not in o:
            prob = {"Out": 0.0, "Doubtful": 0.25, "Questionable": 0.75}.get(status[0], prob)
        flags = []
        rec = {"k": norm_name(p["name"]) + "|" + tm, "n": p["name"], "t": tm, "p": pos, "o": opp, "pp": round(prob, 2)}
        if status:
            rec["inj"] = status[0] or ""
            rec["pr"] = status[1] or ""
            rec["ij"] = status[2] or ""
        if o.get("source"):
            rec["src"] = o["source"]

        if pos == "K":
            hist = k_pts_rows(me)
            def kmean(i):
                vegas = i * 0.36
                return (0.5 * vegas + 0.5 * float(np.mean(hist)) if len(hist) >= 3 else vegas), vegas
            nk, _ = kmean(ppg.get(tm, lg_ppg))
            nsim = np.round(sim_comp(RNG, "K", {"km": nk}, 1.0, N))
            rec["nm"], rec["ns"] = round(float(nsim.mean()), 2), round(float(nsim.std()), 2)
            if not has_game or imp is None:
                rec.update({"bye": not has_game, "m": 0, "lo": 0, "hi": 0, "c": [], "f": ["NO GAME / LINE"]})
                out.append(rec); continue
            km, vegas = kmean(imp)
            comps = [{"w": 1, "km": round(km, 3)}]
            sim = np.round(sim_player(RNG, "K", comps, prob))
            basis = f"Vegas {vegas:.1f} blended with season avg {np.mean(hist):.1f}" if len(hist) >= 3 else "Vegas only"
            rec.update(summ(sim, comps, 1.0, basis, flags))
            out.append(rec); continue

        part = partial_weeks(me, p["name"], tm)
        full = me.filter(~pl.col("week").is_in(list(part)))
        season_avg = float(np.mean(league_pts_rows(full if full.height else me, pos)))
        if me["week"].max() < week - STALE_GAP:
            flags.append(f"STALE: last played wk {me['week'].max()}")
        mix = o.get("mix") or [{"p": 1.0, "weeks": o.get("weeks")}]

        def comp_for(weeks_override, imp_, opp_, neutral):
            if weeks_override:
                weeks = list(weeks_override)
            else:
                good = [w for w in me["week"].to_list() if w not in part]
                weeks = (good or me["week"].to_list())[-WINDOW.get(pos, 3):]
            win = me.filter(pl.col("week").is_in(weeks)).sort("week")
            n = win.height
            if n == 0:
                return None, weeks
            w = list(range(1, n + 1)); wsum = sum(w)
            wavg = lambda col: sum(a * b for a, b in zip(win[col].to_list(), w)) / wsum
            env = shrink((imp_ / ppg.get(tm, imp_)) if imp_ else 1.0, ENV_K)
            mu = 1.0 if neutral else o.get("usage_mult", 1.0)
            m = 1.0 if neutral else shrink(dratio.get((opp_, pos), 1.0), DEF_K)
            imp_tds = (imp_ or 21) * TD_PER_POINT
            rf = rush_frac.get(tm, 0.4)
            if pos == "QB":
                if QB_PY_SEASON and not weeks_override:
                    gw = [w for w in me["week"].to_list() if w not in part]
                    base = me.filter(pl.col("week").is_in(gw))["passing_yards"].mean() if gw else me["passing_yards"].mean()
                else:
                    base = wavg("passing_yards")
                pass_mean = (base or 0) * env * m
                return {"py": round(pass_mean, 2), "ps": round(0.28 * pass_mean + 20, 2), "pt": round(imp_tds * (1 - rf) * 0.92, 4),
                        "it": round(me["passing_interceptions"].sum() / max(me.height, 1), 4),
                        "ry": round(QB_RY[0] + QB_RY[1] * me["rushing_yards"].mean(), 2),
                        "rt": round(me["rushing_tds"].sum() / max(me.height, 1), 4)}, weeks
            car, tgt = wavg("carries") * mu * env, wavg("targets") * mu * env
            ypc0, k0 = PRIOR["ypc"]
            ypc = (me["rushing_yards"].sum() + ypc0 * k0) / (me["carries"].sum() + k0)
            ypt0, k1 = PRIOR["ypt"].get(pos, PRIOR["ypt"]["WR"])
            ypt = (me["receiving_yards"].sum() + ypt0 * k1) / (me["targets"].sum() + k1)
            tw = team.filter((pl.col("team") == tm) & pl.col("week").is_in(weeks))
            car_sh = win["carries"].sum() / max(tw["t_car"].sum(), 1)
            tgt_sh = win["targets"].sum() / max(tw["t_tgt"].sum(), 1)
            g_me = gl.filter((pl.col("rusher_player_id") == pid) & pl.col("week").is_in(weeks))["gl_car"].sum()
            g_tm = gl.filter((pl.col("posteam") == tm) & pl.col("week").is_in(weeks))["gl_car"].sum()
            r_me = rz.filter((pl.col("receiver_player_id") == pid) & pl.col("week").is_in(weeks))["rz_tgt"].sum()
            r_tm = rz.filter((pl.col("posteam") == tm) & pl.col("week").is_in(weeks))["rz_tgt"].sum()
            gl_sh = g_me / g_tm if g_tm else car_sh
            rz_sh = r_me / r_tm if r_tm else tgt_sh
            cv_r, cv_c = CV.get(pos, CV["WR"])
            c = {"ry": round(car * ypc * m, 2), "rv": cv_r, "cy": round(tgt * ypt * m, 2), "cv": cv_c,
                 "rt": round(imp_tds * rf * (0.4 * car_sh + 0.6 * gl_sh) * mu * m, 4),
                 "ct": round(imp_tds * (1 - rf) * 0.9 * (0.5 * tgt_sh + 0.5 * rz_sh) * mu * m, 4)}
            c["_tgt"] = wavg("targets")
            return c, weeks

        # neutral (future weeks): team's own scoring average, average defense, healthy
        nc, _ = comp_for(None, ppg.get(tm, lg_ppg), None, True)
        if nc is None:
            continue
        nc.pop("_tgt", None)
        nsim = np.round(sim_comp(RNG, pos, nc, 1.0, N))
        rec["nm"], rec["ns"] = round(float(nsim.mean()), 2), round(float(nsim.std()), 2)
        if pos == "WR":
            t_ = wr1.get(tm)
            nt = comp_for(None, ppg.get(tm, lg_ppg), None, True)[0]["_tgt"]
            if not t_ or nt > t_[1]:
                wr1[tm] = (rec["k"], nt)
        if not has_game or imp is None:
            rec.update({"bye": not has_game, "m": 0, "lo": 0, "hi": 0, "c": [], "f": flags + ["NO GAME / LINE"]})
            out.append(rec); continue
        comps, wk_used = [], None
        for mx in mix:
            c, wk = comp_for(mx.get("weeks"), imp, opp, False)
            if c is None:
                continue
            c.pop("_tgt", None)
            c["w"] = mx.get("p", 1.0)
            comps.append(c); wk_used = wk
        if not comps:
            continue
        tot = sum(c["w"] for c in comps)
        for c in comps:
            c["w"] = round(c["w"] / tot, 4)
        if not o.get("weeks") and not o.get("mix"):
            dropped = [w for w in me["week"].to_list()[-4:] if w in part]
            if dropped:
                flags.append(f"partial game(s) wk {dropped} excluded")
        sim = np.round(sim_player(RNG, pos, comps, prob))
        if prob > 0 and abs(sim.mean() / prob - season_avg) > max(OUTLIER_ABS, OUTLIER_PCT * season_avg):
            flags.append(f"OUTLIER: proj {sim.mean() / prob:.1f} vs season avg {season_avg:.1f}")
        c0 = comps[0]
        if pos == "QB":
            basis = f"{c0['py']:.0f} pass yds, {c0['pt']:.1f} pass TD"
        else:
            basis = f"wks {wk_used}: {c0['ry']:.0f} rush yds, {c0['cy']:.0f} rec yds; TD {c0['rt'] + c0['ct']:.2f}; vs {opp}"
        if wx.get(tm):
            basis += f"; WEATHER: {wx[tm]}"
        scale = 1.0
        fpp = fp_lookup(p["name"], tm, pos) if fp else None
        if fpp is not None:
            FP_STATS["matched"] += 1
        if fpp is not None and FP_BLEND > 0 and sim.mean() > 0:
            target = (1 - FP_BLEND) * sim.mean() + FP_BLEND * fpp * prob
            scale = target / sim.mean()
            basis += f"; FantasyPros blended {FP_BLEND:.0%}"
            score_fields(rec, fpp, sim.mean(), prob, p["name"], tm, pos)
        rec.update(summ(sim, comps, scale, basis, flags))
        out.append(rec)

    first_day = sched.filter((pl.col("week") == week) & (pl.col("game_type") == "REG"))["gameday"].min() or "9999-12-31"
    out += no_games_yet(week, first_day, {r["k"] for r in out}, {p["pid"] for p in players}, implied, opp_of, playing, inj, ppg, lg_ppg, dratio, fp_lookup if fp else None)

    for tm, (k, _) in wr1.items():
        for r in out:
            if r["k"] == k:
                r["wr1"] = 1

    # defenses
    dst = []
    for tm in sorted(set(ALIAS.get(t, t) for t in sched.filter(pl.col("game_type") == "REG")["home_team"].to_list())):
        d_sk, d_in = def_rates.get(tm, (2.4, 0.8))
        rec = {"k": "DST|" + tm, "n": tm + " D/ST", "t": tm, "p": "DST", "pp": 1.0}
        o_sk = np.mean([v[0] for v in off_rates.values()]) if off_rates else 2.4
        o_in = np.mean([v[1] for v in off_rates.values()]) if off_rates else 0.8
        nc = {"oi": round(lg_ppg, 2), "sk": round((d_sk + o_sk) / 2, 3), "in": round((d_in + o_in) / 2, 3)}
        nsim = sim_comp(RNG, "DST", nc, 1.0, N)
        rec["nm"], rec["ns"] = round(float(nsim.mean()), 2), round(float(nsim.std()), 2)
        if tm not in playing:
            rec.update({"bye": True, "m": 0, "lo": 0, "hi": 0, "c": [], "f": ["NO GAME / LINE"]})
            dst.append(rec); continue
        opp = opp_of[tm]
        rec["o"] = opp
        o_sk2, o_in2 = off_rates.get(opp, (2.4, 0.8))
        comps = [{"w": 1, "oi": round(implied.get(opp, 21), 2), "sk": round((d_sk + o_sk2) / 2, 3), "in": round((d_in + o_in2) / 2, 3)}]
        sim = sim_player(RNG, "DST", comps, 1.0)
        rec.update(summ(sim, comps, 1.0, f"{opp} implied {comps[0]['oi']:.1f}; sacks {comps[0]['sk']:.1f}, INT {comps[0]['in']:.1f}/gm", []))
        dst.append(rec)

    consensus = apply_consensus(out, dst, src_file) if src_file else None

    for r in out + dst:
        if r.get("t") in no_line_al and not r.get("bye"):
            r.setdefault("f", []).append("NO LINE YET: team scoring average used")
    reg = sched.filter(pl.col("game_type") == "REG")
    teams_all = set(ALIAS.get(t, t) for t in reg["home_team"].to_list())
    byes = {}
    for wk in range(week, 19):
        s = reg.filter(pl.col("week") == wk)
        on = set(ALIAS.get(t, t) for t in s["home_team"].to_list() + s["away_team"].to_list())
        byes[str(wk)] = sorted(teams_all - on)
    return {
        "season": SEASON, "week": week, "model": "Consensus of outside projections (Nov 11 2026); Drop 1 model as fallback" if src_file else "Drop 1 Appendix A (Nov 6 2026) port",
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "fp_blended": bool(fp), "fp_source": (json.load(open(fp_file)).get("source", "") if fp_file else ""),
        "fp_matched": FP_STATS["matched"], "spread_k": SPREAD_K, "spread_pos": SPREAD_POS, "spread_rho": SPREAD_RHO,
        "lg_ppg": round(lg_ppg, 2), "byes": byes, "consensus": consensus,
        "players": out + dst,
    }


# ---------- consensus prediction engine (Nov 11 2026, Wes) ----------
# Averages of several projection sources beat any single source (Fantasy Football Analytics accuracy studies), and a
# plain average beats tuned weights ("forecast combination puzzle"), so: simple average of each raw stat across every
# source that has the player, then OUR converter (tiers, TD lengths, simulations) turns it into this league's points.
# Our own model is only the fallback for a player with fewer than CONSENSUS_MIN sources.
CONSENSUS_MIN = 2
K_SHARE = (0.55, 0.25, 0.20)        # FG made <40 / 40-49 / 50+ when a source has no distance buckets
SRC_LABEL = {"cbs": "CBS", "sleeper": "Sleeper", "espn": "ESPN", "fp": "FantasyPros"}
SKILL_KEYS = ("pyd", "ptd", "ints", "ryd", "rtd", "cyd", "ctd", "fl")
DST_KEYS = ("pa", "sk", "dint", "fr", "dtd", "sf")


OUT_STATUS = ("out", "ir", "injury_reserve", "injured_reserve", "sus", "suspension", "suspended", "pup", "nfi", "dnr", "na")


def fold(n):
    """Name key for matching across sites: accents folded (Estimé = Estime), then the same rules as norm_name."""
    import unicodedata
    return norm_name(unicodedata.normalize("NFKD", str(n or "")).encode("ascii", "ignore").decode())


def load_sources(path):
    j = json.load(open(path))
    idx, by_name, by_last, inj = {}, {}, {}, {}
    for r in j.get("records", []):
        tm, pos = ALIAS.get(r.get("team", ""), r.get("team", "")), r.get("pos")
        key = ("DST", tm) if pos == "DST" else (fold(r.get("name", "")), tm, pos)
        if r["src"].endswith("_inj"):
            inj.setdefault(key, {})[r["src"][:-4]] = str(r.get("inj") or "")
            continue
        idx.setdefault(key, {}).setdefault(r["src"], r.get("stats") or {})
        if pos != "DST":
            by_name.setdefault((key[0], pos), set()).add(key)
            last = key[0].split(" ")[-1] if key[0] else ""
            by_last.setdefault((last, tm, pos), set()).add(key)
    return idx, by_name, by_last, inj, j.get("status", {})


def k_points(st, share=None):
    """Kicker points in this league (FG <40 = 3, 40-49 = 4, 50+ = 5, XP = 1) from one source's projected stats."""
    b = [st.get("fg_u40"), st.get("fg_40"), st.get("fg_50")]
    fg = st.get("fg")
    if all(v is not None for v in b) and sum(b) > 0:
        f = (fg / sum(b)) if fg else 1.0          # buckets that don't add up to the FG total are scaled to it
        u, m4, m5 = (v * f for v in b)
    else:
        sh = share or K_SHARE
        u, m4, m5 = ((fg or 0) * x for x in sh)
    return 3 * u + 4 * m4 + 5 * m5 + (st.get("xp") or 0)


def avg_keys(srcs, keys):
    out = {}
    for k in keys:
        vals = [s[k] for s in srcs.values() if s.get(k) is not None]
        if vals:
            out[k] = sum(vals) / len(vals)
    return out


def src_points(pos, st):
    """One source's projection in this league's points (scorecard)."""
    if pos == "K":
        return k_points(st)
    if pos == "DST":
        if st.get("pa") is None:
            return None
        c = {"oi": st["pa"], "sk": st.get("sk", 0), "in": st.get("dint", 0), "fr": st.get("fr", 0.6), "td": st.get("dtd", 0.13),
             "sf": st.get("sf", 0.03)}
        return float(sim_comp(np.random.default_rng(13), "DST", c, 1.0, 20000).mean())
    return fp_to_league(pos, *(st.get(k, 0) or 0 for k in ("pyd", "ptd", "ints", "ryd", "rtd", "cyd", "ctd"))) - (st.get("fl") or 0)


def apply_consensus(out, dst, src_file):
    idx, by_name, by_last, inj, status = load_sources(src_file)
    healthy = sum(1 for v in status.values() if isinstance(v, dict) and v.get("ok"))
    used, fallback, counts, outs, zero, single = 0, 0, {}, 0, 0, 0
    matched_keys = set()

    def find(key, table):
        if key in table:
            return key
        same = by_name.get((key[0], key[2]), set())           # traded player: a site may still list his old team
        if len(same) == 1:
            return next(iter(same))
        last = key[0].split(" ")[-1] if key[0] else ""
        same = by_last.get((last, key[1], key[2]), set())     # nickname (Bill / Jacory, Chig / Chigoziem): last name + team
        return next(iter(same)) if len(same) == 1 else None

    for rec in out + dst:
        pos = rec.get("p")
        if rec.get("bye") or not rec.get("c") or pos not in ("QB", "RB", "WR", "TE", "K", "DST"):
            continue
        if pos == "DST":
            k_ = ("DST", rec["t"])
            srcs, istat = idx.get(k_, {}), {}
        else:
            key = (fold(rec["n"]), rec["t"], pos)
            k_ = find(key, idx)
            srcs = idx.get(k_, {}) if k_ else {}
            ik = key if key in inj else (k_ if k_ in inj else None)
            istat = inj.get(ik, {}) if ik else {}
        if k_:
            matched_keys.add(k_)
        srcs = {k: v for k, v in srcs.items() if v}
        rec["sp"] = {k: round(v, 2) for k, v in ((k, src_points(pos, st)) for k, st in srcs.items()) if v is not None}
        rec["cs"] = sorted(srcs)
        counts[len(srcs)] = counts.get(len(srcs), 0) + 1
        own = rec["m"] / rec["sc"] if rec.get("sc") else rec["m"]
        out_by = [f"{SRC_LABEL.get(s_, s_)} {v}" for s_, v in istat.items() if v.lower().replace(" ", "_") in OUT_STATUS]
        if out_by:
            # Sleeper / ESPN list him Out, on IR or suspended: 0, even before the NFL's own Week injury report is out
            outs += 1
            rec["own"] = round(float(own), 2)
            rec.update({"pp": 0.0, "m": 0, "lo": 0, "hi": 0, "inj": rec.get("inj") or "Out"})
            rec["b"] = f"OUT ({', '.join(out_by)})"
            continue
        if not srcs and healthy >= CONSENSUS_MIN and pos != "DST":
            # every site that answered leaves him out of its projections: backup or not expected to play
            zero += 1
            rec["own"] = round(float(own), 2)
            rec.update({"pp": 0.0, "m": 0, "lo": 0, "hi": 0})
            rec["b"] = "No site projects him this week (backup or not expected to play)"
            rec.setdefault("f", []).append("NO OUTSIDE PROJECTION")
            continue
        if len(srcs) < CONSENSUS_MIN:
            # one site only: our model counts as the second vote (50/50), same scaling as the old FantasyPros blend
            fallback += 1
            if len(srcs) == 1 and rec["sp"] and own > 0:
                (s1, v1), = rec["sp"].items()
                single += 1
                target = 0.5 * own + 0.5 * v1 * (rec.get("pp", 1.0) or 0)
                sc_ = target / own
                rec["own"] = round(float(own), 2)
                rec["m"], rec["lo"], rec["hi"], rec["sc"] = round(target, 2), round(rec["lo"] * sc_ / (rec.get("sc") or 1), 1), round(rec["hi"] * sc_ / (rec.get("sc") or 1), 1), round(sc_, 4)
                rec["b"] = (rec.get("b") or "").split("; FantasyPros")[0] + f"; blended 50/50 with {SRC_LABEL.get(s1, s1)} (only site)"
            continue
        own = rec["m"] / rec["sc"] if rec.get("sc") else rec["m"]
        rec["own"] = round(float(own), 2)
        # The sources already build injuries and roles into their numbers: no second injury cut (no double counting),
        # except a player ruled Out.
        prob = 0.0 if rec.get("inj") == "Out" else 1.0
        names = "+".join(SRC_LABEL.get(k, k) for k in sorted(srcs))
        flags = [f for f in rec.get("f", []) if not f.startswith(("OUTLIER", "partial game"))]
        if pos == "K":
            km = sum(k_points(st) for st in srcs.values()) / len(srcs)
            comps = [{"w": 1, "km": round(km, 3)}]
            sim = np.round(sim_player(RNG, "K", comps, prob))
            basis = f"Consensus of {len(srcs)} ({names}): {km:.1f} pts from FGs by distance + XPs"
        elif pos == "DST":
            a = avg_keys(srcs, DST_KEYS)
            c = {"w": 1, "oi": round(a.get("pa", 21), 2), "sk": round(a.get("sk", 2.4), 3), "in": round(a.get("dint", 0.8), 3),
                 "fr": round(a.get("fr", 0.6), 3), "td": round(a.get("dtd", 0.13), 3), "sf": round(a.get("sf", 0.03), 3)}
            comps = [c]
            sim = sim_player(RNG, "DST", comps, 1.0)
            basis = (f"Consensus of {len(srcs)} ({names}): {rec.get('o', '')} scores {c['oi']:.1f}; sacks {c['sk']:.1f}, "
                     f"INT {c['in']:.1f}, FR {c['fr']:.1f}")
        else:
            a = {k: 0.0 for k in SKILL_KEYS}
            a.update(avg_keys(srcs, SKILL_KEYS))
            if pos == "QB":
                c = {"w": 1, "py": round(a["pyd"], 2), "ps": round(0.28 * a["pyd"] + 20, 2), "pt": round(a["ptd"], 4),
                     "it": round(a["ints"], 4), "ry": round(a["ryd"], 2), "rt": round(a["rtd"], 4), "fl": round(a["fl"], 4)}
                basis = f"Consensus of {len(srcs)} ({names}): {c['py']:.0f} pass yds, {c['pt']:.1f} pass TD"
            else:
                cv_r, cv_c = CV.get(pos, CV["WR"])
                c = {"w": 1, "ry": round(a["ryd"], 2), "rv": cv_r, "cy": round(a["cyd"], 2), "cv": cv_c,
                     "rt": round(a["rtd"], 4), "ct": round(a["ctd"], 4), "fl": round(a["fl"], 4)}
                basis = (f"Consensus of {len(srcs)} ({names}): {c['ry']:.0f} rush yds, {c['cy']:.0f} rec yds; "
                         f"TD {c['rt'] + c['ct']:.2f}; vs {rec.get('o', '')}")
            comps = [c]
            sim = np.round(sim_player(RNG, pos, comps, prob))
        rec["pp"] = prob
        rec.update(summ(sim, comps, 1.0, basis, flags))
        used += 1
    unmatched = []
    for k_, srcs in idx.items():
        if k_ in matched_keys or k_[0] == "DST":
            continue
        pts = [src_points(k_[2], st) for st in srcs.values() if st]
        pts = [p for p in pts if p is not None]
        if pts and max(pts) >= 4:
            unmatched.append(f"{k_[0]} {k_[1]} {k_[2]} {max(pts):.1f}")
    return {"used": used, "fallback": fallback, "single_source_blend": single, "out_by_injury": outs, "no_source_zero": zero,
            "unmatched_source_players_4plus": sorted(unmatched)[:40], "unmatched_count": len(unmatched),
            "sources_per_player": {str(k): v for k, v in sorted(counts.items())},
            "min_sources": CONSENSUS_MIN, "status": {k: {kk: vv for kk, vv in v.items() if kk != "info"} for k, v in status.items()}}


def summ(sim, comps, scale, basis, flags):
    s = sim * scale
    return {"m": round(float(s.mean()), 2), "lo": round(float(np.percentile(s, 20)), 1), "hi": round(float(np.percentile(s, 80)), 1),
            "sc": round(scale, 4), "c": comps, "b": basis, "f": flags}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int)
    ap.add_argument("--fp")
    ap.add_argument("--overrides")
    ap.add_argument("--sources")
    ap.add_argument("--out", default="projections.json")
    a = ap.parse_args()
    wk = a.week or target_week(nfl.load_schedules([SEASON]))
    res = build(wk, a.fp, a.overrides, a.sources)
    with open(a.out, "w") as f:
        json.dump(res, f, separators=(",", ":"))
    pl_ = [p for p in res["players"] if p.get("c")]
    print(f"week {wk}: {len(res['players'])} players ({len(pl_)} with a game), FP blended: {res['fp_blended']} -> {a.out}")
