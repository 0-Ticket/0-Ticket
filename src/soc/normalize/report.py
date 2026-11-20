"""소스별 정규화 채움률 점검(#326, #351). normalize_status만 읽고 건수만 낸다(원문 없음)."""

import psycopg

KINDS = ("alert", "event")
_OUTCOMES = """
SELECT source, outcome, count(*) FROM normalize_status
WHERE status = 'succeeded' AND result_kind = %s AND outcome IS NOT NULL
GROUP BY source, outcome ORDER BY source, outcome
"""
_MISSING = """
SELECT s.source, f.field, count(*) FROM normalize_status s, unnest(s.missing_fields) AS f(field)
WHERE s.status = 'succeeded' AND s.result_kind = %s AND s.outcome IS NOT NULL
GROUP BY s.source, f.field ORDER BY s.source, f.field
"""


def report_lines(conn: psycopg.Connection, kind: str = "alert") -> list[str]:
    """소스별 총 건수·outcome별 건수와 얻지 못한 필드별 건수를 줄로 돌려준다.

    result_kind가 kind인 성공 행 중 품질이 기록된 행만 센다. 기록 전 행(outcome이 NULL)은 빠진다.

    Args:
        conn: DB 연결.
        kind: 집계할 결과 종류. "alert"(기본) 또는 "event".

    Raises:
        ValueError: kind가 틀렸다.
    """
    if kind not in KINDS:
        raise ValueError("보고서 종류가 맞지 않는다")
    counts: dict[str, dict[str, int]] = {}
    for source, outcome, number in conn.execute(_OUTCOMES, (kind,)).fetchall():
        counts.setdefault(source, {})[outcome] = number
    gaps = conn.execute(_MISSING, (kind,)).fetchall()
    lines = []
    for source, by_outcome in counts.items():
        total = sum(by_outcome.values())
        parts = " ".join(f"{o}={by_outcome.get(o, 0)}" for o in ("ok", "partial", "fallback"))
        lines.append(f"{source} total={total} {parts}")
        lines.extend(
            f"{source} missing {field}={number}/{total}"
            for found, field, number in gaps
            if found == source
        )
    return lines or [f"기록된 {'Alert' if kind == 'alert' else 'Event'} 정규화 결과가 없다"]
