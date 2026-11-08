"""orders-api — mock application for scenario KB7 (dev/test only, not part of AutoAWS).

  v2.4.x  every request answers 200
  v2.5.x  every /api/* request first connects to the database; nothing answers there, so the
          request fails with an OperationalError traceback in the log and returns 500

The version is read from APP_VERSION_FILE on every request, so "deploying" a release is
`echo 2.5.0 > $APP_VERSION_FILE` (what `scenario.py fault kb7` does through SSM).

Settings (environment; defaults are the values used on the scenario's EC2 instance):
  APP_PORT          80
  APP_VERSION_FILE  /opt/app/VERSION   (missing file -> APP_VERSION)
  APP_VERSION       2.4.3
  APP_LOG_FILE      /var/log/app.log   ("-" = stdout)
  DB_HOST, DB_PORT  10.70.9.15, 5432   (an address in the VPC where nothing listens)
  DB_TIMEOUT        3 seconds
  LOG_GROUP         optional: also send each log line to this CloudWatch Logs group with boto3
                    (local runs against LocalStack: set AWS_ENDPOINT_URL too). On EC2 the
                    CloudWatch agent ships APP_LOG_FILE instead.

Standard library only (boto3 is imported only when LOG_GROUP is set).
"""

import contextlib
import http.server
import logging
import os
import pathlib
import socket
import sys
import time

PORT = int(os.environ.get("APP_PORT", "80"))
VERSION_FILE = pathlib.Path(os.environ.get("APP_VERSION_FILE", "/opt/app/VERSION"))
DEFAULT_VERSION = os.environ.get("APP_VERSION", "2.4.3")
LOG_FILE = os.environ.get("APP_LOG_FILE", "/var/log/app.log")
DB = (os.environ.get("DB_HOST", "10.70.9.15"), int(os.environ.get("DB_PORT", "5432")))
DB_TIMEOUT = float(os.environ.get("DB_TIMEOUT", "3"))
LOG_GROUP = os.environ.get("LOG_GROUP", "")

log = logging.getLogger("orders-api")


class OperationalError(Exception):
    """Same message shape as psycopg2's, which is what the scenario's log shows."""


class CloudWatchHandler(logging.Handler):
    """Send every record to CloudWatch Logs (one stream per process). Demo-grade: no batching."""

    def __init__(self, group: str) -> None:
        super().__init__()
        import boto3  # only needed for this optional handler

        self.client = boto3.client("logs", endpoint_url=os.environ.get("AWS_ENDPOINT_URL") or None)
        self.group = group
        self.stream = f"{socket.gethostname()}-{os.getpid()}"
        with contextlib.suppress(self.client.exceptions.ResourceAlreadyExistsException):
            self.client.create_log_group(logGroupName=group)
        self.client.create_log_stream(logGroupName=group, logStreamName=self.stream)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.client.put_log_events(
                logGroupName=self.group,
                logStreamName=self.stream,
                logEvents=[
                    {"timestamp": int(record.created * 1000), "message": self.format(record)}
                ],
            )
        except Exception:  # noqa: BLE001 — logging must never break the app
            self.handleError(record)


def version() -> str:
    try:
        return VERSION_FILE.read_text().strip() or DEFAULT_VERSION
    except OSError:
        return DEFAULT_VERSION


def connect_db() -> None:
    try:
        socket.create_connection(DB, timeout=DB_TIMEOUT).close()
    except OSError as e:
        raise OperationalError(
            "could not connect to server: Connection timed out. Is the server running on host "
            f'"orders-db.internal" ({DB[0]}) and accepting TCP/IP connections on port {DB[1]}?'
        ) from e


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        v = version()
        code = 200
        if self.path.startswith("/api/") and v.startswith("2.5"):
            try:
                connect_db()
            except OperationalError:
                log.exception("GET %s failed", self.path)
                code = 500
        body = f"orders-api v{v}\n".encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        log.log(logging.ERROR if code >= 500 else logging.INFO, "GET %s %s", self.path, code)

    def log_message(self, *args) -> None:  # silence the default stderr access log
        pass


def setup_logging() -> None:
    handler = (
        logging.StreamHandler(sys.stdout) if LOG_FILE == "-" else logging.FileHandler(LOG_FILE)
    )
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fmt.converter = time.gmtime  # UTC, like the tool outputs
    handlers = [handler]
    if LOG_GROUP:
        handlers.append(CloudWatchHandler(LOG_GROUP))
    for h in handlers:
        h.setFormatter(fmt)
        log.addHandler(h)
    log.setLevel(logging.INFO)


def main() -> None:
    setup_logging()
    log.info("starting orders-api v%s", version())
    http.server.ThreadingHTTPServer(("", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
