#!/usr/bin/env python3
"""bundle.py — make a single self-contained HTML file for previewing or emailing (opens by double-click,"""
import argparse, base64, json, os
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ap = argparse.ArgumentParser()
ap.add_argument("--name", default="prototype_1.6.html"); ap.add_argument("--title", default=None)
ap.add_argument("--release", action="append", help="release id to include (repeatable); default: every release under --max-mb")
ap.add_argument("--max-mb", type=float, default=20); ap.add_argument("--zoning", action="store_true")
a = ap.parse_args()
rd = lambda p: open(os.path.join(ROOT, p), encoding="utf-8").read()
b64 = lambda p: base64.b64encode(open(os.path.join(ROOT, p), "rb").read()).decode()
html, css, js = rd("index.html"), rd("style.css"), rd("app.js")
releases = json.load(open(os.path.join(ROOT, "data", "releases.json"), encoding="utf-8"))
keep = [r for r in releases if (r["id"] in a.release if a.release else r.get("bytes", 0) <= a.max_mb * 1e6)]
if not keep: raise SystemExit("no release small enough; pass --release")
files = {}
for r in keep:
    d = os.path.join("data", r.get("dir", r["id"]))
    for f in os.listdir(os.path.join(ROOT, d)): files[f"{d}/{f}".replace("\\", "/")] = b64(os.path.join(d, f))
extra = {}
idx = json.load(open(os.path.join(ROOT, "data", "transit_index.json")))
used = {r.get("transit") for r in keep} - {None}
idx["snapshots"] = [s for s in idx["snapshots"] if not used or s["file"] in used]
extra["transitIndex"] = idx
extra["transitFiles"] = {s["file"]: json.load(open(os.path.join(ROOT, "data", s["file"]), encoding="utf-8")) for s in idx["snapshots"]}
if a.zoning and os.path.exists(os.path.join(ROOT, "data", "zoning_index.json")):
    zi = json.load(open(os.path.join(ROOT, "data", "zoning_index.json"))); zi["snapshots"] = zi["snapshots"][-1:]
    extra["zoningIndex"] = zi
    for s in zi["snapshots"]: files["data/" + s["file"]] = b64(os.path.join("data", s["file"]))
payload = json.dumps({"releases": keep, "files": files, **extra}, separators=(",", ":"))
assert "</script" not in js
html = html.replace('<link rel="stylesheet" href="style.css">', "<style>\n" + css + "</style>")
html = html.replace('<script src="app.js"></script>', "<script>window.__LP__=" + payload + ";</script>\n<script>\n" + js + "</script>")
if a.title: html = html.replace("<title>Lot Profiler</title>", f"<title>{a.title}</title>")
out = os.path.join(ROOT, a.name)
open(out, "w", encoding="utf-8").write(html)
print(f"{a.name}: {os.path.getsize(out)/1e6:.2f} MB, releases: {', '.join(r['id'] for r in keep)}, "
      f"{len(extra['transitFiles'])} subway snapshot(s){', zoning tiles' if a.zoning else ''}")
