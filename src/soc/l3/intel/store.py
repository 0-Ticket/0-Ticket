"""수집한 항목을 L3 테이블(0300_threat_intel.sql)에 쓴다. 호출하는 쪽이 출처마다 트랜잭션을 연다."""

from collections.abc import Iterable
from datetime import datetime

import psycopg

from soc.l3.intel.parse import NewsItem, Technique

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


def has_attack_version(conn: psycopg.Connection, version: str) -> bool:
    """한 버전은 트랜잭션 하나로 모두 넣으므로, 행이 있으면 그 버전을 다 받은 것이다."""
    row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM attack_techniques WHERE attack_version = %s)", (version,)
    ).fetchone()
    return bool(row and row[0])


def save_attack(conn: psycopg.Connection, version: str, techniques: list[Technique]) -> int:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO attack_techniques (attack_version, technique_id, name, tactics)"
            " VALUES (%s, %s, %s, %s)",
            [(version, t.technique_id, t.name, list(t.tactics)) for t in techniques],
        )
    return len(techniques)
