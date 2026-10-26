"""#112 (C-02a): the read-only Wazuh connection probe (scripts/probe_wazuh.py).

Only a fake Wazuh is reached here (tests/ingest/fake_wazuh.py). The fixtures are
hand-made in the Wazuh 4.x answer shapes; no real Wazuh answer is read.
"""

import importlib.util
import json
import logging
import ssl
import sys
from pathlib import Path

import pytest
from fake_wazuh import (
    API_PASSWORD,
    API_USER,
    INDEXER_PASSWORD,
    INDEXER_USER,
    FakeWazuh,
    PlainHttpsHandler,
    load,
    unreachable_url,
)

ROOT = Path(__file__).resolve().parents[2]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "probe_wazuh", ROOT / "scripts" / "probe_wazuh.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe = _load_script()

ENVIRON = {
    "WAZUH_INDEXER_USER": INDEXER_USER,
    "WAZUH_INDEXER_PASSWORD": INDEXER_PASSWORD,
    "WAZUH_API_USER": API_USER,
    "WAZUH_API_PASSWORD": API_PASSWORD,
}
JWT = load("authenticate_ok.json")["data"]["token"]


def _run(capsys, fake_url, *extra, environ=ENVIRON, data_dir=None, api=True, timeout="1"):
    argv = ["--indexer-url", fake_url, "--timeout", timeout, *extra]
    if api:
        argv += ["--api-url", fake_url]
    code = probe.main(argv, environ=environ, data_dir=data_dir, https_handler=PlainHttpsHandler())
    out, err = capsys.readouterr()
    return code, json.loads(out) if out.strip() else None, out, err


def _outcomes(report):
    return {name: target["outcome"] for name, target in report["targets"].items()}


def test_all_targets_ok_against_a_working_wazuh(capsys):
    with FakeWazuh() as fake:
        code, report, _, _ = _run(capsys, fake.url)
    assert code == 0
    assert _outcomes(report) == {"indexer": "ok", "alerts": "ok", "events": "ok", "api": "ok"}
    assert report["targets"]["indexer"]["version"] == "2.19.1"
    assert report["targets"]["indexer"]["distribution"] == "opensearch"
    assert report["targets"]["alerts"]["total"] == 3
    assert report["targets"]["events"]["total"] == 2
    assert report["notes"] == []


@pytest.mark.parametrize(
    ("status", "outcome"),
    [(401, "auth_failed"), (403, "forbidden"), (404, "index_missing"), (500, "bad_response")],
)
def test_http_failures_are_told_apart(capsys, status, outcome):
    with FakeWazuh() as fake:
        fake.status["alerts"] = status
        code, report, _, _ = _run(capsys, fake.url)
    assert code == 1
    assert report["targets"]["alerts"]["outcome"] == outcome
    assert report["targets"]["alerts"]["http_status"] == status
    assert report["targets"]["indexer"]["outcome"] == "ok"


def test_wrong_password_is_auth_failed_not_unreachable(capsys):
    environ = {**ENVIRON, "WAZUH_INDEXER_PASSWORD": "wrong-password-not-a-secret"}
    with FakeWazuh() as fake:
        _, report, _, _ = _run(capsys, fake.url, environ=environ)
    outcomes = _outcomes(report)
    assert outcomes["indexer"] == outcomes["alerts"] == outcomes["events"] == "auth_failed"
    assert outcomes["api"] == "ok"


def test_api_wrong_password_is_auth_failed(capsys):
    environ = {**ENVIRON, "WAZUH_API_PASSWORD": "wrong-password-not-a-secret"}
    with FakeWazuh() as fake:
        _, report, _, _ = _run(capsys, fake.url, environ=environ)
    assert report["targets"]["api"]["outcome"] == "auth_failed"
    assert report["targets"]["alerts"]["outcome"] == "ok"


def test_nothing_listening_is_unreachable(capsys):
    # Windows retries a refused connection for about two seconds before giving up.
    code, report, _, _ = _run(capsys, unreachable_url(), timeout="5")
    assert code == 1
    assert set(_outcomes(report).values()) == {"unreachable"}


