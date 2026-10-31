#!/usr/bin/env python3
"""philly.py — turn Philadelphia's parcels and property records into a MapPLUTO-shaped file and boundary files for build.py"""
import argparse, os, re, sys
import numpy as np, pandas as pd
import native as N

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "..", "..", "Data", "philadelphia_2026-10-30"))
CRS = 2272

def land_use(cat, desc, stories):
    d = desc if isinstance(desc, str) else ""
    if re.search(r"PARKING|PKG LOT|GARAGE", d): return "10"
    if re.search(r"SCHOOL|COLLEGE|UNIVERS|HOSP|HSE WORSHIP|RELIGIOUS|CHURCH|FIRE/POLICE|LIBRARY|GOVT|DAY CARE|HEALTH FAC|NURSING", d): return "08"
    if re.search(r"CEMETERY|PARK|RECREAT|PLAYGROUND", d): return "09"
    if re.search(r"RR |RAILROAD|UTIL|TRANSIT|AIRPORT|PIER", d): return "07"
    if cat in ("6", "12", "13"): return "11"
    if cat in ("1", "8"): return "01"
    if cat in ("2", "14"): return "03" if (stories or 0) >= 6 or re.search(r"HIGH RISE|100\+|51-100", d) else "02"
    if cat == "3": return "04"
    if cat in ("4", "9", "10", "15", "7"): return "05"
    if cat == "5": return "06"
    return ""

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "work"))
    a = ap.parse_args()
    import geopandas as gpd, pyogrio, shapely
    os.makedirs(a.out, exist_ok=True)
    s = lambda f: os.path.join(a.src, f)
    par = pyogrio.read_dataframe(s("parcels.gpkg")).to_crs(CRS)
    par = par[par.geometry.notna() & ~par.geometry.is_empty].reset_index(drop=True)
    par["geometry"] = shapely.make_valid(par.geometry.values)
    opa = pyogrio.read_dataframe(s("opa.gpkg")).to_crs(CRS)
    print(f"{len(par):,} parcels, {len(opa):,} property records", flush=True)
    opa["lu"] = [land_use(c, d, n) for c, d, n in zip(opa.category_code, opa.building_code_description, opa.number_stories)]
    opa["yb"] = pd.to_numeric(opa.year_built, errors="coerce")
    pt = opa[opa.geometry.notna()]
    j = gpd.sjoin(pt, par[["geometry"]], predicate="within", how="inner")
    j = j[~j.index.duplicated()]
    by = opa.set_index("parcel_number")
    acc = j.rename(columns={"index_right": "p"})
    miss = par.index.difference(acc.p.unique())
    bb = par.loc[miss].dropna(subset=["brt_id"])
    bb = bb[bb.brt_id.isin(by.index)]
    extra = by.loc[bb.brt_id].reset_index(); extra["p"] = bb.index.values
    acc = pd.concat([acc.drop(columns="geometry"), extra.drop(columns="geometry")], ignore_index=True)
    print(f"  {acc.p.nunique():,} parcels matched to {len(acc):,} records", flush=True)
    acc["la"] = pd.to_numeric(acc.total_area, errors="coerce"); acc["ba"] = pd.to_numeric(acc.total_livable_area, errors="coerce").fillna(0)
    acc["st"] = pd.to_numeric(acc.number_stories, errors="coerce")
    acc["mv"] = pd.to_numeric(acc.market_value, errors="coerce").fillna(0)
    main_rec = acc.sort_values(["p", "ba", "la"], ascending=[True, False, False]).drop_duplicates("p").set_index("p")
    g = acc.groupby("p")
    agg = pd.DataFrame({"BldgArea": g.ba.sum(), "NumFloors": g.st.max(), "AssessTot": g.mv.sum(), "n": g.size()})
    df = par.join(agg).join(main_rec[["lu", "yb", "zoning", "building_code_description", "category_code_description", "owner_1", "frontage", "depth", "zip_code", "la"]])
    df["UnitsRes"] = 0
    df["LotArea"] = np.where(df.la > 0, df.la, df.geometry.area)
    df["BldgArea"] = df.BldgArea.fillna(0)
    df["BuiltFAR"] = np.where(df.LotArea > 0, df.BldgArea / df.LotArea, np.nan).round(2)
    df["YearBuilt"] = df.yb.where(df.yb > 1600, 0).fillna(0)
    df["LandUse"] = df.lu.fillna("")
    cen = gpd.GeoDataFrame(geometry=df.geometry.representative_point(), crs=CRS)
    zon = pyogrio.read_dataframe(s("zoning.gpkg")).to_crs(CRS)
    z = gpd.sjoin(cen, zon[["long_code", "geometry"]], predicate="within", how="left"); z = z[~z.index.duplicated()]
    df["ZoneDist1"] = z.long_code.reindex(df.index).fillna(df.zoning).fillna("")
    blk = pyogrio.read_dataframe("/vsizip/" + s("blocks.zip"), where="COUNTYFP20='101'", columns=["GEOID20", "COUNTYFP20"]).to_crs(CRS)
    b = gpd.sjoin(cen, blk, predicate="within", how="left"); b = b[~b.index.duplicated()]
    gid = b.GEOID20.reindex(df.index)
    near = gid.isna()
    if near.any():
        nb = gpd.sjoin_nearest(cen[near], blk, how="left"); nb = nb[~nb.index.duplicated()]
        gid[near] = nb.GEOID20
    df["blkid"] = gid.values
    df["BCT2020"] = df.blkid.str[:11]
    codes = {c: k + 1 for k, c in enumerate(sorted(df.blkid.unique()))}
    df["bk"] = df.blkid.map(codes)
    df = df.sort_values(["bk", "parcelid"]).reset_index(drop=True)
    df["lot"] = df.groupby("bk").cumcount() + 1
    if df.lot.max() > 9999: sys.exit(f"a census block has more than 9,999 parcels: {df.blkid.value_counts().head(3).to_dict()} {int(near.sum())} placed by nearest")
    df["BBL"] = df.bk.astype(np.int64) * 10000 + df.lot
    df["Address"] = df.address.fillna("")
    df["Version"] = "phl26"
    df["OwnerName"] = df.owner_1; df["BldgClass"] = df.building_code_description; df["LotFront"] = pd.to_numeric(df.frontage, errors="coerce")
    df["LotDepth"] = pd.to_numeric(df.depth, errors="coerce"); df["ZipCode"] = df.zip_code
    df["NumBldgs"] = df.n.fillna(0)
    df["NativeLU"] = N.encode(df.category_code_description.str.strip().str.title(), N.by_keyword([("single", "#F7E08A"), ("multi", "#F2A541"), ("apartment", "#B5651D"),
        ("mixed", "#F07C4A"), ("retail", "#E8453C"), ("commercial", "#D7263D"), ("office", "#A4161A"), ("hotel", "#C9184A"), ("industrial", "#9B5DE5"),
        ("garage - r", "#BDBDBD"), ("garage", "#8D8D8D"), ("vacant", "#555B61"), ("special", "#4A90C2")]),
        "OPA category", os.path.join(a.out, "philly_pluto.native.json"))
    cols = ["BBL", "Address", "LandUse", "UnitsRes", "BldgArea", "LotArea", "BuiltFAR", "YearBuilt", "NumFloors", "ZoneDist1",
            "BCT2020", "Version", "OwnerName", "BldgClass", "LotFront", "LotDepth", "ZipCode", "AssessTot", "NumBldgs", "NativeLU"]
    gpd.GeoDataFrame(df[cols], geometry=df.geometry.values, crs=CRS).to_file(os.path.join(a.out, "philly_pluto.gpkg"), layer="lots", driver="GPKG")
    print(f"  {len(df):,} lots in {len(codes):,} census blocks; land use known for {(df.LandUse!='').mean()*100:.1f}%", flush=True)
    tr = pyogrio.read_dataframe("/vsizip/" + s("tracts.zip"), where="COUNTYFP='101'").to_crs(CRS)
    hd = pyogrio.read_dataframe(s("hoods.geojson")).to_crs(CRS)
    ov = gpd.overlay(tr[["GEOID", "geometry"]], hd[["MAPNAME", "geometry"]], how="intersection")
    ov["a"] = ov.area
    best = ov.sort_values("a", ascending=False).drop_duplicates("GEOID").set_index("GEOID").MAPNAME
    names = {n: f"{k:03d}" for k, n in enumerate(sorted(best.unique()), 1)}
    tr["boroct2020"] = tr.GEOID; tr["nta2020"] = tr.GEOID.map(best).map(names).fillna("000")
    tr["ctlabel"] = tr.NAMELSAD.str.replace("Census Tract ", ""); tr["boroname"] = "Philadelphia"
    bd = os.path.join(a.out, "boundaries"); os.makedirs(bd, exist_ok=True)
    tr[["boroct2020", "nta2020", "ctlabel", "boroname", "geometry"]].to_crs(4326).to_file(os.path.join(bd, "63ge-mke6.geojson"), driver="GeoJSON")
    nt = tr.dissolve(by="nta2020").reset_index()
    inv = {v: k for k, v in names.items()}
    nt["ntaname"] = nt.nta2020.map(inv).fillna("Unassigned")
    nt[["nta2020", "ntaname", "geometry"]].to_crs(4326).to_file(os.path.join(bd, "9nt8-h7nd.geojson"), driver="GeoJSON")
    print(f"  {len(tr)} tracts, {len(nt)} neighborhoods (each tract assigned to the neighborhood it overlaps most)")

if __name__ == "__main__":
    main()
