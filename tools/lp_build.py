"""lp_build.py — shared writers for a Lot Profiler release folder (data/<release>/), used by"""
import gzip, json, os, struct, time, zlib
import numpy as np

Q = 1e6
BOX_UNIT = 1e-5
CHUNK = 512

LAND_USE = ["1-2 family", "Multifamily walk-up", "Multifamily elevator",
            "Mixed residential/commercial", "Commercial/office", "Industrial/manufacturing",
            "Transportation/utility", "Public facilities/institutions", "Open space/recreation",
            "Parking", "Vacant land", "Other/unknown"]
UNIT_BUCKETS = ["1 unit", "2 units", "3 units", "4 units", "5-9 units", "10-19 units",
                "20-49 units", "50-99 units", "100+ units"]
FAR_CATS = ["High unused FAR", "Moderate unused FAR", "Low unused FAR", "Near FAR limit",
            "Over modeled FAR", "Use not allowed / no modeled FAR", "Excluded: park/transit/open space"]

def land_use_index(code):
    s = np.asarray(code, dtype=object)
    out = np.full(len(s), 11, np.uint8)
    for k in range(1, 12):
        out[(s == f"{k:02d}") | (s == str(k))] = k - 1
    return out

def unit_band(units, lu):
    u = np.nan_to_num(np.asarray(units, np.float64), nan=0)
    res = (lu <= 3) | (lu == 11)
    edges = np.array([1, 2, 3, 4, 5, 10, 20, 50, 100])
    band = (np.searchsorted(edges, u, side="right") - 1).astype(np.int16)
    band[(u <= 0) | ~res] = 255
    return band.astype(np.uint8)

def whole_floors(numfloors):
    f = np.asarray(numfloors, np.float64)
    out = np.where(np.isnan(f) | (f <= 0), 0, np.clip(np.floor(np.nan_to_num(f)), 1, 255))
    return out.astype(np.uint8)

def varints(z):
    z = np.asarray(z, np.uint64)
    nb = 1 + sum((z >= np.uint64(1 << (7 * k))).astype(np.int64) for k in range(1, 5))
    pos = np.cumsum(nb) - nb
    buf = np.zeros(int(nb.sum()), np.uint8)
    for k in range(5):
        m = nb > k
        if not m.any(): break
        v = ((z[m] >> np.uint64(7 * k)) & np.uint64(127)).astype(np.uint8)
        buf[pos[m] + k] = v | ((nb[m] > k + 1).astype(np.uint8) << 7)
    return buf.tobytes()

def zigzag(v):
    v = np.asarray(v, np.int64)
    return ((v << 1) ^ (v >> 63)).astype(np.uint64)

def deflate(b):
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    return c.compress(b) + c.flush()

def write_pack(path, magic, header, sections):
    body, offset = [], 0
    header = dict(header); header["sections"] = {}
    for name, arr in sections.items():
        arr = np.ascontiguousarray(arr)
        pad = (-offset) % 8
        if pad: body.append(b"\0" * pad); offset += pad
        header["sections"][name] = [arr.dtype.str.lstrip("<|="), offset, int(arr.size)]
        b = arr.astype(arr.dtype.newbyteorder("<")).tobytes(); body.append(b); offset += len(b)
    hj = json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode()
    head = magic + struct.pack("<I", len(hj)) + hj
    head += b"\0" * ((-len(head)) % 8)
    raw = head + b"".join(body)
    with open(path, "wb") as fh: fh.write(gzip.compress(raw, 9))
    return len(raw), os.path.getsize(path)

