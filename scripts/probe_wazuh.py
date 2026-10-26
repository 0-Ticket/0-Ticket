"""#112 (C-02a): read-only connection probe for an already built Wazuh (box 3 spike).

Not the box 3 connector (C-02b). It checks that the Wazuh indexer and server API
can be reached and logged in to, and reports the *shape* of the raw alert and
event answers so the connector can be written against them:

- indexer ``GET /``: reachability, login, OpenSearch distribution and version
- indexer ``POST /<alert pattern>/_search`` and ``/<event pattern>/_search``
  (a few newest documents): outcome, total, envelope keys, ``_source`` key paths
  with their types and how many documents have them, index names with the date
  part replaced by ``<date>``
- server API ``POST /security/user/authenticate``: whether a JWT is issued. The
  token is dropped at once and never used for another call.

Nothing else is sent; the probe never writes to Wazuh or changes its settings.
Every failure is one of ``OUTCOMES``. The report holds no field values, no
addresses, no user names, no passwords, no token and no error text from the
answer: document content may be attacker-written (docs/security-policy.md 3).
Key names are reduced to a safe character set because Wazuh's JSON decoder can
take them from log content.

Secrets come only from environment variables (names below, overridable). Both
URLs must be ``https://``: plain http would send the Basic credentials in clear,
so the probe stops before any request, and there is no flag to allow it. TLS is
always checked; a self-signed Wazuh certificate is trusted with ``--ca``.
Redirects are never followed (a 3xx is ``bad_response``), so the Authorization
header never reaches a redirect target.

    uv run python scripts/probe_wazuh.py --indexer-url https://<indexer>:9200 \\
        --api-url https://<manager>:55000 --ca <root-ca.pem> --out wazuh/probe.json

``--out`` is relative to ``data/`` (not committed) and may not leave it.
Exit code: 0 every target ok, 1 some target failed, 2 setup error (no request sent).
"""

