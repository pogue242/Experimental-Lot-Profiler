#!/usr/bin/env python3
"""vienna.py — turn Vienna's cadastre parcels and city map layers into a MapPLUTO-shaped file and boundary files for build.py"""
import argparse, glob, os, re, sys
import numpy as np, pandas as pd
import native as N

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "..", "..", "Data", "vienna_2026-10-30"))
CRS = 31256
SQFT = 10.7639
STOREY = 3.5
LU = {111: "R", 112: "R", 113: "R", 114: "R", 121: "04", 122: "05", 123: "05", 131: "06", 141: "08", 142: "08", 143: "08", 144: "08",
      151: "07", 152: "07", 153: "07", 154: "11", 155: "07", 211: "09", 212: "09", 221: "09", 222: "09", 223: "09", 231: "09",
      232: "09", 233: "09", 241: "09", 311: "", 321: "10", 322: "07", 323: "06"}
AGE = {"Vor 1683": 1660, "vor 1848": 1820, "Nach 1976": 1995, "nach 1945": 1965, "Keine Angabe": 0}

def year_of(t):
    if not isinstance(t, str): return 0
    if t in AGE: return AGE[t]
    y = [int(v) for v in re.findall(r"\d{4}", t)]
    return int(np.mean(y)) if y else 0

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "work", "vie"))
    a = ap.parse_args()
    import geopandas as gpd, pyogrio, shapely
    os.makedirs(a.out, exist_ok=True)
    s = lambda f: os.path.join(a.src, f)
    rd = lambda f, **k: pyogrio.read_dataframe(s(f), **k).set_crs(CRS, allow_override=True)
    par = pd.concat([pyogrio.read_dataframe(f) for f in sorted(glob.glob(s("dkm/*/*GST_V2.shp")))], ignore_index=True)
    par = gpd.GeoDataFrame(par, geometry="geometry", crs=CRS)
    par = par[par.geometry.notna() & ~par.geometry.is_empty].reset_index(drop=True)
    par["geometry"] = shapely.make_valid(par.geometry.values)
    nfl = pd.concat([pyogrio.read_dataframe(f) for f in sorted(glob.glob(s("dkm/*/*NFL_V2.shp")))], ignore_index=True)
    nfl = gpd.GeoDataFrame(nfl[["NS"]], geometry=nfl.geometry.values, crs=CRS)
    road = nfl[nfl.NS == 95].copy(); road["geometry"] = road.representative_point()
    road["a"] = nfl.loc[road.index].geometry.area.values
    rj = gpd.sjoin(road, par[["geometry"]], predicate="within")
    share = rj.groupby("index_right").a.sum() / par.geometry.area
    par = par[~(share.reindex(par.index).fillna(0) > 0.5)].reset_index(drop=True)
    print(f"{len(par):,} parcels after dropping street parcels", flush=True)
    cen = gpd.GeoDataFrame(geometry=par.geometry.representative_point(), crs=CRS)
    def at(layer, cols):
        j = gpd.sjoin(cen, layer[cols + ["geometry"]], predicate="within", how="left")
        return j[~j.index.duplicated()][cols].reindex(cen.index)
    rnj = at(rd("REALNUT2024OGD.json"), ["CODE", "LEV3"]); rn = rnj.CODE
    wid = at(rd("GENFLWIDMUNGOGD.json"), ["WIDMUNG"]).WIDMUNG
    zb = rd("ZAEHLBEZIRKOGD.json")
    zbz = at(zb, ["ZBEZ"]).ZBEZ
    if zbz.isna().any():
        m = zbz.isna(); nb = gpd.sjoin_nearest(cen[m], zb[["ZBEZ", "geometry"]]); zbz[m] = nb[~nb.index.duplicated()].ZBEZ
    blk = rd("BAUBLOCKOGD.json")
    bk = at(blk, ["BLK"]).BLK
    if bk.isna().any():
        m = bk.isna(); nb = gpd.sjoin_nearest(cen[m], blk[["BLK", "geometry"]]); bk[m] = nb[~nb.index.duplicated()].BLK
    two = lambda f, cols: pd.concat([rd(f + ".json", columns=cols), rd(f + "_2.json", columns=cols)], ignore_index=True)
    bld = two("FMZKBKMOGD", ["LAYER", "O_KOTE", "T_KOTE", "HOEHE_DGM"])
    print(f"{len(bld):,} building-model parts", flush=True)
    bld = bld[bld.LAYER == "Gebäude"].reset_index(drop=True)
    base = bld.T_KOTE.fillna(bld.HOEHE_DGM)
    bld["h"] = (bld.O_KOTE - base).clip(lower=0)
    bld["fl"] = np.where(bld.h > 0, np.maximum(1, np.round(bld.h / STOREY)), 0)
    bld["fa"] = bld.geometry.area * bld.fl
    bp = gpd.GeoDataFrame(bld[["fl", "fa"]], geometry=bld.geometry.representative_point(), crs=CRS)
    bj = gpd.sjoin(bp, par[["geometry"]], predicate="within")
    g = bj.groupby("index_right")
    agg = pd.DataFrame({"fa": g.fa.sum(), "fl": g.fl.max(), "nb": g.size()})
    gt = two("GEBAEUDETYPOGD", ["OBJ_STR_TXT", "BAUTYP_TXT"])
    print(f"{len(gt):,} building-type records", flush=True)
    gt["a"] = gt.geometry.area; gt["geometry"] = gt.representative_point()
    tj = gpd.sjoin(gt, par[["geometry"]], predicate="within").sort_values("a", ascending=False)
    tj = tj[~tj.index_right.duplicated()].set_index("index_right")
    ad = rd("ADRESSENOGD.json", columns=["NAME", "ON_VON_NUM"])
    ad["label"] = ad.NAME.fillna("")
    ad["n"] = pd.to_numeric(ad.ON_VON_NUM, errors="coerce").fillna(1e6)
    aj = gpd.sjoin(ad[["label", "n", "geometry"]], par[["geometry"]], predicate="within").sort_values(["n", "label"])
    aj = aj[~aj.index_right.duplicated()].set_index("index_right").label
    df = par.join(agg)
    df["fa"] = df.fa.fillna(0); df["fl"] = df.fl.fillna(0); df["nb"] = df.nb.fillna(0)
    code = rn.fillna(0).astype(int)
    lu = code.map(LU).fillna("")
    res = lu == "R"
    lu = np.where(res, np.where(df.fl <= 2, "01", np.where(df.fl <= 5, "02", "03")), lu)
    lu = np.where((lu == "") & (df.fa == 0) & (code != 311), "11", lu)
    df["LandUse"] = lu
    sqm = df.geometry.area
    df["LotArea"] = (sqm * SQFT).round()
    df["BldgArea"] = (df.fa * SQFT).round()
    df["BuiltFAR"] = np.where(sqm > 0, df.fa / sqm, np.nan).round(2)
    df["NumFloors"] = df.fl
    df["NumBldgs"] = df.nb
    df["UnitsRes"] = 0
    fam = {1: "#E8B04B", 2: "#5FA35A", 3: "#8A8F96"}
    sub = {111: "#B5651D", 112: "#D08A3A", 113: "#E8B04B", 114: "#F5DA8C", 121: "#E8603C", 122: "#C0392B", 123: "#E57373", 131: "#8E5CB5",
           141: "#2E86C1", 142: "#5DADE2", 143: "#1B4F72", 144: "#85C1E9", 151: "#5D6D7E", 152: "#7F8C8D", 153: "#3498DB", 154: "#A6ACAF",
           155: "#6E5A4E", 211: "#1E6B3A", 212: "#8BC48A", 221: "#D9C77A", 222: "#9E7A3C", 223: "#B8D07A", 231: "#6B8E6B", 232: "#3FA65A",
           233: "#7DCEA0", 241: "#4FA3D9", 311: "#BFC5CB", 321: "#9AA3AC", 322: "#6C7A89", 323: "#A569BD"}
    lev3 = rnj.LEV3.where(rnj.LEV3.notna(), None).values
    names = [t for c, t in sorted(set(zip(rnj.CODE.dropna().astype(int), rnj.LEV3.dropna())))]
    code_of = dict((t, c) for c, t in set(zip(rnj.CODE.dropna().astype(int), rnj.LEV3.dropna())))
    df["NativeLU"] = N.encode(lev3, lambda n, k: sub.get(code_of.get(n), fam.get(code_of.get(n, 300) // 100, "#999999")), "Realnutzung 2024",
                              os.path.join(a.out, "vienna_pluto.native.json"), order=names)
    df["YearBuilt"] = [year_of(t) for t in tj.OBJ_STR_TXT.reindex(df.index)]
    df["BldgClass"] = tj.BAUTYP_TXT.reindex(df.index).fillna("")
    df["ZoneDist1"] = wid.fillna("").values
    df["Address"] = aj.reindex(df.index).fillna("").values
    df["BCT2020"] = zbz.values
    df["blk"] = bk.values
    codes = {c: k + 1 for k, c in enumerate(sorted(df.blk.astype(str).unique()))}
    df["bk"] = df.blk.astype(str).map(codes)
    df["gnr"] = df.KG.astype(str) + "-" + df.GNR.astype(str)
    df = df.sort_values(["bk", "gnr"]).reset_index(drop=True)
    df["lot"] = df.groupby("bk").cumcount() + 1
    if df.lot.max() > 9999: sys.exit("a block has more than 9,999 parcels")
    df["BBL"] = df.bk.astype(np.int64) * 10000 + df.lot
    df["Version"] = "vie26"
    df["OwnerName"] = "KG " + df.KG.astype(str) + ", parcel " + df.GNR.astype(str)
    cols = ["BBL", "Address", "LandUse", "UnitsRes", "BldgArea", "LotArea", "BuiltFAR", "YearBuilt", "NumFloors",
            "ZoneDist1", "BCT2020", "Version", "OwnerName", "BldgClass", "NumBldgs", "NativeLU"]
    gpd.GeoDataFrame(df[cols], geometry=df.geometry.values, crs=CRS).to_file(os.path.join(a.out, "vienna_pluto.gpkg"), layer="lots", driver="GPKG")
    print(f"  {len(df):,} lots in {len(codes):,} blocks; land use known for {(df.LandUse != '').mean() * 100:.1f}%; "
          f"{(df.Address != '').mean() * 100:.1f}% with an address", flush=True)
    bz = rd("BEZIRKSGRENZEOGD.json")
    zb["boroct2020"] = zb.ZBEZ; zb["nta2020"] = zb.BEZ.astype(str).str.zfill(2)
    zb["ctlabel"] = zb.ZBEZ.str[:2].str.lstrip("0") + "/" + zb.ZBEZ.str[2:]; zb["boroname"] = "Wien"
    bd = os.path.join(a.out, "boundaries"); os.makedirs(bd, exist_ok=True)
    zb[["boroct2020", "nta2020", "ctlabel", "boroname", "geometry"]].to_crs(4326).to_file(os.path.join(bd, "63ge-mke6.geojson"), driver="GeoJSON")
    bz["nta2020"] = bz.BEZ.astype(str).str.zfill(2); bz["ntaname"] = bz.NAMEK_NUM
    bz[["nta2020", "ntaname", "geometry"]].to_crs(4326).to_file(os.path.join(bd, "9nt8-h7nd.geojson"), driver="GeoJSON")
    print(f"  {len(zb)} census districts (Zählbezirke), {len(bz)} districts")

if __name__ == "__main__":
    main()
