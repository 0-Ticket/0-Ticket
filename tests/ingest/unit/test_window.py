"""수동 수집의 조회 시작 시각, --since, 요약, 동시 실행 잠금, 인증서 실패 구분(#317).

저장소는 FakeStore(메모리)다. 실제 트랜잭션·잠금은 db/test_manual_ingest_db.py가 본다.
"""

import contextlib
from datetime import UTC, datetime

import httpx
import pytest
from fake_elk import ALERTS, API_KEY, BASE_URL, EVENTS, FakeElk, FakeStore, make_settings, respond

from soc.ingest import __main__ as main_module
from soc.ingest import elk, run
from soc.ingest.config import ConfigError, parse_since, read_settings
from soc.ingest.errors import FAILURES

PROFILE = "elk-test"
EVENT_CP = (PROFILE, "event", "logs-web-*")
NOW = 1_793_800_000_000  # 고정한 "지금"(epoch ms)
HOUR = 3_600_000


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    fake = FakeStore()
    monkeypatch.setattr(run, "store", fake)
    monkeypatch.setattr(main_module, "store", fake)
    return fake


def checkpoint(time_ms: int) -> dict:
    return {
        "siem_profile": PROFILE,
        "source_kind": "event",
        "source_key": "logs-web-*",
        "cursor": {"time_ms": time_ms},
        "updated_at": time_ms,
    }


def run_with(fake: FakeElk, since_ms: int | None = None, **settings) -> list[run.SourceResult]:
    with fake.client() as client:
        return run.run(make_settings(**settings), None, client, since_ms=since_ms, now_ms=NOW)


def gte_of(fake: FakeElk) -> int:
    (body, *_) = fake.search_bodies()
    return body["query"]["range"]["@timestamp"]["gte"]


# --- --since 읽기 ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("30m", NOW - 30 * 60_000),
        ("24h", NOW - 24 * HOUR),
        ("7d", NOW - 7 * 24 * HOUR),
        ("2026-11-04T09:00:00Z", 1_793_782_800_000),
        ("2026-11-04T18:00:00+09:00", 1_793_782_800_000),
    ],
)
def test_parse_since_accepts_relative_and_aware_iso(text: str, expected: int) -> None:
    assert parse_since(text, now_ms=NOW) == expected


@pytest.mark.parametrize(
    "text",
    ["", "24", "h", "0h", "-1h", "1.5h", "24H x", "1w", "2026-11-04T09:00:00", "2026-11-04", "x"],
)
def test_parse_since_rejects_bad_values(text: str) -> None:
    with pytest.raises(ConfigError):
        parse_since(text, now_ms=NOW)


def test_parse_since_rejects_future_time() -> None:
    future = datetime.fromtimestamp(NOW / 1000 + 3600, UTC).isoformat()
    with pytest.raises(ConfigError):
        parse_since(future, now_ms=NOW)


# --- 시작 시각 규칙(표의 네 경우) ---


def test_first_run_uses_default_lookback(store: FakeStore) -> None:
    fake = FakeElk({"logs-web-*": ["elk_empty.json"]})
    run_with(fake, initial_lookback_seconds=3600)
    assert gte_of(fake) == NOW - HOUR


def test_first_run_with_since_uses_since(store: FakeStore) -> None:
    fake = FakeElk({"logs-web-*": ["elk_empty.json"]})
    run_with(fake, since_ms=NOW - 2 * HOUR, initial_lookback_seconds=3600)
    assert gte_of(fake) == NOW - 2 * HOUR


def test_checkpoint_is_read_back_by_overlap(store: FakeStore) -> None:
    store.checkpoints[EVENT_CP] = checkpoint(NOW - HOUR)
    fake = FakeElk({"logs-web-*": ["elk_empty.json"]})
    run_with(fake, overlap_seconds=60)
    assert gte_of(fake) == NOW - HOUR - 60_000


def test_since_before_checkpoint_goes_back(store: FakeStore) -> None:
    store.checkpoints[EVENT_CP] = checkpoint(NOW - HOUR)
    fake = FakeElk({"logs-web-*": ["elk_empty.json"]})
    run_with(fake, since_ms=NOW - 5 * HOUR, overlap_seconds=60)
    assert gte_of(fake) == NOW - 5 * HOUR


def test_since_after_checkpoint_is_ignored_so_no_gap(store: FakeStore) -> None:
    store.checkpoints[EVENT_CP] = checkpoint(NOW - 5 * HOUR)
    fake = FakeElk({"logs-web-*": ["elk_empty.json"]})
    run_with(fake, since_ms=NOW - HOUR, overlap_seconds=60)
    assert gte_of(fake) == NOW - 5 * HOUR - 60_000


