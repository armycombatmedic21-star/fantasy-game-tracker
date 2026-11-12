"""Outside projection sources for the consensus prediction engine (Nov 11 2026, Wes: "pull the raw projected stats
from several places, average them, and let our model convert them into our scoring").

Every source is turned into the same raw-stat record, for every lineup spot (QB, RB, WR, TE, K, DST):
  name, team (nflverse abbreviation), pos, src, and stats:
    QB/RB/WR/TE: pyd ptd ints ryd rtd cyd ctd fl
    K:           fg (made), fg_u40, fg_40, fg_50 (made by distance, when the source has buckets), xp (made)
    DST:         pa (points allowed), sk, dint, fr, dtd (defense/special-teams TDs), sf (safeties)
A stat a source doesn't give is left out (never filled with 0), so the average only uses sources that have it.

Sources (all free, tested in Wes's Chrome Nov 11 2026):
  sleeper - api.sleeper.app projections (Sleeper's numbers come from RotoWire). No key.
  espn    - ESPN fantasy kona_player_info projected stats (statSourceId 1). No key.
  cbs     - CBS's own projections, through our Worker's /proj (the Worker holds the CBS key). Rostered players only.
  fp      - FantasyPros raw stats from model/fetch_fp.py (free API key = 10 players per position; QB-TE only).
Each source is fetched once per run (a few requests per day in total), with retries, and a failed source is just skipped.

Usage: python3 model/fetch_sources.py --week N --out sources.json
"""
import argparse, datetime, json, sys, time, urllib.error, urllib.parse, urllib.request

SEASON = 2026
WORKER = "https://fgt-lineups.armycombatmedic21.workers.dev"
UA = "fgt-projections/2.0 (personal fantasy league app)"
ALIAS = {"LAR": "LA", "JAC": "JAX", "WSH": "WAS", "LVR": "LV", "OAK": "LV", "SD": "LAC", "STL": "LA", "ARZ": "ARI", "GNB": "GB",
         "KAN": "KC", "NWE": "NE", "NOR": "NO", "SFO": "SF", "TAM": "TB"}
SKILL = ("QB", "RB", "WR", "TE")
# ESPN proTeamId -> abbreviation
ESPN_TEAM = {1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET", 9: "GB", 10: "TEN", 11: "IND",
             12: "KC", 13: "LV", 14: "LA", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI",
             23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WAS", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU"}
ESPN_POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}
# team full names -> abbreviation (Sleeper/ESPN/CBS DST names)
NICK = {"Cardinals": "ARI", "Falcons": "ATL", "Ravens": "BAL", "Bills": "BUF", "Panthers": "CAR", "Bears": "CHI", "Bengals": "CIN",
        "Browns": "CLE", "Cowboys": "DAL", "Broncos": "DEN", "Lions": "DET", "Packers": "GB", "Texans": "HOU", "Colts": "IND",
        "Jaguars": "JAX", "Chiefs": "KC", "Raiders": "LV", "Chargers": "LAC", "Rams": "LA", "Dolphins": "MIA", "Vikings": "MIN",
        "Patriots": "NE", "Saints": "NO", "Giants": "NYG", "Jets": "NYJ", "Eagles": "PHI", "Steelers": "PIT", "49ers": "SF",
        "Seahawks": "SEA", "Buccaneers": "TB", "Titans": "TEN", "Commanders": "WAS"}


def team(t):
    t = (t or "").upper().strip()
    return ALIAS.get(t, t)


def num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def get_json(url, headers=None, tries=3, timeout=40):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (400, 401, 403, 404):
                break
        except Exception as e:
            last = type(e).__name__
        time.sleep(3 * (i + 1))
    raise RuntimeError(last or "fetch failed")


def put(stats, key, v):
    v = num(v)
    if v is not None:
        stats[key] = round(v, 4)


# ---------------- Sleeper ----------------
SLEEPER_POS = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "K": "K", "DEF": "DST"}
SLEEPER_SKILL = {"pyd": "pass_yd", "ptd": "pass_td", "ints": "pass_int", "ryd": "rush_yd", "rtd": "rush_td",
                 "cyd": "rec_yd", "ctd": "rec_td", "fl": "fum_lost"}


