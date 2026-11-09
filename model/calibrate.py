"""Win % calibration + blend check on our league's real games (CBS lineups and official points).

For each past week W: rebuild projections exactly as they would have been before week W (data through W-1,
that week's lines and injury report), unblended and 50/50 FantasyPros-blended. Then simulate every real
starting lineup the way the app does (same distributions, scale, same-team correlation, ties -> bench) and
compare with what happened.

Reports:
  - player MAE (rostered players with a game): ours, FantasyPros alone, 50/50 blend
  - team totals: bias, how often the actual total lands inside the 20-80% range, CRPS for each spread multiplier K
  - matchups: Brier score / log loss of the pregame win % for each K, and a calibration table
Usage: python3 model/calibrate.py DATA_DIR [--weeks 4,5,6,7,8,9] [--k-grid 0.9,1.0,...]
"""
import argparse, glob, json, math, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fgt_model as M

N = 20000
RHO = {("QB", "WR1"): .45, ("QB", "K"): .25, ("WR", "K"): .15, ("RB", "WR1"): .15}


def rho(a, b):
    def w1(x): return x["pos"] == "WR" and x.get("wr1")
    if (a["pos"] == "QB" and w1(b)) or (b["pos"] == "QB" and w1(a)): return .45
    s = lambda x, y: (a["pos"] == x and b["pos"] == y) or (a["pos"] == y and b["pos"] == x)
    if s("QB", "K"): return .25
    if s("WR", "K"): return .15
    if (a["pos"] == "RB" and w1(b)) or (b["pos"] == "RB" and w1(a)): return .15
    return 0.0


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def team_code(t):
    t = (t or "").upper()
    return M.ALIAS.get(t, t)


class Proj:
    def __init__(self, res):
        self.byKey, self.byName, self.raw = {}, {}, res["players"]
        for r in self.raw:
            self.byKey[r["k"]] = r
            self.byName.setdefault(r["k"].split("|")[0], []).append(r)

    def find(self, name, pos, nfl):
        t = team_code(nfl)
        if pos == "DST":
            return self.byKey.get("DST|" + t)
        nm = M.norm_name(name)
        if nm + "|" + t in self.byKey:
            return self.byKey[nm + "|" + t]
        same = [r for r in self.byName.get(nm, []) if r["p"] == pos]
        if len(same) == 1:
            return same[0]
        last, fi = nm.split(" ")[-1] if nm else "", nm[:1]
        c = [r for r in self.raw if r["t"] == t and r["p"] == pos and r["k"].split("|")[0].split(" ")[-1] == last]
        c2 = [r for r in c if r["k"][:1] == fi]
        return c2[0] if len(c2) == 1 else (c[0] if len(c) == 1 else None)


def sims_for(rec, pos, seed):
    if not rec or not rec.get("c"):
        return np.zeros(N)
    rng = np.random.default_rng(seed)
    s = M.sim_player(rng, pos, rec["c"], rec.get("pp", 1.0), N)
    return np.round(s * rec.get("sc", 1.0))


def correlate(members, seed):
    by = {}
    for m in members:
        by.setdefault(m["nfl"], []).append(m)
    rng = np.random.default_rng(seed)
    for g in by.values():
        if len(g) < 2:
            continue
        C = np.array([[1.0 if i == j else rho(a, b) for j, b in enumerate(g)] for i, a in enumerate(g)])
        if not (C - np.eye(len(g))).any():
            continue
        for _ in range(10):
            try:
                L = np.linalg.cholesky(C); break
            except np.linalg.LinAlgError:
                C = np.where(np.eye(len(g)) == 1, 1, C * 0.9)
        else:
            continue
        X = rng.standard_normal((N, len(g))) @ L.T
        for a, m in enumerate(g):
            srt = np.sort(m["arr"])
            out = np.empty(N)
            out[np.argsort(X[:, a])] = srt
            m["arr"] = out


