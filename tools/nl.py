#!/usr/bin/env python3
"""nl.py — turn one Dutch municipality's cadastral parcels, BAG buildings and units, 3D BAG floors and CBS land use into a MapPLUTO-shaped file and boundary files for build.py"""
import argparse, json, os
import numpy as np, pandas as pd
import native as N

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.abspath(os.path.join(HERE, "..", "..", "..", "Data", "netherlands_2026-11-07"))
CRS = 28992
SQFT = 10.7639
STOREY = 3.0
IN_USE = ("Verblijfsobject in gebruik", "Verblijfsobject in gebruik (niet ingemeten)", "Verbouwing verblijfsobject")
COMM = ["winkelfunctie", "kantoorfunctie", "logiesfunctie", "bijeenkomstfunctie"]
FUNC_LU = {"winkelfunctie": "05", "kantoorfunctie": "05", "logiesfunctie": "05", "bijeenkomstfunctie": "05", "industriefunctie": "06",
           "onderwijsfunctie": "08", "gezondheidszorgfunctie": "08", "celfunctie": "08", "sportfunctie": "08"}
FUNC_EN = {"woonfunctie": "Residential", "winkelfunctie": "Retail", "kantoorfunctie": "Office", "logiesfunctie": "Hotel (lodging)",
           "bijeenkomstfunctie": "Assembly", "industriefunctie": "Industrial", "onderwijsfunctie": "Education", "gezondheidszorgfunctie": "Health care",
           "celfunctie": "Detention", "sportfunctie": "Sport", "overige gebruiksfunctie": "Other use"}
BBG_LU = {10: "07", 11: "07", 12: "07", 30: "07", 31: "06", 32: "09", 33: "06", 34: "11", 40: "09", 41: "09", 42: "09", 43: "09", 44: "09",
          50: "06", 51: "09", 60: "09", 61: "09", 62: "09"}
