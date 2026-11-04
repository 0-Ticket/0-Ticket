"""수집 실행: 페이지 저장, 체크포인트 재개, 실패 시 멈춤과 기록, 명령 진입점(#218).

저장소는 FakeStore(메모리)로 바꿔 DB 없이 확인한다. 실제 트랜잭션은 store 쪽 db 테스트가 본다.
"""

import contextlib

import httpx
import psycopg
import pytest
from fake_elk import ALERTS, API_KEY, BASE_URL, EVENTS, FakeElk, FakeStore, make_settings, respond

from soc.ingest import __main__ as main_module
from soc.ingest import elk, run
from soc.ingest.run import exit_code, format_results

PROFILE = "elk-test"
EVENT_CP = (PROFILE, "event", "logs-web-*")


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    fake = FakeStore()
    monkeypatch.setattr(run, "store", fake)
    return fake


def run_with(fake: FakeElk, *sources, **settings) -> list[run.SourceResult]:
    with fake.client() as client:
        return run.run(make_settings(*sources, **settings), None, client)


def test_pages_are_saved_with_checkpoint(store: FakeStore) -> None:
    fake = FakeElk({"logs-web-*": ["elk_events_page1.json", "elk_events_page2.json"]})
    (result,) = run_with(fake)

    assert (result.name, result.pages, result.inserted, result.failure) == (
        "event:logs-web-*",
        2,
        3,
        None,
    )
    # 두 인덱스의 같은 _id는 다른 원본이다
    assert sorted(ref for _, ref in store.records) == [
        ".ds-logs-apache.access-default-2026.11.04-000001/dup-1",
        ".ds-logs-nginx.access-default-2026.11.04-000001/dup-1",
        ".ds-logs-nginx.access-default-2026.11.04-000001/evt-3",
    ]
    record = store.records[(PROFILE, ".ds-logs-nginx.access-default-2026.11.04-000001/dup-1")]
    assert record["id"].startswith("raw_")
    assert record["kind"] == "event"
    assert isinstance(record["fetched_at"], int)
    assert record["original"]["_source"]["message"].startswith("HIT-MARKER")
    assert record["original"]["sort"] == [1793754000000, 11]  # hit 객체 그대로
    checkpoint = store.checkpoints[EVENT_CP]
    assert checkpoint["cursor"] == {"time_ms": 1793754300000}  # 마지막 페이지 마지막 hit의 시각
    assert checkpoint["last_error"] is None


def test_next_run_resumes_from_checkpoint_and_skips_stored(store: FakeStore) -> None:
    run_with(FakeElk({"logs-web-*": ["elk_events_page1.json", "elk_events_page2.json"]}))
    before = dict(store.records)

    fake = FakeElk({"logs-web-*": ["elk_events_page2.json"]})
    (result,) = run_with(fake)

    (body,) = fake.search_bodies()
    assert body["query"] == {
        "range": {"@timestamp": {"gte": 1793754300000, "format": "epoch_millis"}}
    }
    assert (result.pages, result.inserted, result.failure) == (1, 0, None)
    assert store.records == before  # 겹친 원본을 덮어쓰지 않는다


def test_empty_result_keeps_checkpoint(store: FakeStore) -> None:
    (result,) = run_with(FakeElk({"logs-web-*": ["elk_empty.json"]}))
    assert (result.pages, result.inserted, result.failure) == (0, 0, None)
    assert store.checkpoints == {}


def test_bad_record_stops_with_contract_rejected(store: FakeStore) -> None:
    fake = FakeElk({"logs-web-*": ["elk_events_page1.json", "elk_bad_record.json"]})
    (result,) = run_with(fake)

    assert (result.pages, result.inserted, result.failure) == (1, 2, "contract_rejected")
    assert len(store.records) == 2  # 거부된 페이지는 아무것도 넣지 않았다
    checkpoint = store.checkpoints[EVENT_CP]
    assert checkpoint["cursor"] == {"time_ms": 1793754000000}  # 마지막 성공 페이지
    assert checkpoint["last_error"] == "contract_rejected"
    assert store.failures == [(*EVENT_CP, "contract_rejected")]
    assert fake.calls()[-1] == "DELETE /_pit"


def test_siem_failure_keeps_checkpoint_and_other_sources_run(store: FakeStore) -> None:
    store.checkpoints[EVENT_CP] = {
        "siem_profile": PROFILE,
        "source_kind": "event",
        "source_key": "logs-web-*",
        "cursor": {"time_ms": 1793750000000},
        "updated_at": 1793750000000,
        "last_error": None,
    }
    fake = FakeElk(
        {
            "logs-web-*": [respond(500, {"error": "SECRET-BODY"})],
            ".alerts-security.alerts-default": ["elk_alerts_page1.json"],
        }
    )
    events, alerts = run_with(fake, EVENTS, ALERTS)

    assert events.failure == "http_status"
    assert store.checkpoints[EVENT_CP]["cursor"] == {"time_ms": 1793750000000}
    assert store.checkpoints[EVENT_CP]["last_error"] == "http_status"
    assert (alerts.pages, alerts.inserted, alerts.failure) == (1, 1, None)
    assert store.records[(PROFILE, ".internal.alerts-security.alerts-default-000001/alert-1")][
        "kind"
    ] == ("alert")
    assert exit_code([events, alerts]) == 1


