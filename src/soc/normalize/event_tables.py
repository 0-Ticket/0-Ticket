"""이벤트 요약 정의(`mapping_tables/events/<클래스 번호>.yaml`)를 읽고 요약 문장을 만든다(D-068).

파일 하나는 클래스 하나의 `summary`를 가진다. `summary`는 OCSF 경로의 목록이고, 목록의 한 칸은
경로 하나이거나 대안 경로 목록이다(앞에서부터 처음 값이 있는 것을 쓴다). 값이 있는 칸을 공백으로
이어 1순위 요약을 만든다. 알럿 매핑표 로더(`tables.py`)는 이 폴더를 읽지 않는다. 이벤트 매핑표
이슈가 같은 파일에 `entries`·`entities`를 더한다.
"""

import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from soc.normalize.ocsf_schema import field_definition, has_class_definition
from soc.normalize.paths import read_value
from soc.normalize.tables import TABLE_DIR, MappingTableError

EVENT_TABLE_DIR = TABLE_DIR / "events"
# 요약 정의를 두는 클래스. 저장한 이벤트 클래스(D-067)에서 2004를 뺀 것이다
EVENT_CLASSES = (0, 2003, 3002, 4001, 4002, 4003, 6003)
_KEYS = {"class_uid", "summary"}


@dataclass(frozen=True)
class EventSummary:
    """한 클래스의 요약 정의.

    Attributes:
        class_uid: OCSF 클래스 번호.
        parts: 칸 목록. 칸 하나는 대안 OCSF 경로 튜플이고 앞에서부터 처음 값이 있는 것을 쓴다.
    """

    class_uid: int
    parts: tuple[tuple[str, ...], ...]


def load_event_summaries(directory: Path | None = None) -> dict[int, EventSummary]:
    """폴더의 모든 *.yaml을 읽어 클래스 번호별 요약 정의를 돌려준다. 같은 폴더는 한 번만 읽는다.

    Args:
        directory: 이벤트 표 폴더. 없으면 mapping_tables/events/.

    Raises:
        MappingTableError: 형식이 틀렸거나 파일 이름이 `class_uid`와 다르다.
    """
    return _load(directory or EVENT_TABLE_DIR)


@cache
def _load(directory: Path) -> dict[int, EventSummary]:
    summaries: dict[int, EventSummary] = {}
    for path in sorted(directory.glob("*.yaml")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            summary = _parse(path.stem, document)
        except (yaml.YAMLError, UnicodeDecodeError) as error:
            raise MappingTableError(
                f"{path.name}: YAML을 읽을 수 없다 ({type(error).__name__})"
            ) from None
        except MappingTableError as error:
            raise MappingTableError(f"{path.name}: {error}") from None
        summaries[summary.class_uid] = summary
    return summaries


def _parse(stem: str, document: Any) -> EventSummary:
    if not isinstance(document, dict):
        raise MappingTableError("최상위가 객체여야 한다")
    unknown = set(document) - _KEYS
    if unknown:
        raise MappingTableError("알 수 없는 키: " + ", ".join(sorted(map(str, unknown))))
    class_uid = document.get("class_uid")
    if type(class_uid) is not int or str(class_uid) != stem:
        raise MappingTableError("class_uid는 파일 이름과 같은 정수여야 한다")
    cells = document.get("summary")
    if not isinstance(cells, list) or not cells:
        raise MappingTableError("summary는 비어 있지 않은 목록이어야 한다")
    parts = []
    for cell in cells:
        alternatives = (cell,) if isinstance(cell, str) else tuple(cell) if _is_list(cell) else ()
        if not alternatives or not all(isinstance(path, str) and path for path in alternatives):
            raise MappingTableError("summary 칸은 경로 문자열 또는 그 목록이어야 한다")
        parts.append(alternatives)
    return EventSummary(class_uid, tuple(parts))


def _is_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def check_event_summaries(summaries: dict[int, EventSummary]) -> list[str]:
    """요약 경로가 클래스 정의에 있는지, 저장한 클래스를 모두 덮는지 본다.

    Args:
        summaries: load_event_summaries의 결과.

    Returns:
        "종류 [클래스] 경로" 꼴의 문제 문장들. 비어 있으면 통과다.
    """
    problems = []
    for class_uid in EVENT_CLASSES:
        if class_uid not in summaries:
            problems.append(f"missing_class [{class_uid}]")
    for class_uid, summary in sorted(summaries.items()):
        if class_uid not in EVENT_CLASSES or not has_class_definition(class_uid):
            problems.append(f"unknown_class [{class_uid}]")
            continue
        for alternatives in summary.parts:
            for path in alternatives:
                if field_definition(class_uid, path) is None:
                    problems.append(f"unknown_path [{class_uid}] {path}")
    return problems


def _text(value: Any) -> str | None:
    """요약에 넣을 글자. 공백이 아닌 문자열, 정수, 유한한 실수만 쓰고 그 밖은 None이다.

    정수와 값이 정수인 실수(404.0)는 소수점 없이 쓴다. bool·목록·객체·NaN·무한대는 쓰지 않는다.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, str) and value.strip():
        return value
    return None


def summary_text(class_uid: int, ocsf: dict[str, Any]) -> str | None:
    """OCSF 문서에서 클래스의 1순위 요약을 만든다. 값이 하나도 없으면 None이다.

    Args:
        class_uid: OCSF 클래스 번호.
        ocsf: 이벤트의 OCSF 문서(message 없이도 된다).
    """
    summary = load_event_summaries().get(class_uid)
    if summary is None:
        return None
    texts = []
    for alternatives in summary.parts:
        for path in alternatives:
            text = _text(read_value(ocsf, path))
            if text is not None:
                texts.append(text)
                break
    return " ".join(texts) or None
