#!/usr/bin/env python3
"""zoning.py — ZoLa-style zoning map layers from DCP's "NYC GIS Zoning Features" file geodatabase,"""
import argparse, gzip, json, math, os, sys, time
import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SRC = {"nyzd": ("zd", {"z": "ZONEDIST"}), "nyco": ("co", {"o": "OVERLAY"}),
       "nysp": ("sp", {"n": "SDNAME", "l": "SDLBL"}),
       "nysp_sd": ("ss", {"n": "SPNAME", "l": "SPLBL", "s": "SUBDIST", "sl": "SUBDIST_LBL", "a2": "SUBAREA_LBL", "o2": "SUBAREA_OTR"}),
       "nylh": ("lh", {"n": "LHNAME", "l": "LHLBL"})}
MINZ, MAXZ, EXTENT, BUF = 10, 15, 4096, 64
R = 6378137.0
WORLD = 2 * math.pi * R

def clean(v):
    if v is None or (isinstance(v, float) and math.isnan(v)): return None
    v = str(v).strip()
    return None if v in ("", "None", "nan") else v

def label_text(layer, p):
    if layer == "zd": return p.get("z")
    if layer == "co": return p.get("o")
    if layer == "ss": return p.get("sl") if p.get("sl") and len(p["sl"]) <= 6 else p.get("a2") if p.get("a2") and len(p["a2"]) <= 6 else None
    return p.get("l")

