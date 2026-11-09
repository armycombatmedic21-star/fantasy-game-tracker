"""Fetch FantasyPros consensus RAW stat projections (QB/RB/WR/TE) for one NFL week -> fp.json for fgt_model.py --fp.

Preferred: FantasyPros' official API with Wes's personal key (env FP_API_KEY, GitHub secret) -> every player.
Fallback: the public projection pages, which only embed the top 10 per position.
We only take raw stats (yards, TDs, INTs), never FantasyPros' point totals (their points don't use our tiered
scoring; Drop 1 §3.8). Data from FantasyPros: personal, non-commercial use under their API terms.

Usage: python3 model/fetch_fp.py --week N --out fp.json
Exit code 0 = fp.json written for exactly week N; 2 = FantasyPros hasn't posted week N yet (page shows another week);
1 = fetch/parse problem. The page's own week is checked so we never blend last week's numbers.
"""
import argparse, datetime, json, re, sys, time, urllib.parse, urllib.request

POS = ["qb", "rb", "wr", "te"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36")
# our fp.json field -> FantasyPros row keys that can hold it (first one present wins)
FIELDS = {
    "pyd": ["pass_yds", "passing_yds", "pass_yards"],
    "ptd": ["pass_tds", "passing_tds", "pass_td"],
    "ints": ["pass_ints", "ints", "int", "interceptions"],
    "ryd": ["rush_yds", "rushing_yds", "rush_yards"],
    "rtd": ["rush_tds", "rushing_tds", "rush_td"],
    "cyd": ["rec_yds", "receiving_yds", "rec_yards"],
    "ctd": ["rec_tds", "receiving_tds", "rec_td"],
}
NEEDED = {"qb": ["pyd", "ptd", "ints", "ryd", "rtd"], "rb": ["ryd", "rtd", "cyd", "ctd"],
          "wr": ["cyd", "ctd"], "te": ["cyd", "ctd"]}


def get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml",
                                                       "Accept-Language": "en-US,en;q=0.9"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # network hiccup or a temporary block: wait and retry
            last = e
            time.sleep(4 * (i + 1))
    raise RuntimeError(f"fetch failed: {url}: {last}")


def rows_from(html):
    """Every embedded "rows":[...] array; return the one that holds player rows."""
    dec = json.JSONDecoder()
    for m in re.finditer(r'"rows"\s*:\s*\[', html):
        try:
            arr, _ = dec.raw_decode(html, m.end() - 1)
        except ValueError:
            continue
        if isinstance(arr, list) and arr and isinstance(arr[0], dict) and isinstance(arr[0].get("player"), dict):
            return arr
    return None


def page_week(html):
    m = re.search(r"<title>\s*Week\s+(\d+)\b", html)
    return int(m.group(1)) if m else None


def num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


API_HOSTS = ["https://api.fantasypros.com/public/v2/json/nfl/{season}/projections",
             "https://api.fantasypros.com/v2/json/nfl/{season}/projections"]
API_FIELDS = {"pyd": ["pass_yds"], "ptd": ["pass_tds"], "ints": ["pass_ints"], "ryd": ["rush_yds"], "rtd": ["rush_tds"],
              "cyd": ["rec_yds"], "ctd": ["rec_tds"]}


def fetch_api(week, key, season=2026):
    """FantasyPros official API (personal key, sent as x-api-key), one request per position (QB, RB, WR, TE).
    Free keys return a truncated list (top 10 per request); a full key returns every player with the same code.
    Returns (players, info, code) like fetch(). The key is never logged or written anywhere."""
    import urllib.error
    info, players, by_pos, host_ok = {"source": "api", "requests": 0}, [], {}, None
    for pos in ("QB", "RB", "WR", "TE"):
        q = urllib.parse.urlencode({"week": week, "position": pos, "scoring": "STD"})
        j, last = None, None
        for host in ([host_ok] if host_ok else API_HOSTS):
            try:
                info["requests"] += 1
                req = urllib.request.Request(host.format(season=season) + "?" + q,
                                             headers={"x-api-key": key, "User-Agent": "fgt-projections/1.0", "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    j = json.loads(r.read().decode("utf-8", "replace"))
                host_ok = host
                break
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code} at {host.split('/json')[0]}"
            except Exception as e:
                last = f"{type(e).__name__} at {host.split('/json')[0]}"
        if j is None:
            info["error"] = last
            return None, info, 1
        rows = j.get("players") or []
        info.setdefault("total_available", {})[pos] = j.get("count")
        info["endpoint"] = host_ok.split("/json")[0]
        info["stat_keys"] = sorted({k for p in rows[:20] for k in (p.get("stats") or {})})[:40]
        try:
            api_week = int(j.get("week"))
        except (TypeError, ValueError):
            api_week = None
        info["api_week"] = api_week
        if api_week != week:
            return None, info, 2          # FantasyPros hasn't posted this week yet
        for p in rows:
            st = p.get("stats") or {}
            rec = {"name": p.get("name") or p.get("player_name") or "", "pos": pos,
                   "team": (p.get("team_id") or p.get("team") or "").upper()}
            for f, ks in API_FIELDS.items():
                k = next((k for k in ks if k in st), None)
                rec[f] = round(num(st[k]), 3) if k else 0.0
            if rec["name"]:
                players.append(rec)
                by_pos[pos] = by_pos.get(pos, 0) + 1
        time.sleep(1.2)                   # API terms: max 1 request per second
    info["by_pos"] = by_pos
    info["truncated"] = any(int(info["total_available"].get(p) or 0) > by_pos.get(p, 0) for p in by_pos)
    return players, info, (0 if players else 1)


def fetch_best(week):
    """Official API when FP_API_KEY is set (full player list); otherwise the public pages (top 10 per position)."""
    import os
    key = os.environ.get("FP_API_KEY", "").strip()
    if key:
        players, info, code = fetch_api(week, key)
        if code in (0, 2):
            return players, info, code
        p2, i2, c2 = fetch(week)          # API problem: fall back to the public pages
        i2["api_problem"] = info
        return p2, i2, c2
    return fetch(week)


def fetch(week):
    players, info = [], {"source": "pages"}
    for pos in POS:
        html = get(f"https://www.fantasypros.com/nfl/projections/{pos}.php?week={week}")
        wk = page_week(html)
        rows = rows_from(html)
        keys = sorted(rows[0].keys()) if rows else []
        info[pos] = {"page_week": wk, "rows": len(rows or []), "keys": keys}
        if wk != week:
            return None, info, 2
        if not rows:
            return None, info, 1
        missing = [f for f in NEEDED[pos] if not any(k in keys for k in FIELDS[f])]
        if missing:   # FantasyPros changed its column names: stop rather than blend zeros
            info[pos]["missing"] = missing
            return None, info, 1
        for r in rows:
            p = r.get("player") or {}
            name, team = p.get("name") or "", (p.get("team") or "").upper()
            if not name:
                continue
            rec = {"name": name, "pos": pos.upper(), "team": team}
            for f, ks in FIELDS.items():
                k = next((k for k in ks if k in r), None)
                rec[f] = round(num(r[k]), 3) if k else 0.0
            players.append(rec)
        time.sleep(1.5)   # be polite: 4 page loads per run
    return players, info, 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--out", default="fp.json")
    a = ap.parse_args()
    try:
        players, info, code = fetch_best(a.week)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)[:300]}))
        sys.exit(1)
    if code:
        print(json.dumps({"ok": False, "code": code, "info": info}))
        sys.exit(code)
    out = {"source": f"FantasyPros consensus raw stats, week {a.week}",
           "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "week": a.week, "info": info, "players": players}
    json.dump(out, open(a.out, "w"), separators=(",", ":"))
    print(json.dumps({"ok": True, "week": a.week, "players": len(players), "info": info}))
