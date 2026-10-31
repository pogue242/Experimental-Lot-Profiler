#!/usr/bin/env python3
"""tokyo.py — turn PLATEAU land-use parcels, buildings and zoning for Tokyo's 23 wards into a MapPLUTO-shaped file and boundary files for build.py"""
import argparse, glob, os, sys
import numpy as np, pandas as pd
import native as N

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "..", "..", "Data", "tokyo_2026-10-30"))
UDX = "13100_tokyo23-ku_2020_citygml_4_2_op/udx"
CRS = 6677
SQFT = 10.7639
WARDS = {13101: "Chiyoda", 13102: "Chuo", 13103: "Minato", 13104: "Shinjuku", 13105: "Bunkyo", 13106: "Taito", 13107: "Sumida",
         13108: "Koto", 13109: "Shinagawa", 13110: "Meguro", 13111: "Ota", 13112: "Setagaya", 13113: "Shibuya", 13114: "Nakano",
         13115: "Suginami", 13116: "Toshima", 13117: "Kita", 13118: "Arakawa", 13119: "Itabashi", 13120: "Nerima", 13121: "Adachi",
         13122: "Katsushika", 13123: "Edogawa"}
ZONE = {1: "R1L Low-rise residential 1", 2: "R2L Low-rise residential 2", 3: "R1M Mid/high-rise residential 1",
        4: "R2M Mid/high-rise residential 2", 5: "R1 Residential 1", 6: "R2 Residential 2", 7: "RQ Quasi-residential",
        8: "RR Rural residential", 9: "CN Neighborhood commercial", 10: "C Commercial", 11: "MQ Quasi-industrial",
        12: "M Industrial", 13: "MX Exclusively industrial"}
USE = {401: "05", 402: "05", 403: "05", 404: "05", 411: "01", 412: "R", 413: "04", 414: "04", 415: "04", 421: "08", 422: "08",
       431: "07", 441: "06", 451: "06", 452: "07", 453: "08"}
