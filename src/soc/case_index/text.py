"""Case 색인 텍스트(#391, D-084). 라벨 붙은 줄을 정해진 순서로 합친다.

넣는 것: Case 제목·요약, 승인 당시 Artifact의 원인·영향·추가 위험, ATT&CK 기법 이름.
넣지 않는 것: 타임라인, 근거 ID, 엔티티 값, 권고 조치, 반려 이력, 기법 ID, Artifact 요약
(승인 때 Case 요약으로 복사된 같은 문장). 문장은 L2가 쓴 것이라 밖에서 온 문자열처럼 길이를 자르고
임베딩에만 쓴다.

상한은 임베더의 8192토큰 절단과 별도다. 임베더는 뒤를 조용히 자르므로, 앞 필드가 길어도 뒤 필드가
밀려나지 않게 필드마다 먼저 자른다. 값은 초안이다(docs/plans/391-case-index.md).
"""

from collections.abc import Mapping
from typing import Any

MAX_FIELD_CHARS = 1000
MAX_TECHNIQUES = 10
MAX_TEXT_CHARS = 4000

_ARTIFACT_FIELDS = ("cause", "impact", "further_risk")


def _clean(value: Any) -> str:
    """문자열이 아니면 빈 값. 공백을 한 칸으로 접고 필드 상한으로 자른다."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:MAX_FIELD_CHARS]


def case_text(title: str, summary: str | None, artifact: Mapping[str, Any] | None) -> str:
    """Case와 승인 당시 Artifact(없으면 None)로 색인 텍스트를 만든다. 빈 값은 줄을 생략한다."""
    lines: list[str] = []

    def add(label: str, value: Any) -> None:
        cleaned = _clean(value)
        if cleaned:
            lines.append(f"{label}: {cleaned}")

    add("title", title)
    add("summary", summary)
    if artifact is not None:
        for field in _ARTIFACT_FIELDS:
            add(field, artifact.get(field))
        names = [
            _clean(item.get("name"))
            for item in artifact.get("techniques") or []
            if isinstance(item, Mapping)
        ]
        for name in [name for name in names if name][:MAX_TECHNIQUES]:
            lines.append(f"technique: {name}")
    return "\n".join(lines)[:MAX_TEXT_CHARS]