import argparse
import base64
import json
import os
import re
import ssl
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from soc.config import MissingSecretError, read_secret

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
REPORT_VERSION = 1
OUTCOMES = (
    "ok",
    "unreachable",
    "timeout",
    "tls_error",
    "auth_failed",
    "forbidden",
    "index_missing",
    "bad_response",
)
MAX_BODY_BYTES = 5 * 1024 * 1024
MAX_KEY_LENGTH = 64
MAX_PATH_LENGTH = 200
MAX_PATHS = 500
_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9_@\-]")
_INDEX_DATE = re.compile(r"\d{4}\.\d{2}\.\d{2}")
_VERSION_CHARS = re.compile(r"[^A-Za-z0-9.\-]")
_UNSAFE_INDEX_CHARS = re.compile(r"[^A-Za-z0-9_.*,\-]")


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only Wazuh connection probe (#112).")
    parser.add_argument(
        "--indexer-url", required=True, help="Wazuh indexer, https only, e.g. https://host:9200"
    )
    parser.add_argument(
        "--api-url", help="Wazuh server API, https only, e.g. https://host:55000. Skipped if empty"
    )
    parser.add_argument("--alert-index", default="wazuh-alerts-*")
    parser.add_argument("--event-index", default="wazuh-archives-*")
    parser.add_argument(
        "--ca", help="CA file that signs the Wazuh certificates (self-signed setups)"
    )
    parser.add_argument("--size", type=int, default=20, help="documents read per pattern (1-100)")
    parser.add_argument("--timeout", type=float, default=10.0, help="seconds per request")
    parser.add_argument("--out", help="also write the report to this path under data/")
    parser.add_argument("--indexer-user-env", default="WAZUH_INDEXER_USER")
    parser.add_argument("--indexer-password-env", default="WAZUH_INDEXER_PASSWORD")
    parser.add_argument("--api-user-env", default="WAZUH_API_USER")
    parser.add_argument("--api-password-env", default="WAZUH_API_PASSWORD")
    args = parser.parse_args(argv)
    if not 1 <= args.size <= 100:
        parser.error("--size must be between 1 and 100")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    return args


def classify_error(error: BaseException) -> tuple[str, int | None]:
    """Map a request failure to an outcome and HTTP status. Never reads the message."""
    if isinstance(error, HTTPError):
        status = error.code
        if status == 401:
            return "auth_failed", status
        if status == 403:
            return "forbidden", status
        if status == 404:
            return "index_missing", status
        return "bad_response", status
    if isinstance(error, URLError) and isinstance(error.reason, BaseException):
        return classify_error(error.reason)
    if isinstance(error, ssl.SSLError):
        return "tls_error", None
    if isinstance(error, TimeoutError):
        return "timeout", None
    if isinstance(error, (URLError, OSError)):
        return "unreachable", None
    return "bad_response", None


def safe_key(key: Any) -> str:
    text = _UNSAFE_KEY_CHARS.sub("?", str(key))
    return text[:MAX_KEY_LENGTH]


def safe_index(name: str) -> str:
    return _UNSAFE_INDEX_CHARS.sub("?", name)[:MAX_PATH_LENGTH]


def _type_name(value: Any) -> str:
    return type(value).__name__


def _walk(value: Any, path: str, seen: dict[str, set[str]]) -> None:
    if path:
        seen.setdefault(path, set()).add(_type_name(value))
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{safe_key(key)}" if path else safe_key(key)
            if len(child_path) > MAX_PATH_LENGTH:
                child_path = child_path[:MAX_PATH_LENGTH]
            _walk(child, child_path, seen)
    elif isinstance(value, list):
        for item in value:
            _walk(item, f"{path}[]"[:MAX_PATH_LENGTH], seen)


def source_shape(sources: Sequence[Any]) -> dict[str, dict[str, Any]]:
    """Key path -> types seen and how many of the documents have it. No values."""
    types: dict[str, set[str]] = {}
    present: dict[str, int] = {}
    for source in sources:
        seen: dict[str, set[str]] = {}
        _walk(source, "", seen)
        for path, names in seen.items():
            types.setdefault(path, set()).update(names)
            present[path] = present.get(path, 0) + 1
    paths = sorted(types)[:MAX_PATHS]
    return {
        path: {"types": sorted(types[path]), "present": present[path], "of": len(sources)}
        for path in paths
    }


def envelope_shape(answer: Mapping[str, Any]) -> dict[str, Any]:
    """Key -> type of the ``_search`` answer around the documents."""
    shape: dict[str, Any] = {safe_key(k): _type_name(v) for k, v in answer.items()}
    hits = answer.get("hits")
    if isinstance(hits, dict):
        shape.update({f"hits.{safe_key(k)}": _type_name(v) for k, v in hits.items()})
        items = hits.get("hits")
        if isinstance(items, list):
            keys: dict[str, str] = {}
            for item in items:
                if isinstance(item, dict):
                    keys.update({safe_key(k): _type_name(v) for k, v in item.items()})
            shape["hits.hits[]"] = dict(sorted(keys.items()))
    return dict(sorted(shape.items()))


def index_names(items: Sequence[Any]) -> list[str]:
    names = {
        _INDEX_DATE.sub("<date>", safe_index(item["_index"]))
        for item in items
        if isinstance(item, dict) and isinstance(item.get("_index"), str)
    }
    return sorted(names)


class _NoRedirect(HTTPRedirectHandler):
    """Never follow a redirect: the 3xx comes back as an ``HTTPError`` (``bad_response``).

    urllib would otherwise send the request again, Authorization header included,
    to whatever ``Location`` names, another host too.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _Client:
    """Sends the probe's read requests. Holds the Basic credentials; never shows them.

    ``https_handler`` is for tests only (a fake Wazuh without TLS behind an
    ``https://`` URL); the CLI always uses ``HTTPSHandler`` with the checked context.
    """

    def __init__(
        self,
        timeout: float,
        context: ssl.SSLContext,
        https_handler: HTTPSHandler | None = None,
    ):
        self._timeout = timeout
        self._opener = build_opener(_NoRedirect(), https_handler or HTTPSHandler(context=context))

    def __repr__(self) -> str:
        return "_Client()"

    def call(
        self, method: str, url: str, authorization: str, body: dict[str, Any] | None = None
    ) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode()
        request = Request(url, data=data, method=method)
        request.add_header("Authorization", authorization)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        with self._opener.open(request, timeout=self._timeout) as response:
            status = response.status
            raw = response.read(MAX_BODY_BYTES + 1)
        if len(raw) > MAX_BODY_BYTES:
            raise ValueError("answer too large")
        return status, json.loads(raw)


def _basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def _attempt(client: _Client, method: str, url: str, auth: str, body: Any = None):
    """(outcome, status, answer). The answer is None unless the outcome is ok."""
    try:
        status, answer = client.call(method, url, auth, body)
    except (HTTPError, URLError, OSError) as error:
        outcome, status = classify_error(error)
        return outcome, status, None
    except ValueError:  # JSON that does not parse, or an oversized answer
        return "bad_response", 200, None
    return "ok", status, answer


def probe_indexer_root(client: _Client, base: str, auth: str) -> dict[str, Any]:
    outcome, status, answer = _attempt(client, "GET", f"{base}/", auth)
    result: dict[str, Any] = {"outcome": outcome, "http_status": status}
    if outcome == "ok":
        version = answer.get("version") if isinstance(answer, dict) else None
        if not isinstance(version, dict):
            return {"outcome": "bad_response", "http_status": status}
        for key, name in (("distribution", "distribution"), ("number", "version")):
            value = version.get(key)
            result[name] = _VERSION_CHARS.sub("", value)[:32] if isinstance(value, str) else None
    return result


def probe_search(client: _Client, base: str, pattern: str, auth: str, size: int) -> dict[str, Any]:
    body = {
        "size": size,
        "track_total_hits": True,
        "sort": [{"@timestamp": {"order": "desc", "unmapped_type": "date"}}],
        "query": {"match_all": {}},
    }
    outcome, status, answer = _attempt(client, "POST", f"{base}/{pattern}/_search", auth, body)
    if outcome != "ok":
        return {"outcome": outcome, "http_status": status}
    hits = answer.get("hits") if isinstance(answer, dict) else None
    items = hits.get("hits") if isinstance(hits, dict) else None
    if not isinstance(items, list):
        return {"outcome": "bad_response", "http_status": status}
    total = hits.get("total")
    if isinstance(total, dict):
        total = total.get("value")
    if not isinstance(total, int):
        total = len(items)
    sources = [item.get("_source") for item in items if isinstance(item, dict)]
    return {
        "outcome": "ok" if items else "index_missing",
        "http_status": status,
        "total": total,
        "read": len(items),
        "index_names": index_names(items),
        "envelope": envelope_shape(answer),
        "source_shape": source_shape(sources),
    }


def probe_api(client: _Client, base: str, auth: str) -> dict[str, Any]:
    outcome, status, answer = _attempt(client, "POST", f"{base}/security/user/authenticate", auth)
    if outcome != "ok":
        return {"outcome": outcome, "http_status": status}
    data = answer.get("data") if isinstance(answer, dict) else None
    issued = isinstance(data, dict) and isinstance(data.get("token"), str) and data["token"]
    del answer, data  # drop the token now
    return {"outcome": "ok" if issued else "bad_response", "http_status": status}


def _notes(targets: Mapping[str, Mapping[str, Any]]) -> list[str]:
    notes = []
    if targets["alerts"]["outcome"] == "index_missing":
        notes.append("alert pattern matched no document: check the alert index pattern")
    if targets["events"]["outcome"] == "index_missing":
        notes.append(
            "event pattern matched no document: archives (logall_json) may be off; "
            "collecting events needs a Wazuh setting change, not made by this probe"
        )
    return notes


def plain_http_urls(args: argparse.Namespace) -> list[str]:
    """Names of the URL options that are not https. Their values are never shown."""
    urls = {"--indexer-url": args.indexer_url, "--api-url": args.api_url}
    return [
        name
        for name, url in urls.items()
        if url is not None and not url.lower().startswith("https://")
    ]


def run(
    args: argparse.Namespace,
    environ: Mapping[str, str],
    https_handler: HTTPSHandler | None = None,
) -> dict[str, Any]:
    if plain_http_urls(args):
        raise ValueError("the probe sends credentials over https only")
    context = (
        ssl.create_default_context(cafile=args.ca) if args.ca else ssl.create_default_context()
    )
    client = _Client(args.timeout, context, https_handler)
    indexer = args.indexer_url.rstrip("/")
    indexer_auth = _basic(
        read_secret(args.indexer_user_env, environ), read_secret(args.indexer_password_env, environ)
    )
    api_auth = (
        _basic(read_secret(args.api_user_env, environ), read_secret(args.api_password_env, environ))
        if args.api_url
        else None
    )
    targets: dict[str, dict[str, Any]] = {
        "indexer": probe_indexer_root(client, indexer, indexer_auth),
        "alerts": probe_search(client, indexer, args.alert_index, indexer_auth, args.size),
        "events": probe_search(client, indexer, args.event_index, indexer_auth, args.size),
    }
    if api_auth is not None:
        targets["api"] = probe_api(client, args.api_url.rstrip("/"), api_auth)
    del indexer_auth, api_auth
    return {
        "report_version": REPORT_VERSION,
        "checked": {
            "alert_index": safe_index(args.alert_index),
            "event_index": safe_index(args.event_index),
            "size": args.size,
            "ca_given": bool(args.ca),
        },
        "targets": targets,
        "notes": _notes(targets),
    }


def _out_path(out: str, data_dir: Path) -> Path | None:
    base = data_dir.resolve()
    path = (base / out).resolve()
    return path if path.is_relative_to(base) and path != base else None


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    data_dir: Path | None = None,
    https_handler: HTTPSHandler | None = None,
) -> int:
    args = parse_args(argv)
    environ = os.environ if environ is None else environ
    plain = plain_http_urls(args)
    if plain:
        print(
            f"{' and '.join(plain)} must start with https:// "
            "(plain http would send the credentials unencrypted)",
            file=sys.stderr,
        )
        return 2
    out_path = None
    if args.out:
        out_path = _out_path(args.out, data_dir or DATA_DIR)
        if out_path is None:
            print("--out must be a relative path that stays under data/", file=sys.stderr)
            return 2
    if args.ca and not Path(args.ca).is_file():
        print("--ca file not found", file=sys.stderr)
        return 2
    names = [args.indexer_user_env, args.indexer_password_env]
    if args.api_url:
        names += [args.api_user_env, args.api_password_env]
    missing = [name for name in names if not environ.get(name)]
    if missing:
        print(
            f"Environment variables not set (see .env.example): {', '.join(missing)}",
            file=sys.stderr,
        )
        return 2
    try:
        report = run(args, environ, https_handler)
    except MissingSecretError:  # checked above; kept so a race never prints a secret
        print("Environment variables not set (see .env.example)", file=sys.stderr)
        return 2
    text = json.dumps(report, indent=2, ensure_ascii=True)
    print(text)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    return 0 if all(t["outcome"] == "ok" for t in report["targets"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
