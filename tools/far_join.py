#!/usr/bin/env python3
"""far_join.py — join a maximum-FAR table to a built release, keyed by BBL. This is the hook for the"""
import argparse, json, os, sys, time
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp_build as L

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
KNOWN = {"far_std": {"label": "Maximum FAR", "kind": "base"},
         "far_qual": {"label": "Maximum FAR with qualifying / UAP housing", "short": "UAP", "kind": "bonus"},
         "far_cf": {"label": "Community facility FAR", "kind": "other"},
         "far_comm": {"label": "Commercial FAR", "kind": "other"}}
STATUS = ["modeled", "provisional", "not_modeled"]
NONE = -99999

def category(fdiff, fstd, status):
    fc = np.full(len(fdiff), 255, np.uint8)
    ok = ~np.isnan(fstd)
    fc[ok & (fdiff > 2)] = 0
    fc[ok & (fdiff <= 2) & (fdiff >= 1)] = 1
    fc[ok & (fdiff < 1) & (fdiff >= 0.25)] = 2
    fc[ok & (fdiff < 0.25) & (fdiff >= -0.1)] = 3
    fc[ok & (fdiff < -0.1)] = 4
    fc[ok & (fstd <= 0)] = 5
    fc[status == STATUS.index("not_modeled")] = 7
    return fc

def lot_bbls(core):
    return core["blkKey"][core["blk"]].astype(np.int64) * 10000 + core["lotno"].astype(np.int64)

