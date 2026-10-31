"""pluto_io.py — dependency-free readers for the MapPLUTO shapefiles exported"""
import math, re, struct
import numpy as np

FT = 1200 / 3937
A, INV_F = 6378137.0, 298.257222101
E2 = (2 - 1 / INV_F) / INV_F
E = math.sqrt(E2)
LAT1, LAT2 = math.radians(40 + 40 / 60), math.radians(41 + 2 / 60)
LAT0, LON0 = math.radians(40 + 10 / 60), math.radians(-74.0)
FE, FN = 984250.0 * FT, 0.0

def _m(phi):  return math.cos(phi) / math.sqrt(1 - E2 * math.sin(phi) ** 2)
def _t(phi):
    s = math.sin(phi)
    return math.tan(math.pi / 4 - phi / 2) / ((1 - E * s) / (1 + E * s)) ** (E / 2)

_N = (math.log(_m(LAT1)) - math.log(_m(LAT2))) / (math.log(_t(LAT1)) - math.log(_t(LAT2)))
_F = _m(LAT1) / (_N * _t(LAT1) ** _N)
_RHO0 = A * _F * _t(LAT0) ** _N

def sp_to_lnglat(x_ft, y_ft):
    x = np.asarray(x_ft, dtype=np.float64) * FT - FE
    y = _RHO0 - (np.asarray(y_ft, dtype=np.float64) * FT - FN)
    rho = np.sign(_N) * np.hypot(x, y)
    t = (rho / (A * _F)) ** (1 / _N)
    theta = np.arctan2(x, y)
    lng = theta / _N + LON0
    phi = np.pi / 2 - 2 * np.arctan(t)
    for _ in range(8):
        s = np.sin(phi)
        phi = np.pi / 2 - 2 * np.arctan(t * ((1 - E * s) / (1 + E * s)) ** (E / 2))
    return np.degrees(lng), np.degrees(phi)

def read_dbf(path, encoding="utf-8"):
    with open(path, "rb") as f:
        data = f.read()
    n, hlen, rlen = struct.unpack("<IHH", data[4:12])
    fields, pos = [], 32
    while data[pos] != 0x0D:
        name = data[pos:pos + 11].split(b"\0")[0].decode("ascii")
        ftype = chr(data[pos + 11]); flen = data[pos + 16]; fdec = data[pos + 17]
        fields.append((name, ftype, flen, fdec)); pos += 32
    cols = {f[0]: [] for f in fields}
    for i in range(n):
        rec = data[hlen + i * rlen: hlen + (i + 1) * rlen]
        off = 1
        for name, ftype, flen, fdec in fields:
            raw = rec[off:off + flen]; off += flen
            s = raw.decode(encoding, "replace").strip()
            if ftype in "NF":
                try: v = float(s) if s and not s.startswith("*") else None
                except ValueError: v = None
            else:
                v = s
            cols[name].append(v)
    return n, cols

def read_shp_polygons(path):
    with open(path, "rb") as f:
        data = f.read()
    pos, out = 100, []
    while pos < len(data):
        _, clen = struct.unpack(">ii", data[pos:pos + 8]); pos += 8
        body = data[pos:pos + clen * 2]; pos += clen * 2
        stype = struct.unpack("<i", body[:4])[0]
        if stype == 0:
            out.append([]); continue
        nparts, npts = struct.unpack("<ii", body[36:44])
        parts = struct.unpack(f"<{nparts}i", body[44:44 + 4 * nparts])
        pts = np.frombuffer(body, dtype="<f8", count=2 * npts,
                            offset=44 + 4 * nparts).reshape(-1, 2)
        bounds = list(parts) + [npts]
        out.append([pts[bounds[k]:bounds[k + 1]] for k in range(nparts)])
    return out

def signed_area(ring):
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.dot(x[:-1], y[1:]) - np.dot(x[1:], y[:-1]))

def group_polygons(rings):
    polys = []
    for r in rings:
        if len(r) < 4: continue
        if signed_area(r) <= 0 or not polys: polys.append([r])
        else: polys[-1].append(r)
    return polys

def read_release(xml_path):
    try:
        txt = open(xml_path, encoding="utf-8", errors="ignore").read()
    except OSError:
        return None
    m = re.search(r"MapPLUTO\s+(\d{2}v\d+(?:\.\d+)?)", txt, re.I)
    return m.group(1).lower() if m else None
