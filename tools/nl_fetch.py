#!/usr/bin/env python3
"""nl_fetch.py — download a Dutch municipality's cadastral parcels (PDOK BRK) and building floor counts (3D BAG) for nl.py"""
import argparse, json, os, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.abspath(os.path.join(HERE, "..", "..", "..", "Data", "netherlands_2026-11-07"))
BRK = "https://api.pdok.nl/kadaster/brk-kadastrale-kaart/ogc/v1/collections/perceel/items"
BAG3D = "https://data.3dbag.nl/api/BAG3D/wfs"

def get(url):
    for k in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "LotProfiler (nl_fetch.py)"}), timeout=300) as r: return json.loads(r.read())
        except Exception as e:
            print(f"  {e}; retrying", flush=True); time.sleep(5 + 10 * k)
    raise SystemExit("no answer from " + url)

def parcels(bbox, out):
    url = BRK + "?" + urllib.parse.urlencode({"f": "json", "limit": 1000, "bbox": ",".join(map(str, bbox))})
    feats = []
    while url:
        d = get(url); feats += d["features"]
        url = next((l["href"] for l in d.get("links", []) if l["rel"] == "next"), None)
        if len(feats) % 20000 < 1000: print(f"  {len(feats):,} parcels", flush=True)
        if not d["features"]: break
    json.dump({"type": "FeatureCollection", "features": feats}, open(out, "w", encoding="utf-8"))
    print(f"{len(feats):,} parcels -> {out}", flush=True)

def floors(bbox_rd, out):
    rows, start, n = [], 0, 10000
    while True:
        q = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": "BAG3D:lod12", "outputFormat": "application/json",
             "count": n, "startIndex": start, "sortBy": "fid", "bbox": ",".join(map(str, bbox_rd)) + ",EPSG:28992",
             "propertyName": "identificatie,b3_bouwlagen,b3_h_70p,b3_h_maaiveld,oorspronkelijkbouwjaar"}
        d = get(BAG3D + "?" + urllib.parse.urlencode(q))
        f = d.get("features", [])
        rows += [x["properties"] for x in f]
        print(f"  {len(rows):,} 3D BAG buildings", flush=True)
        if len(f) < n: break
        start += n
    json.dump(rows, open(out, "w", encoding="utf-8"))
    print(f"{len(rows):,} buildings -> {out}", flush=True)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gm", default="0363", help="CBS municipality code (Amsterdam: 0363)")
    ap.add_argument("--what", default="both", choices=["both", "parcels", "floors"])
    a = ap.parse_args()
    import geopandas as gpd
    g = gpd.read_file(os.path.join(DATA, "wijkenbuurten_2025.gpkg"), layer="gemeenten", where=f"gemeentecode='GM{a.gm}'")
    d = os.path.join(DATA, a.gm); os.makedirs(d, exist_ok=True)
    if a.what in ("both", "parcels"): parcels([round(v, 5) for v in g.to_crs(4326).total_bounds], os.path.join(d, "parcels.geojson"))
    if a.what in ("both", "floors"): floors([round(v) for v in g.to_crs(28992).total_bounds], os.path.join(d, "floors3d.json"))

if __name__ == "__main__":
    main()
