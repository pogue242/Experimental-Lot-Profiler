#!/usr/bin/env python3
"""sf.py — turn San Francisco's land use parcels, assessor roll and zoning into a MapPLUTO-shaped file and boundary files for build.py"""
import argparse, os, re
import numpy as np, pandas as pd
import native as N

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "..", "..", "Data", "sanfrancisco_2026-11-07"))
CRS = 2227
COMM = ["mips", "retail", "visitor", "pdr", "cie", "med"]
COMM_LU = {"mips": "05", "retail": "05", "visitor": "05", "pdr": "06", "cie": "08", "med": "08"}
NAT = {"res": "Residential", "mixed": "Residential and commercial", "mips": "Office (MIPS)", "retail": "Retail", "visitor": "Hotel (visitor)",
       "pdr": "Production, distribution, repair (PDR)", "cie": "Cultural, institutional, educational", "med": "Medical",
       "parking": "Parking lot", "garage": "Parking garage", "open": "Open space", "none": "No recorded use"}
NAT_COL = {"res": "#E8B04B", "mixed": "#E8703C", "mips": "#A4161A", "retail": "#E8453C", "visitor": "#C9184A", "pdr": "#8E5CB5",
           "cie": "#2E86C1", "med": "#5DADE2", "parking": "#9AA3AC", "garage": "#6C7A89", "open": "#5FA35A", "none": "#555B61"}