NAT = {**FUNC_EN, "mixed": "Residential and commercial", "nobld": "No building (CBS land use)"}
NAT_COL = {"Residential": "#E8B04B", "Residential and commercial": "#E8703C", "Retail": "#E8453C", "Office": "#A4161A", "Hotel (lodging)": "#C9184A",
           "Assembly": "#F28E2B", "Industrial": "#8E5CB5", "Education": "#2E86C1", "Health care": "#5DADE2", "Detention": "#1B4F72", "Sport": "#76B7B2",
           "Other use": "#9AA3AC", "No building (CBS land use)": "#555B61"}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gm", default="0363", help="CBS municipality code (Amsterdam: 0363)")
    ap.add_argument("--release", default="ams26")
    ap.add_argument("--city", default="Amsterdam")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    import geopandas as gpd, pyogrio, shapely
    src = os.path.join(DATA, a.gm); out = a.out or os.path.join(HERE, "..", "work", a.release[:3]); os.makedirs(out, exist_ok=True)
    wb = os.path.join(DATA, "wijkenbuurten_2025.gpkg")
    gm = gpd.read_file(wb, layer="gemeenten", where=f"gemeentecode='GM{a.gm}' AND water='NEE'").to_crs(CRS)
    land = shapely.union_all(gm.geometry.values)
    par = pyogrio.read_dataframe(os.path.join(src, "parcels.geojson"), columns=["identificatie_lokaal_id", "kadastrale_gemeente_waarde", "sectie", "perceelnummer"]).to_crs(CRS)
    par = par.drop_duplicates("identificatie_lokaal_id")
    par["geometry"] = [shapely.MultiPolygon([q for p in shapely.get_parts(g) for q in (p.geoms if p.geom_type == "MultiPolygon" else [p]) if q.geom_type == "Polygon"])
                       for g in shapely.make_valid(par.geometry.values)]
    par = par[~par.geometry.is_empty]
    rp = shapely.point_on_surface(par.geometry.values)
    shapely.prepare(land)
    par = par[shapely.contains(land, rp)].reset_index(drop=True)
    print(f"{len(par):,} parcels in {a.city}", flush=True)
    xmin, ymin, xmax, ymax = par.total_bounds
    bag = os.path.join(DATA, "bag-light.gpkg")
    vbo = pyogrio.read_dataframe(bag, layer="verblijfsobject", bbox=(xmin, ymin, xmax, ymax),
                                 columns=["identificatie", "gebruiksdoel", "oppervlakte", "status", "openbare_ruimte_naam", "huisnummer", "huisletter", "toevoeging", "pand_identificatie"])
    vbo = vbo[vbo.status.isin(IN_USE)]
    pand = pyogrio.read_dataframe(bag, layer="pand", bbox=(xmin, ymin, xmax, ymax), columns=["identificatie", "bouwjaar", "status"])
    pand = pand[pand.status.isin(["Pand in gebruik", "Pand in gebruik (niet ingemeten)", "Verbouwing pand", "Sloopvergunning verleend"])].reset_index(drop=True)
    print(f"{len(vbo):,} units (verblijfsobjecten), {len(pand):,} buildings (panden)", flush=True)
    f3 = pd.DataFrame(json.load(open(os.path.join(src, "floors3d.json"), encoding="utf-8")))
    f3["id"] = f3.identificatie.str.replace("NL.IMBAG.Pand.", "", regex=False)
    est = np.round((pd.to_numeric(f3.b3_h_70p, errors="coerce") - pd.to_numeric(f3.b3_h_maaiveld, errors="coerce")) / STOREY).clip(lower=1)
    bl = pd.to_numeric(f3.b3_bouwlagen, errors="coerce")
    f3["fl"] = bl.where(bl.notna() & (bl < 5), np.fmax(est, bl.fillna(0)))
    fl = f3.groupby("id").fl.max()
    pand["fl"] = pd.to_numeric(fl.reindex(pand.identificatie.astype(str)).values, errors="coerce")
    pand["fp"] = pand.geometry.area
    pand["yb"] = pd.to_numeric(pand.bouwjaar, errors="coerce")
    pj = gpd.sjoin(gpd.GeoDataFrame(pand.drop(columns="geometry"), geometry=shapely.point_on_surface(pand.geometry.values), crs=CRS),
                   par[["geometry"]], predicate="within").rename(columns={"index_right": "p"})
    g = pj.groupby("p")
    pagg = pd.DataFrame({"NumFloors": g.fl.max(), "NumBldgs": g.size()})
    pagg["YearBuilt"] = pj[pj.yb.between(1000, 2030)].sort_values("fp", ascending=False).drop_duplicates("p").set_index("p").yb
    vj = gpd.sjoin(vbo, par[["geometry"]], predicate="within").rename(columns={"index_right": "p"})
    vj["opp"] = pd.to_numeric(vj.oppervlakte, errors="coerce").fillna(0)
    vj["doel"] = vj.gebruiksdoel.fillna("").str.split(",")
    vj["share"] = vj.opp / vj.doel.str.len().clip(lower=1)
    ex = vj.explode("doel"); ex["doel"] = ex.doel.str.strip()
    area = ex.pivot_table(index="p", columns="doel", values="share", aggfunc="sum", fill_value=0)
    units = vj[vj.gebruiksdoel.fillna("").str.contains("woonfunctie")].groupby("p").size()
    vagg = pd.DataFrame({"BldgArea": vj.groupby("p").opp.sum(), "UnitsRes": units, "nv": vj.groupby("p").size()})
    adr = vj.assign(n=pd.to_numeric(vj.huisnummer, errors="coerce").fillna(1e6)).sort_values(["p", "n"]).drop_duplicates("p").set_index("p")
    adr = (adr.openbare_ruimte_naam.fillna("") + " " + adr.huisnummer.fillna("").astype(str).str.replace(r"\.0$", "", regex=True)
           + adr.huisletter.fillna("") + np.where(adr.toevoeging.fillna("") != "", "-" + adr.toevoeging.fillna(""), "")).str.strip()
    df = par.join(pagg).join(vagg)
    df["Address"] = adr.reindex(df.index).fillna("").values
    for c in ("NumFloors", "NumBldgs", "BldgArea", "UnitsRes", "nv", "YearBuilt"): df[c] = df[c].fillna(0)
    df["UnitsRes"] = df.UnitsRes.astype(int)
    df["BldgArea"] = (df.BldgArea * SQFT).round()
    sqm = df.geometry.area
    df["LotArea"] = (sqm * SQFT).round()
    df["BuiltFAR"] = np.where(df.LotArea > 0, df.BldgArea / df.LotArea, np.nan).round(2)
    A = area.reindex(df.index).fillna(0)
    for c in list(FUNC_EN): A[c] = A[c] if c in A else 0
    res = A["woonfunctie"] > 0
    comm = A[COMM].sum(axis=1) > 0
    other = A[[c for c in FUNC_EN if c != "woonfunctie"]]
    top = other.idxmax(axis=1).where(other.sum(axis=1) > 0, "")
    bbg = pyogrio.read_dataframe(os.path.join(DATA, "bbg2017.gpkg"), layer="bestand_bodemgebruik_2017", bbox=(xmin, ymin, xmax, ymax), columns=["bg2017"])
    cen = gpd.GeoDataFrame(geometry=shapely.point_on_surface(df.geometry.values), crs=CRS)
    bj = gpd.sjoin(cen, bbg, predicate="within", how="left"); bj = bj[~bj.index.duplicated()]
    bg = pd.to_numeric(bj.bg2017.reindex(df.index), errors="coerce").fillna(-1).astype(int)
    nob = (df.NumBldgs == 0) & (df.nv == 0)
    shape = 4 * np.pi * sqm / df.geometry.length ** 2
    water = nob & bg.between(70, 83)
    street = nob & ~bg.isin(list(BBG_LU)) & (shape < 0.12)
    df = df[~(water | street)].copy()
    print(f"  dropped {int(water.sum()):,} water parcels and {int(street.sum()):,} street parcels (no buildings, thin shape)", flush=True)
    keep = df.index
    res, comm, top, bg, nob, A = res[keep], comm[keep], top[keep], bg[keep], nob[keep], A.loc[keep]
    lu = np.where(res & comm, "04",
         np.where(res, np.where(df.UnitsRes <= 2, "01", np.where(df.NumFloors >= 6, "03", "02")),
         np.where(top != "", top.map(FUNC_LU).fillna(""),
         np.where(nob, bg.map(BBG_LU).fillna("11"), ""))))
    df["LandUse"] = lu
    nat = np.where(res & comm, "mixed", np.where(res, "woonfunctie", np.where(top != "", top, np.where(nob, "nobld", ""))))
    labels = pd.Series(nat, index=df.index).map(NAT).where(lambda s: s.notna(), None)
    order = [v for v in NAT.values() if (labels == v).any()]
    df["NativeLU"] = N.encode(labels.values, lambda n, k: NAT_COL[n], "BAG unit use",
                              os.path.join(out, f"{a.release}.native.json"), order=order)
    df["BldgClass"] = labels.fillna("").values
    df["ZoneDist1"] = ""
    bu = gpd.read_file(wb, layer="buurten", where=f"gemeentecode='GM{a.gm}' AND water='NEE'").to_crs(CRS)
    wk = gpd.read_file(wb, layer="wijken", where=f"gemeentecode='GM{a.gm}' AND water='NEE'").to_crs(CRS)
    cen = gpd.GeoDataFrame(geometry=shapely.point_on_surface(df.geometry.values), crs=CRS, index=df.index)
    t = gpd.sjoin(cen, bu[["buurtcode", "geometry"]], predicate="within", how="left"); t = t[~t.index.duplicated()]
    gid = t.buurtcode.reindex(df.index)
    near = gid.isna()
    if near.any():
        nb = gpd.sjoin_nearest(cen[near], bu[["buurtcode", "geometry"]]); gid[near] = nb[~nb.index.duplicated()].buurtcode
    df["BCT2020"] = gid.str[2:].values
    wkc = gid.str[:8].values
    blk = np.zeros(len(df), dtype=np.int64); nxt = 0
    for w in sorted(set(wkc)):
        idx = np.flatnonzero(wkc == w)
        u = shapely.union_all(shapely.buffer(df.geometry.values[idx], 0.3, quad_segs=1))
        comps = gpd.GeoDataFrame(geometry=list(getattr(u, "geoms", [u])), crs=CRS)
        j = gpd.sjoin(cen.iloc[idx], comps, predicate="within", how="left")
        j = j[~j.index.duplicated()].index_right.reindex(cen.index[idx])
        miss = j.isna()
        if miss.any():
            nb = gpd.sjoin_nearest(cen.iloc[idx][miss.values], comps); j[miss] = nb[~nb.index.duplicated()].index_right
        blk[idx] = j.values.astype(np.int64) + nxt + 1; nxt += len(comps)
    codes = {c: k + 1 for k, c in enumerate(sorted(set(blk)))}
    df["bk"] = pd.Series(blk, index=df.index).map(codes)
    df = df.sort_values(["bk", "perceelnummer"]).reset_index(drop=True)
    df["lot"] = df.groupby("bk").cumcount() + 1
    big = df.lot > 9999
    if big.any():
        df.loc[big, "bk"] = df.loc[big, "bk"] + len(codes) + 1 + (df.loc[big, "lot"] - 1) // 9999
        df["lot"] = df.groupby("bk").cumcount() + 1
    df["BBL"] = df.bk.astype(np.int64) * 10000 + df.lot
    df["Version"] = a.release
    cols = ["BBL", "Address", "LandUse", "UnitsRes", "BldgArea", "LotArea", "BuiltFAR", "YearBuilt", "NumFloors", "ZoneDist1",
            "BCT2020", "Version", "BldgClass", "NumBldgs", "NativeLU"]
    gp = os.path.join(out, f"{a.release}_pluto.gpkg")
    os.replace(os.path.join(out, f"{a.release}.native.json"), os.path.splitext(gp)[0] + ".native.json")
    gpd.GeoDataFrame(df[cols], geometry=df.geometry.values, crs=CRS).to_file(gp, layer="lots", driver="GPKG")
    print(f"  {len(df):,} lots in {len(codes):,} street blocks; land use known for {(df.LandUse != '').mean() * 100:.1f}%; {int(df.UnitsRes.sum()):,} dwellings", flush=True)
    bu = bu[bu.buurtcode.str[2:].isin(set(df.BCT2020))].copy()
    bu["boroct2020"] = bu.buurtcode.str[2:]; bu["nta2020"] = bu.wijkcode.str[2:]; bu["ctlabel"] = bu.buurtnaam; bu["boroname"] = a.city
    bd = os.path.join(out, "boundaries"); os.makedirs(bd, exist_ok=True)
    bu[["boroct2020", "nta2020", "ctlabel", "boroname", "geometry"]].to_crs(4326).to_file(os.path.join(bd, "63ge-mke6.geojson"), driver="GeoJSON")
    wk["nta2020"] = wk.wijkcode.str[2:]; wk["ntaname"] = wk.wijknaam.str.replace(r"^Wijk \d+\s+", "", regex=True)
    wk = wk[wk.nta2020.isin(set(bu.nta2020))]
    wk[["nta2020", "ntaname", "geometry"]].to_crs(4326).to_file(os.path.join(bd, "9nt8-h7nd.geojson"), driver="GeoJSON")
    print(f"  {len(bu):,} buurten (as tracts), {len(wk)} wijken (as neighborhoods)")

if __name__ == "__main__":
    main()
