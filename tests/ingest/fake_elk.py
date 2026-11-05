"""수집 테스트용 가짜 ELK와 가짜 저장소. tests/ 안에서만 쓴다.

FakeElk는 httpx.MockTransport에 넣는 처리기다. PIT 열기·닫기에 답하고, _search에는 미리 넣은
응답을 앞에서부터 하나씩 돌려준다. 받은 요청은 requests에 남긴다.
FakeStore는 soc.ingest.store의 load_checkpoint·save_page·record_run을 메모리로 흉내 낸다.
"""

import copy
import json
from pathlib import Path
from typing import Any

import httpx

from soc.contracts import validate_contract
from soc.ingest.config import Settings, Source

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ingest"
BASE_URL = "https://elk.example.com:9200"
API_KEY = "fake-api-key-SECRET-MARKER"

EVENTS = Source(kind="event", key="logs-web-*", time_field="@timestamp")
ALERTS = Source(kind="alert", key=".alerts-security.alerts-default", time_field="@timestamp")


def fixture(name: str) -> dict[str, Any]:
    """tests/fixtures/ingest/의 JSON 파일을 읽는다.

    인자 name: 파일 이름(예: "elk_pit.json").
    """
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_settings(*sources: Source, page_size: int = 2, max_bytes: int = 1_000_000) -> Settings:
    """테스트용 Settings. 인자:
    sources: 조회 대상. 없으면 EVENTS 하나.
    page_size: 한 번에 받는 문서 수. 기본 2라 적은 문서로도 여러 페이지가 된다.
    max_bytes: 응답 하나의 크기 상한.
    """
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
    """JSON 본문을 가진 응답을 만든다. 인자 status는 HTTP 상태 코드, body는 JSON으로 보낼 값."""
    return httpx.Response(status, json=body)


class FakeElk:
    """httpx.MockTransport의 처리기로 쓰는 가짜 ELK.

    속성:
        searches: 대상 키 → 검색 응답 목록. 응답은 httpx.Response 또는 fixture 파일 이름이다.
        requests: 받은 요청 전부(순서대로).
        pit_response: 지정하면 PIT 열기 요청에 이 응답을 준다(실패 주입용).
        close_response: 지정하면 PIT 닫기 요청에 이 응답을 준다(실패 주입용).
    """

    def __init__(self, searches: dict[str, list[httpx.Response | str]]) -> None:
        """인자 searches: 대상 키 → 검색 응답 목록(앞에서부터 하나씩 쓴다)."""
        self.searches = {key: list(responses) for key, responses in searches.items()}
        self.requests: list[httpx.Request] = []
        self.pit_response: httpx.Response | None = None
        self.close_response: httpx.Response | None = None
        self._open: dict[str, str] = {}  # PIT ID → 키 패턴

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """요청 하나에 답한다. 인자 request는 httpx가 보낸 요청이고, 반환은 미리 정한 응답이다.

        PIT 열기·닫기와 _search를 처리하고, 모르는 요청에는 404를 준다.
        """
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
        """이 가짜 ELK를 쓰는 httpx.Client를 돌려준다(기준 주소는 BASE_URL)."""
        return httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(self))

    def search_bodies(self) -> list[dict[str, Any]]:
        """받은 _search 요청의 JSON 본문 목록. 커서와 search_after가 맞는지 볼 때 쓴다."""
        return [json.loads(r.content) for r in self.requests if r.url.path == "/_search"]

    def calls(self) -> list[str]:
        """받은 요청을 "메서드 경로" 문자열 목록으로 돌려준다(예: "POST /_search")."""
        return [f"{r.method} {r.url.path}" for r in self.requests]


class FakeStore:
    """soc.ingest.store의 메모리 대역. 실제 DB 대신 쓴다. 검증은 실제 계약 함수로 한다.

    속성:
        records: (siem_profile, siem_ref) → RawRecord.
        checkpoints: (siem_profile, source_kind, source_key) → 체크포인트.
        runs: record_run이 받아 계약 검사를 통과한 실행 이력 목록. 받은 순서대로다.
        save_error: 지정하면 save_page가 이 예외를 던진다(DB 실패 주입용).
        run_error: 지정하면 record_run이 계약 검사 뒤 이 예외를 던지고 기록하지 않는다.
    """

    def __init__(self) -> None:
        """빈 저장소를 만든다."""
        self.records: dict[tuple[str, str], dict[str, Any]] = {}
        self.checkpoints: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.runs: list[dict[str, Any]] = []
        self.save_error: Exception | None = None
        self.run_error: Exception | None = None

    def load_checkpoint(self, conn, siem_profile, source_kind, source_key):
        """인자는 store.load_checkpoint와 같다(conn은 쓰지 않는다). 복사본을 돌려준다."""
        found = self.checkpoints.get((siem_profile, source_kind, source_key))
        return copy.deepcopy(found)

    def save_page(self, conn, records, checkpoint):
        """store.save_page와 같은 계약: 모두 검증한 뒤 원본은 새 것만 넣고 체크포인트를 덮어쓴다.

        반환: 새로 넣은 원본 수.
        """
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

    def record_run(self, conn, run):
        """store.record_run과 같은 계약: 검사를 통과한 실행 이력을 runs 끝에 붙인다.

        인자는 store.record_run과 같다(conn은 쓰지 않는다).
        """
        validate_contract("ingest_run", run)
        if self.run_error is not None:
            raise self.run_error
        self.runs.append(copy.deepcopy(run))
