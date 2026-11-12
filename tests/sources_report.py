"""Coverage report for the consensus engine test run (prints only; used by .github/workflows/sources-check.yml)."""
import collections, json, sys
s = json.load(open(sys.argv[1])); p = json.load(open(sys.argv[2]))
r = s["records"]
print("records by source/pos:", sorted(collections.Counter((x["src"], x["pos"]) for x in r).items()))
print("consensus:", p.get("consensus"))
pl = [x for x in p["players"] if x.get("c") and not x.get("bye")]
for lim in (5, 8):
    big = [x for x in pl if (x.get("own") if x.get("own") is not None else x["m"]) >= lim]
    print(f"players with own model >= {lim}: by number of sources", sorted(collections.Counter(len(x.get("cs", [])) for x in big).items()))
big = [x for x in pl if (x.get("own") if x.get("own") is not None else x["m"]) >= 5]
print("under 2 sources (own>=5):", [(x["n"], x["t"], x["p"], x.get("cs")) for x in big if len(x.get("cs", [])) < 2][:40])
byp = collections.defaultdict(list)
for x in pl:
    if x.get("own") is not None and x.get("cs") and len(x["cs"]) >= 2:
        byp[x["p"]].append(x["m"] - x["own"])
print("consensus minus own model, avg by pos:", {k: (len(v), round(sum(v) / len(v), 2)) for k, v in byp.items()})
names = {"Dak Prescott", "Josh Allen", "Bhayshul Tuten", "Cam Skattebo", "Tucker Kraft", "CeeDee Lamb", "Cam Little", "HOU D/ST",
         "Jaylen Warren", "Stefon Diggs", "Javonte Williams", "Michael Mayer", "Harrison Butker", "BAL D/ST", "Devaughn Vele", "KC Concepcion"}
for x in p["players"]:
    if x["n"] in names:
        print(f"  {x['n']:18s} {x['p']:3s} m {x['m']:5.2f} own {x.get('own')} sp {x.get('sp')} | {x.get('b', '')[:80]}")
espn_k = [x for x in r if x["src"] == "espn"]
print("espn by pos:", sorted(collections.Counter(x["pos"] for x in espn_k).items()))
