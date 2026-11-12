"""One automated projection run (GitHub Actions; no Claude, no laptop).

1. Pick the NFL week (first regular-season week with an unplayed game).
2. Pull FantasyPros consensus raw stats for that week (model/fetch_fp.py). If FantasyPros hasn't posted the week yet
   or can't be reached, reuse this week's last good pull (fp-cache/, kept in the Actions cache, not in the repo);
   if there is none, run our model alone and label it unblended.
3. Run model/fgt_model.py (Drop 1 model, 50/50 FantasyPros blend when available).
4. Sanity checks (same as the old Claude task): 400+ players, week 1-18, no player mean above 45 or below -3.
   A failed check keeps the previous projections.json.
5. Write projections-status.json (what happened, in plain fields) so anyone can see the last run from the repo.
"""
import datetime, json, os, shutil, sys, traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nflreadpy as nfl
import fgt_model as M
import fetch_fp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "fp-cache")
OUT = os.path.join(ROOT, "projections.json")
STATUS = os.path.join(ROOT, "projections-status.json")


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def main():
    st = {"at": now(), "ok": False, "runner": "github-actions" if os.environ.get("GITHUB_ACTIONS") else "local"}
    try:
        week = int(os.environ.get("FGT_WEEK") or M.target_week(nfl.load_schedules([M.SEASON])))
        st["week"] = week
        os.makedirs(CACHE, exist_ok=True)
        fp_file, cached = os.path.join(CACHE, f"fp-week{week}.json"), None
        try:
            players, info, code = fetch_fp.fetch_best(week)
        except Exception as e:
            players, info, code = None, {"error": str(e)[:300]}, 1
        st["fp_fetch"] = {"code": code, "info": info}
        st["fp_source"] = (info or {}).get("source", "?")
        if code == 0:
            json.dump({"source": f"FantasyPros consensus raw stats ({st['fp_source']}), week {week}", "at": now(), "week": week,
                       "players": players}, open(fp_file, "w"), separators=(",", ":"))
            st["fp"] = "fresh"
        elif os.path.exists(fp_file):
            cached = json.load(open(fp_file))
            st["fp"] = "reused pull from " + cached.get("at", "?")
        else:
            fp_file = None
            st["fp"] = "not posted yet" if code == 2 else "unavailable"

        res = M.build(week, fp_file, None)
        pl_ = res["players"]
        bad = [f"{p['n']} {p['m']}" for p in pl_ if p.get("m", 0) > 45 or p.get("m", 0) < -3]
        checks = {"players": len(pl_), "week_ok": 1 <= week <= 18, "outliers": bad[:10]}
        st["checks"] = checks
        if len(pl_) < 400 or not checks["week_ok"] or bad:
            st["error"] = "sanity check failed; kept the previous projections.json"
            return st, 1
        # who got no FantasyPros number (for spotting name mismatches)
        if fp_file:
            miss = [p["n"] + " " + p["t"] for p in pl_ if p.get("p") in ("QB", "RB", "WR", "TE") and p.get("c")
                    and p.get("m", 0) >= 5 and p.get("fp") is None and "FantasyPros" not in (p.get("b") or "")]
            st["fp_unmatched_5plus"] = miss[:25]
            st["fp_unmatched_5plus_count"] = len(miss)
        tmp = OUT + ".tmp"
        json.dump(res, open(tmp, "w"), separators=(",", ":"))
        shutil.move(tmp, OUT)
        try:
            st["scorecard"] = snapshot(week, res)
        except Exception as e:
            st["scorecard"] = f"snapshot failed: {type(e).__name__}: {e}"[:200]
        st.update({"ok": True, "fp_blended": res["fp_blended"], "fp_matched": res.get("fp_matched", 0),
                   "players": len(pl_), "spread_k": res.get("spread_k"), "spread_rho": res.get("spread_rho"),
                   "no_games_yet": sum(1 for p in pl_ if any("NO 2026 GAMES" in f for f in p.get("f", [])))})
        return st, 0
    except Exception as e:
        st["error"] = f"{type(e).__name__}: {e}"[:500]
        st["trace"] = traceback.format_exc()[-1500:]
        return st, 1


def snapshot(week, res):
    """Projection scorecard: keep each player's last projection made BEFORE his game kicked off (history/proj-wN.json),
    so model/grade.py can grade ours, FantasyPros alone and our model alone against the real CBS points afterwards."""
    import zoneinfo
    hist = os.path.join(ROOT, "history"); os.makedirs(hist, exist_ok=True)
    path = os.path.join(hist, f"proj-w{week}.json")
    old = json.load(open(path)) if os.path.exists(path) else {"week": week, "players": {}}
    sched = nfl.load_schedules([M.SEASON])
    s = sched.filter((sched["week"] == week) & (sched["game_type"] == "REG"))
    et = zoneinfo.ZoneInfo("America/New_York")
    kick = {}
    for r in s.iter_rows(named=True):
        try:
            t = datetime.datetime.strptime(f"{r['gameday']} {r['gametime']}", "%Y-%m-%d %H:%M").replace(tzinfo=et)
        except Exception:
            continue
        for tm in (r["home_team"], r["away_team"]):
            kick[M.ALIAS.get(tm, tm)] = t
    t_now = datetime.datetime.now(datetime.timezone.utc)
    n = 0
    for p in res["players"]:
        k = kick.get(p.get("t"))
        if p.get("bye") or k is None or t_now >= k:
            continue                      # no game, or his game already started: keep the pre-kickoff snapshot
        e = {"m": p.get("m"), "pos": p.get("p")}
        for f in ("fp", "own", "fps"):
            if p.get(f) is not None:
                e[f] = p[f]
        old["players"][p["k"]] = e
        n += 1
    old["at"] = now()
    json.dump(old, open(path, "w"), separators=(",", ":"))
    return f"week {week}: {n} pre-kickoff projections saved"


if __name__ == "__main__":
    st, code = main()
    json.dump(st, open(STATUS, "w"), indent=1)
    print(json.dumps({k: v for k, v in st.items() if k != "trace"}, indent=1))
    sys.exit(code)
