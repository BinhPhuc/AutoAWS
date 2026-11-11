"""web — mock application for scenario KB3 (dev/test only, not part of AutoAWS).

  v1.x  health endpoint /health   (what the ALB target group checks)
  v2.x  health endpoint renamed to /api/health; /health now answers 404, so the target group
        marks every target unhealthy while "/" keeps working (ALB fail-open)

The version is read from APP_VERSION_FILE on every request, so "deploying" a release is
`echo 2.0.0 > $APP_VERSION_FILE` (what `scenario.py fault kb3` does through SSM).

Settings (environment; defaults are the values used on the scenario's EC2 instances):
  APP_PORT 80 · APP_VERSION_FILE /opt/app/VERSION · APP_VERSION 1.4.2 (missing file)
  APP_LOG_FILE /var/log/app.log ("-" = stdout)
Standard library only.
"""

import http.server
import logging
import os
import pathlib
import sys
import time

PORT = int(os.environ.get("APP_PORT", "80"))
VERSION_FILE = pathlib.Path(os.environ.get("APP_VERSION_FILE", "/opt/app/VERSION"))
DEFAULT_VERSION = os.environ.get("APP_VERSION", "1.4.2")
LOG_FILE = os.environ.get("APP_LOG_FILE", "/var/log/app.log")

log = logging.getLogger("web")


def version() -> str:
    try:
        return VERSION_FILE.read_text().strip() or DEFAULT_VERSION
    except OSError:
        return DEFAULT_VERSION


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        v = version()
        health = "/api/health" if v.startswith("2") else "/health"
        code = 200 if self.path in ("/", health) else 404
        body = f"web v{v}\n".encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        log.info("GET %s %s (v%s)", self.path, code, v)

    def log_message(self, *args) -> None:
        pass


def main() -> None:
    handler = (
        logging.StreamHandler(sys.stdout) if LOG_FILE == "-" else logging.FileHandler(LOG_FILE)
    )
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fmt.converter = time.gmtime
    handler.setFormatter(fmt)
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.info("starting web v%s", version())
    http.server.ThreadingHTTPServer(("", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