def rebuild_tiles(release, out, far=None):
    import geopandas as gpd
    src = os.path.join(ROOT, "work", f"{release}_lots.parquet")
    if not os.path.exists(src):
        print(f"  (no {src}; rebuild the release with build.py to add FAR to the lot tiles)"); return
    g = gpd.read_parquet(src)
    g = g[[c for c in ("i", "lu", "ub", "zn", "yb", "bf", "fl", "geometry") if c in g.columns]]
    if far:
        for k, v in far.items(): g[k] = v
    L.write_tiles(os.path.join(out, "lots.pmtiles"), g, "lots", L.LOT_TILE_MINZOOM, 16, name=f"Lot Profiler {release} lots")

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("table", nargs="?"); ap.add_argument("--release", required=True); ap.add_argument("--meta")
    ap.add_argument("--remove", action="store_true"); ap.add_argument("--no-tiles", action="store_true")
    ap.add_argument("--data", default=os.path.join(ROOT, "data"))
    a = ap.parse_args()
    out = os.path.join(a.data, a.release)
    core = L.read_pack(os.path.join(out, "core.lpk"))
    man_path = os.path.join(a.data, "releases.json")
    man = json.load(open(man_path, encoding="utf-8"))
    entry = next(m for m in man if m["id"] == a.release)
    if a.remove:
        for f in ("far.lpk", "far_rec.bin"):
            if os.path.exists(os.path.join(out, f)): os.remove(os.path.join(out, f))
        entry.pop("far", None); json.dump(man, open(man_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        if not a.no_tiles: rebuild_tiles(a.release, out)
        print(f"{a.release}: FAR table removed"); return
    if not a.table: sys.exit("give the FAR table (CSV or Parquet)")
    t0 = time.time()
    df = pd.read_parquet(a.table) if a.table.endswith(".parquet") else pd.read_csv(a.table, dtype={"far_status": str, "far_cat": str, "far_trace": str, "split_shares": str})
    df.columns = [c.lower() for c in df.columns]
    if "bbl" not in df.columns: sys.exit("the FAR table needs a bbl column")
    meta = json.load(open(a.meta, encoding="utf-8")) if a.meta else {}
    df["bbl"] = pd.to_numeric(df["bbl"], errors="coerce").astype("Int64")
    if df.bbl.duplicated().any(): sys.exit(f"NOTICE: {int(df.bbl.duplicated().sum())} duplicate BBLs in the FAR table")
    bbls = lot_bbls(core); n = len(bbls)
    pos = pd.Series(np.arange(n), index=bbls)
    hit = df.bbl.isin(pos.index)
    if (~hit).any(): print(f"  NOTICE: {int((~hit).sum())} FAR rows match no lot in {a.release} (e.g. {df.bbl[~hit].head(5).tolist()})")
    df = df[hit]; idx = pos.loc[df.bbl.astype(np.int64)].to_numpy()
    print(f"  {len(df):,} of {n:,} lots have a FAR row")

    num = [c for c in df.columns if c.startswith("far_") and c not in ("far_status", "far_trace", "far_cat", "far_diff")
           and pd.api.types.is_numeric_dtype(df[c])]
    if "far_std" not in num: sys.exit("the FAR table needs far_std (the base maximum FAR)")
    cols, sections = [], {}
    for c in num:
        v = np.full(n, np.nan, np.float32); v[idx] = df[c].to_numpy(np.float32)
        if np.isnan(v).all(): continue
        m = {**KNOWN.get(c, {"label": c, "short": c[4:].upper(), "kind": "bonus"}), **meta.get("columns", {}).get(c, {})}
        cols.append({"key": c, **m}); sections[c] = v
    status = np.full(n, 255, np.uint8)
    if "far_status" in df.columns:
        s = df.far_status.fillna("").str.strip().str.lower().map({k: i for i, k in enumerate(STATUS)})
        bad = df.far_status[s.isna() & df.far_status.notna()].unique()
        if len(bad): print(f"  NOTICE: unknown far_status values {list(bad)[:10]} (expected {STATUS})")
        status[idx] = s.fillna(255).astype(np.uint8).to_numpy()
    bfar = core["bfar"].astype(np.float64)
    if core["H"].get("bfarScale"): bfar = np.where(bfar == 65535, np.nan, bfar / core["H"]["bfarScale"])
    fstd = sections["far_std"].astype(np.float64)
    if "far_diff" in df.columns:
        fdiff = np.full(n, np.nan, np.float32); fdiff[idx] = pd.to_numeric(df.far_diff, errors="coerce").to_numpy(np.float32)
    else: fdiff = (fstd - bfar).astype(np.float32)
    if "far_cat" in df.columns:
        fc = np.full(n, 255, np.uint8)
        fc[idx] = df.far_cat.map({k: i for i, k in enumerate(L.FAR_CATS)}).fillna(255).astype(np.uint8).to_numpy()
    else:
        fc = category(fdiff.astype(np.float64), fstd, status)
    sections.update({"status": status, "fc": fc, "fdiff": fdiff})

    has_rec = any(c in df.columns for c in ("far_trace", "split_shares"))
    if has_rec:
        rc = {}
        for c in ("far_trace", "split_shares"):
            if c in df.columns:
                col = [None] * n
                for k, v in zip(idx, df[c].tolist()): col[k] = None if pd.isna(v) else str(v)
                rc[c] = col
        sections["rOff"] = L.write_rec_chunks(os.path.join(out, "far_rec.bin"), rc, n).astype(np.uint32)
    header = {"format": 1, "release": a.release, "built": time.strftime("%Y-%m-%d"), "base": "far_std",
              "source": meta.get("source", os.path.basename(a.table)), "rules": meta.get("rules"),
              "columns": cols, "status": STATUS, "cats": L.FAR_CATS + ["Not yet modeled"], "rec": "far_rec.bin" if has_rec else None}
    raw, size = L.write_pack(os.path.join(out, "far.lpk"), b"LPF1", header, sections)
    entry["far"] = {"file": "far.lpk", "source": header["source"], "built": header["built"]}
    if header["rules"]: entry["far"]["rules"] = header["rules"]
    entry["bytes"] = L.folder_bytes(out)
    json.dump(man, open(man_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"  far.lpk {size/1e6:.2f} MB; columns {[c['key'] for c in cols]}; categories {np.bincount(fc[fc<255], minlength=8).tolist()}")

    if not a.no_tiles:
        sc = lambda v: np.where(np.isnan(v), NONE, np.round(np.clip(v, -600, 600) * 100)).astype(np.int32)
        far = {"mf": sc(fstd), "fd": sc(fdiff.astype(np.float64)), "fc": fc.astype(np.int16)}
        for c in cols:
            if c["kind"] == "bonus":
                v = sections[c["key"]].astype(np.float64)
                far["b_" + c["key"][4:]] = sc(v); far["g_" + c["key"][4:]] = sc(v - fstd)
        rebuild_tiles(a.release, out, far)
        entry["bytes"] = L.folder_bytes(out)
        json.dump(man, open(man_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"{a.release}: FAR joined in {time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()
