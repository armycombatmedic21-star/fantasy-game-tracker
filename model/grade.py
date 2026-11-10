"""Projection scorecard (Nov 10 2026, Wes): how close were our projections vs FantasyPros, graded against the real CBS
points of every player rostered in the league. Runs after each projections run (GitHub Actions; no Claude, no laptop).

Inputs:  history/proj-wN.json (each player's last projection before his game, saved by run_projections.py)
         the Worker's /live?week=N (CBS's official points per rostered player)
Output:  history/grades.json

Numbers per week (and season to date), all in this league's CBS scoring:
  ours      = our published projection (what the app shows)
  own       = our model alone, before the 50/50 FantasyPros blend
  fp        = FantasyPros' consensus stats converted to this league's scoring
  fp_std    = FantasyPros' own standard-scoring points (what the FantasyPros app shows for this league)
MAE = average miss in points per player (lower is better). Bias = average (projection - actual); + means too high.
The head-to-head rows only use players that have every number, so the comparison is apples to apples.
"""
import datetime, json, os, sys, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fgt_model as M

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, "history")
WORKER = "https://fgt-lineups.armycombatmedic21.workers.dev/live?week={w}"
TEAM = dict(M.ALIAS, WSH="WAS", LAR="LA", JAC="JAX")


def cbs_points(week):
    req = urllib.request.Request(WORKER.format(w=week), headers={"User-Agent": "fgt-grade/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.loads(r.read().decode("utf-8", "replace"))
    ls = (j.get("data") or {}).get("live_scoring") or {}
    if not j.get("ok") or int(ls.get("period") or 0) != week:
        return None
    out = {}
    for t in ls.get("teams") or []:
        for p in t.get("players") or []:
            pos = str(p.get("position") or "").upper()
            tm = TEAM.get(str(p.get("pro_team") or "").upper(), str(p.get("pro_team") or "").upper())
            key = ("DST|" + tm) if pos in ("D", "DST", "DEF") else (M.norm_name(p.get("fullname")) + "|" + tm)
            v = p.get("fpts")
            if v in ("", None) or key in out:
                continue
            try:
                out[key] = float(v)
            except (TypeError, ValueError):
                pass
    return out


def stats(pairs):
    if not pairs:
        return None
    err = [p - a for p, a in pairs]
    return {"n": len(err), "mae": round(sum(abs(e) for e in err) / len(err), 2), "bias": round(sum(err) / len(err), 2)}


def grade_week(week):
    path = os.path.join(HIST, f"proj-w{week}.json")
    if not os.path.exists(path):
        return None
    proj = json.load(open(path))["players"]
    act = cbs_points(week)
    if not act:
        return None
    rows = [(k, proj[k], act[k]) for k in act if k in proj]
    full = [(e, a) for k, e, a in rows if e.get("fp") is not None and e.get("own") is not None]
    res = {"graded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "all_rostered": {"ours": stats([(e["m"], a) for k, e, a in rows])},
           "head_to_head": {"ours": stats([(e["m"], a) for e, a in full]), "own": stats([(e["own"], a) for e, a in full]),
                            "fp": stats([(e["fp"], a) for e, a in full])}}
    std = [(e, a) for e, a in full if e.get("fps") is not None]
    if std:
        res["fp_app"] = {"ours": stats([(e["m"], a) for e, a in std]), "fp_std": stats([(e["fps"], a) for e, a in std])}
    res["_pairs"] = [[e["m"], e.get("own"), e.get("fp"), e.get("fps"), a] for e, a in full]
    res["_all"] = [[e["m"], a] for k, e, a in rows]
    return res


def main():
    import nflreadpy as nfl
    cur = M.target_week(nfl.load_schedules([M.SEASON]))
    out_path = os.path.join(HIST, "grades.json")
    G = json.load(open(out_path)) if os.path.exists(out_path) else {"weeks": {}}
    for f in sorted(os.listdir(HIST)) if os.path.isdir(HIST) else []:
        if not (f.startswith("proj-w") and f.endswith(".json")):
            continue
        w = int(f[6:-5])
        if w >= cur or str(w) in G["weeks"]:
            continue                      # week not over yet, or already graded
        try:
            r = grade_week(w)
        except Exception as e:
            print(f"week {w}: {type(e).__name__}: {e}")
            continue
        if r:
            G["weeks"][str(w)] = r
    pairs = [p for r in G["weeks"].values() for p in r.get("_pairs", [])]
    allp = [p for r in G["weeks"].values() for p in r.get("_all", [])]
    G["season"] = {"weeks": sorted(G["weeks"], key=int),
                   "all_rostered": {"ours": stats([(m, a) for m, a in allp])},
                   "head_to_head": {"ours": stats([(p[0], p[4]) for p in pairs]), "own": stats([(p[1], p[4]) for p in pairs]),
                                    "fp": stats([(p[2], p[4]) for p in pairs])},
                   "fp_app": {"ours": stats([(p[0], p[4]) for p in pairs if p[3] is not None]),
                              "fp_std": stats([(p[3], p[4]) for p in pairs if p[3] is not None])}}
    os.makedirs(HIST, exist_ok=True)
    json.dump(G, open(out_path, "w"), separators=(",", ":"))
    print(json.dumps(G["season"], indent=1))


if __name__ == "__main__":
    main()
