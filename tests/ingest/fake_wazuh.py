"""A fake Wazuh for the connection probe tests (#112). Never a real Wazuh.

One ``http.server`` plays both the indexer (``GET /``, ``GET|POST /<pattern>/_search``
with Basic auth) and the server API (``POST /security/user/authenticate`` with
Basic auth, answering a fake JWT). Answers come from ``tests/fixtures/wazuh/``.
A test picks a failure per target with ``status``, slows every answer with
``delay``, or makes a target answer a body that is not JSON with ``not_json``.
Every request is recorded so tests can check what the probe sent.
"""

import base64
import json
import socket
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "wazuh"
INDEXER_USER = "test-reader-01"
INDEXER_PASSWORD = "fake-indexer-password-not-a-secret"
API_USER = "test-api-01"
API_PASSWORD = "fake-api-password-not-a-secret"
ALERT_PATTERN = "wazuh-alerts-*"
EVENT_PATTERN = "wazuh-archives-*"
ERROR_BODIES = {401: "error_401.json", 403: "error_403.json", 404: "error_404_index.json"}


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def unreachable_url() -> str:
    """An http URL nothing listens on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    has_authorization: bool


class FakeWazuh:
    """Targets: ``root``, ``alerts``, ``events``, ``auth``."""

    def __init__(self, archives: bool = True):
        self.archives = archives
        self.status: dict[str, int] = {}
        self.not_json: set[str] = set()
        self.delay = 0.0
        self.requests: list[Request] = []
        self._server: ThreadingHTTPServer | None = None

    def __enter__(self) -> "FakeWazuh":
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (http.server naming)
                fake._handle(self)

            def do_POST(self) -> None:  # noqa: N802
                fake._handle(self)

            def do_PUT(self) -> None:  # noqa: N802
                fake._handle(self)

            def do_DELETE(self) -> None:  # noqa: N802
                fake._handle(self)

            def log_message(self, *args: Any) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()
        return self

    def __exit__(self, *exc: Any) -> None:
        assert self._server is not None
        self._server.shutdown()
        self._server.server_close()

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        length = int(handler.headers.get("Content-Length") or 0)
        if length:
            handler.rfile.read(length)
        path = handler.path.split("?", 1)[0]
        authorization = handler.headers.get("Authorization")
        self.requests.append(Request(handler.command, path, authorization is not None))
        if self.delay:
            time.sleep(self.delay)
        status, body = self._answer(handler.command, path, authorization)
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        try:
            handler.send_response(status)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
        except OSError:
            pass  # the probe gave up waiting (timeout tests)

    def _target(self, method: str, path: str) -> str | None:
        if method == "GET" and path == "/":
            return "root"
        if method == "POST" and path == "/security/user/authenticate":
            return "auth"
        if method in {"GET", "POST"} and path == f"/{ALERT_PATTERN}/_search":
            return "alerts"
        if method in {"GET", "POST"} and path == f"/{EVENT_PATTERN}/_search":
            return "events"
        return None

    def _answer(self, method: str, path: str, authorization: str | None) -> tuple[int, Any]:
        target = self._target(method, path)
        if target is None:
            return 405, {"error": "the fake answers read requests only"}
        expected = (
            basic(API_USER, API_PASSWORD)
            if target == "auth"
            else basic(INDEXER_USER, INDEXER_PASSWORD)
        )
        status = self.status.get(target) or (200 if authorization == expected else 401)
        if status != 200:
            return status, load(ERROR_BODIES.get(status, "error_401.json"))
        if target in self.not_json:
            return 200, b"<html>not json</html>"
        if target == "root":
            return 200, load("indexer_root.json")
        if target == "auth":
            return 200, load("authenticate_ok.json")
        if target == "alerts":
            return 200, load("alert_search.json")
        if not self.archives:
            # A wildcard that matches no index answers 200 with no hits.
            empty = load("archive_search.json")
            empty["hits"] = {"total": {"value": 0, "relation": "eq"}, "max_score": None, "hits": []}
            return 200, empty
        return 200, load("archive_search.json")
