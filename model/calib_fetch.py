"""One-time calibration data pull (run by .github/workflows/calibrate-data.yml, results pushed to a temporary branch).

- CBS league lineups + official points per player for past weeks, through our own Worker (/live?week=N).
- FantasyPros consensus raw stats for the same weeks (to test the 50/50 blend on our league's real games).
Output: calib-out/cbs-weekN.json, calib-out/fp-weekN.json, calib-out/summary.json
"""
import json, os, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_fp

WORKER = "https://fgt-lineups.armycombatmedic21.workers.dev"
OUT = "calib-out"
WEEKS = [int(w) for w in os.environ.get("CALIB_WEEKS", "1,2,3,4,5,6,7,8,9").split(",")]


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "fgt-calibration/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def compact(body):
    ls = body.get("live_scoring") or body
    teams = []
    for t in ls.get("teams", []):
        teams.append({"id": str(t.get("id")), "name": (t.get("name") or "").strip(), "opp": str(t.get("opp_team_id") or ""),
                      "pts": t.get("pts"), "division": t.get("division"),
                      "players": [{"name": p.get("fullname"), "pos": p.get("position"), "nfl": p.get("pro_team"),
                                   "status": p.get("status"), "slot": p.get("roster_pos"), "fpts": p.get("fpts"),
                                   "gs": (p.get("game_info") or {}).get("game_status") if isinstance(p.get("game_info"), dict) else None}
                                  for p in t.get("players", [])]})
    return {"period": ls.get("period"), "teams": teams}


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    if os.environ.get("SAVE_HTML"):   # debugging: keep one raw page to see how the full table is delivered
        for pos in ("rb",):
            open(f"{OUT}/raw-{pos}.html", "w").write(fetch_fp.get(f"https://www.fantasypros.com/nfl/projections/{pos}.php?week=9"))
            open(f"{OUT}/raw-{pos}-std.html", "w").write(fetch_fp.get(f"https://www.fantasypros.com/nfl/projections/{pos}.php?week=9&scoring=STD&max-yes=true"))
        if os.environ.get("SAVE_HTML") == "only":
            sys.exit(0)
    summary = {"cbs": {}, "fp": {}}
    for w in WEEKS:
        try:
            j = get_json(f"{WORKER}/live?week={w}")
            c = compact(j.get("data") or {})
            json.dump(c, open(f"{OUT}/cbs-week{w}.json", "w"), separators=(",", ":"))
            summary["cbs"][w] = {"ok": j.get("ok"), "source": j.get("source"), "period": c["period"], "teams": len(c["teams"])}
        except Exception as e:
            summary["cbs"][w] = {"error": str(e)[:200]}
        time.sleep(2)
    for w in WEEKS + [max(WEEKS) + 1]:
        try:
            players, info, code = fetch_fp.fetch(w)
            if code == 0:
                json.dump({"week": w, "players": players}, open(f"{OUT}/fp-week{w}.json", "w"), separators=(",", ":"))
            summary["fp"][w] = {"code": code, "players": len(players or []), "info": info}
        except Exception as e:
            summary["fp"][w] = {"error": str(e)[:200]}
    json.dump(summary, open(f"{OUT}/summary.json", "w"), indent=1)
    print(json.dumps(summary, indent=1)[:4000])
