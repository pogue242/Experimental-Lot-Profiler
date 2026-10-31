#!/usr/bin/env python3
"""transit.py — download NYC subway (and PATH, LIRR, Metro-North) data for the Lot Profiler and"""
import argparse, collections, csv, datetime, gzip, io, json, math, os, re, struct, sys, time
import urllib.error, urllib.parse, urllib.request, zipfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")
STATIONS = "https://data.ny.gov/api/views/39hk-dx4f/rows.csv?accessType=DOWNLOAD"
ENTRANCES = "https://data.ny.gov/api/views/i9wp-a4ja/rows.csv?accessType=DOWNLOAD"
GTFS = ["https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip",
        "http://web.mta.info/developers/data/nyct/subway/google_transit.zip"]
RAIL_BRANCHES = ["https://data.ny.gov/resource/2vcb-zrh4.geojson?$limit=1000",
                 "https://data.ny.gov/api/geospatial/2vcb-zrh4?method=export&format=GeoJSON",
                 "https://data.ny.gov/api/v3/views/2vcb-zrh4/query.geojson?accessType=DOWNLOAD"]
OVERPASS = ["https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter"]
NYC = [-74.26, 40.49, -73.70, 40.92]
UA = {"User-Agent": "LotProfiler/1.7 (transit.py)"}
RAIL_GTFS = {"LIRR": "https://rrgtfsfeeds.s3.amazonaws.com/gtfslirr.zip", "MNR": "https://rrgtfsfeeds.s3.amazonaws.com/gtfsmnr.zip"}

TRUNK = {"A": "ACE", "C": "ACE", "E": "ACE", "B": "BDFM", "D": "BDFM", "F": "BDFM", "FX": "BDFM", "M": "BDFM",
         "G": "G", "J": "JZ", "Z": "JZ", "L": "L", "N": "NQRW", "Q": "NQRW", "R": "NQRW", "W": "NQRW",
         "GS": "S", "FS": "S", "H": "S", "1": "123", "2": "123", "3": "123", "4": "456", "5": "456",
         "6": "456", "6X": "456", "7": "7", "7X": "7", "SI": "SIR", "SIR": "SIR"}
TRUNK_COLOR = {"123": "#EE352E", "456": "#00933C", "7": "#B933AD", "ACE": "#0039A6", "BDFM": "#FF6319",
               "G": "#6CBE45", "JZ": "#996633", "L": "#A7A9AC", "NQRW": "#FCCC0A", "S": "#808183", "SIR": "#1D2F6F"}
TRUNK_ORDER = list(TRUNK_COLOR)
SHOW = {"FX": "F", "6X": "6", "7X": "7", "GS": "S", "FS": "S", "H": "S", "SI": "SIR"}
ROUTE_ORDER = list("1234567ACEBDFMGJZLNQRWS") + ["SIR"]
A_DIVISION = {"1", "2", "3", "4", "5", "6", "6X", "7", "7X", "GS"}
SECONDARY = {"G": 0.3, "S": 0.3, "SIR": 0.3}
RAIL_COLOR = "#4F5B66"

KX, KY = 111320 * math.cos(math.radians(40.7)), 110574