def read_pack(path):
    u = gzip.decompress(open(path, "rb").read())
    hl = struct.unpack("<I", u[4:8])[0]; H = json.loads(u[8:8 + hl]); base = -(-(8 + hl) // 8) * 8
    P = {"_magic": u[:4], "H": H}
    for name, (t, off, cnt) in H["sections"].items():
        P[name] = np.frombuffer(u, dtype="<" + t, count=cnt, offset=base + off)
    return P

def ragged(geoms):
    import shapely
    out = []
    for g in geoms:
        polys = []
        if g is not None and not g.is_empty:
            for p in (g.geoms if g.geom_type == "MultiPolygon" else [g]):
                if p.geom_type != "Polygon" or p.is_empty: continue
                rings = []
                for r in [p.exterior, *p.interiors]:
                    c = np.round(np.asarray(r.coords)[:-1] * Q).astype(np.int64)
                    if len(c) >= 3: rings.append(c)
                if rings: polys.append(rings)
        out.append(polys)
    return out

def encode_shapes(shapes, origin_q):
    ox, oy = origin_q
    out = []
    for polys in shapes:
        toks = [np.array([len(polys)], np.uint64)]
        px, py = ox, oy
        for rings in polys:
            toks.append(np.array([len(rings)], np.uint64))
            for r in rings:
                toks.append(np.array([len(r)], np.uint64))
                d = np.diff(r, axis=0, prepend=np.array([[px, py]]))
                toks.append(zigzag(d.ravel()))
                px, py = r[-1]
        out.append(varints(np.concatenate(toks)))
    return out

def write_chunks(path, blobs, size=CHUNK):
    offs = [0]
    with open(path, "wb") as fh:
        for s in range(0, len(blobs), size):
            c = deflate(b"".join(blobs[s:s + size])); fh.write(c); offs.append(offs[-1] + len(c))
    return np.array(offs, np.uint64)

def write_rec_chunks(path, cols, n, size=CHUNK):
    def clean(v):
        if v is None: return None
        if isinstance(v, (float, np.floating)):
            if np.isnan(v): return None
            return int(v) if float(v).is_integer() else round(float(v), 4)
        if isinstance(v, (np.integer,)): return int(v)
        if isinstance(v, str): v = v.strip(); return v or None
        return v
    offs = [0]
    with open(path, "wb") as fh:
        for s in range(0, n, size):
            obj = {k: [clean(x) for x in v[s:s + size]] for k, v in cols.items()}
            c = deflate(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()); fh.write(c); offs.append(offs[-1] + len(c))
    return np.array(offs, np.uint64)

LOT_TILE_MINZOOM = 12

def write_tiles(path, gdf, layer, minzoom, maxzoom, simplification=0.5, name=None):
    import pyogrio
    if os.path.exists(path): os.remove(path)
    t = time.time()
    pyogrio.write_dataframe(gdf, path, driver="PMTiles", layer=layer, dataset_options={
        "NAME": name or layer, "MINZOOM": str(minzoom), "MAXZOOM": str(maxzoom),
        "MAX_SIZE": "20000000", "MAX_FEATURES": "5000000", "SIMPLIFICATION": str(simplification)})
    print(f"  {os.path.basename(path)}: {len(gdf):,} features, z{minzoom}-{maxzoom}, "
          f"{os.path.getsize(path)/1e6:.1f} MB in {time.time()-t:.0f}s", flush=True)

def tile_frame(geoms, props):
    import geopandas as gpd
    return gpd.GeoDataFrame(props, geometry=list(geoms), crs=4326)

def release_order(rid):
    yy, rest = rid.split("v"); return (int(yy), float(rest))

def update_manifest(data_dir, entry):
    man_path = os.path.join(data_dir, "releases.json")
    man = json.load(open(man_path, encoding="utf-8")) if os.path.exists(man_path) else []
    prev = next((m for m in man if m["id"] == entry["id"]), {})
    for k in ("transit", "released", "far"):
        if prev.get(k) and not entry.get(k): entry[k] = prev[k]
    man = [m for m in man if m["id"] != entry["id"]] + [entry]
    man.sort(key=lambda m: release_order(m["id"]))
    json.dump(man, open(man_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return man

def folder_bytes(d):
    return sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)))
