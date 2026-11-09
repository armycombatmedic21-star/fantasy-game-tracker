"""Live win % replay test on our league's real weeks (CBS lineups + official points).

For each past week, rebuild the moments a live viewer sees: before kickoff, then after each kickoff window
(Thursday, London, Sunday 1 PM, Sunday 4 PM, Sunday night, ...). Players whose game is over are locked at their
real points; everyone else is simulated from the pre-week projections exactly like the app. Each moment's win %
is scored against who actually won (Brier score, log loss).

It compares ways of setting the spread (how wide the team-total range is):
  old      the v1.3.5 engine: whole remaining team total stretched by spread_k (1.35), plain rounding
  k1       no stretch at all
  adaptive v1.3.6: each still-to-play player gets his position's stretch (spread_pos), plus a small
           same-week correlation term (spread_rho) that only matters when several players are left;
           random (dithered) rounding so exact ties keep their real chance
Usage: PYTHONHASHSEED=0 python3 model/calibrate_live.py DATA_DIR [--weeks 2,...,9] [--rho 0.03]
DATA_DIR holds cbs-weekN.json and proj-cache/proj-wN-ours.json (from model/calibrate.py).
"""
import argparse, datetime, json, os, sys
import numpy as np
import polars as pl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nflreadpy as nfl
import fgt_model as M
import calibrate as C

N = 20000
C.N = N
KLOG = {}   # effective stretch per call (for the report)
PREK = {}   # effective stretch of full teams before kickoff, per rho


def windows(sched, week):
    """team -> kickoff window index (0 = first window of the week); windows = kickoffs less than 2.5 h apart."""
    s = sched.filter((pl.col("week") == week) & (pl.col("game_type") == "REG"))
    games = []
    for r in s.iter_rows(named=True):
        t = datetime.datetime.strptime(r["gameday"] + " " + (r["gametime"] or "13:00"), "%Y-%m-%d %H:%M")
        games.append((t, M.ALIAS.get(r["home_team"], r["home_team"]), M.ALIAS.get(r["away_team"], r["away_team"])))
    games.sort()
    win, idx, last = {}, -1, None
    for t, h, a in games:
        if last is None or (t - last).total_seconds() > 2.5 * 3600:
            idx += 1
        last = t
        win[h] = win[a] = idx
    return win, idx + 1


def dither_round(x, rng):
    return np.floor(x + rng.random(len(x)))


