"""수집한 항목을 L3 테이블(0300_threat_intel.sql)에 쓴다. 호출하는 쪽이 출처마다 트랜잭션을 연다."""

from collections.abc import Iterable
from datetime import datetime

import psycopg

from soc.l3.intel.parse import KevCatalog, NewsItem, Technique

# 처음 보는 항목은 넣고, 이미 있으면 제목·요약·링크·발행 시각 중 하나라도 다를 때만 갱신한다.
# 넣거나 갱신한 행만 돌아온다. xmax = 0이면 이번에 넣은 행이다(갱신한 행은 xmax가 0이 아니다).
_UPSERT_NEWS = """
INSERT INTO threat_news AS t
    (source, kind, source_ref, title, summary, link, published_at, fetched_at, updated_at)
VALUES (%(source)s, %(kind)s, %(source_ref)s, %(title)s, %(summary)s, %(link)s, %(published_at)s,
        %(now)s, %(now)s)
ON CONFLICT (source, source_ref) DO UPDATE SET
    title = EXCLUDED.title,
    summary = EXCLUDED.summary,
    link = EXCLUDED.link,
    published_at = EXCLUDED.published_at,
    updated_at = EXCLUDED.updated_at
WHERE (t.title, t.summary, t.link, t.published_at)
    IS DISTINCT FROM (EXCLUDED.title, EXCLUDED.summary, EXCLUDED.link, EXCLUDED.published_at)
RETURNING (t.xmax = 0) AS inserted
"""


def save_news(
    conn: psycopg.Connection,
    *,
    source: str,
    kind: str,
    items: Iterable[NewsItem],
    now: datetime,
) -> tuple[int, int]:
    """(새로 저장한 건수, 갱신한 건수)."""
    inserted = updated = 0
    for item in items:
        row = conn.execute(
            _UPSERT_NEWS,
            {
                "source": source,
                "kind": kind,
                "source_ref": item.source_ref,
                "title": item.title,
                "summary": item.summary,
                "link": item.link,
                "published_at": item.published_at,
                "now": now,
            },
        ).fetchone()
        if row is None:
            continue
        if row[0]:
            inserted += 1
        else:
            updated += 1
    return inserted, updated


_UPSERT_KEV = """
INSERT INTO kev_entries AS k
    (cve_id, vulnerability_name, short_description, vendor_project, product, date_added,
     due_date, known_ransomware_use, required_action, updated_at)
VALUES (%(cve_id)s, %(vulnerability_name)s, %(short_description)s, %(vendor_project)s,
        %(product)s, %(date_added)s, %(due_date)s, %(known_ransomware_use)s,
        %(required_action)s, %(now)s)
ON CONFLICT (cve_id) DO UPDATE SET
    vulnerability_name = EXCLUDED.vulnerability_name,
    short_description = EXCLUDED.short_description,
    vendor_project = EXCLUDED.vendor_project,
    product = EXCLUDED.product,
    date_added = EXCLUDED.date_added,
    due_date = EXCLUDED.due_date,
    known_ransomware_use = EXCLUDED.known_ransomware_use,
    required_action = EXCLUDED.required_action,
    updated_at = EXCLUDED.updated_at
WHERE (k.vulnerability_name, k.short_description, k.vendor_project, k.product, k.date_added,
       k.due_date, k.known_ransomware_use, k.required_action)
    IS DISTINCT FROM (EXCLUDED.vulnerability_name, EXCLUDED.short_description,
       EXCLUDED.vendor_project, EXCLUDED.product, EXCLUDED.date_added, EXCLUDED.due_date,
       EXCLUDED.known_ransomware_use, EXCLUDED.required_action)
"""

_UPSERT_STATE = """
INSERT INTO intel_source_state (source, catalog_version, released_at, collected_at)
VALUES (%(source)s, %(catalog_version)s, %(released_at)s, %(now)s)
ON CONFLICT (source) DO UPDATE SET
    catalog_version = EXCLUDED.catalog_version,
    released_at = EXCLUDED.released_at,
    collected_at = EXCLUDED.collected_at
"""


def save_kev(conn: psycopg.Connection, *, source: str, catalog: KevCatalog, now: datetime) -> None:
    """KEV 항목 상세(바뀐 것만 갱신)와 이 출처의 마지막 성공 수집을 쓴다(#311).

    카탈로그에서 빠진 CVE는 지우지 않는다.
    """
    for entry in catalog.entries:
        conn.execute(
            _UPSERT_KEV,
            {
                "cve_id": entry.cve_id,
                "vulnerability_name": entry.vulnerability_name,
                "short_description": entry.short_description,
                "vendor_project": entry.vendor_project,
                "product": entry.product,
                "date_added": entry.date_added,
                "due_date": entry.due_date,
                "known_ransomware_use": entry.known_ransomware_use,
                "required_action": entry.required_action,
                "now": now,
            },
        )
    conn.execute(
        _UPSERT_STATE,
        {
            "source": source,
            "catalog_version": catalog.catalog_version,
            "released_at": catalog.released_at,
            "now": now,
        },
    )


def has_attack_version(conn: psycopg.Connection, version: str) -> bool:
    """한 버전은 트랜잭션 하나로 모두 넣으므로, 채워 넣은 행이 있으면 그 버전을 다 받은 것이다.

    collected_at이 NULL인 행은 설명·탐지 데이터 소스 열이 생기기 전(0301 이전)에 저장한 것이라
    버전이 있어도 다시 받는다(#311).
    """
    row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM attack_techniques"
        " WHERE attack_version = %s AND collected_at IS NOT NULL)",
        (version,),
    ).fetchone()
    return bool(row and row[0])


_UPSERT_TECHNIQUE = """
INSERT INTO attack_techniques AS t
    (attack_version, technique_id, name, tactics, description, detection_sources, collected_at)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (attack_version, technique_id) DO UPDATE SET
    name = EXCLUDED.name,
    tactics = EXCLUDED.tactics,
    description = EXCLUDED.description,
    detection_sources = EXCLUDED.detection_sources,
    collected_at = EXCLUDED.collected_at
RETURNING (t.xmax = 0) AS inserted
"""


def save_attack(
    conn: psycopg.Connection, version: str, techniques: list[Technique], *, now: datetime
) -> tuple[int, int]:
    """(새로 저장한 건수, 이미 있어서 채워 넣은 건수)."""
    inserted = updated = 0
    for t in techniques:
        row = conn.execute(
            _UPSERT_TECHNIQUE,
            (
                version,
                t.technique_id,
                t.name,
                list(t.tactics),
                t.description,
                list(t.detection_sources),
                now,
            ),
        ).fetchone()
        if row is not None and row[0]:
            inserted += 1
        else:
            updated += 1
    return inserted, updated
