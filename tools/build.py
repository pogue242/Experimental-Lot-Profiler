#!/usr/bin/env python3
"""build.py — build a citywide Lot Profiler release straight from an unmodified MapPLUTO file"""
import argparse, gzip, json, os, subprocess, sys, time
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp_build as L

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
REPO_DATA = os.path.abspath(os.path.join(ROOT, "..", "..", "Data"))

NEED = ["BBL", "Address", "LandUse", "UnitsRes", "BldgArea", "LotArea", "BuiltFAR", "YearBuilt", "ZoneDist1", "BCT2020", "Version"]
REC_FIELDS = ["OwnerName", "OwnerType", "BldgClass", "LandUse", "BldgArea", "ResArea", "ComArea", "OfficeArea",
    "RetailArea", "GarageArea", "StrgeArea", "FactryArea", "OtherArea", "NumBldgs", "NumFloors", "UnitsTotal", "LotFront",
    "LotDepth", "BldgFront", "BldgDepth", "YearAlter1", "YearAlter2", "ZoneDist1", "ZoneDist2", "ZoneDist3", "ZoneDist4",
    "Overlay1", "Overlay2", "SPDist1", "SPDist2", "SPDist3", "LtdHeight", "SplitZone", "ResidFAR", "AffResFAR", "CommFAR",
    "FacilFAR", "ManuFAR", "TrnstZone", "MIHOption1", "MIHOption2", "MIHOption3", "MIHOption4", "ZoneMap", "ZMCode", "CD",
    "Council", "SchoolDist", "PolicePrct", "FireComp", "ZipCode", "HistDist", "Landmark", "AssessLand", "AssessTot",
    "ExemptTot", "CondoNo", "Easements", "EDesigNum", "Sanborn", "TaxMap", "IrrLotCode", "LotType", "ProxCode", "BsmtCode",
    "Ext", "PFIRM15_FLAG", "FIRM07_FLAG", "APPBBL", "APPDate", "BuiltFAR", "DCPEdited"]

def load_areas(bdir):
    import geopandas as gpd
    nta = gpd.read_file(os.path.join(bdir, "9nt8-h7nd.geojson"))
    tr = gpd.read_file(os.path.join(bdir, "63ge-mke6.geojson"))
    for need, df, name in ((["nta2020", "ntaname"], nta, "NTA"), (["boroct2020", "nta2020", "ctlabel", "boroname"], tr, "tract")):
        miss = [c for c in need if c not in df.columns]
        if miss: sys.exit(f"NOTICE: the {name} boundary file lacks {miss}; check the download.")
    return nta.to_crs(4326), tr.to_crs(4326)

