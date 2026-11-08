#!/usr/bin/env python3
"""spain.py — turn one Spanish municipality's Catastro INSPIRE parcels, buildings and addresses into a MapPLUTO-shaped file and boundary files for build.py"""
import argparse, glob, os, re, zipfile
import numpy as np, pandas as pd
import native as N

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.abspath(os.path.join(HERE, "..", "..", "..", "Data", "spain_2026-11-07"))
SQFT = 10.7639
USE = {"1_residential": "R", "2_agriculture": "09", "3_industrial": "06", "4_1_office": "05", "4_2_retail": "05", "4_3_publicServices": "08"}
USE_EN = {"1_residential": "Residential", "2_agriculture": "Agriculture", "3_industrial": "Industrial", "4_1_office": "Office",
          "4_2_retail": "Retail", "4_3_publicServices": "Public services", "none": "No building in the cadastre", "rural": "Rural land, no building"}
USE_COL = {"1_residential": "#E8B04B", "2_agriculture": "#9CC27A", "3_industrial": "#8E5CB5", "4_1_office": "#A4161A",
           "4_2_retail": "#E8453C", "4_3_publicServices": "#2E86C1", "none": "#555B61", "rural": "#C9DFA6"}
STREET = {"CL": "Calle", "AV": "Avenida", "PZ": "Plaza", "PS": "Paseo", "CR": "Carretera", "GL": "Glorieta", "TR": "Travesía", "RD": "Ronda",
          "CM": "Camino", "PJ": "Pasaje", "CJ": "Callejón", "CS": "Cuesta", "BV": "Bulevar", "PQ": "Parque", "AU": "Autovía", "CU": "Costanilla",
          "RB": "Rambla", "GV": "Gran Vía", "TO": "Torrente", "BJ": "Bajada", "RR": "Riera", "VI": "Vía", "ML": "Muelle", "JR": "Jardín"}
DISTRICTS = {"28079": ["Centro", "Arganzuela", "Retiro", "Salamanca", "Chamartín", "Tetuán", "Chamberí", "Fuencarral-El Pardo", "Moncloa-Aravaca",
                       "Latina", "Carabanchel", "Usera", "Puente de Vallecas", "Moratalaz", "Ciudad Lineal", "Hortaleza", "Villaverde",
                       "Villa de Vallecas", "Vicálvaro", "San Blas-Canillejas", "Barajas"],
             "08019": ["Ciutat Vella", "Eixample", "Sants-Montjuïc", "Les Corts", "Sarrià-Sant Gervasi", "Gràcia", "Horta-Guinardó", "Nou Barris",
                       "Sant Andreu", "Sant Martí"],
             "46250": ["Ciutat Vella", "L'Eixample", "Extramurs", "Campanar", "La Saïdia", "El Pla del Real", "L'Olivereta", "Patraix", "Jesús",
                       "Quatre Carreres", "Poblats Marítims", "Camins al Grau", "Algirós", "Benimaclet", "Rascanya", "Benicalap", "Pobles del Nord",
                       "Pobles de l'Oest", "Pobles del Sud"]}

def gml(z, part):
    return "/vsizip/" + z + "/" + next(n for n in zipfile.ZipFile(z).namelist() if n.endswith(part + ".gml"))

