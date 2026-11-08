#!/usr/bin/env python3
"""city_transit.py — build a transit file (metro stations and entrances, rail and tram lines) for a prototype city from OpenStreetMap"""
import argparse, json, math, os, re, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter"]
CITIES = {"phl26": ("Philadelphia", [-75.2803, 39.8670, -74.9557, 40.1379]),
          "vie26": ("Vienna", [16.1800, 48.1100, 16.5800, 48.3300]),
          "tyo26": ("Tokyo", [139.5600, 35.5200, 139.9200, 35.8200]),
          "sfo26": ("San Francisco", [-122.5200, 37.7000, -122.3500, 37.8350]),
          "ams26": ("Amsterdam", [4.7200, 52.2700, 5.0800, 52.4350]),
          "mad26": ("Madrid", [-3.8900, 40.3100, -3.5200, 40.6450]),
          "bcn26": ("Barcelona", [2.0500, 41.3100, 2.2300, 41.4700]),
          "vlc26": ("Valencia", [-0.4400, 39.4000, -0.3000, 39.5200]),
          "rtm26": ("Rotterdam", [4.3500, 51.8500, 4.6000, 51.9900]),
          "hag26": ("The Hague", [4.1800, 52.0100, 4.4100, 52.1300])}
MODE = {"subway": "subway", "light_rail": "lightrail", "tram": "lightrail", "train": "path"}
DEFAULT = {"subway": "#1F5FA6", "lightrail": "#2E9E5B", "path": "#6B5B95"}

def overpass(q):
    for k in range(6):
        url = OVERPASS[k % len(OVERPASS)]
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(), headers={"User-Agent": "LotProfiler/1.8 (city_transit.py)"})
            with urllib.request.urlopen(req, timeout=900) as r: return json.loads(r.read())
        except Exception as e:
            print(f"  {url}: {e}; retrying", flush=True); time.sleep(10 + 10 * k)
    raise SystemExit("Overpass did not answer")

def dist(a, b):
    return math.hypot((a[0] - b[0]) * 111320 * math.cos(math.radians(a[1])), (a[1] - b[1]) * 110574)