def test_db_error_is_db_error_and_failed_failure_record_is_ignored(store: FakeStore) -> None:
    store.save_error = psycopg.OperationalError("server closed the connection")
    store.failure_error = psycopg.OperationalError("still down")
    (result,) = run_with(FakeElk({"logs-web-*": ["elk_events_page2.json"]}))
    assert (result.pages, result.inserted, result.failure) == (0, 0, "db_error")
    assert store.checkpoints == {}


def test_failure_prints_name_and_kind_only(
    store: FakeStore, capsys: pytest.CaptureFixture[str]
) -> None:
    run_with(FakeElk({"logs-web-*": ["elk_events_page1.json", respond(401, {"e": "SECRET-BODY"})]}))
    captured = capsys.readouterr()
    assert captured.err == "event:logs-web-*: 실패 auth\n"
    assert captured.out == ""


def test_format_results_has_counts_only() -> None:
    results = [
        run.SourceResult(name="event:logs-web-*", pages=2, inserted=3),
        run.SourceResult(name="alert:.alerts-security.alerts-default", failure="auth"),
    ]
    assert format_results(results) == [
        "event:logs-web-*: 페이지 2, 새로 저장 3, 실패 없음",
        "alert:.alerts-security.alerts-default: 페이지 0, 새로 저장 0, 실패 auth",
    ]
    assert exit_code(results[:1]) == 0


# --- 명령 진입점 ---


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setenv("ELK_URL", BASE_URL)
    monkeypatch.setenv("ELK_API_KEY", API_KEY)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake-user:DB-SECRET@db.example.com/soc")
    return monkeypatch


def connect_must_not_run(*args, **kwargs):
    raise AssertionError("설정 오류에서는 연결하지 않는다")


@pytest.mark.parametrize("missing", ["ELK_URL", "ELK_API_KEY", "DATABASE_URL"])
def test_missing_env_is_exit_2_without_connecting(
    env: pytest.MonkeyPatch, missing: str, capsys: pytest.CaptureFixture[str]
) -> None:
    env.delenv(missing)
    env.setattr(main_module.psycopg, "connect", connect_must_not_run)
    env.setattr(main_module.elk, "make_client", connect_must_not_run)
    assert main_module.main() == 2
    err = capsys.readouterr().err
    assert missing in err
    assert API_KEY not in err and "DB-SECRET" not in err


@pytest.mark.parametrize(
    "url", ["ftp://elk.example.com", "elk.example.com:9200", "https://user:pw@elk.example.com"]
)
def test_bad_elk_url_is_exit_2(env: pytest.MonkeyPatch, url: str, capsys) -> None:
    env.setenv("ELK_URL", url)
    env.setattr(main_module.psycopg, "connect", connect_must_not_run)
    assert main_module.main() == 2
    assert url not in capsys.readouterr().err


def test_main_runs_sources_and_never_prints_secrets(
    env: pytest.MonkeyPatch, store: FakeStore, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeElk(
        {
            "logs-web-*": ["elk_events_page2.json"],
            ".alerts-security.alerts-default": [respond(500, {"error": "SECRET-BODY"})],
        }
    )
    connected: list[dict] = []

    @contextlib.contextmanager
    def fake_connect(url: str, **kwargs):
        connected.append(kwargs)
        yield None

    make_client = elk.make_client

    def fake_client(settings, base_url: str, api_key: str) -> httpx.Client:
        with make_client(settings, base_url, api_key) as real:
            headers = real.headers
        return httpx.Client(base_url=base_url, headers=headers, transport=httpx.MockTransport(fake))

    env.setattr(main_module.psycopg, "connect", fake_connect)
    env.setattr(main_module.elk, "make_client", fake_client)
    env.setattr(main_module, "load_config", lambda: {"ingest": settings_table(EVENTS, ALERTS)})

    assert main_module.main() == 1
    assert connected == [{"autocommit": True}]
    assert fake.requests[0].headers["Authorization"] == f"ApiKey {API_KEY}"
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "event:logs-web-*: 페이지 1, 새로 저장 1, 실패 없음",
        "alert:.alerts-security.alerts-default: 페이지 0, 새로 저장 0, 실패 http_status",
    ]
    assert captured.err == "alert:.alerts-security.alerts-default: 실패 http_status\n"
    output = captured.out + captured.err
    for secret in (API_KEY, "DB-SECRET", BASE_URL, "SECRET-BODY", "192.0.2.15"):
        assert secret not in output


def test_db_connect_failure_is_exit_1(env: pytest.MonkeyPatch, capsys) -> None:
    def refused(url: str, **kwargs):
        raise psycopg.OperationalError("connection to db.example.com DB-SECRET failed")

    env.setattr(main_module.psycopg, "connect", refused)
    assert main_module.main() == 1
    err = capsys.readouterr().err
    assert "OperationalError" in err and "DB-SECRET" not in err


def settings_table(*sources) -> dict:
    return {
        "siem_profile": PROFILE,
        "url_env": "ELK_URL",
        "api_key_env": "ELK_API_KEY",
        "page_size": 2,
        "connect_timeout_seconds": 5,
        "read_timeout_seconds": 5,
        "max_bytes": 1_000_000,
        "deadline_seconds": 30,
        "sources": [{"kind": s.kind, "key": s.key, "time_field": s.time_field} for s in sources],
    }
