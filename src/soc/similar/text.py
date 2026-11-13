"""유사 사례 검색에 쓰는 Ticket 텍스트(#313, D-053).

색인할 때와 질의할 때 같은 종류의 텍스트가 되도록 Alert 제목만 쓴다. 판정 이유(`verdict.reason`)는
넣지 않는다. 질의 쪽에는 이유가 없고, LLM이 쓴 문장이 검색 순위를 좌우하지 않게 하려는 것이다.
Event 요약도 넣지 않는다. 판정 전 Ticket에는 근거 Event가 없다.
"""

from collections.abc import Sequence


def similar_text(titles: Sequence[str], hunt_hypothesis: str | None = None) -> str:
    """Alert 제목을 줄바꿈으로 잇는다. 제목이 없으면(L3 Ticket) Hunt 가설을 쓴다."""
    values = list(dict.fromkeys(t.strip() for t in titles if t and t.strip()))
    if not values and hunt_hypothesis and hunt_hypothesis.strip():
        values = [hunt_hypothesis.strip()]
    return "\n".join(values)