def address(s):
    if not isinstance(s, str): return ""
    m = re.match(r"\s*(\d{4})\s+(\d{4})\s+(.*?)(?:\s{2,}([A-Z]{2}))?(?:[0-9A-Z]*)\s*$", s)
    if not m: return s.strip()
    lo, hi = int(m.group(2)), int(m.group(1))
    st = " ".join(x for x in (re.sub(r"\s+", " ", m.group(3)).strip(), m.group(4)) if x)
    n = lo or hi
    return f"{n} {st}".strip() if n else st

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "work", "sfo"))
    a = ap.parse_args()
    import geopandas as gpd, pyogrio, shapely
    os.makedirs(a.out, exist_ok=True)
    s = lambda f: os.path.join(a.src, f)
    df = pyogrio.read_dataframe(s("landuse.geojson")).to_crs(CRS)
    df = df[df.geometry.notna() & ~df.geometry.is_empty].reset_index(drop=True)
    df["geometry"] = [shapely.MultiPolygon([q for p in shapely.get_parts(g) for q in (p.geoms if p.geom_type == "MultiPolygon" else [p]) if q.geom_type == "Polygon"])
                      for g in shapely.make_valid(df.geometry.values)]
    df = df[~df.geometry.is_empty].reset_index(drop=True)
    print(f"{len(df):,} land use parcels", flush=True)
    for c in ["resunits", "resunits_s", "total_comm"] + COMM: df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    roll = pd.read_csv(s("roll2025.csv"), dtype=str)
    roll = gpd.GeoDataFrame(roll, geometry=gpd.GeoSeries.from_wkt(roll.the_geom.fillna("POINT EMPTY")), crs=4326)
    roll = roll[~roll.geometry.is_empty].to_crs(CRS)
    for c in ["year_property_built", "number_of_stories", "number_of_units", "property_area", "lot_area"]: roll[c] = pd.to_numeric(roll[c], errors="coerce").fillna(0)
    print(f"{len(roll):,} assessor records", flush=True)
    j = gpd.sjoin(roll, df[["geometry"]], predicate="within").rename(columns={"index_right": "p"})
    j = j[~j.index.duplicated()]
    g = j.groupby("p")
    agg = pd.DataFrame({"BldgArea": g.property_area.sum(), "NumFloors": g.number_of_stories.max(), "n": g.size()})
    main_rec = j.sort_values(["p", "property_area"], ascending=[True, False]).drop_duplicates("p").set_index("p")
    yb = j[j.year_property_built > 1800].groupby("p").year_property_built.min()
    df = df.join(agg).join(main_rec[["property_location", "use_definition", "property_class_code_definition"]])
    df["YearBuilt"] = yb.reindex(df.index).fillna(0).values
    df["BldgArea"] = df.BldgArea.fillna(0); df["NumFloors"] = df.NumFloors.fillna(0)
    print(f"  {j.p.nunique():,} parcels matched to {len(j):,} assessor records", flush=True)
    res = (df.resunits > 0) | (df.resunits_s > 0)
    top = df[COMM].idxmax(axis=1).where(df.total_comm > 0, "")
    lu = np.where(res & (df.total_comm > 0), "04",
         np.where(res, np.where(df.resunits <= 2, "01", np.where(df.NumFloors >= 6, "03", "02")),
         np.where(top != "", top.map(COMM_LU).fillna(""),
         np.where(df.garage | df.parking_lo, "10",
         np.where(df.open_space, "09",
         np.where(df.use_definition.eq("Government") | df.special_jurisdiction.fillna("None").ne("None"), "08",
         np.where(df.BldgArea > 0, "", "11")))))))
    df["LandUse"] = lu
    nat = np.where(res & (df.total_comm > 0), "mixed", np.where(res, "res", np.where(top != "", top,
          np.where(df.garage, "garage", np.where(df.parking_lo, "parking", np.where(df.open_space, "open", "none"))))))
    order = [k for k in NAT if (nat == k).any()]
    df["NativeLU"] = N.encode(pd.Series(nat).map(NAT).values, lambda n, k: NAT_COL[order[k]], "SF Planning land use",
                              os.path.join(a.out, "sf_pluto.native.json"), order=[NAT[k] for k in order])
    df["UnitsRes"] = (df.resunits + df.resunits_s).astype(int)
    df["LotArea"] = df.geometry.area.round()
    df["BuiltFAR"] = np.where(df.LotArea > 0, df.BldgArea / df.LotArea, np.nan).round(2)
    df["Address"] = [address(v) for v in df.property_location]
    df["BldgClass"] = df.property_class_code_definition.fillna("")
    df["NumBldgs"] = df.n.fillna(0)
    cen = gpd.GeoDataFrame(geometry=df.geometry.representative_point(), crs=CRS)
    zon = pyogrio.read_dataframe(s("zoning.geojson")).to_crs(CRS)
    z = gpd.sjoin(cen, zon[["zoning", "geometry"]], predicate="within", how="left"); z = z[~z.index.duplicated()]
    df["ZoneDist1"] = z.zoning.reindex(df.index).fillna("").values
    tr = pyogrio.read_dataframe("/vsizip/" + s("tracts.zip"), where="COUNTYFP='075'").to_crs(CRS)
    t = gpd.sjoin(cen, tr[["GEOID", "geometry"]], predicate="within", how="left"); t = t[~t.index.duplicated()]
    gid = t.GEOID.reindex(df.index)
    near = gid.isna()
    if near.any():
        nb = gpd.sjoin_nearest(cen[near], tr[["GEOID", "geometry"]]); gid[near] = nb[~nb.index.duplicated()].GEOID
    df["BCT2020"] = gid.values
    first = df.mapblklot.fillna("").str.extract(r"'?([0-9A-Z]{4})", expand=False).fillna("")
    first = first.where(first != "", "Z" + df.ludb_id.astype(str))
    codes = {c: k + 1 for k, c in enumerate(sorted(first.unique()))}
    df["bk"] = first.map(codes)
    df = df.sort_values(["bk", "mapblklot"]).reset_index(drop=True)
    df["lot"] = df.groupby("bk").cumcount() + 1
    df["BBL"] = df.bk.astype(np.int64) * 10000 + df.lot
    df["Version"] = "sfo26"
    cols = ["BBL", "Address", "LandUse", "UnitsRes", "BldgArea", "LotArea", "BuiltFAR", "YearBuilt", "NumFloors", "ZoneDist1",
            "BCT2020", "Version", "BldgClass", "NumBldgs", "NativeLU"]
    gpd.GeoDataFrame(df[cols], geometry=df.geometry.values, crs=CRS).to_file(os.path.join(a.out, "sf_pluto.gpkg"), layer="lots", driver="GPKG")
    print(f"  {len(df):,} lots in {len(codes):,} assessor blocks; land use known for {(df.LandUse != '').mean() * 100:.1f}%; {int(df.UnitsRes.sum()):,} housing units", flush=True)
    hd = pyogrio.read_dataframe(s("hoods.geojson")).to_crs(CRS)
    tr = tr[tr.GEOID.isin(set(df.BCT2020))]
    ov = gpd.overlay(tr[["GEOID", "geometry"]], hd[["nhood", "geometry"]], how="intersection")
    ov["a"] = ov.area
    best = ov.sort_values("a", ascending=False).drop_duplicates("GEOID").set_index("GEOID").nhood
    names = {n: f"{k:03d}" for k, n in enumerate(sorted(best.unique()), 1)}
    tr = tr.copy()
    tr["boroct2020"] = tr.GEOID; tr["nta2020"] = tr.GEOID.map(best).map(names).fillna("000")
    tr["ctlabel"] = tr.NAMELSAD.str.replace("Census Tract ", ""); tr["boroname"] = "San Francisco"
    land = shapely.union_all(shapely.buffer(df.geometry.values, 50, quad_segs=2))
    tr["geometry"] = tr.geometry.intersection(land)
    bd = os.path.join(a.out, "boundaries"); os.makedirs(bd, exist_ok=True)
    tr[["boroct2020", "nta2020", "ctlabel", "boroname", "geometry"]].to_crs(4326).to_file(os.path.join(bd, "63ge-mke6.geojson"), driver="GeoJSON")
    nt = tr.dissolve(by="nta2020").reset_index()
    inv = {v: k for k, v in names.items()}
    nt["ntaname"] = nt.nta2020.map(inv).fillna("Unassigned")
    nt[["nta2020", "ntaname", "geometry"]].to_crs(4326).to_file(os.path.join(bd, "9nt8-h7nd.geojson"), driver="GeoJSON")
    print(f"  {len(tr)} tracts, {len(nt)} neighborhoods (each tract assigned to the Analysis Neighborhood it overlaps most)")

if __name__ == "__main__":
    main()