USE_EN = {401: "Office", 402: "Commercial", 403: "Hotel", 404: "Mixed commercial", 411: "House", 412: "Apartment building",
          413: "House with shop", 414: "Apartments with shops", 415: "House with workshop", 421: "Government", 422: "School, health or welfare",
          431: "Transport or warehouse", 441: "Factory", 451: "Farm building", 452: "Utility", 453: "Defense", 454: "Other"}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "work", "tyo"))
    a = ap.parse_args()
    import geopandas as gpd, pyogrio, shapely
    os.makedirs(a.out, exist_ok=True)
    s = lambda f: os.path.join(a.src, f)
    parts = []
    for f in sorted(glob.glob(s(UDX + "/luse/*_luse_6668_2_op.gml"))):
        d = pyogrio.read_dataframe(f, columns=["13_区市町村コード_大字・町コード_町・丁目コード", "町丁目名称", "city"])
        d.columns = ["chome", "cname", "city", "geometry"]
        parts.append(d); print(f"  {os.path.basename(f)}: {len(d):,}", flush=True)
    par = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=6668)
    par["geometry"] = shapely.force_2d(par.geometry.values)
    par = par.to_crs(CRS)
    par["geometry"] = shapely.make_valid(par.geometry.values)
    par = par[par.geometry.notna() & ~par.geometry.is_empty & par.city.isin(WARDS.keys())].reset_index(drop=True)
    print(f"{len(par):,} land-use parcels", flush=True)
    cen = gpd.GeoDataFrame(geometry=par.geometry.representative_point(), crs=CRS)
    uz = pd.concat([pyogrio.read_dataframe(f, layer="UseDistrict", columns=["function", "floorAreaRate"])
                    for f in sorted(glob.glob(s(UDX + "/urf/*.gml")))], ignore_index=True)
    uz = gpd.GeoDataFrame(uz, crs=6668); uz["geometry"] = shapely.force_2d(uz.geometry.values); uz = uz.to_crs(CRS)
    zj = gpd.sjoin(cen, uz[["function", "floorAreaRate", "geometry"]], predicate="within", how="left")
    zj = zj[~zj.index.duplicated()].reindex(cen.index)
    far = (pd.to_numeric(zj.floorAreaRate, errors="coerce") * 100).round()
    zone = zj.function.map(lambda v: ZONE.get(int(v), "") if pd.notna(v) else "")
    par["ZoneDist1"] = [f"{z} {int(f)}%" if z and f == f else z for z, f in zip(zone, far)]
    bl = []
    for f in sorted(glob.glob(s("bldg/*_building_centroid_lod0.parquet"))):
        b = pd.read_parquet(f, columns=["usage_code", "storeys_above_ground", "measured_height", "cal_area_m2", "gml_name", "GEOM"])
        bl.append(b)
    b = pd.concat(bl, ignore_index=True)
    b = gpd.GeoDataFrame(b.drop(columns="GEOM"), geometry=shapely.from_wkb(b.GEOM.values), crs=6668).to_crs(CRS)
    b["u"] = pd.to_numeric(b.usage_code, errors="coerce").fillna(461).astype(int)
    fl = pd.to_numeric(b.storeys_above_ground, errors="coerce")
    fl = fl.where(fl > 0, np.round(pd.to_numeric(b.measured_height, errors="coerce") / 3.2))
    b["fl"] = fl.fillna(1).clip(lower=1)
    b["fa"] = b.cal_area_m2 * b.fl
    print(f"{len(b):,} buildings", flush=True)
    bj = gpd.sjoin(b, par[["geometry"]], predicate="within")
    g = bj.groupby("index_right")
    agg = pd.DataFrame({"fa": g.fa.sum(), "fl": g.fl.max(), "nb": g.size()})
    main = bj[bj.u != 461].sort_values("fa", ascending=False)
    main = main[~main.index_right.duplicated()].set_index("index_right")
    mix = bj.assign(r=bj.u.isin([411, 412]), c=bj.u.isin([401, 402, 403, 404])).groupby("index_right")[["r", "c"]].any()
    name = bj.dropna(subset=["gml_name"]).sort_values("fa", ascending=False)
    name = name[~name.index_right.duplicated()].set_index("index_right").gml_name
    df = par.join(agg)
    for c in ("fa", "fl", "nb"): df[c] = df[c].fillna(0)
    mu = main.u.reindex(df.index)
    lu = mu.map(USE).fillna("")
    lu = np.where(lu == "R", np.where(df.fl <= 5, "02", "03"), lu)
    both = mix.reindex(df.index).fillna(False)
    lu = np.where(both.r & both.c, "04", lu)
    lu = np.where((lu == "") & (df.nb == 0), "11", lu)
    df["LandUse"] = lu
    sqm = df.geometry.area
    df["LotArea"] = (sqm * SQFT).round()
    df["BldgArea"] = (df.fa * SQFT).round()
    df["BuiltFAR"] = np.where(sqm > 0, df.fa / sqm, np.nan).round(2)
    df["NumFloors"] = df.fl
    df["NumBldgs"] = df.nb
    df["UnitsRes"] = 0
    df["YearBuilt"] = 0
    df["BldgClass"] = mu.map(lambda v: USE_EN.get(int(v), "") if pd.notna(v) else "").values
    jp = {401: "業務施設", 402: "商業施設", 403: "宿泊施設", 404: "商業系複合施設", 411: "住宅", 412: "共同住宅", 413: "店舗等併用住宅",
          414: "店舗等併用共同住宅", 415: "作業所併用住宅", 421: "官公庁施設", 422: "文教厚生施設", 431: "運輸倉庫施設", 441: "工場",
          451: "農林漁業用施設", 452: "供給処理施設", 453: "防衛施設", 454: "その他"}
    col = {401: "#C0392B", 402: "#E74C3C", 403: "#EC7063", 404: "#F1948A", 411: "#F7DC6F", 412: "#D68910", 413: "#F0B27A", 414: "#DC7633",
           415: "#E59866", 421: "#2E86C1", 422: "#5DADE2", 431: "#7F8C8D", 441: "#8E44AD", 451: "#82B366", 452: "#566573", 453: "#1B2631", 454: "#BFC9CA"}
    lab = {k: f"{jp[k]} ({USE_EN[k].lower()})" for k in jp}
    seen = [k for k in jp if (mu == k).any()]
    df["NativeLU"] = N.encode(mu.map(lambda v: lab.get(int(v)) if pd.notna(v) else None).values, lambda n, k: col[seen[k]],
                              "PLATEAU building use", os.path.join(a.out, "tokyo_pluto.native.json"), order=[lab[k] for k in seen])
    ward = df.city.map(WARDS)
    nm = name.reindex(df.index)
    df["Address"] = [f"{n}, {c}, {w}" if isinstance(n, str) else f"{c}, {w}" for n, c, w in zip(nm, df.cname.fillna(""), ward)]
    df["BCT2020"] = df.chome.astype(np.int64).astype(str)
    shape = 4 * np.pi * df.geometry.area / df.geometry.length ** 2
    road = (df.nb == 0) & ((shape < 0.12) | (df.geometry.area < 15))
    df = df[~road].reset_index(drop=True)
    cen = gpd.GeoDataFrame(geometry=df.geometry.representative_point(), crs=CRS)
    print(f"  dropped {int(road.sum()):,} road, river and sliver polygons; grouping parcels into street blocks …", flush=True)
    blk = np.zeros(len(df), dtype=np.int64); nxt = 0
    for w in sorted(df.city.unique()):
        idx = np.flatnonzero(df.city.values == w)
        u = shapely.union_all(shapely.buffer(df.geometry.values[idx], 0.3, quad_segs=1))
        comps = gpd.GeoDataFrame(geometry=list(getattr(u, "geoms", [u])), crs=CRS)
        j = gpd.sjoin(cen.iloc[idx], comps, predicate="within", how="left")
        j = j[~j.index.duplicated()].index_right.reindex(cen.index[idx])
        miss = j.isna()
        if miss.any():
            nb = gpd.sjoin_nearest(cen.iloc[idx][miss.values], comps); j[miss] = nb[~nb.index.duplicated()].index_right
        blk[idx] = j.values.astype(np.int64) + nxt + 1; nxt += len(comps)
    df["bk"] = blk
    df = df.sort_values(["bk", "chome"]).reset_index(drop=True)
    df["lot"] = df.groupby("bk").cumcount() + 1
    big = df.lot > 9999
    if big.any():
        df.loc[big, "bk"] = df.loc[big, "bk"] + nxt + 1 + (df.loc[big, "lot"] - 1) // 9999
        df["lot"] = df.groupby("bk").cumcount() + 1
    codes = {c: k + 1 for k, c in enumerate(sorted(df.bk.unique()))}
    df["BBL"] = df.bk.map(codes).astype(np.int64) * 10000 + df.lot
    df["Version"] = "tyo26"
    cols = ["BBL", "Address", "LandUse", "UnitsRes", "BldgArea", "LotArea", "BuiltFAR", "YearBuilt", "NumFloors",
            "ZoneDist1", "BCT2020", "Version", "BldgClass", "NumBldgs", "NativeLU"]
    gpd.GeoDataFrame(df[cols], geometry=df.geometry.values, crs=CRS).to_file(os.path.join(a.out, "tokyo_pluto.gpkg"), layer="lots", driver="GPKG")
    print(f"  {len(df):,} lots in {len(codes):,} blocks; land use known for {(df.LandUse != '').mean() * 100:.1f}%", flush=True)
    def solid(g):
        ps = [shapely.Polygon(p.exterior, [r for r in p.interiors if shapely.Polygon(r).area > 20000]) for p in getattr(g, "geoms", [g]) if p.area > 200]
        return shapely.MultiPolygon(ps) if ps else g
    cov = par.assign(BCT2020=par.chome.astype(np.int64).astype(str))
    cov = cov[cov.BCT2020.isin(set(df.BCT2020))]
    tr = gpd.GeoDataFrame(cov[["BCT2020", "cname", "city"]], geometry=shapely.buffer(cov.geometry.values, 1, quad_segs=1), crs=CRS).dissolve(by="BCT2020", aggfunc="first").reset_index()
    tr["geometry"] = [solid(g) for g in shapely.buffer(tr.geometry.values, -1, quad_segs=1)]
    tr["boroct2020"] = tr.BCT2020; tr["nta2020"] = tr.city.astype(str); tr["ctlabel"] = tr.cname; tr["boroname"] = "Tokyo"
    bd = os.path.join(a.out, "boundaries"); os.makedirs(bd, exist_ok=True)
    tr[["boroct2020", "nta2020", "ctlabel", "boroname", "geometry"]].to_crs(4326).to_file(os.path.join(bd, "63ge-mke6.geojson"), driver="GeoJSON")
    wd = tr.dissolve(by="nta2020").reset_index(); wd["geometry"] = [solid(g) for g in wd.geometry.values]
    wd["ntaname"] = wd.nta2020.astype(int).map(WARDS) + " Ward"
    wd[["nta2020", "ntaname", "geometry"]].to_crs(4326).to_file(os.path.join(bd, "9nt8-h7nd.geojson"), driver="GeoJSON")
    print(f"  {len(tr):,} chome (as tracts), {len(wd)} wards")

if __name__ == "__main__":
    main()
