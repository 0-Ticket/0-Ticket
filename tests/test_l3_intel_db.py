"""L3 수집 계층의 저장을 실제 PostgreSQL로 확인한다(#221, db 마커)."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import psycopg
import pytest

from soc.db.migrate import migrate
from soc.l3.intel.collect import collect, exit_code, format_results, read_settings

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).parent / "fixtures" / "l3_intel"
NOW = datetime(2026, 11, 4, 6, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)

BOANNEWS = "https://feeds.example.com/boannews.xml"
THN = "https://feeds.example.com/thn.xml"
KEV = "https://feeds.example.com/kev.json"
ATTACK = "https://attack.example.com/enterprise-attack-20.0.json"


def l3_config(*, version: str = "20.0", attack_url: str = ATTACK) -> dict:
    return {
        "intel": {
            "summary_max_chars": 1000,
            "connect_timeout_seconds": 10,
            "read_timeout_seconds": 10,
            "limits": {
                "rss": {"max_bytes": 5_000, "deadline_seconds": 30},
                "cisa_kev": {"max_bytes": 10_000, "deadline_seconds": 30},
            },
            "sources": [
                {"name": "boannews", "kind": "rss", "url": BOANNEWS},
                {"name": "thehackernews", "kind": "rss", "url": THN},
                {"name": "cisa_kev", "kind": "cisa_kev", "url": KEV},
            ],
            "attack": {
                "version": version,
                "url": attack_url,
                "max_bytes": 100_000,
                "deadline_seconds": 180,
            },
        }
    }


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeWeb:
    """URL → 응답. 받은 요청 URL을 requested에 남긴다."""

    def __init__(self, responses: dict[str, httpx.Response | bytes]) -> None:
        self.responses = responses
        self.requested: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requested.append(url)
        answer = self.responses[url]
        if isinstance(answer, bytes):
            return httpx.Response(200, content=answer)
        return answer

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def all_sources() -> dict[str, httpx.Response | bytes]:
    return {
        BOANNEWS: fixture("boannews_rss.xml"),
        THN: fixture("thn_rss.xml"),
        KEV: fixture("kev.json"),
        ATTACK: fixture("attack.json"),
    }


@pytest.fixture
def conn(temp_database: str) -> Iterator[psycopg.Connection]:
    migrate(temp_database)
    with psycopg.connect(temp_database, autocommit=True) as connection:
        yield connection


def run(conn: psycopg.Connection, web: FakeWeb, *, now: datetime = NOW, **config):
    settings = read_settings(l3_config(**config))
    with web.client() as client:
        return {r.name: r for r in collect(settings, conn, client, now=now)}


def counts(result) -> tuple[int, int, int, str | None]:
    return (result.fetched, result.inserted, result.updated, result.failure)


def news_rows(conn: psycopg.Connection) -> dict[tuple[str, str], dict]:
    cur = conn.execute(
        "SELECT id, source, kind, source_ref, title, summary, link, published_at,"
        " fetched_at, updated_at FROM threat_news"
    )
    names = [c.name for c in cur.description]
    rows = [dict(zip(names, row, strict=True)) for row in cur.fetchall()]
    return {(r["source"], r["source_ref"]): r for r in rows}


def test_collect_saves_all_sources(conn: psycopg.Connection) -> None:
    results = run(conn, FakeWeb(all_sources()))
    assert {name: counts(r) for name, r in results.items()} == {
        "boannews": (2, 2, 0, None),
        "thehackernews": (3, 3, 0, None),
        "cisa_kev": (3, 3, 0, None),
        "attack": (2, 2, 0, None),
    }
    rows = news_rows(conn)
    assert len(rows) == 8
    kev = rows[("cisa_kev", "CVE-2026-0001")]
    assert kev["kind"] == "cisa_kev"
    assert kev["link"] is None
    assert kev["published_at"] == datetime(2026, 11, 3, tzinfo=UTC)
    assert kev["fetched_at"] == kev["updated_at"] == NOW
    assert (
        rows[("thehackernews", "https://hn.example.com/2026/11/no-guid.html")]["published_at"]
        is None
    )
    techniques = conn.execute(
        "SELECT attack_version, technique_id, name, tactics FROM attack_techniques"
        " ORDER BY technique_id"
    ).fetchall()
    assert techniques == [
        ("20.0", "T1059.004", "Unix Shell", ["execution"]),
        ("20.0", "T1190", "Exploit Public-Facing Application", ["initial-access"]),
    ]


def test_same_items_twice_are_stored_once(conn: psycopg.Connection) -> None:
    run(conn, FakeWeb(all_sources()))
    before = news_rows(conn)
    results = run(conn, FakeWeb(all_sources()), now=LATER)
    assert {name: counts(r) for name, r in results.items() if name != "attack"} == {
        "boannews": (2, 0, 0, None),
        "thehackernews": (3, 0, 0, None),
        "cisa_kev": (3, 0, 0, None),
    }
    assert news_rows(conn) == before  # updated_at도 그대로다


def test_changed_item_is_updated(conn: psycopg.Connection) -> None:
    run(conn, FakeWeb(all_sources()))
    before = news_rows(conn)[("cisa_kev", "CVE-2026-0001")]

    kev = json.loads(fixture("kev.json"))
    kev["vulnerabilities"][0]["vulnerabilityName"] = "Example VPN Command Injection Vulnerability"
    sources = all_sources() | {KEV: json.dumps(kev).encode()}
    results = run(conn, FakeWeb(sources), now=LATER)

    assert counts(results["cisa_kev"]) == (3, 0, 1, None)
    after = news_rows(conn)[("cisa_kev", "CVE-2026-0001")]
    assert after["title"] == "Example VPN Command Injection Vulnerability"
    assert after["id"] == before["id"]
    assert after["fetched_at"] == NOW
    assert after["updated_at"] == LATER


def test_failed_sources_are_skipped_and_others_saved(conn: psycopg.Connection) -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(100):
            yield b"x" * 100

    web = FakeWeb(
        {
            BOANNEWS: httpx.Response(200, content=chunks()),  # 5,000바이트 상한 초과
            THN: fixture("broken_rss.xml"),
            KEV: fixture("kev.json"),
            ATTACK: fixture("attack.json"),
        }
    )
    results = run(conn, web)
    assert results["boannews"].failure == "too_large"
    assert results["thehackernews"].failure == "parse"
    assert counts(results["cisa_kev"]) == (3, 3, 0, None)
    assert counts(results["attack"]) == (2, 2, 0, None)
    assert exit_code(list(results.values())) == 1

    web.responses[BOANNEWS] = fixture("boannews_rss.xml")
    web.responses[THN] = fixture("doctype_rss.xml")
    web.responses[KEV] = httpx.Response(503)
    results = run(conn, web)
    assert results["thehackernews"].failure == "doctype"
    assert results["cisa_kev"].failure == "http_status"
    assert counts(results["boannews"]) == (2, 2, 0, None)


def test_timeout_source_is_skipped(conn: psycopg.Connection) -> None:
    web = FakeWeb(all_sources())
    original = web.handler

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == THN:
            raise httpx.ReadTimeout("slow", request=request)
        return original(request)

    web.handler = handler
    results = run(conn, web)
    assert results["thehackernews"].failure == "timeout"
    assert counts(results["boannews"]) == (2, 2, 0, None)
    assert exit_code(list(results.values())) == 1


def test_output_has_counts_only(conn: psycopg.Connection) -> None:
    results = list(run(conn, FakeWeb(all_sources() | {THN: fixture("broken_rss.xml")})).values())
    lines = format_results(results)
    assert lines == [
        "boannews: 가져옴 2, 새로 저장 2, 갱신 0, 실패 없음",
        "thehackernews: 가져옴 0, 새로 저장 0, 갱신 0, 실패 parse",
        "cisa_kev: 가져옴 3, 새로 저장 3, 갱신 0, 실패 없음",
        "attack: 가져옴 2, 새로 저장 2, 갱신 0, 실패 없음",
    ]
    assert exit_code(results) == 1
    assert exit_code(list(run(conn, FakeWeb(all_sources())).values())) == 0


def test_same_attack_version_is_not_downloaded_again(conn: psycopg.Connection) -> None:
    run(conn, FakeWeb(all_sources()))
    web = FakeWeb(all_sources())
    results = run(conn, web)
    assert ATTACK not in web.requested
    assert results["attack"].skipped
    assert format_results([results["attack"]]) == ["attack: 버전 20.0이 이미 있어 건너뜀"]


def test_new_attack_version_is_added_next_to_old(conn: psycopg.Connection) -> None:
    run(conn, FakeWeb(all_sources()))
    bundle = json.loads(fixture("attack.json"))
    bundle["objects"][0]["x_mitre_version"] = "20.1"
    bundle["objects"][1]["name"] = "Exploit Public-Facing Application (renamed)"
    url = "https://attack.example.com/enterprise-attack-20.1.json"
    web = FakeWeb(all_sources() | {url: json.dumps(bundle).encode()})
    results = run(conn, web, version="20.1", attack_url=url)
    assert counts(results["attack"]) == (2, 2, 0, None)
    rows = conn.execute(
        "SELECT attack_version, name FROM attack_techniques WHERE technique_id = 'T1190'"
        " ORDER BY attack_version"
    ).fetchall()
    assert rows == [
        ("20.0", "Exploit Public-Facing Application"),
        ("20.1", "Exploit Public-Facing Application (renamed)"),
    ]


def test_attack_version_mismatch_saves_nothing(conn: psycopg.Connection) -> None:
    results = run(conn, FakeWeb(all_sources()), version="19.2")
    assert results["attack"].failure == "version_mismatch"
    assert conn.execute("SELECT count(*) FROM attack_techniques").fetchone() == (0,)


@pytest.mark.parametrize(
    ("table", "values"),
    [
        ("threat_news", {"kind": "atom"}),
        ("threat_news", {"source": ""}),
        ("threat_news", {"source_ref": ""}),
        ("threat_news", {"title": ""}),
        ("attack_techniques", {"technique_id": "T190"}),
        ("attack_techniques", {"technique_id": "T1190\n"}),
        ("attack_techniques", {"tactics": ["execution", None]}),
        ("attack_techniques", {"attack_version": ""}),
        ("attack_techniques", {"name": ""}),
    ],
)
def test_checks_reject_broken_rows(conn: psycopg.Connection, table: str, values: dict) -> None:
    base = {
        "threat_news": {
            "source": "s",
            "kind": "rss",
            "source_ref": "r",
            "title": "t",
            "summary": "",
            "fetched_at": NOW,
            "updated_at": NOW,
        },
        "attack_techniques": {
            "attack_version": "20.0",
            "technique_id": "T1190",
            "name": "n",
            "tactics": ["initial-access"],
        },
    }[table]
    row = base | values
    columns = ", ".join(row)
    placeholders = ", ".join(["%s"] * len(row))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", list(row.values()))


def test_news_id_cannot_be_set_by_hand(conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.GeneratedAlways):
        conn.execute(
            "INSERT INTO threat_news (id, source, kind, source_ref, title, summary, fetched_at,"
            " updated_at) VALUES (1, 's', 'rss', 'r', 't', '', now(), now())"
        )


# --- 로컬 조회 도구용 저장(#311) ---


def attack_detail(conn: psycopg.Connection) -> dict[str, tuple]:
    rows = conn.execute(
        "SELECT technique_id, description, detection_sources, collected_at FROM attack_techniques"
        " ORDER BY technique_id"
    ).fetchall()
    return {r[0]: r[1:] for r in rows}


def kev_rows(conn: psycopg.Connection) -> dict[str, tuple]:
    rows = conn.execute(
        "SELECT cve_id, vulnerability_name, vendor_project, product, date_added, due_date,"
        " known_ransomware_use, required_action, updated_at FROM kev_entries ORDER BY cve_id"
    ).fetchall()
    return {r[0]: r[1:] for r in rows}


def test_collect_saves_attack_and_kev_detail(conn: psycopg.Connection) -> None:
    run(conn, FakeWeb(all_sources()))

    detail = attack_detail(conn)
    assert detail["T1190"] == (
        "Adversaries may attack a public-facing application. (Citation: Example) Second paragraph.",
        ["Application Log Content", "Network Traffic Content"],
        NOW,
    )
    assert detail["T1059.004"][1:] == (["Command Execution"], NOW)
    kev = kev_rows(conn)
    assert list(kev) == ["CVE-2026-0001", "CVE-2026-0002", "CVE-2026-0003"]
    assert kev["CVE-2026-0001"] == (
        "Example VPN Remote Code Execution Vulnerability",
        "Example",
        "Example VPN",
        datetime(2026, 11, 3).date(),
        datetime(2026, 11, 24).date(),
        "Unknown",
        "Apply mitigations per vendor instructions.",
        NOW,
    )
    assert conn.execute(
        "SELECT source, catalog_version, released_at, collected_at FROM intel_source_state"
    ).fetchall() == [
        ("cisa_kev", "2026.11.03", datetime(2026, 11, 3, 20, 0, 24, 874100, tzinfo=UTC), NOW)
    ]


def test_second_collect_keeps_detail_and_moves_collected_time(conn: psycopg.Connection) -> None:
    run(conn, FakeWeb(all_sources()))
    before = kev_rows(conn)
    run(conn, FakeWeb(all_sources()), now=LATER)

    assert kev_rows(conn) == before  # updated_at도 그대로다
    assert conn.execute("SELECT collected_at FROM intel_source_state").fetchall() == [(LATER,)]


def test_changed_kev_detail_updates_only_that_row(conn: psycopg.Connection) -> None:
    run(conn, FakeWeb(all_sources()))
    before = kev_rows(conn)
    kev = json.loads(fixture("kev.json"))
    kev["vulnerabilities"][1]["knownRansomwareCampaignUse"] = "Unknown"
    run(conn, FakeWeb(all_sources() | {KEV: json.dumps(kev).encode()}), now=LATER)

    after = kev_rows(conn)
    assert after["CVE-2026-0001"] == before["CVE-2026-0001"]
    assert after["CVE-2026-0002"][5] == "Unknown"
    assert after["CVE-2026-0002"][-1] == LATER


def test_failed_kev_parse_leaves_kev_detail_and_state_untouched(conn: psycopg.Connection) -> None:
    run(conn, FakeWeb(all_sources()))
    before = kev_rows(conn)
    bad = json.loads(fixture("kev.json"))
    del bad["vulnerabilities"][1]["requiredAction"]
    results = run(conn, FakeWeb(all_sources() | {KEV: json.dumps(bad).encode()}), now=LATER)

    assert results["cisa_kev"].failure == "parse"
    assert kev_rows(conn) == before
    assert conn.execute("SELECT collected_at FROM intel_source_state").fetchall() == [(NOW,)]


def test_stored_attack_version_without_detail_is_downloaded_again(
    conn: psycopg.Connection,
) -> None:
    run(conn, FakeWeb(all_sources()))
    # 0301 전에 저장한 행처럼 새 열을 비운다
    conn.execute("UPDATE attack_techniques SET description = NULL, detection_sources = NULL")
    conn.execute("UPDATE attack_techniques SET collected_at = NULL")
    web = FakeWeb(all_sources())

    results = run(conn, web, now=LATER)

    assert ATTACK in web.requested
    assert counts(results["attack"]) == (2, 0, 2, None)
    detail = attack_detail(conn)
    assert detail["T1190"][2] == LATER
    assert detail["T1190"][1] == ["Application Log Content", "Network Traffic Content"]
    assert conn.execute("SELECT count(*) FROM attack_techniques").fetchone() == (2,)


def test_kev_entries_check_rejects_broken_rows(conn: psycopg.Connection) -> None:
    insert = (
        "INSERT INTO kev_entries (cve_id, vulnerability_name, short_description, vendor_project,"
        " product, date_added, known_ransomware_use, required_action, updated_at)"
        " VALUES (%s, %s, '', '', '', '2026-11-03', 'Unknown', '', now())"
    )
    for cve_id, name in (("CVE-2026-0009\n", "x"), ("CVE-26-1", "x"), ("CVE-2026-0009", "")):
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(insert, (cve_id, name))
