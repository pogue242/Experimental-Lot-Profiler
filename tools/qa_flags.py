#!/usr/bin/env python3
"""qa_flags.py — flag lots whose PLUTO figures don't add up"""
import argparse, json, os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp_build as L

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FLAGS = {"4": "Built FAR above the floor count", "8": "Housing units but no building floor area",
         "16": "Housing units on vacant land, parking or open space", "32": "Under 250 sq ft of residential floor area per unit"}

def main():
    import pyogrio
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gdb"); ap.add_argument("--release", required=True); ap.add_argument("--data", default=os.path.join(ROOT, "data"))
    a = ap.parse_args()
    out = os.path.join(a.data, a.release)
    core = L.read_pack(os.path.join(out, "core.lpk"))
    bbl = core["blkKey"][core["blk"]].astype(np.int64) * 10000 + core["lotno"].astype(np.int64)
    layer = next(n for n, g in pyogrio.list_layers(a.gdb) if g and "Polygon" in g)
    cols = ["BBL", "LotArea", "BldgArea", "ResArea", "BuiltFAR", "NumFloors", "UnitsRes", "LandUse"]
    d = pyogrio.read_dataframe(a.gdb, layer=layer, columns=cols, read_geometry=False)
    d["BBL"] = d["BBL"].astype(np.int64)
    d = d.drop_duplicates("BBL").set_index("BBL")
    missing = int((~np.isin(bbl, d.index.values)).sum())
    d = d.reindex(bbl)
    num = lambda c: d[c].astype(float).fillna(0).values
    ba, ra, bf, fl, u = num("BldgArea"), num("ResArea"), num("BuiltFAR"), num("NumFloors"), num("UnitsRes")
    lu = d["LandUse"].fillna("").astype(str).values
    flags = np.zeros(len(bbl), np.uint8)
    flags |= np.where((fl > 0) & (bf > fl * 1.5), 4, 0).astype(np.uint8)
    flags |= np.where((u > 0) & (ba == 0), 8, 0).astype(np.uint8)
    flags |= np.where((u > 0) & np.isin(lu, ["09", "10", "11"]), 16, 0).astype(np.uint8)
    flags |= np.where((u >= 3) & (ra > 0) & (ra < 250 * np.maximum(u, 1)), 32, 0).astype(np.uint8)
    idx = np.nonzero(flags)[0].astype(np.uint32)
    header = {"format": 2, "release": a.release, "built": time.strftime("%Y-%m-%d"), "source": os.path.basename(os.path.normpath(a.gdb)), "flags": FLAGS}
    raw, size = L.write_pack(os.path.join(out, "qa.lpk"), b"LPQ2", header, {"idx": idx, "flags": flags[idx]})
    man_path = os.path.join(a.data, "releases.json")
    man = json.load(open(man_path, encoding="utf-8"))
    for m in man:
        if m["id"] == a.release:
            m["qa"] = {"file": "qa.lpk", "built": header["built"]}
            m["bytes"] = L.folder_bytes(out)
    json.dump(man, open(man_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"{a.release}: {len(idx):,} lots flagged, qa.lpk {size/1e3:.0f} KB; {missing} lots not in the FGDB")
    for b, t in FLAGS.items(): print(f"  {t}: {int(((flags & int(b)) > 0).sum()):,}")

if __name__ == "__main__":
    main()