def get(url, data=None):
    req = urllib.request.Request(url, data=data, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()

def overpass(q, need):
    body = urllib.parse.urlencode({"data": q}).encode()
    for attempt in range(2):
        for url in OVERPASS:
            try:
                print(f"  asking {url.split('/')[2]} …")
                out = json.loads(get(url, body))
                if out.get("elements") or not need: return out
            except Exception as err:
                print(f"  {url.split('/')[2]} failed ({err.__class__.__name__}); trying the next server")
        time.sleep(20)
    if need: sys.exit("Every Overpass server failed or was busy. Wait a few minutes and run this again.")
    return {"elements": []}

def norm(row):
    return {re.sub(r"[^a-z0-9]", "", k.lower()): v for k, v in row.items()}

def latlon(r, lat_keys, lon_keys):
    for a, b in zip(lat_keys, lon_keys):
        try: return float(r[a]), float(r[b])
        except (KeyError, TypeError, ValueError): pass
    return None, None

def study_bbox(pad):
    man = json.load(open(os.path.join(DATA, "releases.json")))
    raw = gzip.decompress(open(os.path.join(DATA, man[-1]["file"]), "rb").read())
    hl = struct.unpack("<I", raw[4:8])[0]
    h = json.loads(raw[8:8 + hl])
    xs = [p[0] for a in h["areas"] for poly in a["polys"] for p in poly[0]]
    ys = [p[1] for a in h["areas"] for poly in a["polys"] for p in poly[0]]
    return [min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad]

def _densify(pts, step):
    P = [(x * KX, y * KY) for x, y in pts]
    out = [P[0]]
    for (x0, y0), (x1, y1) in zip(P, P[1:]):
        d = math.hypot(x1 - x0, y1 - y0)
        if d < 0.01: continue
        n = max(1, math.ceil(d / step))
        for s in range(1, n + 1): out.append((x0 + (x1 - x0) * s / n, y0 + (y1 - y0) * s / n))
    return out

def corridors(lines, T=6.0, step=6.0, par=0.85, spur=25.0, minshare=0.0):
    NX, NY, NS, TX, TY, NG = [], [], [], [], [], []
    grid = collections.defaultdict(list)
    cell = lambda x, y: (int(math.floor(x / T)), int(math.floor(y / T)))
    ew = collections.defaultdict(collections.Counter)
    for pts, routes, group, _ in sorted(lines, key=lambda l: (-l[3], -len(l[0]))):
        if not isinstance(routes, dict): routes = {r: 1 for r in routes}
        P = _densify(pts, step)
        if len(P) < 2: continue
        seq = []; done = set()
        for i, (x, y) in enumerate(P):
            a, b = P[max(0, i - 2)], P[min(len(P) - 1, i + 2)]
            tx, ty = b[0] - a[0], b[1] - a[1]; L = math.hypot(tx, ty) or 1; tx /= L; ty /= L
            cx, cy = cell(x, y); best, bd = -1, T * T
            for u in (-1, 0, 1):
                for v in (-1, 0, 1):
                    for j in grid.get((cx + u, cy + v), ()):
                        if NG[j] != group or abs(TX[j] * tx + TY[j] * ty) < par: continue
                        mx, my = NX[j] / NS[j], NY[j] / NS[j]
                        d = (mx - x) ** 2 + (my - y) ** 2
                        if d < bd: bd, best = d, j
            if best < 0:
                best = len(NX); NX.append(x); NY.append(y); NS.append(1); TX.append(tx); TY.append(ty); NG.append(group)
                grid[cell(x, y)].append(best)
            elif not seq or seq[-1] != best:
                NX[best] += x; NY[best] += y; NS[best] += 1
            if not seq or seq[-1] != best: seq.append(best)
        for a, b in zip(seq, seq[1:]):
            k = (a, b) if a < b else (b, a)
            if k in done: continue
            done.add(k); ew[k].update(routes)
    top = collections.Counter()
    for c in ew.values():
        for r, v in c.items(): top[r] = max(top[r], v)
    edges = {}
    for k, c in ew.items():
        keep = {r for r, v in c.items() if v >= minshare * top[r]}
        edges[k] = keep or {max(c, key=c.get)}
    X = [NX[i] / NS[i] for i in range(len(NX))]; Y = [NY[i] / NS[i] for i in range(len(NY))]

    key = lambda a, b: (a, b) if a < b else (b, a)
    adj = collections.defaultdict(set)
    for a, b in edges: adj[a].add(b); adj[b].add(a)
    def walk():
        def brk(n):
            if len(adj[n]) != 2: return True
            p, q = adj[n]; return edges[key(n, p)] != edges[key(n, q)]
        seen, out = set(), []
        for a, b in list(edges):
            if (a, b) in seen: continue
            path = [a, b]; seen.add((a, b))
            for fwd in (True, False):
                while True:
                    end, prev = (path[-1], path[-2]) if fwd else (path[0], path[1])
                    if brk(end): break
                    nxt = next(x for x in adj[end] if x != prev)
                    k = key(end, nxt)
                    if k in seen: break
                    seen.add(k)
                    if fwd: path.append(nxt)
                    else: path.insert(0, nxt)
            out.append((path, frozenset(edges[key(a, b)])))
        return out
    for _ in range(3):
        cut = False
        for path, rs in walk():
            L = sum(math.hypot(X[a] - X[b], Y[a] - Y[b]) for a, b in zip(path, path[1:]))
            ends = [len(adj[path[0]]), len(adj[path[-1]])]
            if L < spur and 1 in ends and max(ends) > 2:
                for a, b in zip(path, path[1:]):
                    edges.pop(key(a, b), None); adj[a].discard(b); adj[b].discard(a)
                cut = True
        if not cut: break
    out = []
    for path, rs in walk():
        P = [(X[i], Y[i]) for i in path]
        for _ in range(3):
            if len(P) < 5: break
            P = [P[0]] + [((P[i-1][0] + 2 * P[i][0] + P[i+1][0]) / 4, (P[i-1][1] + 2 * P[i][1] + P[i+1][1]) / 4)
                          for i in range(1, len(P) - 1)] + [P[-1]]
        P = _simplify(P, 0.8)
        out.append(([(round(x / KX, 6), round(y / KY, 6)) for x, y in P], rs, path[0], path[-1]))
    return out

def _simplify(P, tol):
    if len(P) < 3: return P
    keep = [False] * len(P); keep[0] = keep[-1] = True; st = [(0, len(P) - 1)]
    while st:
        a, b = st.pop(); (ax, ay), (bx, by) = P[a], P[b]; L = math.hypot(bx - ax, by - ay) or 1e-9; md, mi = 0, -1
        for i in range(a + 1, b):
            d = abs((bx - ax) * (ay - P[i][1]) - (ax - P[i][0]) * (by - ay)) / L
            if d > md: md, mi = d, i
        if md > tol: keep[mi] = True; st += [(a, mi), (mi, b)]
    return [p for p, k in zip(P, keep) if k]

def subway_lines(gtfs_bytes, bbox):
    z = zipfile.ZipFile(io.BytesIO(gtfs_bytes))
    names = set(z.namelist())
    rd = lambda n: list(csv.DictReader(io.TextIOWrapper(z.open(n), encoding="utf-8-sig"))) if n in names else []
    if "shapes.txt" not in names: sys.exit("That GTFS feed has no shapes.txt, so it can't draw route lines.")
    shapes = collections.defaultdict(list)
    for r in rd("shapes.txt"):
        shapes[r["shape_id"]].append((int(r["shape_pt_sequence"]), float(r["shape_pt_lon"]), float(r["shape_pt_lat"])))
    shapes = {k: [(x, y) for _, x, y in sorted(v)] for k, v in shapes.items()}
    trips = rd("trips.txt")
    use = collections.defaultdict(collections.Counter)
    for t in trips:
        sid = t.get("shape_id") or t["trip_id"].rsplit("_", 1)[-1]
        if sid in shapes: use[sid][t["route_id"]] += 1
    route_trips = collections.Counter(t["route_id"] for t in trips)
    stops = {r["stop_id"]: r for r in rd("stops.txt")}
    parent = lambda sid: (stops.get(sid, {}).get("parent_station") or sid)
    ends = {}
    for r in rd("stop_times.txt"):
        q = int(r["stop_sequence"]); e = ends.get(r["trip_id"])
        if e is None: ends[r["trip_id"]] = [q, r["stop_id"], q, r["stop_id"]]
        else:
            if q < e[0]: e[0], e[1] = q, r["stop_id"]
            if q > e[2]: e[2], e[3] = q, r["stop_id"]
    stations = [(sid, float(r["stop_lon"]) * KX, float(r["stop_lat"]) * KY) for sid, r in stops.items()
                if not r.get("parent_station") and r.get("stop_lat")]
    def end_station(pt):
        x, y = pt[0] * KX, pt[1] * KY; best, bd = None, 350.0
        for sid, sx, sy in stations:
            d = math.hypot(sx - x, sy - y)
            if d < bd: best, bd = sid, d
        return best
    shape_ends = {sid: (end_station(p[0]), end_station(p[-1])) for sid, p in shapes.items()}
    by_ends = collections.defaultdict(list)
    for sid, se in shape_ends.items(): by_ends[(sid.split(".")[0], se)].append(sid)
    for t in trips:
        sid = t.get("shape_id") or t["trip_id"].rsplit("_", 1)[-1]
        if sid in shapes or t["trip_id"] not in ends: continue
        e = ends[t["trip_id"]]; key = (parent(e[1]), parent(e[3]))
        rt = t["route_id"]; pre = sid.split(".")[0] if "." in sid else rt
        cand = by_ends.get((pre, key)) or by_ends.get((rt, key)) or []
        for c in cand: use[c][rt] += 1 / len(cand)
    lines = []
    for sid, pts in shapes.items():
        if sum(use[sid].values()) < 3: continue
        routes = {r: n for r, n in use[sid].items() if r in TRUNK}
        if not routes: continue
        group = "A" if set(routes) <= A_DIVISION else ("SIR" if set(routes) & {"SI", "SIR"} else "B")
        lines.append((pts, routes, group, sum(routes.values())))
    feats = stripes(corridors(lines, minshare=0.25), bbox, lambda r: TRUNK[r], lambda t: TRUNK_COLOR[t],
                    order=TRUNK_ORDER, show=lambda r: SHOW.get(r, r), mode="subway")
    cal = rd("calendar.txt") + rd("feed_info.txt")
    starts = [r.get("start_date") or r.get("feed_start_date") for r in cal if r.get("start_date") or r.get("feed_start_date")]
    ends = [r.get("end_date") or r.get("feed_end_date") for r in cal if r.get("end_date") or r.get("feed_end_date")]
    fmt = lambda d: f"{d[:4]}-{d[4:6]}-{d[6:8]}" if d and len(d) == 8 else d
    return feats, {"start": fmt(min(starts)) if starts else None, "end": fmt(max(ends)) if ends else None}

def _m(p): return (p[0] * KX, p[1] * KY)

def _heading(c, at):
    a = _m(c[0] if at == 0 else c[-1]); b = a
    for k in (range(1, len(c)) if at == 0 else range(len(c) - 2, -1, -1)):
        b = _m(c[k])
        if math.dist(a, b) >= 15: break
    d = math.dist(a, b) or 1
    return ((b[0] - a[0]) / d, (b[1] - a[1]) / d)

def _length(c): return sum(math.dist(_m(a), _m(b)) for a, b in zip(c, c[1:]))

def stripes(pieces, bbox, trunk_of, color_of, order, show, mode, short=90.0):
    P = []
    for coords, rs, a, b in pieces:
        P.append([coords, set(rs), frozenset(trunk_of(r) for r in rs), a, b, _length(coords)])
    at = collections.defaultdict(list)
    for i, p in enumerate(P):
        at[p[3]].append((i, 0)); at[p[4]].append((i, -1))
    def straight(i, e, j, e2):
        h, h2 = _heading(P[i][0], e), _heading(P[j][0], e2)
        return h[0] * h2[0] + h[1] * h2[1]
    node_of = lambda i, e: P[i][3] if e == 0 else P[i][4]
    for i in sorted(range(len(P)), key=lambda i: P[i][5]):
        if P[i][5] >= short: break
        best, bl = None, P[i][5]
        for e in (0, -1):
            for j, e2 in at[node_of(i, e)]:
                if j != i and P[j][5] > bl and straight(i, e, j, e2) < -0.9: best, bl = j, P[j][5]
        if best is not None: P[i][2] = P[best][2]
    link = {}
    for node, inc in at.items():
        cand = []
        for x in range(len(inc)):
            for y in range(x + 1, len(inc)):
                (i, e), (j, e2) = inc[x], inc[y]
                if i != j and P[i][2] == P[j][2]:
                    d = straight(i, e, j, e2)
                    if d < -0.8: cand.append((d, (i, e), (j, e2)))
        used = set()
        for d, u, v in sorted(cand):
            if u in used or v in used: continue
            used |= {u, v}; link[u] = v; link[v] = u
    runs, seen = [], set()
    for i in sorted(range(len(P)), key=lambda i: -P[i][5]):
        if i in seen: continue
        seen.add(i)
        seq = [(i, False)]
        for side in (-1, 0):
            while True:
                pi, rev = seq[-1] if side == -1 else seq[0]
                end = (-1 if not rev else 0) if side == -1 else (0 if not rev else -1)
                nx = link.get((pi, end))
                if not nx or nx[0] in seen: break
                j, e2 = nx; seen.add(j)
                if side == -1: seq.append((j, e2 == -1))
                else: seq.insert(0, (j, e2 == 0))
        coords, routes = [], set()
        for pi, rev in seq:
            c = P[pi][0][::-1] if rev else P[pi][0]
            coords += c if not coords else c[1:]; routes |= P[pi][1]
        first, last = seq[0], seq[-1]
        a = P[first[0]][4] if first[1] else P[first[0]][3]
        b = P[last[0]][3] if last[1] else P[last[0]][4]
        runs.append({"c": coords, "r": routes, "t": P[i][2], "a": a, "b": b, "L": _length(coords), "flip": None, "seq": seq})
    ends = collections.defaultdict(list)
    for k, r in enumerate(runs): ends[r["a"]].append((k, 0)); ends[r["b"]].append((k, -1))
    def dirat(k, e):
        return _heading(runs[k]["c"], e)
    for k0 in sorted(range(len(runs)), key=lambda k: -runs[k]["L"]):
        if runs[k0]["flip"] is not None: continue
        c = runs[k0]["c"]; dx, dy = _m(c[-1])[0] - _m(c[0])[0], _m(c[-1])[1] - _m(c[0])[1]
        runs[k0]["flip"] = (dx + 0.3 * dy) < 0
        q = [k0]
        while q:
            k = q.pop()
            for e in (0, -1):
                node = runs[k]["a"] if e == 0 else runs[k]["b"]
                h = dirat(k, e)
                out_end = (e == -1) != runs[k]["flip"]
                for j, e2 in ends[node]:
                    if j == k or runs[j]["flip"] is not None: continue
                    h2 = dirat(j, e2)
                    if h[0] * h2[0] + h[1] * h2[1] > -0.7: continue
                    runs[j]["flip"] = (e2 == -1) if out_end else (e2 == 0)
                    q.append(j)
    for r in runs:
        if r["flip"]:
            r["c"] = r["c"][::-1]; r["a"], r["b"] = r["b"], r["a"]
            r["seq"] = [(pi, not rev) for pi, rev in r["seq"][::-1]]
    ends = collections.defaultdict(list)
    for k, r in enumerate(runs): ends[r["a"]].append((k, 0)); ends[r["b"]].append((k, -1))
    slot = {}
    for k in sorted(range(len(runs)), key=lambda k: -runs[k]["L"]):
        r = runs[k]; T = list(r["t"])
        if len(T) == 1: slot[k] = T; continue
        score = collections.Counter(); ref = {}
        for e in (0, -1):
            node = r["a"] if e == 0 else r["b"]
            h = _heading(r["c"], e)
            fwd = (-h[0], -h[1]) if e == -1 else h
            for j, e2 in ends[node]:
                if j == k: continue
                h2 = _heading(runs[j]["c"], e2)
                cross = fwd[0] * h2[1] - fwd[1] * h2[0]
                dot = fwd[0] * h2[0] + fwd[1] * h2[1]
                shared = [t for t in T if t in runs[j]["t"]]
                if (dot > 0.8) if e == -1 else (dot < -0.8):
                    if j in slot:
                        same_dir = (e == -1 and e2 == 0) or (e == 0 and e2 == -1)
                        o = slot[j] if same_dir else slot[j][::-1]
                        for t in shared: ref.setdefault(t, o.index(t) / max(1, len(o) - 1))
                    continue
                for t in shared: score[t] += -1 if cross > 0 else 1
        slot[k] = sorted(T, key=lambda t: (score[t], ref.get(t, 0.5), order.index(t) if t in order else 99))
    feats = []
    sort = lambda xs: sorted(xs, key=lambda x: ROUTE_ORDER.index(x) if x in ROUTE_ORDER else 99)
    for k, r in enumerate(runs):
        if not _in_box(r["c"], bbox): continue
        o = slot[k]
        for pi, rev in r["seq"]:
            c = P[pi][0][::-1] if rev else P[pi][0]
            for i, t in enumerate(o):
                rs = {show(x) for x in P[pi][1] if trunk_of(x) == t} or {show(x) for x in r["r"] if trunk_of(x) == t}
                feats.append({"type": "Feature", "properties": {"m": mode, "t": t, "c": color_of(t), "k": i, "n": len(o), "r": " ".join(sort(rs))},
                              "geometry": {"type": "LineString", "coordinates": c}})
    return feats

def _in_box(coords, bbox):
    w, s, e, n = bbox
    return any(w <= x <= e and s <= y <= n for x, y in coords)

PATH_ORDER = ["NWK–WTC", "HOB–WTC", "JSQ–33", "HOB–33"]

def path_lines(osm, bbox):
    lines, colors = [], {}
    for el in osm.get("elements", []):
        t = el.get("tags", {})
        if el.get("type") != "relation" or not el.get("members"): continue
        if t.get("route") != "subway" or "PATH" not in f"{t.get('network', '')} {t.get('operator', '')}": continue
        base = (t.get("ref") or "PATH").replace("-", "–").split(" via")[0]
        if t.get("colour"): colors.setdefault(base, t["colour"])
        for run in _member_runs(el): lines.append((run, {base}, "path", 1))
    if not lines: return []
    return stripes(corridors(lines, T=14.0, step=6.0), bbox, lambda r: r, lambda r: colors.get(r, "#0079C1"),
                   order=PATH_ORDER, show=lambda r: r, mode="path")

def _member_runs(el):
    for m in el["members"]:
        if m.get("type") != "way" or re.search(r"platform|stop", m.get("role") or "") or not m.get("geometry"): continue
        run = []
        for p in m["geometry"] + [None]:
            if p: run.append((p["lon"], p["lat"])); continue
            if len(run) > 1: yield run
            run = []

def _rail_feature(coords, name):
    P = _simplify([_m(p) for p in coords], 2.0)
    return {"type": "Feature", "properties": {"m": "rail", "t": "RAIL", "c": RAIL_COLOR, "k": 0, "n": 1, "r": name},
            "geometry": {"type": "LineString", "coordinates": [[round(x / KX, 6), round(y / KY, 6)] for x, y in P]}}

def rail_lines_mta(gj, bbox):
    feats = []
    for f in gj.get("features", []):
        pr = {k.lower(): v for k, v in (f.get("properties") or {}).items()}
        g = f.get("geometry") or {}
        name = (pr.get("route_name") or pr.get("routename") or "").strip()
        lirr = bool((pr.get("branch_code") or pr.get("branchcode") or "").strip()) or re.search(r"branch|LIRR|Long Island", name, re.I)
        label = ("LIRR " if lirr else "Metro-North ") + (name or "line")
        parts = g.get("coordinates") or []
        if g.get("type") == "LineString": parts = [parts]
        for part in parts:
            c = [(p[0], p[1]) for p in part if p]
            if len(c) > 1 and _in_box(c, bbox): feats.append(_rail_feature(c, label))
    return feats

def rail_lines_osm(osm, bbox):
    feats = []
    for el in osm.get("elements", []):
        t = el.get("tags", {})
        if el.get("type") != "relation" or not el.get("members") or t.get("route") != "train": continue
        net = f"{t.get('network', '')} {t.get('operator', '')}"
        if not re.search(r"LIRR|Long Island Rail|Metro-North|Metro North|MNR", net, re.I): continue
        label = ("Metro-North " if re.search(r"Metro.?North|MNR", net, re.I) else "LIRR ") + (t.get("name") or "")
        for run in _member_runs(el):
            if _in_box(run, bbox): feats.append(_rail_feature(run, label.strip()))
    return feats

def platforms(osm, near=None, reach=350.0):
    grid = collections.defaultdict(list)
    for x, y in near or []: grid[(int(x * KX // reach), int(y * KY // reach))].append((x * KX, y * KY))
    def close(c):
        if not near: return True
        x = sum(p[0] for p in c) / len(c) * KX; y = sum(p[1] for p in c) / len(c) * KY
        gx, gy = int(x // reach), int(y // reach)
        return any(math.hypot(px - x, py - y) <= reach for u in (-1, 0, 1) for v in (-1, 0, 1) for px, py in grid.get((gx + u, gy + v), ()))
    out = []
    for el in osm.get("elements", []):
        t = el.get("tags", {})
        if t.get("railway") != "platform": continue
        if t.get("access") in ("private", "no") or t.get("public_transport") == "no": continue
        net = f"{t.get('network', '')} {t.get('operator', '')}"
        transit = t.get("subway") == "yes" or re.search(r"NYC Subway|New York City Transit|Staten Island|PATH|Port Authority|" + LR_NET, net) or t.get("gtfs:stop_id")
        if not transit: continue
        geoms = [el.get("geometry")] if el.get("type") == "way" else \
                [m.get("geometry") for m in el.get("members", []) if m.get("role") == "outer" and m.get("geometry")]
        for g in geoms:
            if not g or len(g) < 2 or not all(g): continue
            c = [[round(p["lon"], 6), round(p["lat"], 6)] for p in g]
            if not close(c): continue
            closed = len(c) > 3 and c[0] == c[-1]
            out.append({"type": "Feature", "properties": {"name": t.get("name", "")},
                        "geometry": {"type": "Polygon", "coordinates": [c]} if closed else {"type": "LineString", "coordinates": c}})
    return {"type": "FeatureCollection", "features": out}

PATH_NAMES = [("Newark Penn Station", -74.1644, 40.7347), ("Harrison", -74.1557, 40.7394), ("Journal Square", -74.0628, 40.7331),
              ("Grove Street", -74.0431, 40.7194), ("Exchange Place", -74.0327, 40.7163), ("World Trade Center", -74.0110, 40.7118),
              ("Newport", -74.0340, 40.7268), ("Hoboken", -74.0293, 40.7353), ("Christopher Street", -74.0071, 40.7329),
              ("9th Street", -73.9990, 40.7342), ("14th Street", -73.9968, 40.7374), ("23rd Street", -73.9929, 40.7429),
              ("33rd Street", -73.9884, 40.7488)]

LR_NET = r"Hudson.Bergen|Newark Light Rail|River LINE"
LR_COLOR = {"HBLR": "#1C8FC7", "NLR": "#8C4FA3"}
LR_NAME = {"HBLR": "Hudson-Bergen Light Rail", "NLR": "Newark Light Rail"}
LR_SHORT = lambda net: "HBLR" if re.search(r"Hudson.Bergen", net) else "NLR" if re.search(r"Newark", net) else None

def lightrail_lines(osm, bbox):
    lines, colors = [], {}
    for el in osm.get("elements", []):
        t = el.get("tags", {})
        if el.get("type") != "relation" or not el.get("members") or t.get("route") not in ("light_rail", "tram"): continue
        net = LR_SHORT(f"{t.get('network', '')} {t.get('name', '')}")
        if not net: continue
        for run in _member_runs(el): lines.append((run, {net}, "lr", 1))
    if not lines: return []
    return stripes(corridors(lines, T=12.0, step=6.0), bbox, lambda r: r, lambda r: LR_COLOR.get(r, "#1C8FC7"),
                   order=list(LR_COLOR), show=lambda r: r, mode="lightrail")

def lightrail_stations(osm):
    out = []
    for el in osm.get("elements", []):
        t = el.get("tags", {})
        if el.get("type") == "node" and t.get("railway") in ("station", "halt", "tram_stop"):
            net = LR_SHORT(f"{t.get('network', '')} {t.get('operator', '')}")
            if net: out.append({"net": net, "name": t.get("name") or f"{LR_NAME[net]} station", "lng": round(el["lon"], 6), "lat": round(el["lat"], 6), "routes": [net]})
    if out: return out
    pts = []
    for el in osm.get("elements", []):
        t = el.get("tags", {})
        if t.get("railway") != "platform" or el.get("type") != "way" or not el.get("geometry"): continue
        net = LR_SHORT(t.get("network", ""))
        if not net: continue
        g = [p for p in el["geometry"] if p]
        pts.append((sum(p["lon"] for p in g) / len(g), sum(p["lat"] for p in g) / len(g), net, t.get("name")))
    for x, y, net, name in pts:
        hit = next((c for c in out if c["net"] == net and math.hypot((c["lng"] - x) * KX, (c["lat"] - y) * KY) < 160), None)
        if hit:
            if name and hit["name"].endswith("station"): hit["name"] = name
            continue
        out.append({"net": net, "name": name or f"{LR_NAME[net]} station", "lng": round(x, 6), "lat": round(y, 6), "routes": [net]})
    return out

def path_stations(osm):
    found = []
    for el in osm.get("elements", []):
        t = el.get("tags", {})
        if el.get("type") == "node" and t.get("railway") == "station" and "PATH" in f"{t.get('network', '')} {t.get('operator', '')}":
            found.append({"name": re.sub(r"\s*\(PATH\)", "", t.get("name", "PATH station")), "lng": el["lon"], "lat": el["lat"], "routes": set()})
    stops = []
    for el in osm.get("elements", []):
        t = el.get("tags", {})
        if el.get("type") == "relation" and t.get("route") == "subway" and "PATH" in f"{t.get('network', '')} {t.get('operator', '')}":
            ref = (t.get("ref") or "PATH").replace("-", "–").split(" via")[0]
            for m in el.get("members", []):
                if m.get("type") == "node" and re.match(r"stop", m.get("role") or "") and m.get("lat") is not None:
                    stops.append((m["lon"], m["lat"], ref))
    if not found:
        for x, y, ref in stops:
            hit = next((f for f in found if math.hypot((f["lng"] - x) * KX, (f["lat"] - y) * KY) < 180), None)
            if not hit: found.append({"name": None, "lng": x, "lat": y, "routes": set(), "n": 0})
        for f in found:
            nm = min(PATH_NAMES, key=lambda p: math.hypot((p[1] - f["lng"]) * KX, (p[2] - f["lat"]) * KY))
            f["name"] = nm[0] if math.hypot((nm[1] - f["lng"]) * KX, (nm[2] - f["lat"]) * KY) < 450 else "PATH station"
    for x, y, ref in stops:
        f = min(found, key=lambda f: math.hypot((f["lng"] - x) * KX, (f["lat"] - y) * KY), default=None)
        if f and math.hypot((f["lng"] - x) * KX, (f["lat"] - y) * KY) < 300: f["routes"].add(ref)
    out, seen = [], set()
    for f in found:
        if f["name"] in seen and f["name"] != "PATH station": continue
        seen.add(f["name"])
        out.append({"net": "PATH", "name": f["name"], "lng": round(f["lng"], 6), "lat": round(f["lat"], 6),
                    "routes": sorted(f["routes"], key=lambda r: PATH_ORDER.index(r) if r in PATH_ORDER else 9)})
    return out

def rail_stations(feeds, bbox):
    """LIRR and Metro-North stations inside bbox from the MTA's GTFS feeds, with the branches that stop there."""
    w, s, e, n = bbox
    out = []
    for net, gz in feeds.items():
        z = zipfile.ZipFile(io.BytesIO(gz))
        rd = lambda f: list(csv.DictReader(io.StringIO(z.read(f).decode("utf-8-sig"))))
        routes = {r["route_id"]: (r.get("route_long_name") or r.get("route_short_name") or "").strip() for r in rd("routes.txt")}
        rcol = {r["route_id"]: "#" + (r.get("route_color") or "4F5B66").strip() for r in rd("routes.txt")}
        trip_route = {t["trip_id"]: t["route_id"] for t in rd("trips.txt")}
        served = collections.defaultdict(set)
        for st in rd("stop_times.txt"):
            rid = trip_route.get(st["trip_id"])
            if rid: served[st["stop_id"]].add(rid)
        for stp in rd("stops.txt"):
            if (stp.get("location_type") or "0") not in ("0", ""): continue
            la, lo = float(stp["stop_lat"]), float(stp["stop_lon"])
            if not (s <= la <= n and w <= lo <= e): continue
            rids = sorted((r for r in served.get(stp["stop_id"], ()) if not re.search(r"Terminal Zone", routes.get(r, ""))), key=lambda r: routes.get(r, r))
            if not rids or re.search(r"\b(Yard|Facility)\b", stp["stop_name"]): continue
            out.append({"net": net, "name": stp["stop_name"].strip(), "lng": round(lo, 6), "lat": round(la, 6), "code": stp.get("stop_code") or stp["stop_id"],
                        "routes": [routes[r] for r in rids], "colors": {routes[r]: rcol[r] for r in rids}})
    return out

def rail_entrances(osm, stations, reach=300.0):
    """OpenStreetMap train-station entrances, each joined to the nearest LIRR / Metro-North station within reach (m)."""
    out = []
    for el in (osm or {}).get("elements", []):
        t = el.get("tags", {})
        if el.get("type") != "node" or t.get("railway") != "train_station_entrance": continue
        best = min(range(len(stations)), key=lambda k: math.hypot((stations[k]["lng"] - el["lon"]) * KX, (stations[k]["lat"] - el["lat"]) * KY), default=None)
        if best is None or math.hypot((stations[best]["lng"] - el["lon"]) * KX, (stations[best]["lat"] - el["lat"]) * KY) > reach: continue
        out.append({"station": best, "lng": round(el["lon"], 6), "lat": round(el["lat"], 6), "type": "Elevator" if t.get("elevator") == "yes" or t.get("entrance") == "elevator" else "Entrance"})
    return out

def near_lots(stations, parquet, reach):
    """Keep stations within reach (m) of a lot centroid in the release's lot file (work/<release>_lots.parquet)."""
    import geopandas as gpd
    pts = gpd.read_parquet(parquet, columns=["geometry"]).geometry.representative_point()
    cell = 0.01; grid = set()
    for x, y in zip(pts.x.values, pts.y.values): grid.add((int(x // cell), int(y // cell)))
    xs = collections.defaultdict(list)
    for x, y in zip(pts.x.values, pts.y.values): xs[(int(x // cell), int(y // cell))].append((x, y))
    def ok(st):
        cx, cy = int(st["lng"] // cell), int(st["lat"] // cell)
        return any(math.hypot((x - st["lng"]) * KX, (y - st["lat"]) * KY) <= reach
                   for a in (-1, 0, 1) for b in (-1, 0, 1) for x, y in xs.get((cx + a, cy + b), ()))
    return [st for st in stations if ok(st)]

def add_rail(snapshot, date, release, bbox, near=None, reach=804.7):
    """Add LIRR and Metro-North stations (MTA GTFS) and, when OpenStreetMap answers, their entrances to an existing snapshot."""
    old = json.load(open(snapshot, encoding="utf-8"))
    feeds = {}
    for net, url in RAIL_GTFS.items():
        print(f"  downloading {url} …"); feeds[net] = get(url)
    rs = rail_stations(feeds, bbox)
    if near: n0 = len(rs); rs = near_lots(rs, near, reach); print(f"  {len(rs)} of {n0} stations are within {reach:.0f} m of a lot in {os.path.basename(near)}")
    w, s, e, n = bbox
    osm = overpass(f"[out:json][timeout:120];node[\"railway\"=\"train_station_entrance\"]({s},{w},{n},{e});out;", need=False)
    ents = rail_entrances(osm, rs) if osm else []
    if not ents: print("  No entrances from OpenStreetMap (Overpass busy or none mapped); LIRR / Metro-North walksheds will use the station point until you rerun this")
    keep = [x for x in old.get("other_stations", []) if x.get("net") not in ("LIRR", "MNR")]
    base = len(keep)
    old["other_stations"] = keep + rs
    old["other_entrances"] = [{**x, "station": base + x["station"]} for x in ents]
    old["date"], old["built"] = date, time.strftime("%Y-%m-%d")
    old["sources"] = [x for x in old.get("sources", []) if "LIRR" not in x] + ["MTA LIRR and Metro-North GTFS (stations)"] + (["© OpenStreetMap contributors (rail entrances)"] if ents else [])
    path = save_snapshot(old, date, release)
    c = collections.Counter(x["net"] for x in rs)
    print(f"{c['LIRR']} LIRR and {c['MNR']} Metro-North stations, {len(ents)} entrances -> data/{os.path.basename(path)}")

def save_snapshot(out, date, release):
    name = f"transit_{date}.json"
    path = os.path.join(DATA, name)
    json.dump(out, open(path, "w"), separators=(",", ":"))
    ip = os.path.join(DATA, "transit_index.json")
    idx = json.load(open(ip)) if os.path.exists(ip) else {"snapshots": []}
    idx["snapshots"] = [s for s in idx["snapshots"] if s["file"] != name] + [{
        "file": name, "date": date, "built": out["built"], "gtfs": out.get("gtfs"),
        "stations": out.get("stations_date"), "bytes": os.path.getsize(path)}]
    idx["snapshots"].sort(key=lambda s: s["date"])
    json.dump(idx, open(ip, "w"), indent=1)
    if release:
        rp = os.path.join(DATA, "releases.json")
        rel = json.load(open(rp))
        hit = [r for r in rel if r["id"] == release]
        if hit: hit[0]["transit"] = name; json.dump(rel, open(rp, "w"), indent=1); print(f"  release {release} now uses {name}")
        else: print(f"  (no release {release} in data/releases.json; the snapshot is saved but not tied to a release)")
    return path

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--study", action="store_true", help="only the area around the newest release instead of all of NYC")
    ap.add_argument("--pad", type=float, default=0.03, help="degrees added around the study area (0.03 ≈ 1.5 mi)")
    ap.add_argument("--release", help="tie this snapshot to a PLUTO release id in data/releases.json, e.g. 25v4")
    ap.add_argument("--date", help="date the snapshot shows (YYYY-MM-DD); default today")
    ap.add_argument("--reuse", help="take stations, entrances and platforms from this existing transit JSON (no downloads)")
    ap.add_argument("--no-rail", action="store_true", help="leave out PATH, LIRR and Metro-North")
    ap.add_argument("--stations"); ap.add_argument("--entrances"); ap.add_argument("--osm"); ap.add_argument("--gtfs")
    ap.add_argument("--branches", help="MTA Rail Branches GeoJSON you downloaded yourself (LIRR + Metro-North)")
    ap.add_argument("--add-rail", metavar="SNAPSHOT", help="copy this snapshot and add LIRR / Metro-North stations and entrances (dated --date)")
    ap.add_argument("--near", metavar="PARQUET", help="with --add-rail: keep stations within ½ mile of a lot in this lot file (e.g. work/26v2_lots.parquet)")
    a = ap.parse_args()
    w, s, e, n = study_bbox(a.pad) if a.study else NYC
    bbox = [w, s, e, n]
    inside = lambda la, lo: la is not None and s <= la <= n and w <= lo <= e
    today = time.strftime("%Y-%m-%d")
    date = a.date or today
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date): sys.exit("--date needs the form YYYY-MM-DD")
    if a.add_rail: return add_rail(a.add_rail, date, a.release, bbox, a.near)

    old = json.load(open(a.reuse)) if a.reuse else None
    if old:
        print(f"reusing stations, entrances and platforms from {a.reuse}")
        keep_st, keep_en = old["stations"], old["entrances"]
        plat = None
        stations_date = old.get("stations_date") or old.get("built")
        osm = old.get("osm")
    else:
        print("stations…")
        txt = open(a.stations, encoding="utf-8-sig").read() if a.stations else get(STATIONS).decode("utf-8-sig")
        keep_st = [r for r in (norm(x) for x in csv.DictReader(io.StringIO(txt)))
                   if inside(*latlon(r, ["gtfslatitude", "latitude"], ["gtfslongitude", "longitude"]))]
        ids = {r.get("complexid") for r in keep_st}
        print("entrances…")
        txt = open(a.entrances, encoding="utf-8-sig").read() if a.entrances else get(ENTRANCES).decode("utf-8-sig")
        keep_en = [r for r in (norm(x) for x in csv.DictReader(io.StringIO(txt))) if r.get("complexid") in ids]
        for r in keep_en + keep_st: r.pop("entrancegeoreference", None); r.pop("georeference", None)
        stations_date = today
        print("OpenStreetMap platforms" + ("" if a.no_rail else ", PATH, LIRR and Metro-North") + "…")
        q = (f"[out:json][timeout:180];"
             f"(way[\"railway\"=\"platform\"]({s},{w},{n},{e});relation[\"railway\"=\"platform\"]({s},{w},{n},{e}););out geom;")
        if not a.no_rail:
            q += (f"node[\"railway\"~\"station|halt|tram_stop\"][\"network\"~\"PATH|{LR_NET}\"]({s},{w},{n},{e});out;"
                  f"relation[\"route\"~\"light_rail|tram\"][\"network\"~\"{LR_NET}\"]({s},{w},{n},{e});out geom({s},{w},{n},{e});"
                  f"relation[\"route\"~\"light_rail|tram\"][!\"network\"][\"name\"~\"{LR_NET}\"]({s},{w},{n},{e});out geom({s},{w},{n},{e});"
                  f"relation[\"route\"=\"subway\"][\"network\"~\"PATH\"]({s},{w},{n},{e});out geom({s},{w},{n},{e});"
                  f"relation[\"route\"=\"train\"][\"network\"~\"LIRR|Long Island|Metro-North|MNR\"]({s},{w},{n},{e});out geom({s},{w},{n},{e});")
        osm = json.load(open(a.osm)) if a.osm else overpass(q, need=True)
        plat = None

    print("subway route lines (MTA GTFS)…")
    if a.gtfs and os.path.exists(a.gtfs): gz = open(a.gtfs, "rb").read()
    else:
        gz = None
        for url in ([a.gtfs] if a.gtfs else GTFS):
            try: print(f"  downloading {url} …"); gz = get(url); break
            except Exception as err: print(f"  failed ({err.__class__.__name__})")
        if gz is None: sys.exit("Couldn't download the MTA GTFS feed. Download gtfs_subway.zip yourself and pass --gtfs gtfs_subway.zip")
    lines, feed = subway_lines(gz, bbox)
    other_st = (path_stations(osm) + lightrail_stations(osm)) if osm and not a.no_rail else [x for x in (old or {}).get("other_stations", []) if not a.no_rail and x.get("net") not in ("LIRR", "MNR")]
    st_pts = [latlon(norm(r), ["gtfslatitude", "latitude"], ["gtfslongitude", "longitude"])[::-1] for r in keep_st]
    st_pts = [p for p in st_pts if p[0] is not None] + [(x["lng"], x["lat"]) for x in other_st]
    if osm: plat = platforms(osm, st_pts)
    else:
        oldp = (old or {}).get("platforms") or {"features": []}
        plat = {"type": "FeatureCollection", "features": oldp["features"]}
    rail = []
    if not a.no_rail:
        old_other = [f for f in (old or {}).get("lines", {}).get("features", []) if f["properties"].get("m") != "subway"]
        print("PATH (OpenStreetMap)…")
        path_f = path_lines(osm, bbox) if osm else [f for f in old_other if f["properties"]["m"] == "path"]
        print("LIRR and Metro-North (MTA Rail Branches)…")
        gj = None
        if a.branches: gj = json.load(open(a.branches))
        else:
            for url in RAIL_BRANCHES:
                try:
                    print(f"  downloading {url.split('?')[0]} …"); x = json.loads(get(url))
                    if x.get("features"): gj = x; break
                    print("  no features in that response")
                except Exception as err: print(f"  failed ({err.__class__.__name__})")
        rail_f = rail_lines_mta(gj, bbox) if gj else []
        if not rail_f and osm: rail_f = rail_lines_osm(osm, bbox)
        if not rail_f: rail_f = [f for f in old_other if f["properties"]["m"] == "rail"]
        if not rail_f: print("  WARNING: no LIRR or Metro-North lines found. Download MTA Rail Branches as GeoJSON from "
                             "https://data.ny.gov/d/2vcb-zrh4 and rerun with --branches that_file.geojson")
        lr_f = lightrail_lines(osm, bbox) if osm else [f for f in old_other if f["properties"]["m"] == "lightrail"]
        if not lr_f: print("  (no New Jersey light rail lines in this OpenStreetMap data; a fresh download adds them)")
        rail = path_f + lr_f + rail_f
    out = {"format": 2, "date": date, "built": today, "stations_date": stations_date, "gtfs": feed, "bbox": bbox,
           "stations": keep_st, "entrances": keep_en, "platforms": plat, "other_stations": other_st,
           "lines": {"type": "FeatureCollection", "features": lines + rail},
           "sources": ["MTA Subway Stations, data.ny.gov", "MTA Subway Entrances and Exits: 2024, data.ny.gov",
                       f"MTA subway GTFS{' (' + feed['start'] + ' to ' + feed['end'] + ')' if feed.get('start') else ''}",
                       "MTA Rail Branches, data.ny.gov", "© OpenStreetMap contributors (ODbL)"]}
    path = save_snapshot(out, date, a.release)
    mode = collections.Counter(f["properties"]["m"] for f in out["lines"]["features"])
    print(f"{len(keep_st)} stations, {len(keep_en)} entrances, {mode['subway']} subway stripes, "
          f"{mode['path']} PATH stripes, {mode['lightrail']} light rail lines ({len(other_st)} PATH and light rail stations), {mode['rail']} LIRR/Metro-North lines, {len(plat['features'])} platforms "
          f"-> data/{os.path.basename(path)} ({os.path.getsize(path)/1e6:.1f} MB), listed in data/transit_index.json")

if __name__ == "__main__":
    try: main()
    except urllib.error.URLError as err:
        sys.exit(f"Download failed ({err}). Check your connection, or pass files with --stations/--entrances/--osm/--gtfs.")