def fetch_sleeper(week):
    out, info = [], {}
    for sp, pos in SLEEPER_POS.items():
        url = f"https://api.sleeper.app/projections/nfl/{SEASON}/{week}?season_type=regular&position[]={sp}"
        rows = get_json(url)
        info[pos] = len(rows)
        for e in rows:
            p, st = e.get("player") or {}, e.get("stats") or {}
            if int(e.get("week") or week) != week:
                continue
            s = {}
            if pos in SKILL:
                if not any(k in st for k in ("pass_yd", "rush_yd", "rec_yd", "rush_att", "rec", "pass_att")):
                    continue            # no projection for this player (not the same as a 0 projection)
                for k, sk in SLEEPER_SKILL.items():
                    put(s, k, st.get(sk, 0))     # Sleeper leaves zero stats out
                name, tm = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(), team(e.get("team") or p.get("team"))
            elif pos == "K":
                if "fgm" not in st and "xpm" not in st:
                    continue
                put(s, "fg", st.get("fgm", 0)); put(s, "xp", st.get("xpm", 0))
                u40 = sum(num(st.get(k)) or 0 for k in ("fgm_0_19", "fgm_20_29", "fgm_30_39"))
                b40, b50 = num(st.get("fgm_40_49")) or 0, num(st.get("fgm_50p")) or 0
                if u40 + b40 + b50 > 0:
                    s.update({"fg_u40": round(u40, 4), "fg_40": round(b40, 4), "fg_50": round(b50, 4)})
                name, tm = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(), team(e.get("team") or p.get("team"))
            else:
                if "pts_allow" not in st:
                    continue
                put(s, "pa", st.get("pts_allow")); put(s, "sk", st.get("sack", 0)); put(s, "dint", st.get("int", 0))
                put(s, "fr", st.get("fum_rec", 0)); put(s, "dtd", st.get("def_td", 0)); put(s, "sf", st.get("safe", 0))
                tm = team(e.get("player_id") or e.get("team") or p.get("team"))
                name = tm + " D/ST"
            if not tm:
                continue
            out.append({"src": "sleeper", "name": name, "team": tm, "pos": pos, "id": str(e.get("player_id") or ""), "stats": s})
        time.sleep(0.5)
    return out, info


# ---------------- ESPN ----------------
ESPN_SKILL = {"pyd": "3", "ptd": "4", "ints": "20", "ryd": "24", "rtd": "25", "cyd": "42", "ctd": "43", "fl": "72"}


def fetch_espn(week):
    filt = {"players": {"filterStatsForCurrentSeasonScoringPeriodId": {"value": [week]}, "limit": 1500,
                        "sortPercOwned": {"sortPriority": 1, "sortAsc": False}, "filterSlotIds": {"value": [0, 2, 4, 6, 16, 17]}}}
    url = (f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{SEASON}/segments/0/leaguedefaults/1"
           f"?scoringPeriodId={week}&view=kona_player_info")
    j = get_json(url, {"X-Fantasy-Filter": json.dumps(filt), "X-Fantasy-Source": "kona", "X-Fantasy-Platform": "kona-PROD",
                       "Referer": "https://fantasy.espn.com/football/players/projections"})
    out, info = [], {"players": len(j.get("players") or [])}
    drop = {"pos": 0, "team": 0, "no_week_proj": 0}
    for row in j.get("players") or []:
        p = row.get("player") or {}
        pos = ESPN_POS.get(p.get("defaultPositionId"))
        tm = ESPN_TEAM.get(p.get("proTeamId"))
        if not pos:
            drop["pos"] += 1; continue
        if not tm:
            drop["team"] += 1; continue        # free agent (proTeamId 0)
        cand = [x for x in (p.get("stats") or []) if x.get("statSourceId") == 1 and x.get("scoringPeriodId") == week and x.get("stats")]
        st = next((x for x in cand if x.get("statSplitTypeId") == 1), cand[0] if cand else None)
        if not st:
            drop["no_week_proj"] += 1; continue
        v, s = st["stats"], {}
        g = lambda k: num(v.get(k)) or 0
        if pos in SKILL:
            for k, sk in ESPN_SKILL.items():
                s[k] = round(g(sk), 4)
            name = p.get("fullName") or ""
        elif pos == "K":
            s.update({"fg": round(g("83"), 4), "fg_u40": round(g("80"), 4), "fg_40": round(g("77"), 4), "fg_50": round(g("74"), 4),
                      "xp": round(g("86"), 4)})
            name = p.get("fullName") or ""
        else:
            if "120" not in v:
                continue
            s.update({"pa": round(g("120"), 4), "sk": round(g("99"), 4), "dint": round(g("95"), 4), "fr": round(g("96"), 4),
                      "dtd": round(g("105") or g("94"), 4), "sf": round(g("98"), 4)})
            name = tm + " D/ST"
        out.append({"src": "espn", "name": name, "team": tm, "pos": pos, "id": str(p.get("id") or ""), "stats": s})
    info["kept"], info["dropped"] = len(out), drop
    return out, info


# ---------------- CBS (through our Worker) ----------------
CBS_SKILL = {"pyd": "PaYd", "ptd": "PaTD", "ints": "PaInt", "ryd": "RuYd", "rtd": "RuTD", "cyd": "ReYd", "ctd": "ReTD", "fl": "FL"}