def test_rereading_old_range_does_not_move_checkpoint_back(store: FakeStore) -> None:
    run_with(FakeElk({"logs-web-*": ["elk_events_page1.json", "elk_events_page2.json"]}))
    assert store.checkpoints[EVENT_CP]["cursor"] == {"time_ms": 1793754300000}
    before = len(store.records)

    # 더 이른 구간만 담은 응답(page1)을 다시 가져온다
    run_with(
        FakeElk({"logs-web-*": ["elk_events_page1.json", "elk_empty.json"]}), since_ms=1793750000000
    )

    assert store.checkpoints[EVENT_CP]["cursor"] == {"time_ms": 1793754300000}
    assert len(store.records) == before


# --- 반복 실행과 요약 ---


def test_second_run_stores_nothing_new_and_counts_skipped(store: FakeStore) -> None:
    pages = ["elk_events_page1.json", "elk_events_page2.json"]
    (first,) = run_with(FakeElk({"logs-web-*": list(pages)}))
    (second,) = run_with(FakeElk({"logs-web-*": list(pages)}))

    assert (first.fetched, first.inserted) == (3, 3)
    assert (second.fetched, second.inserted, second.quarantined) == (3, 0, 0)
    assert second.fetched - second.inserted - second.quarantined == 3  # 건너뜀
    assert len(store.records) == 3
    assert second.failure is None
    assert run.exit_code([first, second]) == 0


def test_partial_failure_keeps_committed_pages_and_other_sources(store: FakeStore) -> None:
    """한 소스가 중간에 실패해도 커밋된 페이지까지만 전진하고, 다른 소스는 수집한다(D-050)."""
    fake = FakeElk(
        {
            "logs-web-*": ["elk_events_page1.json", respond(401, {"e": "SECRET-BODY"})],
            ".alerts-security.alerts-default": ["elk_alerts_page1.json"],
        }
    )
    with fake.client() as client:
        events, alerts = run.run(make_settings(EVENTS, ALERTS), None, client, now_ms=NOW)

    assert (events.failure, events.pages, events.inserted) == ("auth", 1, 2)
    assert store.checkpoints[EVENT_CP]["cursor"] == {"time_ms": 1793754000000}
    assert (alerts.failure, alerts.inserted) == (None, 1)
    assert (PROFILE, "alert", ".alerts-security.alerts-default") in store.checkpoints
    assert run.exit_code([events, alerts]) == 1


def test_summary_lines_have_counts_range_time_and_reason_without_secrets(
    store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks = iter([NOW])  # 처음 한 번(시작)만 NOW, 이후(가져온 시각·끝)는 2.5초 뒤
    monkeypatch.setattr(run, "_now_ms", lambda: next(ticks, NOW + 2_500))
    (ok,) = run_with(FakeElk({"logs-web-*": ["elk_events_page1.json", "elk_empty.json"]}))
    lines = run.format_results([ok])

    assert lines == [
        "event:logs-web-*: 구간 2026-11-03T13:46:40Z ~ 2026-11-04T01:00:00Z, 가져옴 2, "
        "새로 저장 2, 건너뜀 0, 격리 0, 페이지 1, 2.5초, 실패 없음"
    ]


def test_failure_line_has_reason_and_no_secret(store: FakeStore) -> None:
    fake = FakeElk({"logs-web-*": [respond(401, {"e": "SECRET-BODY"})]})
    (bad,) = run_with(fake)
    (line,) = run.format_results([bad])
    assert "실패 auth" in line and "ELK_API_KEY" in line
    assert "구간 " in line and "~ -" in line  # 가져온 문서가 없으면 끝은 -
    for secret in ("SECRET-BODY", API_KEY, BASE_URL):
        assert secret not in line
    footer = run.format_footer([bad])
    assert footer[-1] == "결과 확인: DB의 ingest_runs 테이블(상태 조회 명령은 아직 없다)"
    assert footer[0].startswith("전체 소요 ")


def test_failure_reasons_differ_for_auth_network_and_tls() -> None:
    settings = make_settings()
    reasons = {kind: run.failure_reason(kind, settings) for kind in ("auth", "network", "tls")}
    assert len(set(reasons.values())) == 3
    assert "ELK_API_KEY" in reasons["auth"]
    assert "ca_cert_path" in reasons["tls"]
    assert all(run.failure_reason(kind, settings) for kind in FAILURES)


# --- 인증서 실패 구분(elk) ---


def test_certificate_failure_is_tls_and_not_retried() -> None:
    import ssl

    calls: list[str] = []

    def bad_cert(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        try:
            raise ssl.SSLCertVerificationError("certificate verify failed")
        except ssl.SSLCertVerificationError as cause:
            raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED]") from cause

    client = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(bad_cert))
    with client, pytest.raises(run.IngestError) as caught:
        list(elk.iter_pages(client, make_settings(), EVENTS, None, sleep=lambda _: None))
    assert caught.value.kind == "tls"
    assert calls == ["/logs-web-*/_pit"]  # 재시도하지 않는다


