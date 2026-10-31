#!/usr/bin/env python3
"""convert_25v4.py — turn a 1.5.x release pack (LPK2, one file with shapes inside, built from the"""
import argparse, gzip, json, os, subprocess, sys, time
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp_build as L

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pack"); ap.add_argument("--data", default=os.path.join(ROOT, "data"))
    ap.add_argument("--transit", help="subway snapshot file to tie the release to (default: keep what 1.5.3 had)")
    a = ap.parse_args()
    import shapely, geopandas as gpd
    t0 = time.time()
    P = L.read_pack(a.pack); H = P["H"]
    assert P["_magic"] == b"LPK2", "not a 1.5.x pack"
    release, n = H["release"], H["n"]
    ox, oy = H["origin"]; q = H["q"]; oq = (round(ox * q), round(oy * q))
    rec = json.loads(bytes(P["rec"]))
    V = P["verts"].astype(np.int64).reshape(-1, 2)
    shapes = []
    for i in range(n):
        polys = []
        for p in range(P["polyOff"][i], P["polyOff"][i + 1]):
            rings = []
            for r in range(P["ringOff"][p], P["ringOff"][p + 1]):
                d = V[P["vertOff"][r]:P["vertOff"][r + 1]]
                rings.append(np.cumsum(d, axis=0) + np.array(oq))
            polys.append(rings)
        shapes.append(polys)
    to_poly = lambda polys: shapely.MultiPolygon([shapely.Polygon(rs[0] / q, [h / q for h in rs[1:]]) for rs in polys]) if polys else None
    geoms = [to_poly(s) for s in shapes]
    cx = ox + P["cx"].astype(np.float64) / q; cy = oy + P["cy"].astype(np.float64) / q
    b = np.array([g.bounds if g is not None else (x, y, x, y) for g, x, y in zip(geoms, cx, cy)])
    box = np.stack([cx - b[:, 0], cy - b[:, 1], b[:, 2] - cx, b[:, 3] - cy], 1)
    box = np.clip(np.ceil(np.maximum(box, 0) / L.BOX_UNIT), 0, 65535).astype(np.uint16)
    cxq = np.round((cx - ox) * L.Q).astype(np.int64); cyq = np.round((cy - oy) * L.Q).astype(np.int64)

    blocks = H["blocks"]
    keys = np.array([bk["key"] for bk in blocks], np.uint32)
    bshapes = [[[np.round(np.asarray(r[:-1]) * L.Q).astype(np.int64) for r in poly] for poly in bk["polys"]] for bk in blocks]
    bgeoms = [shapely.MultiPolygon([shapely.Polygon(poly[0], poly[1:]) for poly in bk["polys"]]) if bk["polys"] else None for bk in blocks]
    blk = P["blk"].astype(np.uint32)
    bbl = np.round(P["bbl"]).astype(np.int64)
    assert (keys[blk] == bbl // 10000).all(), "block index mismatch"
    lotno = (bbl % 10000).astype(np.uint16)

    areas, polys = [], {"nta": {}, "tract": {}}
    for ar in H["areas"]:
        xs = [x for poly in ar["polys"] for x, _ in poly[0]]; ys = [y for poly in ar["polys"] for _, y in poly[0]]
        areas.append({"kind": ar["kind"], "code": ar["code"], "name": ar["name"], "label": ar["label"],
                      "bbox": [min(xs), min(ys), max(xs), max(ys)]})
        polys[ar["kind"]][ar["code"]] = ar["polys"]

    out = os.path.join(a.data, release); os.makedirs(out, exist_ok=True)
    g_off = L.write_chunks(os.path.join(out, "geom.bin"), L.encode_shapes(shapes, oq))
    tmp = os.path.join(out, "geom.blk")
    b_off = L.write_chunks(tmp, L.encode_shapes(bshapes, oq)) + g_off[-1]
    with open(os.path.join(out, "geom.bin"), "ab") as fh, open(tmp, "rb") as fb: fh.write(fb.read())
    os.remove(tmp)
    rec_fields = list(rec.keys())
    r_off = L.write_rec_chunks(os.path.join(out, "rec.bin"), rec, n)
    with open(os.path.join(out, "addr.txt.gz"), "wb") as fh: fh.write(gzip.compress("\n".join(H["addr"]).encode("utf-8"), 9))
    with open(os.path.join(out, "areas.json.gz"), "wb") as fh: fh.write(gzip.compress(json.dumps(polys, separators=(",", ":")).encode(), 9))

    bfar = P["bfar"].astype(np.float32)
    floors = L.whole_floors([np.nan if v is None else v for v in rec.get("NumFloors", [None] * n)])
    bf100 = np.where(np.isnan(bfar), -1, np.round(np.minimum(bfar, 600) * 100)).astype(np.int32)
    props = pd.DataFrame({"i": np.arange(n, dtype=np.int32), "lu": P["lu"].astype(np.int16), "ub": P["ub"].astype(np.int16),
                          "zn": P["zone"].astype(np.int16), "yb": P["year"].astype(np.int16), "bf": bf100,
                          "fl": floors.astype(np.int16)})
    os.makedirs(os.path.join(ROOT, "work"), exist_ok=True)
    gpd.GeoDataFrame(props, geometry=geoms, crs=4326).to_parquet(os.path.join(ROOT, "work", f"{release}_lots.parquet"))
    L.write_tiles(os.path.join(out, "blocks.pmtiles"), L.tile_frame(bgeoms, pd.DataFrame({"b": np.arange(len(keys), dtype=np.int32)})),
                  "blocks", 9, 16, name=f"Lot Profiler {release} tax blocks")

    header = {"format": 3, "release": release, "released": H.get("released", ""), "built": H.get("built") or time.strftime("%Y-%m-%d"),
              "source": f"NYC DCP MapPLUTO {release}, ArcGIS export for five Brooklyn NTAs (converted from the 1.5.3 pack)",
              "n": n, "origin": [ox, oy], "q": L.Q, "boxUnit": L.BOX_UNIT, "chunk": L.CHUNK, "bfarScale": 100,
              "dict": {"lu": H["dict"]["lu"], "ub": H["dict"]["ub"], "fc": H["dict"]["fc"], "zone": H["dict"]["zone"]},
              "areas": areas, "nBlocks": len(keys), "recFields": rec_fields,
              "files": {"tiles": "lots.pmtiles", "blockTiles": "blocks.pmtiles", "geom": "geom.bin", "rec": "rec.bin",
                        "addr": "addr.txt.gz", "areas": "areas.json.gz"}, "far": None}
    sections = {"dcx": np.diff(cxq, prepend=0).astype(np.int32), "dcy": np.diff(cyq, prepend=0).astype(np.int32), "box": box.ravel(),
                "area": P["area"].astype(np.uint32), "units": P["units"].astype(np.uint16), "bfar": np.where(np.isnan(bfar), 65535, np.round(np.clip(bfar, 0, 655) * 100)).astype(np.uint16), "year": P["year"].astype(np.uint16), "floors": floors,
                "lu": P["lu"].astype(np.uint8), "ub": P["ub"].astype(np.uint8), "zone": P["zone"].astype(np.uint16),
                "nta": P["nta"].astype(np.uint16), "tract": P["tract"].astype(np.uint16), "blk": blk, "lotno": lotno, "blkKey": keys,
                "gOff": g_off.astype(np.uint32), "bOff": b_off.astype(np.uint32), "rOff": r_off.astype(np.uint32)}
    raw, size = L.write_pack(os.path.join(out, "core.lpk"), b"LPK3", header, sections)

    far_dir = os.path.join(ROOT, "far"); os.makedirs(far_dir, exist_ok=True)
    fc = P["fc"]; cats = H["dict"]["fc"]
    tab = pd.DataFrame({"bbl": bbl, "far_std": P["mfar"].astype(np.float64), "far_diff": P["fdiff"].astype(np.float64),
                        "far_cat": [cats[k] if k < len(cats) else "" for k in fc],
                        "far_status": np.where(fc == 6, "not_modeled", "modeled")})
    tab_path = os.path.join(far_dir, f"far_{release}.csv")
    tab.to_csv(tab_path, index=False)
    json.dump({"source": f"Adrian's ArcGIS model for MapPLUTO {release} (MaxFARUse, FARDiff, FARMapCat): straight FAR from ZR 23-142 Table 1, "
                         "community facility bonus and wide/narrow streets, for the five study NTAs",
               "columns": {"far_std": {"label": "Maximum usable FAR (modeled)", "kind": "base"}}},
              open(os.path.join(far_dir, f"far_{release}.meta.json"), "w"), indent=1)

    entry = {"id": release, "label": f"PLUTO {release}", "released": H.get("released", ""), "built": header["built"], "dir": release,
             "format": 3, "lots": n, "bytes": L.folder_bytes(out), "core": size, "coverage": "Five Brooklyn NTAs",
             "source": header["source"], "ntas": [x["name"] for x in areas if x["kind"] == "nta"]}
    if a.transit: entry["transit"] = a.transit
    L.update_manifest(a.data, entry)
    print(f"{release}: {n:,} lots converted -> data/{release}/ in {time.time()-t0:.0f}s; joining its FAR table …", flush=True)
    subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "far_join.py"), "--release", release,
                    tab_path, "--meta", os.path.join(far_dir, f"far_{release}.meta.json"), "--data", a.data], check=True)

if __name__ == "__main__":
    main()
