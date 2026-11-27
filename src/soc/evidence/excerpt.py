"""발급한 근거의 짧은 발췌(#382). L2 보고 모델이 `evt_` ID를 알고 인용하게 한다.

보고 태스크에는 도구를 주지 않는다(D-084). 그래서 발급한 근거의 ID와 핵심 필드를 입력에 실어
준다. 새로 발급한 근거와 이미 발급돼 재사용한 근거가 같은 경로(DB에 저장된 원문)를 읽으므로
내용이 같다. 발췌는 로그에서 온 문자열이다 — 모델은 데이터로만 읽는다(`docs/security.md`).

발췌 필드는 심 조회 대상 `evidence`의 반환 필드(`TARGET_FIELDS["evidence"]`)다. 소스 고유 칸
(예: 수리카타 시그니처)은 없다. 그것은 `get_raw`로 읽는 원문에만 있다.
"""

import json
from collections.abc import Callable
from datetime import UTC
from typing import Any

import psycopg

from soc.tools.siem import _MISSING, TARGET_FIELDS, _lookup  # 점 경로 읽기를 query_siem과 같게 쓴다

MAX_ITEMS = 20
# 값 하나의 글자 수(잘린 표시 포함). 긴 문자열이 흔한 필드만 300자다
MAX_VALUE_CHARS = 120
MAX_LONG_VALUE_CHARS = 300
LONG_FIELDS = frozenset({"url.path", "url.query", "message", "user_agent.original"})
# 발췌가 입력에 더하는 길이(실제 직렬화와 필터를 거친 길이)의 상한
MAX_TOTAL_CHARS = 24_000
# 남은 예산에서 더 떼어 두는 여유. 형식 오류 재요청이 앞선 답을 입력에 더하고 입력 필터가 값을
# 늘릴 수 있다. 첫 답이 이보다 크면 재요청에서 budget_exceeded가 날 수 있다
RESERVE_CHARS = 8_000
CUT_MARK = "…"


def _clip(path: str, value: Any) -> tuple[Any, bool]:
    """(값, 잘렸는지). 문자열이 아닌 목록·객체는 JSON 글자로 바꾼 뒤 자른다."""
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False)
    if not isinstance(value, str):
        return value, False
    limit = MAX_LONG_VALUE_CHARS if path in LONG_FIELDS else MAX_VALUE_CHARS
    if len(value) <= limit:
        return value, False
    return value[: limit - len(CUT_MARK)] + CUT_MARK, True


def _fields(original_text: str) -> tuple[dict[str, Any], list[str]]:
    try:
        source = json.loads(original_text).get("_source")
    except (ValueError, AttributeError):
        return {}, []
    picked: dict[str, Any] = {}
    cut: list[str] = []
    for path in TARGET_FIELDS["evidence"]:
        value = _lookup(source, path.split("."))
        if value is _MISSING or value is None:
            continue
        picked[path], was_cut = _clip(path, value)
        if was_cut:
            cut.append(path)
    return picked, cut


def evidence_excerpts(conn: psycopg.Connection, evidence_ids: list[str]) -> list[dict[str, Any]]:
    """발급한 근거마다 {evidence_id, siem_ref, time, fields}. 입력 순서를 지킨다.

    저장된 원문을 읽으므로 새 발급과 재사용이 같다. DB에 없는 ID는 건너뛴다. 자른 필드는
    `truncated_fields`에 경로만 적는다.
    """
    if not evidence_ids:
        return []
    rows = conn.execute(
        "SELECT e.id, r.siem_ref, e.time, r.original_text FROM events e"
        " JOIN raw_records r ON r.id = e.raw_id WHERE e.id = ANY(%s)",
        (evidence_ids,),
    ).fetchall()
    by_id = {row[0]: row for row in rows}
    items: list[dict[str, Any]] = []
    for evidence_id in dict.fromkeys(evidence_ids):
        row = by_id.get(evidence_id)
        if row is None:
            continue
        fields, cut = _fields(row[3])
        item: dict[str, Any] = {
            "evidence_id": row[0],
            "siem_ref": row[1],
            "time": row[2].astimezone(UTC).isoformat(),
            "fields": fields,
        }
        if cut:
            item["truncated_fields"] = cut
        items.append(item)
    return items


def fit_to_budget[T](
    excerpts: list[dict[str, Any]],
    build: Callable[[list[dict[str, Any]]], T],
    measure: Callable[[T], tuple[int, int]],
) -> T:
    """입력 예산에 들어가는 만큼의 앞쪽 발췌로 태스크를 만든다.

    `build(items)`는 그 발췌를 실어 태스크를 만들고(뺀 수는 호출한 쪽이 `len(excerpts)`로
    알린다), `measure(task)`는 (첫 호출 입력 글자 수, max_input_chars)다. 발췌가 더하는 길이는
    MAX_TOTAL_CHARS와 `남은 예산 - RESERVE_CHARS` 중 작은 값을 넘지 않는다. 한 건을 중간에서
    자르지 않는다. 남은 예산이 없으면 발췌 없이 만든다. 발췌 없이도 한도를 넘으면 그대로 두고
    기존대로 run이 budget_exceeded가 된다.
    """
    best = build([])
    if not excerpts:
        return best
    base, limit = measure(best)
    allowed = min(MAX_TOTAL_CHARS, limit - base - RESERVE_CHARS)
    for count in range(1, min(len(excerpts), MAX_ITEMS) + 1):
        candidate = build(excerpts[:count])
        if measure(candidate)[0] - base > allowed:
            break
        best = candidate
    return best
