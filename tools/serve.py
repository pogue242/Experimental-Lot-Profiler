#!/usr/bin/env python3
"""serve.py — run the site locally:  python tools/serve.py [port] [folder]  ->  http://localhost:8000"""
import http.server, os, re, sys

ROOT = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TYPES = {".lpk": "application/octet-stream", ".bin": "application/octet-stream", ".pmtiles": "application/octet-stream",
         ".js": "text/javascript", ".json": "application/json", ".gz": "application/gzip"}

class H(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, **TYPES}
    def __init__(self, *a, **k): super().__init__(*a, directory=ROOT, **k)
    def log_message(self, *a): pass
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache"); self.send_header("Accept-Ranges", "bytes"); super().end_headers()
    def send_head(self):
        rng = self.headers.get("Range")
        path = self.translate_path(self.path)
        m = re.match(r"bytes=(\d*)-(\d*)$", rng or "")
        if not m or not os.path.isfile(path): return super().send_head()
        size = os.path.getsize(path)
        a, b = m.group(1), m.group(2)
        start, end = (int(a), int(b) if b else size - 1) if a else (max(0, size - int(b)), size - 1)
        end = min(end, size - 1)
        if start > end:
            self.send_response(416); self.send_header("Content-Range", f"bytes */{size}"); self.end_headers(); return None
        f = open(path, "rb"); f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        self._left = end - start + 1
        return f
    def copyfile(self, src, dst):
        left = getattr(self, "_left", None)
        if left is None: return super().copyfile(src, dst)
        while left > 0:
            buf = src.read(min(65536, left))
            if not buf: break
            dst.write(buf); left -= len(buf)
        self._left = None

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
with http.server.ThreadingHTTPServer(("", port), H) as s:
    print(f"Lot Profiler at http://localhost:{port}  (serving {ROOT})"); s.serve_forever()
