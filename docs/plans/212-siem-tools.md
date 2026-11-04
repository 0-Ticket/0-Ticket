---
issue: 212
date: 2026-11-04
owner: Interludeal
supersedes: []
---

# SIEM 조회 도구 만들기

## 목표

`src/soc/tools/siem.py`에 `query_siem`(l1·l2·l3)과 `count_siem`(l2·l3)을 #211 레지스트리(`ToolSpec`) 위에 만든다.
두 도구는 수집(#218)과 같은 ELK에 `ELK_URL`·`ELK_API_KEY`로 접속해 `POST /<index>/_search` 하나만 부르고, 모델이 고른 대상·필드·값으로 도구가 만든 쿼리만 보낸다.
결과는 ELK 원본 필드(ECS)를 구분자로 감싸 돌려주고 근거 장부에는 `call_id`(agl_)만 들어가며, 아래 완료 기준이 네트워크 없는 테스트로 확인되면 끝이다.

## 방법

접속

- SIEM 연결·프로필(D-021) 화면이 아직 없으므로, 수집(#218)과 같은 ELK에 같은 방식으로 접속한다. D-021 프로필이 생기면 그것으로 바꾼다.
- `[tools.siem]`에 `url_env = "ELK_URL"`, `api_key_env = "ELK_API_KEY"`. 값은 `.env`에만 둔다. 환경변수 이름은 #218과 같다.
- 인증은 `Authorization: ApiKey <키>`. 키는 읽기 전용 API 키다(SIEM 조회 도구 읽기 전용, D-010).
- `docs/security.md`의 `SIEM_` 접두사 제한은 프로필에서 고르는 이름의 규칙이다. `ELK_` 이름은 설정 파일 값이라 대상이 아니다. D-021 때 이름을 맞춰야 할 수 있다(기록에 적는다).
- `ELK_URL`은 계정 정보 없는 http(s) 주소만 받는다(#218과 같은 조건). `ELK_URL`·`ELK_API_KEY`가 없거나 주소가 틀리면 `unavailable`.
- 이 이슈는 #218 코드에 기대지 않는다. #218 브랜치 코드는 가져오지 않는다.

HTTP(httpx, D-039)

- 리다이렉트는 따라가지 않는다. `connect_timeout_seconds`, `read_timeout_seconds`를 둔다.
- D-039대로 요청 단위 timeout과 별도로 전체 마감 시간 `deadline_seconds`를 둔다. 넘으면 `timeout`.
- 응답은 스트리밍으로 받고, 압축을 푼 바이트가 `max_bytes`를 넘으면 그 자리에서 끊는다(`failed`, reason `too_large`).
- 부르는 API는 `POST /<대상 index>/_search` 하나다. PIT·scroll은 쓰지 않는다. 쿼리 문자열 매개변수는 붙이지 않는다.
- 요청 본문 키는 `size`, `query`, `sort`, `_source`, `aggs`, `track_total_hits`만 쓴다.
- 핸들러는 동기 httpx로 부른다. DB 도구처럼 이벤트 루프를 최대 `deadline_seconds`까지 막는다(기록에 적는다).

대상(코드 상수 + 설정)

- 대상 이름과 대상별 필터·반환 필드는 코드 상수다. 도구 설명과 `target` enum이 정적으로 정해져 모델이 정확히 안다.
- 설정 `[[tools.siem.targets]]`는 이름에 `index`(인덱스·데이터 스트림·alias 패턴)와 `time_field`만 붙인다.
- 기본 설정(예시, 실제 값은 `config/local.toml`에서 바꾼다. #218 `[[ingest.sources]]`와 같은 패턴):
  - `alerts`: `.alerts-security.alerts-default`
  - `web_access`: `logs-nginx.access-*,logs-apache.access-*`
  - `cloudtrail`: `logs-aws.cloudtrail-*`
  - `time_field`는 모두 `@timestamp`
- 코드에 없는 이름이 설정에 있으면 설정 오류로 실행이 `provider_error`로 끝난다. 설정에서 뺀 대상을 모델이 고르면 `invalid_argument`.
- `index`·`time_field`는 #218과 같은 규칙의 정규식으로 검사한다(`/`·`?`·`#`·공백, `_`로 시작하는 이름 거부). 틀리면 `failed`, reason `config`.

필터 인자(필드마다 선택 인자 하나)

| 인자 | ELK 필드 | 타입 |
|---|---|---|
| `source_ip` | `source.ip` | 문자열, IP 주소 또는 CIDR |
| `destination_ip` | `destination.ip` | 문자열, IP 주소 또는 CIDR |
| `user_name` | `user.name` | 문자열 |
| `host_name` | `host.name` | 문자열 |
| `url_path` | `url.path` | 문자열 |
| `http_method` | `http.request.method` | 문자열(`[A-Za-z]+`) |
| `status_code` | `http.response.status_code` | 정수 100~599 |
| `event_action` | `event.action` | 문자열 |
| `cloud_account_id` | `cloud.account.id` | 문자열 |
| `rule_name` | `kibana.alert.rule.name` | 문자열 |
| `alert_severity` | `kibana.alert.severity` | `low`·`medium`·`high`·`critical` |

- 문자열 값은 1~200자. IP 인자는 `ipaddress`로 주소나 CIDR인지 확인하고, 아니면 `invalid_argument`.
- 대상별로 쓸 수 있는 필터(도구 설명에 적는다):
  - `alerts`: `rule_name`, `alert_severity`, `source_ip`, `destination_ip`, `user_name`, `host_name`
  - `web_access`: `source_ip`, `destination_ip`, `url_path`, `http_method`, `status_code`, `user_name`, `host_name`
  - `cloudtrail`: `source_ip`, `user_name`, `event_action`, `cloud_account_id`
- 한 번에 쓰는 필터는 최대 5개(`check`). 고른 대상에 없는 필터 인자에 값이 들어오면 `invalid_argument`.
- strict일 때 선택 인자는 #211처럼 "required + null 허용"이다.
- `alerts`의 `kibana.alert.*`는 ECS가 아니라 Elastic Security 필드다. 결과 설명에 적는다. 실제 매핑 확정은 #208이다.

쿼리(도구가 dict로 만든다)

- `{"bool": {"filter": [range, term, …]}}`만 쓴다. `query_string`·`simple_query_string`·`wildcard`·`regexp`·`script`는 쓰지 않는다.
- 시간: `{"range": {<time_field>: {"gte": start_ms, "lt": end_ms, "format": "epoch_millis"}}}`. 끝은 포함하지 않는다.
- 필터: `{"term": {<ELK 필드>: 값}}`. 필드 이름은 위 표의 상수에서만 고르고, 모델이 준 값은 term 값 자리에만 들어간다.
- 시간 범위 상한과 limit은 `[tools]`의 `max_range_days`(7), `default_limit`(20), `max_limit`(100)을 함께 쓴다.

`query_siem(target, start_ms, end_ms, <필터>, limit, sort)`

- `sort`: `time_desc`(기본) / `time_asc`. 정렬은 `time_field` 하나다(PIT가 없어 동점은 가리지 않는다).
- 요청: `size = limit`, `_source`는 대상별 반환 필드, `track_total_hits = 10000`.
- 대상별 반환 필드(코드 상수, `time_field` 포함):
  - `alerts`: `kibana.alert.rule.name`, `kibana.alert.severity`, `kibana.alert.risk_score`, `kibana.alert.reason`, `kibana.alert.workflow_status`, `source.ip`, `destination.ip`, `user.name`, `host.name`, `event.action`
  - `web_access`: `source.ip`, `destination.ip`, `url.path`, `url.query`, `http.request.method`, `http.response.status_code`, `http.response.body.bytes`, `user_agent.original`, `user.name`, `host.name`
  - `cloudtrail`: `event.action`, `event.provider`, `event.outcome`, `source.ip`, `user.name`, `user_agent.original`, `cloud.account.id`, `cloud.region`
- 결과(모양): `{"call_id", "source": "siem", "schema": "ecs", "target", "total", "total_relation": "eq"|"gte", "hits": [{"siem_ref", "fields": {…}}], "truncated", "omitted"}`
  - `siem_ref`는 `"<_index>/<_id>"` 문자열(RawRecord 계약 #192, #218과 같은 모양).
  - `_source`는 점 경로 키로 평평하게 편다(`{"source.ip": …}`). 중첩된 키와 점이 든 키를 모두 읽는다. 반환 필드 밖의 값은 버린다.
  - 문자열 값 하나는 300자에서 자르고(`…`), 자른 경로를 그 히트의 `truncated_fields`에 적는다.
  - 한도(`max_tool_result_chars`)를 넘으면 핸들러가 `ctx.fits`로 뒤 히트부터 빼고 `"truncated": true`, `omitted`를 붙인다. 히트 하나도 맞지 않으면 0건.
- 결과 0건은 오류가 아니다. 빈 `hits`와 `call_id`를 돌려준다.

`count_siem(target, start_ms, end_ms, field, <필터>)`

- `field`는 필터 인자 이름 중 하나(enum)이고, 고른 대상에 있는 필드여야 한다. 아니면 `invalid_argument`.
- 요청: `size = 0`, `aggs = {"top": {"terms": {"field": <ELK 필드>, "size": 10}}}`, `track_total_hits = true`.
- 결과: `{"call_id", "source": "siem", "schema": "ecs", "target", "field", "total", "buckets": [{"value", "count"}], "other_count", "truncated"}`. `other_count`는 `sum_other_doc_count`.
- #211 aggregate 규칙을 그대로 쓴다: 값마다 120자, 넘으면 건수가 적은 항목부터 뺀다.

결과 종류

- 두 도구 모두 `result_kind = "aggregate"`. 레지스트리의 `result_kind`는 바꾸지 않는다.
- `aggregate`의 뜻은 "핸들러가 모양과 한도를 정하고, 인용은 `call_id`만"이다. `query_siem`은 집계가 아니라 이름이 어색하다는 점을 기록에 적는다.
- 결과 전체는 #211처럼 `<tool_result>`로 감싸고 `<`·`>`를 바꿔 탈출을 막는다. 장부에는 `call_id`만 들어간다. `siem_ref`나 본문 속 `alt_` 모양 문자열을 인용하면 `evidence_id_error`.

오류

| 상황 | 코드 | `details.reason` |
|---|---|---|
| 환경변수 없음, 주소 틀림 | `unavailable` | `config` |
| 접속 실패(연결·프로토콜·압축 해제 오류) | `unavailable` | `network` |
| connect·read timeout, `deadline_seconds` 초과 | `timeout` | 없음 |
| 401·403 | `failed` | `auth` |
| 그 밖의 비2xx(3xx·404 포함) | `failed` | `http_status` |
| JSON이 아니거나 모양이 다름 | `failed` | `response_shape` |
| `max_bytes` 초과 | `failed` | `too_large` |
| 설정의 `index`·`time_field` 형식 오류 | `failed` | `config` |

- 와일드카드 패턴에 맞는 인덱스가 없으면 0건(ES 기본 동작). alias 같은 고정 이름이 없으면 404이고 `failed`(`http_status`).
- 모델에게는 #211의 `TOOL_ERROR` 문구만 간다. 응답 본문, ES 주소, 키, 쿼리 원문은 모델·`detail`·Agent Log `details`에 넣지 않는다.
- 연속 2회 차단, 오류·차단 호출은 장부에 없음은 #211 그대로다.

레지스트리·기록기 변경(#211 공용 코드, 원칙 7)

- `ToolError(code, reason=None)`: 선택 인자 `reason`을 더한다. 모델에게 가는 문구는 바뀌지 않는다.
- `ToolRecorder.report_tool(…, reason=None)`, `LogRecorder.report_tool`: reason이 있으면 tool 줄 `details.reason`에 쓴다. `details.failure`는 #211대로 코드 5개 중 하나다.
- `ToolSpec`에 선택 칸 `check_config`(설정의 `[tools]`를 받아 틀리면 `ToolConfigError`)를 더한다. `ToolRegistry.session()`이 허용 목록에 있는 도구의 `check_config`를 불러, 실패하면 실행이 `provider_error`("도구 설정 오류")로 끝난다. 설정에 코드에 없는 대상 이름이 있을 때 이 길을 쓴다. 칸이 없는 도구는 동작이 그대로다.
- reason이 없을 때 동작은 그대로다. #211 테스트는 지우지 않고 그대로 통과해야 한다.
- #213·#214도 이 칸을 쓴다(기록에 적는다).

설정(`config/default.toml`)

- `[tools.siem]`: `url_env = "ELK_URL"`, `api_key_env = "ELK_API_KEY"`, `connect_timeout_seconds = 5`, `read_timeout_seconds = 10`, `deadline_seconds = 15`, `max_bytes = 5_242_880`(5MB).
- `[[tools.siem.targets]]`: 위 기본 대상 3개(`name`, `index`, `time_field`).
- `[tools.allowed]`: l1에 `query_siem`, l2·l3에 `query_siem`, `count_siem`을 더한다.
- `.env.example`: `ELK_URL`, `ELK_API_KEY` 이름(#218과 같은 이름. 먼저 머지되는 쪽이 넣고, 나중 쪽은 겹치지 않게 맞춘다).

비밀 값 가림

- `build_redactor`가 설정 전체의 `*_env`를 보므로 `[tools.siem]`의 `api_key_env`·`url_env` 값은 이미 가려진다. `redact.py`는 고치지 않고 테스트만 더한다.

테스트

- 네트워크 없이 `httpx.MockTransport`로 돈다. 가짜 전송 계층은 `POST /<index>/_search` 밖의 경로·메서드를 받으면 테스트를 실패시키고, 요청 본문 키가 허용 목록 밖이면 실패시킨다.
- `tests/fixtures/siem/`에 손으로 만든 ES 응답: 검색 결과(alerts·web_access·cloudtrail), terms 집계, 빈 결과, 401, 500, 모양 이상, 큰 응답. IP는 문서용 대역, 도메인은 `example.com`.
- 가짜 모델로 "`query_siem` 호출 → 그 `call_id`를 근거로 한 Verdict"가 장부 검사를 통과하는지 확인한다.
- 실제 ELK 테스트는 `elk` 마커로 나눠 기본 실행과 CI에서 뺀다(`pyproject.toml`의 `markers`, `addopts`). 실행 방법은 `docs/notes/`에 적는다.

## 바꿀 곳

- `src/soc/tools/siem.py`: 대상·필드 상수, 인자, 쿼리 만들기, httpx 호출, 결과 모양, `QUERY_SIEM`·`COUNT_SIEM`
- `src/soc/tools/__init__.py`: 운영 레지스트리에 두 도구 추가
- `src/soc/tools/registry.py`: `ToolError`의 `reason`, `ToolRecorder.report_tool`의 `reason`, `_fail`이 reason을 넘김, `ToolSpec.check_config`와 `session()`의 설정 검사
- `src/soc/agent/agent_log.py`: `report_tool`의 `reason` → `details.reason`
- `config/default.toml`: `[tools.siem]`, `[[tools.siem.targets]]`, `[tools.allowed]`
- `.env.example`: `ELK_URL`, `ELK_API_KEY` 이름
- `pyproject.toml`: `elk` 마커, `addopts`
- `tests/`: SIEM 도구 테스트, `tests/fixtures/siem/`, reason 테스트, 가림 테스트, `elk` 마커 테스트

## 다른 코드와 맞물리는 곳

- **`ToolError`·`report_tool`에 선택 인자 `reason`이 생긴다.** Agent Log tool 줄 `details.reason`이 새로 생긴다. 없을 때 동작은 그대로다. #213·#214가 같은 칸을 쓴다.
- **`ToolSpec`에 선택 칸 `check_config`가 생긴다.** `session()`이 허용된 도구의 설정을 실행 전에 검사한다. 칸이 없는 도구는 그대로다.
- **운영 레지스트리에 도구 2개가 늘고, `[tools.allowed]` 기본값이 바뀐다.**
- **새 설정 키**: `[tools.siem]`(`url_env`, `api_key_env`, `connect_timeout_seconds`, `read_timeout_seconds`, `deadline_seconds`, `max_bytes`), `[[tools.siem.targets]]`(`name`, `index`, `time_field`).
- **새 환경변수 이름**: `ELK_URL`, `ELK_API_KEY`. #218과 같은 이름·같은 값을 함께 쓴다.
- **#218과 같은 파일을 고친다**: `config/default.toml`(서로 다른 절), `pyproject.toml`(#218은 `pythonpath`, 이 이슈는 `elk` 마커), `.env.example`. 줄 단위 충돌이 날 수 있고, 나중에 머지되는 쪽이 rebase한다.
- **#208 매핑**: `alerts`의 `kibana.alert.rule.name`·`kibana.alert.severity`와 대상별 필드는 #208 매핑이 확정되면 맞춘다.
- **D-021**: 프로필이 생기면 `[tools.siem]`의 `url_env`·`api_key_env` 대신 프로필로 접속한다. 이름 규칙(`SIEM_`)을 맞춰야 할 수 있다.

## 범위 밖

- SIEM 연결·프로필 화면(D-021) → 그 이슈
- OCSF 정규화 → 결과는 ELK 원본 필드(ECS) 그대로
- 대상·필드를 설정으로 늘리기(설명·스키마를 설정에서 만들기) → 필요해질 때
- 자체 서명 인증서용 CA 설정 → 필요해질 때
- 실제 ELK 매핑 확정 → #208
- 비동기 httpx → 필요해질 때

## 완료 기준

- [ ] `query_siem`이 l1·l2·l3, `count_siem`이 l2·l3 허용 목록에 있다
- [ ] 가짜 ES 응답(`tests/fixtures/siem/`)으로 두 도구가 대상 3개에서 동작한다
- [ ] 보내는 요청은 `POST /<index>/_search` 하나이고, 본문 키는 `size`·`query`·`sort`·`_source`·`aggs`·`track_total_hits`만이다. 다른 경로·메서드면 가짜 전송 계층이 실패시킨다
- [ ] 쿼리는 `bool.filter` 안의 range·term뿐이다. 모델이 준 값은 term 값 자리에만 있다
- [ ] 목록 밖 대상, 설정에서 뺀 대상, 대상에 없는 필터, 필터 6개 이상, IP가 아닌 IP 값, 시간 범위 7일 초과, limit 범위 밖 → `invalid_argument`
- [ ] 코드에 없는 대상 이름이 설정에 있으면 `provider_error`
- [ ] 결과에 `"source": "siem"`, `"schema": "ecs"`, `siem_ref`(`<_index>/<_id>`)가 있고, 반환 필드 밖의 `_source` 값은 없다
- [ ] 문자열 300자 자르기와 `truncated_fields`, 한도를 넘으면 뒤 히트부터 빼기(`truncated`·`omitted`)
- [ ] `count_siem`이 상위 10개·건수·`other_count`를 돌려주고, 값 120자, 넘으면 건수 적은 항목부터 뺀다
- [ ] 결과 0건은 오류가 아니다(빈 결과와 `call_id`)
- [ ] `query_siem`의 `call_id`를 근거로 한 Verdict가 장부 검사를 통과한다(가짜 모델)
- [ ] `siem_ref`나 결과 본문 속 `alt_` 모양 문자열을 인용하면 `evidence_id_error`
- [ ] 결과 본문의 `</tool_result>`가 구분자를 닫지 못한다
- [ ] 환경변수 없음·주소 틀림·접속 실패 → `unavailable`, timeout·`deadline_seconds` 초과 → `timeout`, 401·403 → `failed`(`details.reason=auth`), 500·모양 이상·크기 초과 → `failed`(각 reason)
- [ ] 리다이렉트를 따라가지 않는다
- [ ] 응답 본문·ES 주소·키·쿼리 원문이 모델 입력·`detail`·Agent Log `details`에 없다
- [ ] `[tools.siem]`의 `api_key_env`·`url_env` 값이 Agent Log에서 가려진다(테스트)
- [ ] reason이 없을 때 `ToolError`·`report_tool` 동작이 그대로다. #211 테스트를 지우거나 건너뛰지 않았다
- [ ] 실제 ELK 테스트는 `elk` 마커로 기본 실행·CI에서 빠진다
- [ ] `.env.example`에 `ELK_URL`, `ELK_API_KEY` 이름만 있다
- [ ] `docs/notes/`에 `elk` 마커 실행 방법, D-021 때 바꿀 것과 `SIEM_` 이름 규칙, #208 매핑 확인, aggregate 이름 메모, `details.reason`(#213·#214), 동기 httpx, #218과 줄 충돌을 적었다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록

## 토론으로 정한 것

이슈 본문과 달라진 점

- **SIEM 접속 방법(본문의 "정하지 못함").** D-021 화면이 없으므로 #218과 같은 ELK에 같은 방식(`ELK_URL`·`ELK_API_KEY`, `Authorization: ApiKey`)으로 접속한다. D-021 프로필이 생기면 그것으로 바꾼다. `ELK_` 이름은 설정 파일 값이라 `SIEM_` 접두사 규칙의 대상이 아니지만, D-021 때 맞춰야 할 수 있다.
- **선행.** "SIEM 연결·프로필 이슈(아직 없음)"는 위 접속 방법으로 대신한다. #218 머지는 선행이 아니다. 이 이슈는 #218 코드에 기대지 않는다.
- **#211에서 정해진 것을 따른다.** `ToolSpec`·레지스트리, `TOOL_ERROR` 문구, 연속 2회 차단, 결과 자르기, aggregate 결과 종류, `call_id` 하나, 오류·차단 호출은 장부에 없음.
- **결과는 ELK 원본 필드(ECS)다.** OCSF 정규화를 거치지 않는다. 결과에 `"source": "siem"`, `"schema": "ecs"`를 적는다.

미리 정한 답(사람이 검토 전에 정함)

- A. 도구 두 개, 단계 허용(`query_siem` l1·l2·l3, `count_siem` l2·l3).
- B. 이름 붙은 대상만 고름. 기본 대상 alerts·web_access·cloudtrail.
- C. Query DSL·Lucene 직접 작성 없음. `bool.filter` 안의 range·term만.
- D. 인자, 필터 최대 5개, 값 200자 또는 정수, `[tools]`의 시간 범위·limit, strict일 때 "required + null 허용".
- E. `siem_ref`, 장부에는 `call_id`만, `count_siem`은 terms 상위 10개와 #211 aggregate 규칙, 구분자·`max_tool_result_chars`.
- F. `POST /<index>/_search` 하나, 본문 키 허용 목록, 가짜 전송 계층 검사.
- G. httpx, 리다이렉트 안 따름, connect·read timeout, 스트리밍 크기 상한 5MB.
- H. 오류 코드 대응, 0건은 오류 아님, 비밀·본문·주소 숨김, `*_env` 가림 확인.
- I. 네트워크 없는 테스트, `tests/fixtures/siem/`, 가짜 모델 Verdict, `elk` 마커.
- J. index 패턴 기본값은 예시, 실제 값은 `config/local.toml`.

검토에서 정한 것

- **질문 1: B.** 필터는 `{field, value}` 목록이 아니라 필드마다 선택 인자 하나다. #211 `Arg`가 `string`·`integer`만 받아 객체 목록과 "문자열 또는 정수"를 표현할 수 없고, 엔티티 필터도 같은 방식으로 풀었기 때문이다. 최대 5개는 `check`로 막고, 대상에 없는 필드는 `invalid_argument`, 도구 설명에 대상별 필터를 적는다.
- **질문 2: A.** 대상 이름과 대상별 필터·반환 필드는 코드 상수다. 도구 설명과 enum이 정적이라 설정만으로는 모델에게 대상을 알려 줄 수 없기 때문이다. 설정은 `index`·`time_field`만 붙인다. 코드에 없는 이름은 `provider_error`, 설정에서 뺀 대상은 `invalid_argument`.
- **질문 3: A.** `query_siem`도 `aggregate`를 쓴다. 핸들러가 모양과 한도를 정하고 장부에는 `call_id`만 들어가는 성질이 맞기 때문이다. 레지스트리의 `result_kind`는 바꾸지 않고, 이름이 어색하다는 점을 기록에 적는다.
- **질문 4: A.** `details.failure`는 코드 5개 중 하나로 두고, `ToolError`·`report_tool`에 선택 인자 `reason`을 더해 `details.reason`(`auth`, `http_status`, `response_shape`, `too_large`, `network`, `config`)에 남긴다. #211의 failure 규칙을 지키면서 사유를 남기기 위해서다.
- **D-039 전체 마감 시간.** G에 없던 `[tools.siem] deadline_seconds = 15`를 둔다. 넘으면 `timeout`.
- **alerts 필드.** 룰 이름과 심각도는 `kibana.alert.rule.name`·`kibana.alert.severity`(Elastic Security 필드)다. ECS `rule.name`은 알럿 인덱스에서 비어 있을 수 있다. 확정은 #208.
- **IP 값 검사.** `ipaddress`로 주소나 CIDR인지 확인한다. ES의 ip 필드에 틀린 값을 보내면 400이 나기 때문이다.
- **redact.py는 고치지 않는다.** 테스트만 더한다.
- **#218과 줄 충돌.** `config/default.toml`·`pyproject.toml`·`.env.example`. 나중에 머지되는 쪽이 rebase한다.
- **빈칸 기본값을 그대로 쓴다.** `siem_ref` 모양, 두 결과 모양, `_source` 평탄화, 문자열 300자, 시간 조건(끝 미포함), 대상이 없을 때 처리, `ELK_URL`·index 검사, timeout·크기 기본값, 실패 사유 이름, 동기 httpx, `elk` 마커.

## 바뀐 점
