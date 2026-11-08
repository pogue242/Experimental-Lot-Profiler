#!/usr/bin/env python3
"""spain_fetch.py — download one Spanish municipality's Catastro INSPIRE parcels, buildings and addresses and its INE census sections for spain.py"""
import argparse, json, os, re, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.abspath(os.path.join(HERE, "..", "..", "..", "Data", "spain_2026-11-07"))
CAT = "https://www.catastro.hacienda.gob.es/INSPIRE"
INE = "https://www.ine.es/geoserver/ogc/features/v1/collections/WMS_INE_SECCIONES_G01:SU.VectorStatisticalUnit/items"
THEMES = {"bu": ("buildings", "Buildings", "BU"), "cp": ("CadastralParcels", "CadastralParcels", "CP"), "ad": ("Addresses", "Addresses", "AD")}

def get(url, raw=False):
    for k in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "LotProfiler (spain_fetch.py)"}), timeout=600) as r:
                b = r.read(); return b if raw else json.loads(b)
        except Exception as e:
            print(f"  {e}; retrying", flush=True); time.sleep(5 + 10 * k)
    raise SystemExit("no answer from " + url)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--muni", required=True, help="Catastro municipality code (Barcelona: 08900)")
    ap.add_argument("--ine", required=True, help="INE municipality code (Barcelona: 08019)")
    a = ap.parse_args()
    d = os.path.join(DATA, a.muni); os.makedirs(d, exist_ok=True)
    pr = a.muni[:2]
    feed = get(f"{CAT}/buildings/{pr}/ES.SDGC.bu.atom_{pr}.xml", raw=True).decode("utf-8", "replace")
    folder = re.search(rf"Buildings/{pr}/({a.muni}-[^/]+)/", feed).group(1)
    for f, (_, path, code) in THEMES.items():
        out = os.path.join(d, f + ".zip")
        if not os.path.exists(out) or not os.path.getsize(out):
            b = get(f"{CAT}/{path}/{pr}/{folder}/A.ES.SDGC.{code}.{a.muni}.zip", raw=True)
            open(out + ".part", "wb").write(b); os.replace(out + ".part", out)
        print(f"  {f}.zip {os.path.getsize(out) / 1e6:.0f} MB", flush=True)
    import pyogrio, zipfile
    z = os.path.join(d, "cp.zip"); n = next(x for x in zipfile.ZipFile(z).namelist() if x.endswith("cadastralparcel.gml"))
    b = pyogrio.read_dataframe("/vsizip/" + z + "/" + n, columns=[], max_features=None).to_crs(4326).total_bounds
    url = INE + "?" + urllib.parse.urlencode({"f": "json", "limit": 2000, "bbox": ",".join(f"{v:.4f}" for v in b)})
    feats = []
    while url:
        r = get(url); feats += r["features"]
        url = next((l["href"] for l in r.get("links", []) if l["rel"] == "next"), None) if r["features"] else None
    feats = [f for f in feats if f["properties"].get("CUMUN") == a.ine]
    json.dump({"type": "FeatureCollection", "features": feats}, open(os.path.join(d, "secciones.geojson"), "w", encoding="utf-8"))
    print(f"{len(feats):,} INE units for {a.ine} -> {d}", flush=True)

if __name__ == "__main__":
    main()
