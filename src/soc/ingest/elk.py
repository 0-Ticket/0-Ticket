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
import ssl
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from soc.ingest.config import ConfigError, Settings, Source
from soc.ingest.errors import IngestError
from soc.ingest.quarantine import has_bad_sort, valid_sort_value

# PIT와 검색 요청의 생존 시간. 페이지 사이 간격보다 길어야 PIT가 살아 있다.
KEEP_ALIVE = "1m"


def tls_verify(settings: Settings) -> ssl.SSLContext | bool:
    """httpx.Client의 verify 값을 만든다(#264).

    인자:
        settings: ca_cert_path를 쓴다.

    반환:
        ca_cert_path가 비었으면 True(httpx 기본 신뢰 저장소), 있으면 그 CA 파일만 믿는 SSLContext.
        httpx 0.28은 verify에 경로 문자열을 넘기는 것을 폐기 예정으로 두어 SSLContext를 만든다.

    발생:
        ConfigError: 파일이 없거나 PEM 인증서로 읽을 수 없다. 메시지에 경로를 넣지 않는다.
    """
    if not settings.ca_cert_path:
        return True
    try:
        return ssl.create_default_context(cafile=settings.ca_cert_path)
    except OSError:  # FileNotFoundError, IsADirectoryError, ssl.SSLError(PEM 아님)
        raise ConfigError("ingest.ca_cert_path의 CA 인증서 파일을 읽지 못했다") from None


def make_client(settings: Settings, base_url: str, api_key: str) -> httpx.Client:
    """읽기 전용 ELK 호출에 쓸 HTTP 클라이언트를 만든다.

    인자:
        settings: connect·read 제한 시간과 CA 인증서 경로(tls_verify)를 얻는 데 쓴다.
        base_url: ELK 주소(http 또는 https, 계정 정보 없음).
        api_key: ELK API 키. Authorization: ApiKey 헤더로 보낸다.

    반환:
        리다이렉트를 따라가지 않는 httpx.Client. 호출한 쪽이 닫는다.

    발생:
        ConfigError: CA 인증서 파일을 읽지 못했다(tls_verify).
    """
    timeout = httpx.Timeout(settings.read_timeout_seconds, connect=settings.connect_timeout_seconds)
    return httpx.Client(
        base_url=base_url,
        headers={"Authorization": f"ApiKey {api_key}"},
        timeout=timeout,
        follow_redirects=False,
        verify=tls_verify(settings),
    )