def finish(members, variant, kpos, rho, rng):
    """members: list of dicts with arr (sims or a constant) and pos. Returns the final team-total samples."""
    tot = np.zeros(N)
    for m in members:
        tot += m["arr"]
    if variant == "k1":
        return tot
    mu = tot.mean()
    if variant == "old":
        return np.round(mu + 1.35 * (tot - mu))
    vs = np.var(tot)
    if vs <= 1e-9:
        return tot
    v = np.array([np.var(m["arr"]) for m in members])
    k = np.array([kpos.get(m["pos"], 1.1) for m in members])
    s = np.sqrt(v)
    target = vs + np.sum((k * k - 1) * v) + rho * (np.sum(k * s) ** 2 - np.sum(k * k * v))
    K = np.sqrt(max(target, vs) / vs)
    KLOG.setdefault((variant, rho), []).append(K)
    out = dither_round(mu + K * (tot - mu), rng)
    return np.maximum(out, tot.min())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--weeks", default="2,3,4,5,6,7,8,9")
    ap.add_argument("--rho", default="0.03")
    ap.add_argument("--kpos", default='{"QB":1.10,"RB":1.15,"WR":1.13,"TE":1.12,"K":1.18,"DST":1.08}')
    a = ap.parse_args()
    weeks = [int(w) for w in a.weeks.split(",")]
    kpos = json.loads(a.kpos)
    rhos = [float(x) for x in a.rho.split(",")]
    variants = ["old", "k1"] + [f"adaptive@{r}" for r in rhos]
    sched = nfl.load_schedules([M.SEASON])
    rows = []
    for w in weeks:
        cbs = json.load(open(os.path.join(a.data, f"cbs-week{w}.json")))
        P = C.Proj(json.load(open(os.path.join(a.data, "proj-cache", f"proj-w{w}-ours.json"))))
        win, nwin = windows(sched, w)
        tm = {t["id"]: t for t in cbs["teams"]}
        done = set()
        for t in cbs["teams"]:
            o = tm.get(t["opp"])
            if not o or (o["id"], t["id"]) in done:
                continue
            done.add((t["id"], o["id"]))
            # both teams must be final (week 9: Monday night still to play)
            if any(p.get("gs") not in ("F", None) for T in (t, o) for p in T["players"] if p.get("status") in ("Active", "Reserve")):
                continue
            # base pregame sims for every rostered player (same seed at every moment, like the app's cache)
            sides = []
            for T in (t, o):
                st, bn = [], []
                for i, p in enumerate(T["players"]):
                    if p.get("status") not in ("Active", "Reserve"):
                        continue
                    r = P.find(p["name"], p["pos"], p["nfl"])
                    y = C.fnum(p.get("fpts")) or 0.0
                    sims = C.sims_for(r, p["pos"], hash((w, T["id"], i)) & 0xffffffff) if r else np.zeros(N)
                    rec = {"pos": p["pos"], "nfl": C.team_code(p["nfl"]), "wr1": bool(r and r.get("wr1")), "sims": sims, "y": y,
                           "win": win.get(C.team_code(p["nfl"]), -1) if p.get("gs") is not None else -1}
                    (st if p["status"] == "Active" else bn).append(rec)
                ya, yb = sum(m["y"] for m in st), sum(m["y"] for m in bn)
                sides.append({"st": st, "bn": bn, "y": C.fnum(T.get("pts")) if C.fnum(T.get("pts")) is not None else ya, "yb": yb, "name": T["name"]})
            A, B = sides
            won = 1.0 if A["y"] > B["y"] else 0.0 if A["y"] < B["y"] else (1.0 if A["yb"] > B["yb"] else 0.0 if A["yb"] < B["yb"] else 0.5)
            for cp in range(-1, nwin - 1):   # -1 = before kickoff; cp = windows 0..cp are final
                for side in (A, B):
                    for m in side["st"] + side["bn"]:
                        fixed = m["win"] == -1 or m["win"] <= cp      # bye (win -1) or game over
                        m["arr"] = np.full(N, m["y"]) if fixed else m["sims"].copy()
                        m["left"] = not fixed
                C.correlate(A["st"] + B["st"], hash((w, t["id"], cp)) & 0xffffffff)
                left = sum(m["left"] for m in A["st"] + B["st"])
                rec = {"week": w, "a": A["name"], "b": B["name"], "cp": cp, "left": left, "won": won, "p": {}}
                for vname in variants:
                    rng = np.random.default_rng(abs(hash((w, t["id"], cp, vname))) & 0xffffffff)
                    if vname.startswith("adaptive@"):
                        var, rho = "adaptive", float(vname.split("@")[1])
                    else:
                        var, rho = vname, 0.0
                    if cp == -1:
                        KLOG.pop(("pre", rho), None)
                    ta, tb = finish(A["st"], var, kpos, rho, rng), finish(B["st"], var, kpos, rho, rng)
                    if cp == -1 and var == "adaptive":
                        PREK.setdefault(rho, []).extend(KLOG[(var, rho)][-2:])
                    ba, bb = finish(A["bn"], var, kpos, rho, rng), finish(B["bn"], var, kpos, rho, rng)
                    p = np.where(ta > tb, 1.0, np.where(ta < tb, 0.0, np.where(ba > bb, 1.0, np.where(ba < bb, 0.0, 0.5))))
                    rec["p"][vname] = float(p.mean())
                rows.append(rec)
        print(f"week {w}: {len(done)} matchups, {nwin} kickoff windows", flush=True)

    def score(sel, v):
        ps = np.array([r["p"][v] for r in sel]); ys = np.array([r["won"] for r in sel])
        pc = np.clip(ps, 0.001, 0.999)
        return round(float(np.mean((ps - ys) ** 2)), 4), round(float(-np.mean(ys * np.log(pc) + (1 - ys) * np.log(1 - pc))), 4)
    groups = {"all moments": rows, "before kickoff": [r for r in rows if r["cp"] == -1],
              "games under way (1+ windows done)": [r for r in rows if r["cp"] >= 0 and r["left"] > 0],
              "4 or fewer starters left": [r for r in rows if 0 < r["left"] <= 4],
              "1-2 starters left": [r for r in rows if 0 < r["left"] <= 2]}
    out = {"weeks": weeks, "kpos": kpos, "moments": len(rows), "matchups": len({(r["week"], r["a"]) for r in rows}), "scores": {}}
    for g, sel in groups.items():
        if sel:
            out["scores"][g] = {"n": len(sel), **{v: dict(zip(("brier", "logloss"), score(sel, v))) for v in variants}}
    # calibration table for the moments with games under way
    cal = {}
    for v in variants:
        sel = [r for r in rows if r["left"] > 0]
        tab = []
        for lo, hi in ((0, .1), (.1, .3), (.3, .5), (.5, .7), (.7, .9), (.9, 1.01)):
            s = [r for r in sel if lo <= r["p"][v] < hi]
            if s:
                tab.append({"range": f"{lo:.1f}-{min(hi, 1):.1f}", "n": len(s), "avg_p": round(float(np.mean([r["p"][v] for r in s])), 3),
                            "won": round(float(np.mean([r["won"] for r in s])), 3)})
        cal[v] = tab
    out["calibration"] = cal
    out["pregame_team_stretch"] = {str(r): round(float(np.mean(v)), 3) for r, v in PREK.items()}
    json.dump({"summary": out, "rows": rows}, open(os.path.join(a.data, "calibration-live.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