def test_plain_connection_failure_stays_network() -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(refused))
    with client, pytest.raises(run.IngestError) as caught:
        list(elk.iter_pages(client, make_settings(), EVENTS, None, sleep=lambda _: None))
    assert caught.value.kind == "network"


# --- 설정 ---


def default_table() -> dict:
    return {
        "siem_profile": PROFILE,
        "url_env": "ELK_URL",
        "api_key_env": "ELK_API_KEY",
        "page_size": 2,
        "connect_timeout_seconds": 5,
        "read_timeout_seconds": 5,
        "max_bytes": 1_000_000,
        "deadline_seconds": 30,
        "sources": [{"kind": "event", "key": "logs-web-*", "time_field": "@timestamp"}],
    }


def test_window_settings_have_defaults_and_are_validated() -> None:
    settings = read_settings(default_table())
    assert (settings.initial_lookback_seconds, settings.overlap_seconds) == (86_400, 60)
    ok = read_settings({**default_table(), "initial_lookback_seconds": 3600, "overlap_seconds": 0})
    assert (ok.initial_lookback_seconds, ok.overlap_seconds) == (3600, 0)
    for bad in (
        {"initial_lookback_seconds": 0},
        {"initial_lookback_seconds": "24h"},
        {"overlap_seconds": -1},
        {"overlap_seconds": True},
    ):
        with pytest.raises(ConfigError):
            read_settings({**default_table(), **bad})


# --- 명령 진입점: --since, 잠금 ---


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setenv("ELK_URL", BASE_URL)
    monkeypatch.setenv("ELK_API_KEY", API_KEY)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake-user:DB-SECRET@db.example.com/soc")
    monkeypatch.setattr(main_module, "load_config", lambda: {"ingest": default_table()})
    return monkeypatch


def wire(env: pytest.MonkeyPatch, fake: FakeElk) -> None:
    @contextlib.contextmanager
    def fake_connect(url: str, **kwargs):
        yield None

    make_client = elk.make_client

    def fake_client(settings, base_url: str, api_key: str) -> httpx.Client:
        with make_client(settings, base_url, api_key) as real:
            headers = real.headers
        return httpx.Client(base_url=base_url, headers=headers, transport=httpx.MockTransport(fake))

    env.setattr(main_module.psycopg, "connect", fake_connect)
    env.setattr(main_module.elk, "make_client", fake_client)


@pytest.mark.parametrize("bad", ["24", "2026-11-04T09:00:00", "0h"])
def test_bad_since_is_exit_2_without_connecting(
    env: pytest.MonkeyPatch, store: FakeStore, bad: str, capsys
) -> None:
    def must_not_connect(*args, **kwargs):
        raise AssertionError("설정 오류에서는 연결하지 않는다")

    env.setattr(main_module.psycopg, "connect", must_not_connect)
    assert main_module.main(["--since", bad]) == 2
    assert "--since" in capsys.readouterr().err


def test_second_instance_exits_3_and_writes_nothing(
    env: pytest.MonkeyPatch, store: FakeStore, capsys
) -> None:
    fake = FakeElk({"logs-web-*": ["elk_events_page2.json"]})
    wire(env, fake)
    store.lock_free = False

    assert main_module.main([]) == 3
    captured = capsys.readouterr()
    assert "다른 수집" in captured.err
    assert fake.requests == []  # ELK에 붙지 않았다
    assert store.records == {} and store.checkpoints == {} and store.runs == []
    for secret in (API_KEY, "DB-SECRET", BASE_URL):
        assert secret not in captured.out + captured.err


def test_main_prints_summary_footer_and_guide(
    env: pytest.MonkeyPatch, store: FakeStore, capsys
) -> None:
    wire(env, FakeElk({"logs-web-*": ["elk_events_page2.json"]}))
    assert main_module.main(["--since", "7d"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("event:logs-web-*: 구간 ")
    assert lines[-2].startswith("전체 소요 ")
    assert lines[-1].startswith("결과 확인:")
