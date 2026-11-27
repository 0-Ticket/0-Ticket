"""승인된 Case를 전용 Qdrant 컬렉션에 색인한다(#391, D-084).

워커는 l2 단계에서 돌지만 소비자는 L3 도구(#392)와 승인 API라서 `soc/l2/`·`soc/l3/` 밖에 둔다.
이 `__init__`은 가볍게 둔다. 승인 API(`outbox`)와 검색 도구(`source`)가 이 패키지를 가져다 써도
임베더·Qdrant 클라이언트·L2 runtime을 끌어오지 않아야 한다. 무거운 것은 `index`에 있고
`build_worker`만 지연 import로 부른다(`soc.l2.branch.build_worker`와 같은 방식).
"""

from typing import Any


def build_worker(config: dict[str, Any]) -> Any:
    """실행기 등록용 지연 import. `[executor.l2] workers`가 이 이름을 부른다."""
    from soc.case_index.index import build_worker as factory

    return factory(config)


__all__ = ["build_worker"]