def area_entries(gdf, kind, code_col, name_fn):
    import shapely
    from shapely.ops import polylabel
    out, polys = [], {}
    for _, r in gdf.sort_values(code_col).iterrows():
        g = r.geometry
        s = shapely.simplify(g, 1e-5, preserve_topology=True)
        parts = list(s.geoms) if s.geom_type == "MultiPolygon" else [s]
        big = max((g.geoms if g.geom_type == "MultiPolygon" else [g]), key=lambda p: p.area)
        lab = polylabel(big, 1e-5)
        code = str(r[code_col])
        polys[code] = [[[[round(x, 6), round(y, 6)] for x, y in ring.coords] for ring in [p.exterior, *p.interiors]] for p in parts if not p.is_empty]
        b = g.bounds
        out.append({"kind": kind, "code": code, "name": name_fn(r), "label": [round(lab.x, 6), round(lab.y, 6)],
                    "bbox": [round(v, 6) for v in b]})
    return out, polys

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gdb", help="MapPLUTO file geodatabase (.gdb folder)")
    ap.add_argument("--layer", help="layer name (default: the only/first polygon layer)")
    ap.add_argument("--release", help="release id, e.g. 26v2 (default: PLUTO's Version field)")
    ap.add_argument("--released", default="", help="release month shown on the history bar, e.g. 2026-08")
    ap.add_argument("--boundaries", default=os.path.join(REPO_DATA, "boundaries_2020"),
                    help="folder with DCP's 2020 NTA (9nt8-h7nd.geojson) and census tract (63ge-mke6.geojson) files")
    ap.add_argument("--out", default=os.path.join(ROOT, "data"))
    ap.add_argument("--work", default=os.path.join(ROOT, "work"), help="cache used by far_join.py to rebuild tiles")
    ap.add_argument("--tiles", default="all", choices=["all", "lots", "blocks", "none"], help="which vector tiles to (re)build")
    ap.add_argument("--no-transit", action="store_true")
    a = ap.parse_args()
    import pyogrio, geopandas as gpd, shapely
    t0 = time.time()

    layers = [n for n, g in pyogrio.list_layers(a.gdb) if g and "Polygon" in g]
    layer = a.layer or (layers[0] if layers else None)
    if not layer: sys.exit("no polygon layer in " + a.gdb)
    info = pyogrio.read_info(a.gdb, layer=layer)
    missing = [f for f in NEED if f not in info["fields"]]
    if missing: sys.exit(f"NOTICE: MapPLUTO is missing fields {missing}. A field may have been renamed; check the data dictionary.")
    rec_fields = [f for f in REC_FIELDS if f in info["fields"]]
    gone = [f for f in REC_FIELDS if f not in info["fields"]]
    if gone: print(f"  note: lot-record fields not in this MapPLUTO (left out): {gone}")
    print(f"reading {layer} ({info['features']:,} lots, {info['crs']}) …", flush=True)
    df = pyogrio.read_dataframe(a.gdb, layer=layer, columns=sorted(set(NEED + rec_fields)), use_arrow=True)
    df = df.sort_values("BBL", kind="stable").reset_index(drop=True)
    n = len(df)
    vers = sorted(set(df["Version"].dropna()))
    release = a.release or (vers[0] if len(vers) == 1 else None)
    if not release: sys.exit(f"pass --release (Version values: {vers})")
    if df.BBL.duplicated().any(): sys.exit(f"NOTICE: {int(df.BBL.duplicated().sum())} duplicate BBLs")
    print(f"  {n:,} lots, release {release}, read in {time.time()-t0:.0f}s", flush=True)

    g_ft = df.geometry.values
    cen = gpd.GeoSeries(shapely.centroid(g_ft), crs=df.crs).to_crs(4326)
    g = gpd.GeoSeries(g_ft, crs=df.crs).to_crs(4326).values
    clng, clat = cen.x.values, cen.y.values
    ox, oy = round(float(np.nanmin(clng)) - 0.01, 3), round(float(np.nanmin(clat)) - 0.01, 3)
    cxq = np.round((clng - ox) * L.Q).astype(np.int64); cyq = np.round((clat - oy) * L.Q).astype(np.int64)
    b = shapely.bounds(g)
    bu = L.BOX_UNIT
    box = np.stack([clng - b[:, 0], clat - b[:, 1], b[:, 2] - clng, b[:, 3] - clat], 1)
    box = np.clip(np.ceil(np.maximum(box, 0) / bu), 0, 65535).astype(np.uint16)

    lu = L.land_use_index(df.LandUse.values)
    units = df.UnitsRes.fillna(0).clip(0, 65535).to_numpy(np.float64)
    ub = L.unit_band(units, lu)
    la = df.LotArea.to_numpy(np.float64)
    bfar = np.where(la > 0, df.BldgArea.to_numpy(np.float64) / np.where(la > 0, la, 1), np.nan).astype(np.float32)
    pf = df.BuiltFAR.to_numpy(np.float64)
    both = ~np.isnan(bfar) & ~np.isnan(pf)
    agree = np.abs(np.round(bfar[both], 2) - pf[both]) <= 0.011
    print(f"  built FAR: BldgArea/LotArea matches PLUTO BuiltFAR (±0.01) on {agree.mean()*100:.2f}% of {both.sum():,} lots", flush=True)
    year = df.YearBuilt.fillna(0).clip(0, 65535).astype(np.uint16).values
    floors = L.whole_floors(df.NumFloors.to_numpy(np.float64) if "NumFloors" in df.columns else np.zeros(n))
    zones = sorted({z for z in df.ZoneDist1.fillna("") if z is not None})
    zi = {z: k for k, z in enumerate(zones)}
    zone = np.array([zi[z or ""] for z in df.ZoneDist1.fillna("")], np.uint16)

    nta_g, tr_g = load_areas(a.boundaries)
    nta_e, nta_p = area_entries(nta_g, "nta", "nta2020", lambda r: r["ntaname"])
    tr_e, tr_p = area_entries(tr_g, "tract", "boroct2020", lambda r: f"{r['boroname']} tract {r['ctlabel']}")
    areas = nta_e + tr_e
    a_idx = {(e["kind"], e["code"]): k for k, e in enumerate(areas)}
    tr2nta = dict(zip(tr_g.boroct2020.astype(str), tr_g.nta2020.astype(str)))
    bct = df.BCT2020.fillna("").astype(str).values
    tract = np.array([a_idx.get(("tract", c), 65535) for c in bct], np.uint16)
    nta = np.array([a_idx.get(("nta", tr2nta.get(c, "")), 65535) for c in bct], np.uint16)
    lost = np.where(tract == 65535)[0]
    if len(lost):
        pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(clng[lost], clat[lost]), crs=4326)
        j = gpd.sjoin(pts, tr_g[["boroct2020", "geometry"]], predicate="within", how="left")
        j = j[~j.index.duplicated()]
        for k, code in zip(lost, j.boroct2020.fillna("").astype(str).values):
            if code:
                tract[k] = a_idx[("tract", code)]; nta[k] = a_idx.get(("nta", tr2nta.get(code, "")), 65535)
        still = lost[tract[lost] == 65535]
        if len(still):
            pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(clng[still], clat[still]), crs=4326).to_crs(2263)
            j = gpd.sjoin_nearest(pts, tr_g[["boroct2020", "geometry"]].to_crs(2263), how="left", max_distance=1000)
            j = j[~j.index.duplicated()]
            for k, code in zip(still, j.boroct2020.fillna("").astype(str).values):
                if code: tract[k] = a_idx[("tract", code)]; nta[k] = a_idx.get(("nta", tr2nta.get(code, "")), 65535)
        print(f"  {len(lost)} lots had no usable BCT2020; {int((tract[lost] != 65535).sum())} placed by centroid in, or within 1,000 ft of, a 2020 tract", flush=True)
    unknown = sorted(set(c for c in bct if c and ("tract", c) not in a_idx))
    if unknown: print(f"  NOTICE: BCT2020 codes not in the 2020 tract file: {unknown[:20]}")
    used_n = set(nta.tolist()); used_t = set(tract.tolist())
    keep = [k for k, e in enumerate(areas) if k in used_n or k in used_t]
    remap = {k: j for j, k in enumerate(keep)}
    areas = [areas[k] for k in keep]
    nta = np.array([remap.get(int(v), 65535) for v in nta], np.uint16)
    tract = np.array([remap.get(int(v), 65535) for v in tract], np.uint16)
    print(f"  {sum(e['kind']=='nta' for e in areas)} NTAs and {sum(e['kind']=='tract' for e in areas)} tracts with lots; "
          f"{int((nta==65535).sum())} lots without an NTA", flush=True)

    bbl = df.BBL.to_numpy(np.int64)
    bkey = bbl // 10000
    keys, blk = np.unique(bkey, return_inverse=True)
    lotno = (bbl % 10000).astype(np.uint16)
    print(f"  {len(keys):,} tax blocks; dissolving block outlines …", flush=True)
    tb = time.time()
    bg = gpd.GeoDataFrame({"b": blk}, geometry=g_ft, crs=df.crs).dissolve(by="b")
    bgeom = gpd.GeoSeries(shapely.simplify(bg.geometry.values, 0.5), crs=df.crs).to_crs(4326).values
    print(f"  blocks dissolved in {time.time()-tb:.0f}s", flush=True)

    out = os.path.join(a.out, release); os.makedirs(out, exist_ok=True)
    tg = time.time()
    shapes = L.ragged(g)
    blobs = L.encode_shapes(shapes, (round(ox * L.Q), round(oy * L.Q)))
    bshapes = L.ragged(bgeom)
    bblobs = L.encode_shapes(bshapes, (round(ox * L.Q), round(oy * L.Q)))
    geom_path = os.path.join(out, "geom.bin")
    g_off = L.write_chunks(geom_path, blobs)
    tmp = geom_path + ".blk"
    b_off = L.write_chunks(tmp, bblobs)
    with open(geom_path, "ab") as fh, open(tmp, "rb") as fb: fh.write(fb.read())
    os.remove(tmp)
    b_off = b_off + g_off[-1]
    print(f"  geom.bin {os.path.getsize(geom_path)/1e6:.1f} MB ({len(g_off)-1} lot chunks, {len(b_off)-1} block chunks) in {time.time()-tg:.0f}s", flush=True)

    tr0 = time.time()
    cols = {}
    for f in rec_fields:
        v = df[f]
        cols[f] = v.astype(object).where(v.notna(), None).tolist()
    r_off = L.write_rec_chunks(os.path.join(out, "rec.bin"), cols, n)
    addr = [(s or "").strip() for s in df.Address.fillna("")]
    with open(os.path.join(out, "addr.txt.gz"), "wb") as fh: fh.write(gzip.compress("\n".join(addr).encode("utf-8"), 9))
    with open(os.path.join(out, "areas.json.gz"), "wb") as fh:
        fh.write(gzip.compress(json.dumps({"nta": nta_p, "tract": tr_p}, separators=(",", ":")).encode(), 9))
    print(f"  rec.bin {os.path.getsize(os.path.join(out,'rec.bin'))/1e6:.1f} MB, addresses, areas in {time.time()-tr0:.0f}s", flush=True)

    bf100 = np.where(np.isnan(bfar), -1, np.round(np.minimum(bfar, 600) * 100)).astype(np.int32)
    props = pd.DataFrame({"i": np.arange(n, dtype=np.int32), "lu": lu.astype(np.int16), "ub": ub.astype(np.int16),
                          "zn": zone.astype(np.int16), "yb": year.astype(np.int16), "bf": bf100,
                          "fl": floors.astype(np.int16)})
    os.makedirs(a.work, exist_ok=True)
    gpd.GeoDataFrame(props, geometry=g, crs=4326).to_parquet(os.path.join(a.work, f"{release}_lots.parquet"))
    if a.tiles in ("all", "lots"):
        L.write_tiles(os.path.join(out, "lots.pmtiles"), L.tile_frame(g, props), "lots", L.LOT_TILE_MINZOOM, 16, name=f"Lot Profiler {release} lots")
    if a.tiles in ("all", "blocks"):
        L.write_tiles(os.path.join(out, "blocks.pmtiles"), L.tile_frame(bgeom, pd.DataFrame({"b": np.arange(len(keys), dtype=np.int32)})),
                      "blocks", 9, 16, name=f"Lot Profiler {release} tax blocks")

    dcx = np.diff(cxq, prepend=0).astype(np.int32); dcy = np.diff(cyq, prepend=0).astype(np.int32)
    header = {
        "format": 3, "release": release, "released": a.released, "built": time.strftime("%Y-%m-%d"),
        "source": f"NYC DCP MapPLUTO {release} ({layer}), unmodified",
        "n": n, "origin": [ox, oy], "q": L.Q, "boxUnit": L.BOX_UNIT, "chunk": L.CHUNK, "bfarScale": 100,
        "dict": {"lu": L.LAND_USE, "ub": L.UNIT_BUCKETS, "fc": L.FAR_CATS, "zone": zones},
        "areas": areas, "nBlocks": int(len(keys)), "recFields": rec_fields,
        "files": {"tiles": "lots.pmtiles", "blockTiles": "blocks.pmtiles", "geom": "geom.bin", "rec": "rec.bin",
                  "addr": "addr.txt.gz", "areas": "areas.json.gz"},
        "tileProps": {"i": "lot index", "lu": "land use", "ub": "building size band", "zn": "zoning index",
                      "yb": "year built", "bf": "built FAR x100 (-1 = none)",
                      "fl": "whole floors, half stories counted down (0 = unknown)"},
        "far": None,
    }
    sections = {"dcx": dcx, "dcy": dcy, "box": box.ravel(), "area": np.clip(np.nan_to_num(la, nan=0), 0, 2**32 - 1).astype(np.uint32),
                "units": units.astype(np.uint16), "bfar": np.where(np.isnan(bfar), 65535, np.round(np.clip(bfar, 0, 655) * 100)).astype(np.uint16), "year": year, "floors": floors, "lu": lu, "ub": ub, "zone": zone,
                "nta": nta, "tract": tract, "blk": blk.astype(np.uint32), "lotno": lotno, "blkKey": keys.astype(np.uint32),
                "gOff": g_off.astype(np.uint32), "bOff": b_off.astype(np.uint32), "rOff": r_off.astype(np.uint32)}
    raw, size = L.write_pack(os.path.join(out, "core.lpk"), b"LPK3", header, sections)
    print(f"  core.lpk {size/1e6:.2f} MB (raw {raw/1e6:.1f} MB)", flush=True)

    entry = {"id": release, "label": f"PLUTO {release}", "released": a.released, "built": header["built"], "dir": release,
             "format": 3, "lots": n, "bytes": L.folder_bytes(out), "core": size,
             "coverage": "New York City", "source": header["source"]}
    L.update_manifest(a.out, entry)
    print(f"release {release}: {n:,} lots, {len(keys):,} blocks -> data/{release}/ "
          f"({L.folder_bytes(out)/1e6:.0f} MB) in {time.time()-t0:.0f}s", flush=True)

    if not a.no_transit and os.path.abspath(a.out) == os.path.abspath(os.path.join(ROOT, "data")):
        print("saving a subway snapshot for this release (tools/transit.py) …")
        r = subprocess.run([sys.executable, os.path.join(HERE, "transit.py"), "--release", release])
        if r.returncode: print(f"  the subway snapshot didn't download; the lots are built. Later run: python tools/transit.py --release {release}")

if __name__ == "__main__":
    main()
