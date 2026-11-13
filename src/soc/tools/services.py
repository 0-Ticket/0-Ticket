"""도구가 함께 쓰는 공유 객체(#313). 실행기가 시작할 때 한 번 만들어 둔다.

임베더처럼 만드는 데 비싼 객체를 호출마다 만들지 않기 위한 자리다. 핸들러는 이 모듈을 직접
부르지 않고 CallContext.services로만 받는다(D-049). run_task가 실행마다 snapshot()을 세션에 넘긴다.
"""

from typing import Any

_services: dict[str, Any] = {}


def install(name: str, service: Any) -> None:
    """이름으로 공유 객체를 등록한다. 같은 이름이 있으면 바꾼다."""
    _services[name] = service


def snapshot() -> dict[str, Any]:
    """지금 등록된 공유 객체의 복사본."""
    return dict(_services)


def clear() -> None:
    """모두 지운다(테스트용)."""
    _services.clear()
