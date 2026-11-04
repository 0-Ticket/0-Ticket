"""ELK에서 조회 대상 하나의 문서를 페이지 단위로 읽는다(HTTP 클라이언트 httpx, D-039).

조회만 한다(SIEM 읽기 전용, D-010). 부르는 API는 PIT 열기(POST /{key}/_pit), 검색(POST /_search),
PIT 닫기(DELETE /_pit) 셋이다.

- 실행 안에서는 PIT와 search_after로 넘기고, 실행 사이에는 PIT를 이어 쓰지 않는다. 다음 실행은
  체크포인트의 시각부터 gte로 다시 조회한다. 겹친 문서는 저장할 때 (siem_profile, siem_ref)로
  건너뛴다.
- 리다이렉트는 따라가지 않는다. 401·403은 auth, 그 밖에 2xx가 아니면(3xx 포함) http_status.
- 응답은 스트리밍으로 받으며 압축을 푼 바이트를 세고, 상한을 넘으면 그 자리에서 끊는다.
  요청 단위 timeout(클라이언트 설정)과 별도로 응답 하나마다 전체 마감 시간을 확인한다.
- hit 객체는 모양만 확인하고 바꾸지 않고 넘긴다. 응답 본문과 예외 메시지는 남기지 않는다.
"""

import json
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from soc.ingest.config import Settings, Source
from soc.ingest.errors import IngestError

KEEP_ALIVE = "1m"


def make_client(settings: Settings, base_url: str, api_key: str) -> httpx.Client:
    timeout = httpx.Timeout(settings.read_timeout_seconds, connect=settings.connect_timeout_seconds)
    return httpx.Client(
        base_url=base_url,
        headers={"Authorization": f"ApiKey {api_key}"},
        timeout=timeout,
        follow_redirects=False,
    )


def iter_pages(
    client: httpx.Client,
    settings: Settings,
    source: Source,
    start_ms: int | None,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> Iterator[list[dict[str, Any]]]:
    """시각 오름차순으로 hit 목록을 한 페이지씩 내놓는다. 빈 페이지는 내놓지 않는다.

    start_ms가 있으면 time_field >= start_ms인 문서부터, 없으면 time_field가 있는 문서 전체다.
    끝나거나 실패하거나 호출한 쪽이 멈추면 PIT를 닫는다.
    """

    def call(method: str, path: str, **kwargs: Any) -> Any:
        return _call(client, method, path, settings=settings, clock=clock, **kwargs)

    opened = call("POST", f"/{source.key}/_pit", params={"keep_alive": KEEP_ALIVE})
    if not isinstance(opened, dict) or not _is_text(opened.get("id")):
        raise IngestError("response_shape")
    pit_id = opened["id"]
    try:
        if start_ms is None:
            # 시각 필드가 없는 문서는 정렬 값이 없어 커서를 만들 수 없으므로 처음부터 뺀다.
            query = {"exists": {"field": source.time_field}}
        else:
            query = {"range": {source.time_field: {"gte": start_ms, "format": "epoch_millis"}}}
        body: dict[str, Any] = {
            "size": settings.page_size,
            "pit": {"id": pit_id, "keep_alive": KEEP_ALIVE},
            "sort": [{source.time_field: "asc"}, {"_shard_doc": "asc"}],
            "track_total_hits": False,
            "query": query,
        }
        while True:
            pit_id, hits = _read_page(call("POST", "/_search", json=body))
            if hits:
                yield hits
            if len(hits) < settings.page_size:
                return
            body["pit"]["id"] = pit_id
            body["search_after"] = hits[-1]["sort"]
    finally:
        try:
            call("DELETE", "/_pit", json={"id": pit_id})
        except IngestError:
            # 닫지 못한 PIT는 keep_alive가 지나면 ELK가 지운다.
            # 받은 페이지나 원래 실패를 가리지 않는다.
            pass


def _read_page(data: Any) -> tuple[str, list[dict[str, Any]]]:
    """(다음 요청에 쓸 PIT ID, hit 목록).

    hit마다 _index·_id와 첫 정렬 값(시각 epoch ms 정수)을 본다.
    """
    if not isinstance(data, dict) or not _is_text(data.get("pit_id")):
        raise IngestError("response_shape")
    outer = data.get("hits")
    hits = outer.get("hits") if isinstance(outer, dict) else None
    if not isinstance(hits, list):
        raise IngestError("response_shape")
    for hit in hits:
        if not isinstance(hit, dict) or not _is_text(hit.get("_index")):
            raise IngestError("response_shape")
        sort = hit.get("sort")
        if not _is_text(hit.get("_id")) or not isinstance(sort, list) or not sort:
            raise IngestError("response_shape")
        first = sort[0]
        if isinstance(first, bool) or not isinstance(first, int) or first < 0:
            raise IngestError("response_shape")
    return data["pit_id"], hits


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def _call(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    settings: Settings,
    clock: Callable[[], float],
    **kwargs: Any,
) -> Any:
    started = clock()
    body = bytearray()
    try:
        with client.stream(method, path, follow_redirects=False, **kwargs) as response:
            if response.status_code in (401, 403):
                raise IngestError("auth")
            if not 200 <= response.status_code < 300:
                raise IngestError("http_status")
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > settings.max_bytes:
                    raise IngestError("too_large")
                if clock() - started > settings.deadline_seconds:
                    raise IngestError("timeout")
    except httpx.TimeoutException:
        raise IngestError("timeout") from None
    except httpx.HTTPError:
        # 연결 실패, 프로토콜 오류, 압축 해제 오류 등.
        # 예외 메시지에 주소가 들어 있을 수 있어 남기지 않는다.
        raise IngestError("network") from None
    try:
        return json.loads(body)
    except (ValueError, RecursionError):
        raise IngestError("response_shape") from None