def name_of(t):
    return t.get("name:en") or t.get("name") or ""

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("release", choices=sorted(CITIES))
    ap.add_argument("--date", default=time.strftime("%Y-%m-%d"))
    a = ap.parse_args()
    city, (w, s, e, n) = CITIES[a.release]
    bb = f"{s},{w},{n},{e}"
    print(f"{city}: route relations …", flush=True)
    rels = overpass(f'[out:json][timeout:900];rel["type"="route"]["route"~"^(subway|light_rail|tram|train)$"]({bb});out geom({bb});')["elements"]
    print(f"  {len(rels)} routes; stations and entrances …", flush=True)
    pts = overpass(f'[out:json][timeout:600];(node["railway"~"^(station|halt)$"]({bb});node["railway"="subway_entrance"]({bb}););out;')["elements"]
    feats, seen, stops, colors = [], set(), [], {}
    simple = {(t.get("ref") or "").strip() for t in (x.get("tags", {}) for x in rels) if t.get("route") == "subway" and t.get("ref") and not re.search(r"[;,\-]", t["ref"])}
    def refs(t):
        raw = (t.get("ref") or name_of(t) or "?").strip()
        if t.get("route") != "subway" or raw in simple: return [raw]
        keep = [x for x in re.split(r"[;,\-]", raw) if x.strip() in simple]
        return keep or [raw]
    for r in rels:
        t = r.get("tags", {})
        if t.get("service") == "high_speed": continue
        m = MODE[t["route"]]; rl = refs(t); ref = rl[0]
        col = t.get("colour") or t.get("color") or DEFAULT[m]
        if not col.startswith("#"): col = DEFAULT[m]
        if m == "subway": colors.setdefault(ref, col)
        for mem in r.get("members", []):
            role = mem.get("role", "")
            if mem["type"] == "way" and role in ("", "forward", "backward", "main") and mem.get("geometry"):
                key = (mem["ref"], ref)
                if key in seen: continue
                seen.add(key)
                c = [[round(p["lon"], 6), round(p["lat"], 6)] for p in mem["geometry"] if p]
                if len(c) > 1: feats.append({"type": "Feature", "properties": {"m": m, "t": ref, "c": col, "k": 0, "n": 1, "r": ref}, "geometry": {"type": "LineString", "coordinates": c}})
            elif mem["type"] == "node" and role.startswith("stop") and "lat" in mem:
                for x in rl: stops.append((m, x, (mem["lon"], mem["lat"])))
    sta = [p for p in pts if p.get("tags", {}).get("railway") in ("station", "halt")]
    ent = [p for p in pts if p.get("tags", {}).get("railway") == "subway_entrance"]
    is_metro = lambda t: t.get("station") == "subway" or t.get("subway") == "yes"
    routes = {p["id"]: set() for p in sta}
    for m, ref, xy in stops:
        cand = [p for p in sta if (is_metro(p["tags"]) == (m == "subway")) and abs(p["lon"] - xy[0]) < 0.006 and abs(p["lat"] - xy[1]) < 0.005]
        if cand:
            b = min(cand, key=lambda p: dist((p["lon"], p["lat"]), xy))
            if dist((b["lon"], b["lat"]), xy) < 400: routes[b["id"]].add(ref)
    metro, other = [], []
    for p in sta:
        t = p["tags"]; nm = name_of(t)
        if not nm: continue
        if is_metro(t):
            metro.append({"complexid": str(p["id"]), "stopname": nm, "daytimeroutes": " ".join(sorted(routes[p["id"]])),
                          "gtfslatitude": p["lat"], "gtfslongitude": p["lon"], "structure": ""})
        elif routes[p["id"]] or t.get("train") == "yes" or t.get("station") in ("train", "light_rail"):
            other.append({"net": t.get("network") or t.get("operator") or city, "name": nm, "lng": p["lon"], "lat": p["lat"], "routes": sorted(routes[p["id"]])})
    entrances = []
    for p in ent:
        near = [(dist((m_["gtfslongitude"], m_["gtfslatitude"]), (p["lon"], p["lat"])), m_) for m_ in metro if abs(m_["gtfslongitude"] - p["lon"]) < 0.008 and abs(m_["gtfslatitude"] - p["lat"]) < 0.006]
        if not near: continue
        d, m_ = min(near, key=lambda x: x[0])
        if d > 500: continue
        t = p.get("tags", {})
        kind = "Elevator" if t.get("elevator") == "yes" or t.get("highway") == "elevator" else "Stair"
        entrances.append({"complexid": m_["complexid"], "stopname": m_["stopname"], "entrancelatitude": p["lat"], "entrancelongitude": p["lon"],
                          "entrancetype": kind, "entryallowed": "YES", "exitallowed": "YES"})
    out = {"format": 2, "date": a.date, "built": time.strftime("%Y-%m-%d"), "bbox": [w, s, e, n], "stations": metro, "entrances": entrances,
           "platforms": {"type": "FeatureCollection", "features": []}, "other_stations": other, "lines": {"type": "FeatureCollection", "features": feats},
           "route_colors": colors, "sources": ["© OpenStreetMap contributors"]}
    fn = f"transit_{a.release}_{a.date}.json"
    json.dump(out, open(os.path.join(DATA, fn), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    ip = os.path.join(DATA, "transit_index.json")
    idx = json.load(open(ip, encoding="utf-8")) if os.path.exists(ip) else {"snapshots": []}
    idx["snapshots"] = [x for x in idx["snapshots"] if x["file"] != fn] + [{"file": fn, "date": a.date, "built": out["built"], "bytes": os.path.getsize(os.path.join(DATA, fn))}]
    json.dump(idx, open(ip, "w", encoding="utf-8"), indent=1)
    print(f"  {fn}: {len(metro)} metro stations, {len(entrances)} entrances, {len(other)} rail stations, {len(feats)} line pieces, "
          f"{os.path.getsize(os.path.join(DATA, fn)) / 1e6:.1f} MB", flush=True)

if __name__ == "__main__":
    main()
