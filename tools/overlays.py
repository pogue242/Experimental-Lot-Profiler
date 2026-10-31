#!/usr/bin/env python3
"""overlays.py — ZoLa's supporting zoning layers (MIH, Inclusionary Housing, transit zones, FRESH, E-designations and others) as one PMTiles file"""
import argparse, glob, json, os, re, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import zoning as Z

ROOT = os.path.join(HERE, "..")
REPO_DATA = os.path.abspath(os.path.join(ROOT, "..", "..", "Data"))
CARTO = "https://carto.nycplanningdigital.com/api/v2/sql"
TABLES = {"mih": ("dcp_mandatory_inclusionary_housing", {"n": "projectnam", "o": "mih_option", "s": "status", "a": "dateadopte", "u": "zr_ulurpno"}),
          "ih": ("dcp_inclusionary_housing", {"n": "projectnam", "s": "status", "a": "dateadopte"}),
          "fr": ("dcp_fresh_zones", {"n": "name"}),
          "ed": ("dcp_e_designations", {"e": "enumber", "d": "descriptio", "c": "ceqr_num", "u": "ulurp_num"}),
          "ldg": ("dcp_lower_density_growth_management_areas", {"b": "borough"}),
          "cz": ("dcp_coastal_zone_boundary", {}),
          "wap": ("dcp_waterfront_access_plan", {"n": "name"}),
          "uwa": ("upland_waterfront_areas", {"b": "borough"}),
          "apj": ("dcp_appendixj_designated_mdistricts", {"n": "name", "b": "boroname", "x": "subarea"})}

def fetch(folder):
    os.makedirs(folder, exist_ok=True)
    for name, (table, _) in TABLES.items():
        url = CARTO + "?" + urllib.parse.urlencode({"format": "geojson", "q": f"SELECT * FROM {table}"})
        with urllib.request.urlopen(url, timeout=300) as r, open(os.path.join(folder, table + ".geojson"), "wb") as f: f.write(r.read())
        print(f"  {table}", flush=True)

def tidy(k, v):
    if v is None: return None
    v = re.sub(r"\s+", " ", str(v)).strip()
    if k == "o": v = re.sub(r"Option\s*(\d)", r"Option \1", v)
    if k == "a": v = v[:10]
    return v or None

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", help="folder of downloaded GeoJSON (default: the newest Data/dcp_overlays_*)")
    ap.add_argument("--fetch", metavar="YYYY-MM-DD", help="download DCP's tables into Data/dcp_overlays_<date> first")
    ap.add_argument("--gdb", help="MapPLUTO file geodatabase; transit zones are built from its TrnstZone field")
    ap.add_argument("--out", default=os.path.join(ROOT, "data"))
    a = ap.parse_args()
    import geopandas as gpd, pyogrio, shapely
    t0 = time.time()
    if a.fetch: a.src = os.path.join(REPO_DATA, f"dcp_overlays_{a.fetch}"); fetch(a.src)
    src = a.src or sorted(glob.glob(os.path.join(REPO_DATA, "dcp_overlays_*")))[-1]
    date = os.path.basename(os.path.normpath(src)).split("_")[-1]
    layers, bounds = {}, [180, 90, -180, -90]
    for name, (table, fields) in TABLES.items():
        d = gpd.read_file(os.path.join(src, table + ".geojson"))
        d = d[d.geometry.notna() & ~d.geometry.is_empty]
        ll = d.total_bounds; bounds = [min(bounds[0], ll[0]), min(bounds[1], ll[1]), max(bounds[2], ll[2]), max(bounds[3], ll[3])]
        g = d.to_crs(3857).geometry.values
        if g[0].geom_type != "Point": g = shapely.make_valid(g)
        props = [{k: v for k, v in ((k, tidy(k, r.get(f))) for k, f in fields.items()) if v} for _, r in d.iterrows()]
        layers[name] = (g, props)
        print(f"  {table} -> {name}: {len(d)} features", flush=True)
    if a.gdb:
        lay = next(n for n, t in pyogrio.list_layers(a.gdb) if t and "Polygon" in t)
        p = pyogrio.read_dataframe(a.gdb, layer=lay, columns=["TrnstZone"])
        p = p[p.TrnstZone.notna() & (p.TrnstZone.astype(str).str.strip() != "")]
        p["geometry"] = p.geometry.buffer(100)
        tz = p.dissolve(by="TrnstZone").reset_index()
        tz["geometry"] = shapely.simplify(shapely.buffer(tz.geometry.values, -70), 5)
        layers["tz"] = (tz.to_crs(3857).geometry.values, [{"t": v} for v in tz.TrnstZone])
        print(f"  MapPLUTO TrnstZone -> tz: {len(tz)} zones", flush=True)
    fn = f"overlays_{date}.pmtiles"; path = os.path.join(a.out, fn)
    n = Z.write_pmtiles(layers, {}, bounds, path, {"name": f"NYC supporting zoning layers {date}",
        "attribution": "NYC Department of City Planning (ZoLa data service); transit zones from MapPLUTO"}, point_minz=14, snap=True)
    idx_path = os.path.join(a.out, "overlays_index.json")
    idx = json.load(open(idx_path)) if os.path.exists(idx_path) else {"snapshots": []}
    idx["snapshots"] = [s for s in idx["snapshots"] if s["file"] != fn] + [{"file": fn, "date": date, "built": time.strftime("%Y-%m-%d"),
        "source": "NYC DCP (ZoLa data service, carto.nycplanningdigital.com)" + ("; transit zones from MapPLUTO TrnstZone" if a.gdb else ""), "bytes": os.path.getsize(path)}]
    idx["snapshots"].sort(key=lambda s: s["date"])
    json.dump(idx, open(idx_path, "w"), indent=1)
    print(f"{fn}: {n} tiles, {os.path.getsize(path)/1e6:.1f} MB in {time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()
