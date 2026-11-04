"""SIEM 도구 테스트용 가짜 ELK(#212). tests/ 안에서만 쓴다.

FakeElk는 httpx.MockTransport에 넣는 처리기다. 미리 넣은 답을 앞에서부터 하나씩 돌려준다.
SIEM 도구가 부를 수 있는 것은 POST /<index>/_search 하나뿐이다. 다른 경로·메서드, 쿼리 문자열,
허용 목록 밖의 본문 키를 받으면 violations에 남기고 599로 답한다. 테스트는 끝날 때 violations가
비어 있는지 확인한다(conftest가 아니라 각 테스트의 elk 픽스처가 한다).
"""

import json
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).parent / "fixtures" / "siem"
ELK_URL = "https://elk.example.com:9200"
ELK_KEY = "fake-elk-key-SECRET-7777"
BODY_KEYS = frozenset({"size", "query", "sort", "_source", "aggs", "track_total_hits"})
_SEARCH_PATH = re.compile(r"/[^/]+/_search")

Answer = httpx.Response | Exception | Callable[[httpx.Request], httpx.Response]


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def ok(name: str) -> httpx.Response:
    """fixture 파일을 200 응답으로."""
    return httpx.Response(200, json=fixture(name))


def status(code: int, name: str | None = None, **kwargs: Any) -> httpx.Response:
    if name is None:
        return httpx.Response(code, **kwargs)
    return httpx.Response(code, json=fixture(name), **kwargs)


def chunks(parts: Iterable[bytes]) -> httpx.Response:
    """여러 조각으로 나눠 오는 응답(마감 시간 테스트)."""
    return httpx.Response(200, content=iter(list(parts)))


class FakeElk:
    def __init__(self, *answers: Answer) -> None:
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []
        self.violations: list[str] = []

    def add(self, *answers: Answer) -> None:
        self.answers.extend(answers)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        problem = _violation(request)
        if problem is not None:
            self.violations.append(problem)
            return httpx.Response(599)
        if not self.answers:
            self.violations.append("준비한 답보다 요청이 많다")
            return httpx.Response(599)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if callable(answer) and not isinstance(answer, httpx.Response):
            return answer(request)
        return answer

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def _violation(request: httpx.Request) -> str | None:
    if request.method != "POST":
        return f"메서드 {request.method}"
    if not _SEARCH_PATH.fullmatch(request.url.path):
        return f"경로 {request.url.path}"
    if request.url.query:
        return "쿼리 문자열"
    try:
        body = json.loads(request.content)
    except ValueError:
        return "본문이 JSON이 아니다"
    if not isinstance(body, dict) or set(body) - BODY_KEYS:
        return "허용 목록 밖의 본문 키"
    return None