def test_slow_answer_is_timeout(capsys):
    with FakeWazuh() as fake:
        fake.delay = 1.5
        _, report, _, _ = _run(capsys, fake.url, api=False)
    assert report["targets"]["indexer"]["outcome"] == "timeout"


def test_body_that_is_not_json_is_bad_response(capsys):
    with FakeWazuh() as fake:
        fake.not_json.add("alerts")
        _, report, _, _ = _run(capsys, fake.url)
    assert report["targets"]["alerts"]["outcome"] == "bad_response"
    assert report["targets"]["alerts"]["http_status"] == 200


@pytest.mark.parametrize(
    "error",
    [
        ssl.SSLCertVerificationError(1, "certificate verify failed"),
        probe.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed")),
        probe.URLError(ssl.SSLError(1, "wrong version number")),
    ],
)
def test_tls_failure_is_classified_as_tls_error(error):
    # A real TLS handshake failure is checked only in the manual run (findings doc).
    assert probe.classify_error(error) == ("tls_error", None)


def test_api_auth_checks_the_jwt_issue_only(capsys):
    with FakeWazuh() as fake:
        _run(capsys, fake.url)
    api_calls = [r for r in fake.requests if r.path.startswith("/security")]
    assert [(r.method, r.path) for r in api_calls] == [("POST", "/security/user/authenticate")]
    # Every request after authenticate went to the indexer, never with the JWT.
    assert all(r.has_authorization for r in fake.requests)


def test_only_read_requests_are_sent(capsys):
    with FakeWazuh() as fake:
        _run(capsys, fake.url)
    sent = {(r.method, r.path) for r in fake.requests}
    assert sent == {
        ("GET", "/"),
        ("POST", "/wazuh-alerts-*/_search"),
        ("POST", "/wazuh-archives-*/_search"),
        ("POST", "/security/user/authenticate"),
    }


def test_secrets_and_jwt_never_reach_output_logs_or_report(capsys, caplog, tmp_path):
    caplog.set_level(logging.DEBUG)
    with FakeWazuh() as fake:
        fake.status["events"] = 403
        _, _, out, err = _run(capsys, fake.url, "--out", "probe/report.json", data_dir=tmp_path)
    written = (tmp_path / "probe" / "report.json").read_text(encoding="utf-8")
    for text in (out, err, caplog.text, written):
        for secret in (INDEXER_PASSWORD, API_PASSWORD, JWT):
            assert secret not in text


def test_report_has_shape_not_values(capsys):
    with FakeWazuh() as fake:
        _, report, out, _ = _run(capsys, fake.url)
    for value in (
        "198.51.100.23",
        "192.0.2.10",
        "203.0.113.45",
        "/admin/",
        "test-user-01",
        "Common web attack.",
        "ExampleScanner",
        "web-01.example.com",
        "fake-alert-0001",
        "test-reader-01",
    ):
        assert value not in out
    shape = report["targets"]["alerts"]["source_shape"]
    assert shape["data.srcip"] == {"types": ["str"], "present": 2, "of": 3}
    assert shape["data.src_ip"] == {"types": ["str"], "present": 1, "of": 3}
    assert shape["rule.level"] == {"types": ["int"], "present": 3, "of": 3}
    assert shape["rule.mitre.id[]"] == {"types": ["str"], "present": 2, "of": 3}
    envelope = report["targets"]["alerts"]["envelope"]
    assert envelope["hits.total"] == "dict"
    assert envelope["hits.hits[]"] == {
        "_id": "str",
        "_index": "str",
        "_score": "NoneType",
        "_source": "dict",
        "sort": "list",
    }
    assert report["targets"]["alerts"]["index_names"] == ["wazuh-alerts-4.x-<date>"]
    assert "rule.id" not in report["targets"]["events"]["source_shape"]


def test_key_names_that_look_like_payloads_are_neutralized():
    shape = probe.source_shape([{"data": {"<script>alert(1)</script>": 1, "x" * 300: 2}}])
    for path in shape:
        assert "<" not in path and ">" not in path
        assert len(path) <= probe.MAX_PATH_LENGTH