def crps(samples, y):
    s = np.sort(samples)
    n = len(s)
    e1 = np.mean(np.abs(s - y))
    i = np.arange(1, n + 1)
    e2 = 2 * np.sum((2 * i - n - 1) * s) / (n * n)
    return e1 - 0.5 * e2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--weeks", default="2,3,4,5,6,7,8,9")
    ap.add_argument("--k-grid", default="0.8,0.9,1.0,1.1,1.2,1.3,1.35,1.4,1.5,1.6,1.8,2.0")
    ap.add_argument("--cache", default=None)
    a = ap.parse_args()
    weeks = [int(w) for w in a.weeks.split(",")]
    kgrid = [float(k) for k in a.k_grid.split(",")]
    cache = a.cache or os.path.join(a.data, "proj-cache")
    os.makedirs(cache, exist_ok=True)

    pmae = {"ours": [], "fp": [], "blend": []}
    pbypos = {}
    teams_rows, match_rows = [], []
    for w in weeks:
        cbs_f = os.path.join(a.data, f"cbs-week{w}.json")
        if not os.path.exists(cbs_f):
            print(f"week {w}: no CBS data"); continue
        cbs = json.load(open(cbs_f))
        fp_f = os.path.join(a.data, f"fp-week{w}.json")
        variants = {}
        for name, fpf in (("ours", None), ("blend", fp_f if os.path.exists(fp_f) else None)):
            if name == "blend" and not fpf:
                continue
            cf = os.path.join(cache, f"proj-w{w}-{name}.json")
            if not os.path.exists(cf):
                json.dump(M.build(w, fpf, None), open(cf, "w"))
            variants[name] = Proj(json.load(open(cf)))
        # FantasyPros alone (league points from their raw stats), for the player MAE table
        fp_alone = {}
        if os.path.exists(fp_f):
            for p in json.load(open(fp_f))["players"]:
                v = M.fp_to_league(p["pos"], *(p.get(k, 0) or 0 for k in ("pyd", "ptd", "ints", "ryd", "rtd", "cyd", "ctd")), n=4000)
                fp_alone[(M.norm_name(p["name"]), team_code(p.get("team")), p["pos"])] = v

        # player MAE: every rostered QB/RB/WR/TE with a projection and a game, actual = CBS official points
        for t in cbs["teams"]:
            for p in t["players"]:
                if p["pos"] not in ("QB", "RB", "WR", "TE") or fnum(p.get("fpts")) is None:
                    continue
                r = variants["ours"].find(p["name"], p["pos"], p["nfl"])
                if not r or not r.get("c") or r.get("pp", 1) == 0:
                    continue
                y = fnum(p["fpts"])
                pos = p["pos"]
                pmae["ours"].append(abs(r["m"] - y))
                d = pbypos.setdefault(pos, {"ours": [], "fp": [], "blend": []})
                d["ours"].append(abs(r["m"] - y))
                if "blend" in variants:
                    rb = variants["blend"].find(p["name"], p["pos"], p["nfl"])
                    fv = fp_alone.get((M.norm_name(p["name"]), team_code(p["nfl"]), pos))
                    if rb and fv is not None:
                        pmae["blend"].append(abs(rb["m"] - y)); d["blend"].append(abs(rb["m"] - y))
                        pmae["fp"].append(abs(fv * r.get("pp", 1) - y)); d["fp"].append(abs(fv * r.get("pp", 1) - y))

        # matchups
        tmap = {t["id"]: t for t in cbs["teams"]}
        done = set()
        for t in cbs["teams"]:
            o = tmap.get(t["opp"])
            if not o or (o["id"], t["id"]) in done:
                continue
            done.add((t["id"], o["id"]))
            for vname, P in variants.items():
                arrs, sides = {}, {}
                for side, T in (("A", t), ("B", o)):
                    st = [p for p in T["players"] if p.get("status") == "Active"]
                    bn = [p for p in T["players"] if p.get("status") == "Reserve"]
                    mem, miss = [], 0
                    for i, p in enumerate(st):
                        r = P.find(p["name"], p["pos"], p["nfl"])
                        if not r:
                            miss += 1
                        mem.append({"pos": p["pos"], "nfl": team_code(p["nfl"]), "wr1": bool(r and r.get("wr1")),
                                    "arr": sims_for(r, p["pos"], hash((w, T["id"], i, vname)) & 0xffffffff), "y": fnum(p.get("fpts")) or 0.0})
                    bench = np.zeros(N)
                    for i, p in enumerate(bn):
                        r = P.find(p["name"], p["pos"], p["nfl"])
                        bench += sims_for(r, p["pos"], hash((w, T["id"], "b", i, vname)) & 0xffffffff)
                    sides[side] = {"mem": mem, "bench": bench, "miss": miss, "actual": fnum(T.get("pts")) if fnum(T.get("pts")) is not None else sum(m["y"] for m in mem),
                                   "bench_actual": sum(fnum(p.get("fpts")) or 0.0 for p in bn), "name": T["name"]}
                correlate(sides["A"]["mem"] + sides["B"]["mem"], hash((w, t["id"], vname)) & 0xffffffff)
                for side in "AB":
                    tot = np.zeros(N)
                    for m in sides[side]["mem"]:
                        tot += m["arr"]
                    sides[side]["tot"] = tot
                A, B = sides["A"], sides["B"]
                rec = {"week": w, "variant": vname, "a": A["name"], "b": B["name"], "ya": A["actual"], "yb": B["actual"],
                       "ma": float(A["tot"].mean()), "mb": float(B["tot"].mean()), "miss": A["miss"] + B["miss"],
                       "won": 1.0 if A["actual"] > B["actual"] else 0.0 if A["actual"] < B["actual"] else (1.0 if A["bench_actual"] > B["bench_actual"] else 0.0), "p": {}, "crps": {}, "in2080": {}}
                for K in kgrid:
                    ta = A["tot"].mean() + K * (A["tot"] - A["tot"].mean())
                    tb = B["tot"].mean() + K * (B["tot"] - B["tot"].mean())
                    ba = A["bench"].mean() + K * (A["bench"] - A["bench"].mean())
                    bb = B["bench"].mean() + K * (B["bench"] - B["bench"].mean())
                    win = np.where(np.round(ta) > np.round(tb), 1.0, np.where(np.round(ta) < np.round(tb), 0.0, np.where(ba > bb, 1.0, np.where(ba < bb, 0.0, 0.5))))
                    rec["p"][K] = float(win.mean())
                    rec["crps"][K] = (crps(ta, A["actual"]) + crps(tb, B["actual"])) / 2
                    rec["in2080"][K] = (int(np.percentile(ta, 20) <= A["actual"] <= np.percentile(ta, 80)) + int(np.percentile(tb, 20) <= B["actual"] <= np.percentile(tb, 80))) / 2
                match_rows.append(rec)
        print(f"week {w}: done ({len(done)} matchups, variants {list(variants)})", flush=True)

    # ---------- report ----------
    out = {"weeks": weeks, "player_mae": {k: (round(float(np.mean(v)), 3), len(v)) for k, v in pmae.items() if v},
           "player_mae_by_pos": {pos: {k: (round(float(np.mean(v)), 3), len(v)) for k, v in d.items() if v} for pos, d in pbypos.items()}}
    for vname in ("ours", "blend"):
        rows = [r for r in match_rows if r["variant"] == vname]
        if not rows:
            continue
        bias = np.mean([(r["ya"] - r["ma"] + r["yb"] - r["mb"]) / 2 for r in rows])
        mae_t = np.mean([(abs(r["ya"] - r["ma"]) + abs(r["yb"] - r["mb"])) / 2 for r in rows])
        diff_err = [((r["ya"] - r["yb"]) - (r["ma"] - r["mb"])) for r in rows]
        per_k = {}
        for K in kgrid:
            ps = np.array([r["p"][K] for r in rows]); ys = np.array([r["won"] for r in rows])
            psc = np.clip(ps, 0.01, 0.99)
            per_k[K] = {"brier": round(float(np.mean((ps - ys) ** 2)), 4),
                        "logloss": round(float(-np.mean(ys * np.log(psc) + (1 - ys) * np.log(1 - psc))), 4),
                        "crps_team": round(float(np.mean([r["crps"][K] for r in rows])), 3),
                        "in_20_80": round(float(np.mean([r["in2080"][K] for r in rows])), 3)}
        bestK = min(kgrid, key=lambda K: per_k[K]["crps_team"])
        bestK_ll = min(kgrid, key=lambda K: per_k[K]["logloss"])
        cal = []
        for lo, hi in ((0, .3), (.3, .45), (.45, .55), (.55, .7), (.7, 1.01)):
            sel = [r for r in rows if lo <= max(r["p"][bestK], 1 - r["p"][bestK]) < hi] if False else \
                  [r for r in rows if lo <= r["p"][bestK] < hi]
            if sel:
                cal.append({"range": f"{lo:.2f}-{min(hi,1):.2f}", "n": len(sel), "avg_p": round(float(np.mean([r['p'][bestK] for r in sel])), 3),
                            "won": round(float(np.mean([r['won'] for r in sel])), 3)})
        out[vname] = {"matchups": len(rows), "missing_starters": int(sum(r["miss"] for r in rows)),
                      "team_bias_actual_minus_proj": round(float(bias), 2), "team_mae": round(float(mae_t), 2),
                      "margin_error_sd": round(float(np.std(diff_err)), 2),
                      "best_k_by_team_crps": bestK, "best_k_by_matchup_logloss": bestK_ll, "per_k": per_k, "calibration_at_best_k": cal,
                      "favorite_won": round(float(np.mean([1.0 if (r["p"][bestK] >= .5) == (r["won"] == 1) else 0.0 for r in rows])), 3)}
    json.dump({"summary": out, "matchups": match_rows}, open(os.path.join(a.data, "calibration.json"), "w"), indent=1, default=str)
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
