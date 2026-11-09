"""Fetch FantasyPros consensus RAW stat projections (QB/RB/WR/TE) for one NFL week -> fp.json for fgt_model.py --fp.

The public projection pages (fantasypros.com/nfl/projections/{qb,rb,wr,te}.php?week=N) embed the full table as JSON
("rows":[{...}]) in the page itself, no login needed. We only take raw stats (yards, TDs, INTs), never FantasyPros'
point totals (their points don't use our tiered scoring; Drop 1 §3.8).

Usage: python3 model/fetch_fp.py --week N --out fp.json
Exit code 0 = fp.json written for exactly week N; 2 = FantasyPros hasn't posted week N yet (page shows another week);
1 = fetch/parse problem. The page's own week is checked so we never blend last week's numbers.
"""
import argparse, datetime, json, re, sys, time, urllib.request

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


def fetch(week):
    players, info = [], {}
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
        players, info, code = fetch(a.week)
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