def test_empty_archives_is_flagged_as_needing_a_siem_change(capsys):
    with FakeWazuh(archives=False) as fake:
        code, report, _, _ = _run(capsys, fake.url)
    assert code == 1
    assert report["targets"]["events"]["outcome"] == "index_missing"
    assert report["targets"]["events"]["total"] == 0
    assert any("archives" in note for note in report["notes"])


def test_missing_env_var_stops_before_any_request(capsys):
    environ = {k: v for k, v in ENVIRON.items() if k != "WAZUH_INDEXER_PASSWORD"}
    with FakeWazuh() as fake:
        code, report, out, err = _run(capsys, fake.url, environ=environ)
    assert code == 2
    assert report is None
    assert fake.requests == []
    assert "WAZUH_INDEXER_PASSWORD" in err


def test_env_var_names_can_be_overridden(capsys):
    environ = {
        "OTHER_USER": INDEXER_USER,
        "OTHER_PASSWORD": INDEXER_PASSWORD,
    }
    with FakeWazuh() as fake:
        _, report, _, _ = _run(
            capsys,
            fake.url,
            "--indexer-user-env",
            "OTHER_USER",
            "--indexer-password-env",
            "OTHER_PASSWORD",
            environ=environ,
            api=False,
        )
    assert "api" not in report["targets"]
    assert report["targets"]["alerts"]["outcome"] == "ok"


@pytest.mark.parametrize("out", ["../outside.json", "/tmp/outside.json"])
def test_out_path_outside_data_is_refused(capsys, tmp_path, out):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with FakeWazuh() as fake:
        code, _, _, err = _run(capsys, fake.url, "--out", out, data_dir=data_dir)
    assert code == 2
    assert fake.requests == []
    assert not (tmp_path / "outside.json").exists()
    assert "data/" in err


def test_disabling_tls_checks_is_not_offered():
    with pytest.raises(SystemExit):
        probe.parse_args(["--indexer-url", "https://indexer.example.com:9200", "--insecure"])


@pytest.mark.parametrize("plain", ["indexer", "api", "both"])
def test_plain_http_url_stops_before_any_request(capsys, caplog, plain):
    caplog.set_level(logging.DEBUG)
    with FakeWazuh() as fake:
        indexer = fake.plain_url if plain in {"indexer", "both"} else fake.url
        api = fake.plain_url if plain in {"api", "both"} else fake.url
        argv = ["--indexer-url", indexer, "--api-url", api, "--timeout", "1"]
        code = probe.main(argv, environ=ENVIRON, https_handler=PlainHttpsHandler())
        out, err = capsys.readouterr()
    assert code == 2
    assert out == ""
    assert fake.requests == []
    assert "https://" in err
    for text in (err, caplog.text):
        for secret in (INDEXER_USER, INDEXER_PASSWORD, API_USER, API_PASSWORD, JWT):
            assert secret not in text


def test_run_refuses_plain_http_even_when_called_directly():
    args = probe.parse_args(["--indexer-url", "http://127.0.0.1:9"])
    with pytest.raises(ValueError):
        probe.run(args, ENVIRON)


@pytest.mark.parametrize("where", ["other_host", "same_host"])
def test_redirects_are_not_followed_and_get_no_authorization(capsys, where):
    with FakeWazuh() as fake, FakeWazuh() as elsewhere:
        base = elsewhere.url if where == "other_host" else fake.url
        for target in ("root", "alerts", "events", "auth"):
            fake.redirect[target] = f"{base}/moved/{target}"
        code, report, out, _ = _run(capsys, fake.url)
    assert code == 1
    for name in ("indexer", "alerts", "events", "api"):
        assert report["targets"][name] == {"outcome": "bad_response", "http_status": 302}
    # One request per target, none to the Location: the Authorization header never went there.
    assert len(fake.requests) == 4
    assert not any(r.path.startswith("/moved") for r in fake.requests)
    assert elsewhere.requests == []
    assert "/moved" not in out