def iter_pages(
    client: httpx.Client,
    settings: Settings,
    source: Source,
    start_ms: int | None,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[list[Any]]:
    """시각 오름차순으로 hit 목록을 한 페이지씩 내놓는다. 빈 페이지는 내놓지 않는다.

    start_ms가 있으면 time_field >= start_ms인 문서부터, 없으면 time_field가 있는 문서 전체다.
    끝나거나 실패하거나 호출한 쪽이 멈추면 PIT를 닫는다.

    인자:
        client: make_client()가 만든 클라이언트.
        settings: page_size, max_bytes, deadline_seconds를 쓴다.
        source: 조회 대상(key로 PIT를 열고, time_field로 정렬·범위를 건다).
        start_ms: 체크포인트 커서(epoch ms). None이면 처음부터 조회한다.
        clock: 응답 마감 시간을 재는 함수.

    산출:
        hit 목록(ELK 응답의 hits.hits 항목을 바꾸지 않고 그대로). 한 번에 page_size개 이하다.

    발생:
        IngestError: 응답 오류, 인증 실패, 크기·시간 초과, 연결 실패 등. kind에 원인이 있다.
    """

    def call(method: str, path: str, **kwargs: Any) -> Any:
        retry = kwargs.pop("retry", True)
        return _call(
            client, method, path, settings=settings, clock=clock, sleep=sleep, retry=retry, **kwargs
        )

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
            page_attempts = 0
            while True:
                pit_id, hits = _read_page(call("POST", "/_search", json=body))
                page_attempts += 1
                if not any(has_bad_sort(hit) for hit in hits) or page_attempts == 3:
                    break
                body["pit"]["id"] = pit_id
                sleep(1)
            if hits:
                yield hits
                if not valid_sort_value(hits[-1]):
                    raise IngestError("sort_value")
            if len(hits) < settings.page_size:
                return
            body["pit"]["id"] = pit_id
            body["search_after"] = hits[-1]["sort"]
    finally:
        try:
            call("DELETE", "/_pit", json={"id": pit_id}, retry=False)
        except IngestError:
            # 닫지 못한 PIT는 keep_alive가 지나면 ELK가 지운다.
            # 받은 페이지나 원래 실패를 가리지 않는다.
            pass


def _read_page(data: Any) -> tuple[str, list[Any]]:
    """검색 응답을 검사해 (다음 요청에 쓸 PIT ID, hit 목록)을 돌려준다.

    인자:
        data: JSON으로 파싱한 검색 응답.

    반환:
        (pit_id, hits). hit 내용은 문서 단위 분류를 위해 바꾸지 않고 돌려준다.

    발생:
        IngestError("response_shape"): 필드가 없거나 모양이 다를 때.
    """
    if not isinstance(data, dict) or not _is_text(data.get("pit_id")):
        raise IngestError("response_shape")
    outer = data.get("hits")
    hits = outer.get("hits") if isinstance(outer, dict) else None
    if not isinstance(hits, list):
        raise IngestError("response_shape")
    return data["pit_id"], hits


def _is_text(value: Any) -> bool:
    """인자 value가 비어 있지 않은 문자열이면 True."""
    return isinstance(value, str) and value != ""


def _call(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    settings: Settings,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    retry: bool,
    **kwargs: Any,
) -> Any:
    """ELK 요청 하나를 보내고 응답 본문을 JSON으로 돌려준다.

    인자:
        client: HTTP 클라이언트.
        method: "GET", "POST", "DELETE" 등.
        path: 기준 주소 뒤의 경로(예: "/_search").
        settings: max_bytes와 deadline_seconds를 쓴다.
        clock: 마감 시간을 재는 함수.
        **kwargs: httpx 요청 인자(params, json 등).

    반환:
        JSON으로 파싱한 응답 본문.

    발생:
        IngestError: 401·403은 auth, 그 밖의 비 2xx는 http_status, 크기 초과는 too_large,
        마감 초과는 timeout, 연결·프로토콜 오류는 network, JSON이 아니면 response_shape.
    """
    for attempt in range(3 if retry else 1):
        started = clock()
        body = bytearray()
        try:
            with client.stream(method, path, follow_redirects=False, **kwargs) as response:
                if response.status_code in (401, 403):
                    raise IngestError("auth")
                if not 200 <= response.status_code < 300:
                    retryable = (
                        response.status_code in (408, 429) or 500 <= response.status_code < 600
                    )
                    raise IngestError("http_status", retryable=retryable)
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > settings.max_bytes:
                        raise IngestError("too_large")
                    if clock() - started > settings.deadline_seconds:
                        raise IngestError("timeout", retryable=True)
        except httpx.TimeoutException:
            error = IngestError("timeout", retryable=True)
        except httpx.HTTPError:
            # 연결 실패, 프로토콜 오류, 압축 해제 오류 등.
            # 예외 메시지에 주소가 들어 있을 수 있어 남기지 않는다.
            error = IngestError("network", retryable=True)
        except IngestError as exc:
            error = exc
        else:
            try:
                return json.loads(body)
            except (ValueError, RecursionError):
                raise IngestError("response_shape") from None

        if not retry or not error.retryable or attempt == 2:
            raise error
        sleep(1)

    raise AssertionError("요청 재시도 루프를 마치지 못했다")