def cbs_players():
    """Every player on a league roster (CBS id, name, position, NFL team), from the Worker's /rosters feed."""
    j = get_json(WORKER + "/rosters")
    if not j.get("ok"):
        raise RuntimeError(f"worker rosters: {j.get('error')}")
    d = j.get("data") or {}
    teams = (d.get("rosters") or {}).get("teams") or d.get("teams") or []
    seen = {}
    for t in teams:
        for p in t.get("players") or []:
            pid = str(p.get("id") or "")
            if pid and pid not in seen:
                pos = str(p.get("position") or "").upper()
                seen[pid] = {"id": pid, "name": (p.get("fullname") or "").strip(),
                             "pos": "DST" if pos in ("D", "DEF", "DST") else pos, "team": team(p.get("pro_team"))}
    return list(seen.values())


def fetch_cbs(week):
    pl = [p for p in cbs_players() if p["pos"] in SKILL + ("K", "DST")]
    out, info, bad = [], {"rostered": len(pl), "calls": 0}, 0
    for i in range(0, len(pl), 40):              # Worker Free plan: 50 outgoing requests per call -> 40 players per call
        chunk = pl[i:i + 40]
        q = urllib.parse.urlencode({"week": week, "ids": ",".join(p["id"] for p in chunk)})
        j = get_json(f"{WORKER}/proj?{q}", timeout=60)
        info["calls"] += 1
        if not j.get("ok"):
            raise RuntimeError(f"worker proj: {j.get('error')}")
        data = j.get("data") or {}
        for p in chunk:
            pr = data.get(p["id"])
            if not isinstance(pr, dict) or not pr:
                bad += 1
                continue
            s, pos = {}, p["pos"]
            if pos in SKILL:
                for k, ck in CBS_SKILL.items():
                    put(s, k, pr.get(ck, 0))
            elif pos == "K":
                put(s, "fg", pr.get("FG", 0)); put(s, "xp", pr.get("XP", 0))
                u40 = sum(num(pr.get(k)) or 0 for k in ("FG19", "FG29", "FG39"))
                b40, b50 = num(pr.get("FG49")) or 0, num(pr.get("FG50")) or 0
                if u40 + b40 + b50 > 0:
                    s.update({"fg_u40": round(u40, 4), "fg_40": round(b40, 4), "fg_50": round(b50, 4)})
            else:
                if num(pr.get("PA")) is None:
                    continue
                put(s, "pa", pr.get("PA")); put(s, "sk", pr.get("SACK", 0)); put(s, "dint", pr.get("Int", 0))
                put(s, "fr", pr.get("DFR", 0))
                tds = [num(pr.get(k)) for k in ("IntTD", "DFRTD", "DFTD", "STTD")]
                if any(t is not None for t in tds):
                    s["dtd"] = round(sum(t or 0 for t in tds), 4)
                if "SF" in pr:
                    put(s, "sf", pr.get("SF"))
            name = (p["team"] + " D/ST") if pos == "DST" else p["name"]
            out.append({"src": "cbs", "name": name, "team": p["team"], "pos": pos, "id": p["id"], "stats": s})
        time.sleep(1)
    info["no_projection"] = bad
    return out, info


# ---------------- FantasyPros (existing fetcher) ----------------
def fetch_fp_src(week):
    import fetch_fp
    players, info, code = fetch_fp.fetch_best(week)
    if code:
        raise RuntimeError(f"fantasypros code {code}")
    out = []
    for p in players or []:
        s = {k: round(float(p.get(k, 0) or 0), 4) for k in ("pyd", "ptd", "ints", "ryd", "rtd", "cyd", "ctd")}
        out.append({"src": "fp", "name": p["name"], "team": team(p.get("team")), "pos": p["pos"], "id": "", "stats": s,
                    **({"std": p["std"]} if p.get("std") is not None else {})})
    return out, {"players": len(out), "source": (info or {}).get("source")}


def fetch_fp_src_from(players):
    """FantasyPros records from an fp pull that run_projections.py already made (no second request)."""
    out = []
    for p in players or []:
        s = {k: round(float(p.get(k, 0) or 0), 4) for k in ("pyd", "ptd", "ints", "ryd", "rtd", "cyd", "ctd")}
        out.append({"src": "fp", "name": p["name"], "team": team(p.get("team")), "pos": p["pos"], "id": "", "stats": s})
    return out


FETCHERS = {"sleeper": fetch_sleeper, "espn": fetch_espn, "cbs": fetch_cbs, "fp": fetch_fp_src}


def fetch_all(week, only=None):
    recs, status = [], {}
    for name, fn in FETCHERS.items():
        if only and name not in only:
            continue
        t0 = time.time()
        try:
            r, info = fn(week)
            recs += r
            status[name] = {"ok": True, "records": len(r), "secs": round(time.time() - t0, 1), "info": info}
        except Exception as e:
            status[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:200], "secs": round(time.time() - t0, 1)}
    return recs, status


if __name__ == "__main__":
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--out", default="sources.json")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    recs, status = fetch_all(a.week, a.only)
    json.dump({"week": a.week, "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               "status": status, "records": recs}, open(a.out, "w"), separators=(",", ":"))
    print(json.dumps(status, indent=1))