def write_pmtiles(layers, labels, bounds, path, meta, minz=MINZ, maxz=MAXZ, label_minz=11, point_minz=13, snap=False):
    import shapely, mapbox_vector_tile as mvt
    from mapbox_vector_tile.encoder import on_invalid_geometry_make_valid
    from pmtiles.writer import Writer
    from pmtiles.tile import zxy_to_tileid, TileType, Compression
    t0 = time.time(); trees = {}
    simp = {}
    for z in range(minz, maxz + 1):
        tol = WORLD / 2 ** z / EXTENT * 0.5
        simp[z] = {k: (shapely.make_valid(shapely.simplify(g, tol, preserve_topology=True)) if g[0].geom_type != "Point" else g, p) for k, (g, p) in layers.items()}
    for k, (g, p) in list(layers.items()) + list(labels.items()): trees[k] = shapely.STRtree(g)
    def lng2x(lng): return (lng + 180) / 360
    def lat2y(lat): s = math.sin(math.radians(lat)); return 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
    entries = []
    for z in range(minz, maxz + 1):
        nz = 2 ** z
        x0, x1 = int(lng2x(bounds[0]) * nz), int(lng2x(bounds[2]) * nz)
        y0, y1 = int(lat2y(bounds[3]) * nz), int(lat2y(bounds[1]) * nz)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                size = WORLD / nz
                minx = -WORLD / 2 + x * size; maxy = WORLD / 2 - y * size
                tb = (minx, maxy - size, minx + size, maxy)
                pad = size * BUF / EXTENT
                qb = (tb[0] - pad, tb[1] - pad, tb[2] + pad, tb[3] + pad)
                box = shapely.box(*qb)
                out_layers = []
                for name, (g, props) in simp[z].items():
                    if g[0].geom_type == "Point":
                        if z < point_minz: continue
                        hit = trees[name].query(shapely.box(*tb))
                        feats = [{"geometry": g[k], "properties": props[k], "id": int(k)} for k in hit if tb[0] <= g[k].x < tb[2] and tb[1] <= g[k].y < tb[3]]
                        if feats: out_layers.append({"name": name, "features": feats})
                        continue
                    hit = trees[name].query(box)
                    feats = []
                    for k in hit:
                        c = shapely.clip_by_rect(g[k], *qb)
                        if c.is_empty: continue
                        polys = [q for q in (c.geoms if hasattr(c, "geoms") else [c]) if q.geom_type in ("Polygon", "MultiPolygon") and not q.is_empty]
                        if not polys: continue
                        geom = polys[0] if len(polys) == 1 else shapely.MultiPolygon([pp for q in polys for pp in (q.geoms if q.geom_type == "MultiPolygon" else [q])])
                        feats.append({"geometry": geom, "properties": props[k], "id": int(k)})
                    if feats: out_layers.append({"name": name, "features": feats})
                if z >= label_minz:
                    for name, (pts, props) in labels.items():
                        hit = trees[name].query(shapely.box(*tb))
                        feats = [{"geometry": pts[k], "properties": props[k]} for k in hit
                                 if tb[0] <= pts[k].x < tb[2] and tb[1] <= pts[k].y < tb[3]]
                        if feats: out_layers.append({"name": name, "features": feats})
                if not out_layers: continue
                opts = {"quantize_bounds": tb, "extents": EXTENT, "y_coord_down": False, "on_invalid_geometry": on_invalid_geometry_make_valid}
                if snap:
                    sx, sy = (tb[2] - tb[0]) / EXTENT, (tb[3] - tb[1]) / EXTENT
                    for L_ in out_layers:
                        for f_ in L_["features"]:
                            t_ = shapely.transform(f_["geometry"], lambda c: (c - [tb[0], tb[1]]) / [sx, sy])
                            f_["geometry"] = t_ if t_.geom_type == "Point" else shapely.set_precision(t_, 1.0)
                        L_["features"] = [f_ for f_ in L_["features"] if not f_["geometry"].is_empty]
                    opts.pop("quantize_bounds")
                data = mvt.encode(out_layers, default_options=opts)
                entries.append((zxy_to_tileid(z, x, y), gzip.compress(data, 9, mtime=0)))
        print(f"  z{z}: {len(entries)} tiles so far ({time.time()-t0:.0f}s)", flush=True)
    entries.sort()
    with open(path, "wb") as f:
        w = Writer(f)
        for tid, data in entries: w.write_tile(tid, data)
        e7 = lambda v: int(round(v * 1e7))
        vl = [{"id": n, "fields": {}} for n in list(layers) + list(labels)]
        w.finalize({"tile_type": TileType.MVT, "tile_compression": Compression.GZIP, "min_zoom": minz, "max_zoom": maxz,
                    "min_lon_e7": e7(bounds[0]), "min_lat_e7": e7(bounds[1]), "max_lon_e7": e7(bounds[2]), "max_lat_e7": e7(bounds[3]),
                    "center_zoom": 12, "center_lon_e7": e7((bounds[0] + bounds[2]) / 2), "center_lat_e7": e7((bounds[1] + bounds[3]) / 2)},
                   {**meta, "vector_layers": vl})
    return len(entries)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gdb"); ap.add_argument("--date", required=True, help="release month of the zoning data, YYYY-MM")
    ap.add_argument("--out", default=os.path.join(ROOT, "data"))
    a = ap.parse_args()
    import pyogrio
    from shapely.ops import polylabel
    t0 = time.time()
    layers, labels = {}, {}
    bounds = [180, 90, -180, -90]
    for fc, (name, fields) in SRC.items():
        d = pyogrio.read_dataframe(a.gdb, layer=fc)
        ll = d.to_crs(4326).total_bounds
        bounds = [min(bounds[0], ll[0]), min(bounds[1], ll[1]), max(bounds[2], ll[2]), max(bounds[3], ll[3])]
        props = [{k: clean(r[v]) for k, v in fields.items() if v in d.columns} for _, r in d.iterrows()]
        props = [{k: v for k, v in p.items() if v is not None} for p in props]
        g2263 = d.geometry.values
        lab = []
        for gi, (g, p) in enumerate(zip(g2263, props)):
            txt = label_text(name, p)
            if not txt or g is None: continue
            for part in (g.geoms if g.geom_type == "MultiPolygon" else [g]):
                acres = part.area / 43560
                if acres < 0.4: continue
                pt = polylabel(part, 2.0)
                lab.append((pt, {"t": txt, "a": round(acres, 1)}))
        g3857 = d.to_crs(3857).geometry.values
        layers[name] = (g3857, props)
        if lab:
            import geopandas as gpd
            pts = gpd.GeoSeries([x[0] for x in lab], crs=d.crs).to_crs(3857).values
            labels[name + "_l"] = (pts, [x[1] for x in lab])
        print(f"  {fc} -> {name}: {len(d)} features, {len(lab)} labels", flush=True)
    date = a.date; fn = f"zoning_{date}.pmtiles"; path = os.path.join(a.out, fn)
    n = write_pmtiles(layers, labels, bounds, path, {"name": f"NYC zoning features {date}", "attribution": "NYC Department of City Planning, NYC GIS Zoning Features"}, snap=True)
    idx_path = os.path.join(a.out, "zoning_index.json")
    idx = json.load(open(idx_path)) if os.path.exists(idx_path) else {"snapshots": []}
    idx["snapshots"] = [s for s in idx["snapshots"] if s["file"] != fn] + [{"file": fn, "date": date, "built": time.strftime("%Y-%m-%d"),
        "source": "NYC DCP, NYC GIS Zoning Features (" + os.path.basename(os.path.dirname(os.path.abspath(a.gdb))) + ")", "bytes": os.path.getsize(path)}]
    idx["snapshots"].sort(key=lambda s: s["date"])
    json.dump(idx, open(idx_path, "w"), indent=1)
    print(f"{fn}: {n} tiles, {os.path.getsize(path)/1e6:.1f} MB in {time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()