def street(t):
    if not isinstance(t, str): return ""
    k, _, rest = t.strip().partition(" ")
    rest = " ".join(w if i == 0 or w not in ("De", "Del", "La", "Las", "Los", "Y", "El", "En") else w.lower() for i, w in enumerate(rest.title().split()))
    return f"{STREET.get(k, k.title())} {rest}".strip()

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--muni", default="28900", help="Catastro municipality code (Madrid: 28900)")
    ap.add_argument("--ine", default="28079", help="INE municipality code (Madrid: 28079)")
    ap.add_argument("--release", default="mad26")
    ap.add_argument("--city", default="Madrid")
    ap.add_argument("--crs", type=int, default=25830)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    import geopandas as gpd, pyogrio, shapely
    src = os.path.join(DATA, a.muni); out = a.out or os.path.join(HERE, "..", "work", a.release[:3]); os.makedirs(out, exist_ok=True)
    bu, cp, ad = (os.path.join(src, f) for f in ("bu.zip", "cp.zip", "ad.zip"))
    par = pyogrio.read_dataframe(gml(cp, "cadastralparcel"), columns=["nationalCadastralReference", "areaValue"]).to_crs(a.crs)
    par["geometry"] = [shapely.MultiPolygon([q for p in shapely.get_parts(g) for q in (p.geoms if p.geom_type == "MultiPolygon" else [p]) if q.geom_type == "Polygon"])
                       for g in shapely.make_valid(par.geometry.values)]
    par = par[~par.geometry.is_empty].rename(columns={"nationalCadastralReference": "ref"}).reset_index(drop=True)
    print(f"{len(par):,} parcels", flush=True)
    b = pyogrio.read_dataframe(gml(bu, "building"), read_geometry=False,
                               columns=["localId", "conditionOfConstruction", "beginning", "currentUse", "numberOfBuildingUnits", "numberOfDwellings", "value"])
    b = b.drop_duplicates("localId").set_index("localId")
    fp = os.path.join(src, "floors.parquet")
    if os.path.exists(fp): fl = pd.read_parquet(fp).fl
    else:
        p = pyogrio.read_dataframe(gml(bu, "buildingpart"), read_geometry=False, columns=["localId", "numberOfFloorsAboveGround"])
        p["ref"] = p.localId.str.replace(r"_part\d+$", "", regex=True); p["fl"] = pd.to_numeric(p.numberOfFloorsAboveGround, errors="coerce")
        fl = p.groupby("ref").fl.max(); fl.to_frame().to_parquet(fp)
    print(f"{len(b):,} buildings", flush=True)
    df = par.join(b, on="ref")
    df["NumFloors"] = fl.reindex(df.ref).fillna(0).values
    df["UnitsRes"] = pd.to_numeric(df.numberOfDwellings, errors="coerce").fillna(0).astype(int)
    df["BldgArea"] = (pd.to_numeric(df.value, errors="coerce").fillna(0) * SQFT).round()
    yr = pd.to_numeric(df.beginning.astype(str).str.extract(r"^(\d{4})", expand=False), errors="coerce")
    df["YearBuilt"] = yr.where(yr > 1500, 0).fillna(0)
    sqm = df.geometry.area
    df["LotArea"] = (sqm * SQFT).round()
    df["BuiltFAR"] = np.where(df.LotArea > 0, df.BldgArea / df.LotArea, np.nan).round(2)
    use = df.currentUse
    has = df.currentUse.notna() | df.conditionOfConstruction.notna()
    lu = use.map(USE).fillna("")
    lu = np.where(lu == "R", np.where(df.UnitsRes <= 2, "01", np.where(df.NumFloors >= 6, "03", "02")), lu)
    urban = df.ref.str.match(r"^\d{7}[A-Z]{2}\d{4}[A-Z]$")
    lu = np.where((lu == "") & ~has, np.where(urban, "11", "09"), lu)
    df["LandUse"] = lu
    nat = use.where(has, pd.Series(np.where(urban, "none", "rural"), index=df.index))
    order = [k for k in USE_EN if (nat == k).any()]
    df["NativeLU"] = N.encode(nat.map(USE_EN).values, lambda n, k: USE_COL[order[k]], "Catastro building use",
                              os.path.join(out, f"{a.release}.native.json"), order=[USE_EN[k] for k in order])
    df["BldgClass"] = use.map(USE_EN).fillna("")
    df["NumBldgs"] = has.astype(int)
    adr = pyogrio.read_dataframe(gml(ad, ""), layer="Address", read_geometry=False, columns=["localId", "designator"])
    tn = pyogrio.read_dataframe(gml(ad, ""), layer="ThoroughfareName", read_geometry=False, columns=["gml_id", "text"])
    tn["code"] = tn.gml_id.str.rsplit(".", n=1).str[-1]
    parts = adr.localId.str.split(".")
    adr["code"] = parts.str[2]; adr["ref"] = parts.str[-1]
    adr = adr.merge(tn[["code", "text"]], on="code", how="left")
    adr["n"] = pd.to_numeric(adr.designator, errors="coerce").fillna(1e6)
    adr = adr.sort_values(["ref", "n"]).drop_duplicates("ref").set_index("ref")
    lab = [f"{street(t)} {d}".strip() if isinstance(t, str) else "" for t, d in zip(adr.text, adr.designator.fillna(""))]
    df["Address"] = pd.Series(lab, index=adr.index).reindex(df.ref).fillna("").values
    cen = gpd.GeoDataFrame(geometry=df.geometry.representative_point(), crs=a.crs)
    sec = gpd.read_file(os.path.join(src, "secciones.geojson")).to_crs(a.crs)
    tr = sec[sec.TIPO == "SECCIONADO"].copy(); dis = sec[sec.TIPO == "DISTRITO"].copy()
    t = gpd.sjoin(cen, tr[["CUSEC", "geometry"]], predicate="within", how="left"); t = t[~t.index.duplicated()]
    gid = t.CUSEC.reindex(df.index)
    near = gid.isna()
    if near.any():
        nb = gpd.sjoin_nearest(cen[near], tr[["CUSEC", "geometry"]]); gid[near] = nb[~nb.index.duplicated()].CUSEC
    df["BCT2020"] = gid.values
    df["ZoneDist1"] = ""
    key = np.where(urban, df.ref.str[:5] + df.ref.str[7:14], df.ref.str[:8])
    codes = {c: k + 1 for k, c in enumerate(sorted(set(key)))}
    df["bk"] = pd.Series(key).map(codes).values
    df = df.sort_values(["bk", "ref"]).reset_index(drop=True)
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
    gpd.GeoDataFrame(df[cols], geometry=df.geometry.values, crs=a.crs).to_file(gp, layer="lots", driver="GPKG")
    print(f"  {len(df):,} lots in {len(codes):,} blocks; land use known for {(df.LandUse != '').mean() * 100:.1f}%; {int(df.UnitsRes.sum()):,} dwellings", flush=True)
    names = DISTRICTS.get(a.ine, [])
    tr["boroct2020"] = tr.CUSEC; tr["nta2020"] = tr.CDIS; tr["ctlabel"] = tr.CDIS + "-" + tr.CSEC; tr["boroname"] = a.city
    tr = tr[tr.CUSEC.isin(set(df.BCT2020))]
    bd = os.path.join(out, "boundaries"); os.makedirs(bd, exist_ok=True)
    tr[["boroct2020", "nta2020", "ctlabel", "boroname", "geometry"]].to_crs(4326).to_file(os.path.join(bd, "63ge-mke6.geojson"), driver="GeoJSON")
    dis["nta2020"] = dis.CDIS
    dis["ntaname"] = [names[int(c) - 1] if names and int(c) <= len(names) else f"District {int(c)}" for c in dis.CDIS]
    dis[["nta2020", "ntaname", "geometry"]].to_crs(4326).to_file(os.path.join(bd, "9nt8-h7nd.geojson"), driver="GeoJSON")
    print(f"  {len(tr):,} census sections (as tracts), {len(dis)} districts")

if __name__ == "__main__":
    main()
