"""수집 테스트용 가짜 ELK와 가짜 저장소. tests/ 안에서만 쓴다.

FakeElk는 httpx.MockTransport에 넣는 처리기다. PIT 열기·닫기에 답하고, _search에는 미리 넣은
응답을 앞에서부터 하나씩 돌려준다. 받은 요청은 requests에 남긴다.
FakeStore는 soc.ingest.store의 load_checkpoint·save_page·record_failure를 메모리로 흉내 낸다.
"""

import copy
import json
from pathlib import Path
from typing import Any

import httpx

from soc.contracts import validate_contract
from soc.ingest.config import Settings, Source

FIXTURES = Path(__file__).parent / "fixtures" / "ingest"
BASE_URL = "https://elk.example.com:9200"
API_KEY = "fake-api-key-SECRET-MARKER"

EVENTS = Source(kind="event", key="logs-web-*", time_field="@timestamp")
ALERTS = Source(kind="alert", key=".alerts-security.alerts-default", time_field="@timestamp")


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_settings(*sources: Source, page_size: int = 2, max_bytes: int = 1_000_000) -> Settings:
    return Settings(
        siem_profile="elk-test",
        url_env="ELK_URL",
        api_key_env="ELK_API_KEY",
        page_size=page_size,
        connect_timeout_seconds=5,
        read_timeout_seconds=5,
        max_bytes=max_bytes,
        deadline_seconds=30,
        sources=sources or (EVENTS,),
    )


def respond(status: int, body: Any) -> httpx.Response:
    return httpx.Response(status, json=body)


class FakeElk:
    """searches: 키 패턴 → _search 응답(httpx.Response 또는 fixture 이름) 목록."""

    def __init__(self, searches: dict[str, list[httpx.Response | str]]) -> None:
        self.searches = {key: list(responses) for key, responses in searches.items()}
        self.requests: list[httpx.Request] = []
        self.pit_response: httpx.Response | None = None
        self.close_response: httpx.Response | None = None
        self._open: dict[str, str] = {}  # PIT ID → 키 패턴

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "POST" and path.endswith("/_pit"):
            key = path.removeprefix("/").removesuffix("/_pit")
            if self.pit_response is not None:
                return self.pit_response
            pit_id = f"pit-{key}"
            self._open[pit_id] = key
            return respond(200, {"id": pit_id})
        if request.method == "POST" and path == "/_search":
            body = json.loads(request.content)
            key = self._open[body["pit"]["id"]]
            answer = self.searches[key].pop(0)
            if isinstance(answer, str):
                data = fixture(answer)
                self._open[data["pit_id"]] = key  # ELK는 응답마다 PIT ID를 바꿀 수 있다
                return respond(200, data)
            return answer
        if request.method == "DELETE" and path == "/_pit":
            if self.close_response is not None:
                return self.close_response
            return respond(200, {"succeeded": True, "num_freed": 1})
        return respond(404, {"error": "unexpected request"})

    def client(self) -> httpx.Client:
        return httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(self))

    def search_bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.url.path == "/_search"]

    def calls(self) -> list[str]:
        return [f"{r.method} {r.url.path}" for r in self.requests]


class FakeStore:
    """records: (siem_profile, siem_ref) → RawRecord.

    checkpoints: (siem_profile, source_kind, source_key) → 체크포인트.
    """

    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict[str, Any]] = {}
        self.checkpoints: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.failures: list[tuple[str, str, str, str]] = []
        self.save_error: Exception | None = None
        self.failure_error: Exception | None = None

    def load_checkpoint(self, conn, siem_profile, source_kind, source_key):
        found = self.checkpoints.get((siem_profile, source_kind, source_key))
        return copy.deepcopy(found)

    def save_page(self, conn, records, checkpoint):
        # 검증을 모두 통과해야 아무것이든 쓴다(한 트랜잭션).
        for record in records:
            validate_contract("raw_record", record)
        validate_contract("ingest_checkpoint", checkpoint)
        if self.save_error is not None:
            raise self.save_error
        inserted = 0
        for record in records:
            ref = (record["siem_profile"], record["siem_ref"])
            if ref not in self.records:
                self.records[ref] = copy.deepcopy(record)
                inserted += 1
        key = (checkpoint["siem_profile"], checkpoint["source_kind"], checkpoint["source_key"])
        self.checkpoints[key] = copy.deepcopy(checkpoint)
        return inserted

    def record_failure(self, conn, siem_profile, source_kind, source_key, error_kind, now_ms):
        if self.failure_error is not None:
            raise self.failure_error
        assert isinstance(now_ms, int)
        self.failures.append((siem_profile, source_kind, source_key, error_kind))
        found = self.checkpoints.get((siem_profile, source_kind, source_key))
        if found is not None:
            found["last_error"] = error_kind
            found["updated_at"] = now_ms
