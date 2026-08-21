"""Debug hub server: static files from the repo root + the repair API.

  GET /api/repair?x0=&y0=&x1=&y1=   (map-relative px, from the viewer)
      Runs `isomap.repair export` and returns its JSON (file links + the
      commit command). Sub-second: composes from tiles already on disk.

Binds 0.0.0.0:9090 (user browses http://10.162.90.85:9090 directly on the
private LAN; the SSH tunnel remains an alternative).
"""

import json
import subprocess
import sys
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(REPO), **kw)

    def end_headers(self):
        # the map grows/changes on every commit — never let the browser cache
        # the pyramid or viewer pages (stale DZI hides new tiles)
        if self.path.startswith("/docs/") or self.path.endswith(".html") or self.path == "/":
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/repair":
            return super().do_GET()
        q = dict(urllib.parse.parse_qsl(parsed.query))
        try:
            args = [str(int(float(q[k]))) for k in ("x0", "y0", "x1", "y1")]
        except (KeyError, ValueError):
            self.send_error(400, "need integer x0,y0,x1,y1")
            return
        city = q.get("city", "toronto")
        if not city.isidentifier():
            self.send_error(400, "bad city")
            return
        proc = subprocess.run(
            [sys.executable, "-m", "isomap.repair", "export", city, *args],
            capture_output=True, text=True, cwd=REPO,
        )
        if proc.returncode != 0:
            body = json.dumps({"error": proc.stderr[-500:]}).encode()
            self.send_response(500)
        else:
            body = proc.stdout.strip().splitlines()[-1].encode()
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 9090), Handler).serve_forever()
