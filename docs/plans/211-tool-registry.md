---
issue: 211
date: 2026-11-04
owner: Interludeal
supersedes: []
---

# 도구 레지스트리와 내부 데이터·Web 도구 만들기

## 목표

`src/soc/tools/`에 `ToolRegistry`·`ToolSpec`을 만들고, `run_task`가 stage의 허용 목록에 있는 도구만 SDK 함수 도구로 붙이게 한다.
그 위에 내부 데이터 도구 3개(`get_alert`, `get_event`, `query_records`)와 Web 도구 2개(`query_http_flow`, `summarize_http_flow`)를 만들고, 에이전트 DB 읽기 역할(마이그레이션 0003)로 `alerts`·`events`만 읽게 한다.
도구 결과의 `call_id`, Agent Log tool 줄의 `id`, 근거 장부의 ID가 같은 `agl_` 하나이고, 아래 완료 기준이 테스트로 확인되면 끝이다.

## 방법

결정 반영

- 도구 구현 방식(D-023)을 후보에서 확정으로 옮긴다(이 계획의 확정 커밋에서 함). 내용: 파이썬 함수 도구 레지스트리를 Agents SDK 함수 도구(`FunctionTool`)로 감싼다. MCP 노출은 필요해지면 레지스트리 위에 얹는다. 팀 합의(L1·L2·L3 담당, #211).

레지스트리

- `ToolSpec`: `name`, `description`, `handler`, `bundle`, `result_kind`(`records`/`text`), `id_fields`(예: `id`), `limit_argument`, 인자 정의(이름·타입·허용 값·범위·필수 여부).
- `ToolRegistry`는 `ToolSpec`을 이름으로 모은다. 운영 레지스트리는 내부 데이터·Web 도구 5개를 담는다.
- `run_task`의 `tools` 인자는 `registry: ToolRegistry`로 바꾼다. 기본값은 운영 레지스트리다. 붙는 도구는 `config["tools"]["allowed"][stage]`로만 정한다. `AgentTask`로는 바꿀 수 없다.
- 테스트에서 가짜 도구를 넣는 길: 가짜 `ToolSpec`을 담은 `ToolRegistry`를 만들어 `run_task(registry=…)`로 넘기고, 테스트 설정의 `[tools.allowed]`에 그 이름을 넣는다. 레지스트리를 거치지 않고 도구를 붙이는 길은 없다.
- 허용 목록(`[tools.allowed]`)에 없는 이름은 SDK에 등록하지 않는다(모델에게 보이지 않음). 모델이 그래도 부르면 #209대로 `format_error`(`ModelBehaviorError`)다.
- 허용 목록에 레지스트리에 없는 이름이 있으면(오타) 실행하지 않고 `provider_error`("도구 설정 오류")로 끝낸다.
- `FunctionTool`은 `@function_tool` 데코레이터가 아니라 직접 만든다. `on_invoke_tool`이 원본 JSON 문자열을 받아 우리 인자 검사를 거치게 하고, pydantic 오류 문구(입력 값 포함)가 모델에게 가지 않게 한다. 핸들러 예외는 레지스트리가 모두 잡아 `TOOL_ERROR`로 바꾼다(SDK 기본 `failure_error_function`까지 가지 않는다).
- `strict_json_schema`는 `[llm] strict_mode` 값이다. strict일 때 SDK가 모든 속성을 required로 만들므로, 선택 인자는 "required + null 허용"으로 정의하고 null이면 기본값을 쓴다. `strict_mode = false`여도 인자 검사는 우리 코드가 똑같이 한다.

호출 순서(도구 한 번)

1. SDK가 `on_tool_start`를 부른다. `LogRecorder`가 `new_id("agl")`로 tool 줄을 연다. 열린 줄은 `tool_call_id`별로 보관한다(지금의 칸 하나 `_open["tool"]`를 바꾼다). 한 응답에 도구 호출이 여럿 와도 줄이 섞이지 않는다.
2. 레지스트리의 `on_invoke_tool`이 같은 `ToolContext`의 `tool_call_id`로 기록기에서 그 줄의 `agl_`을 받는다. 레지스트리는 ID를 만들지 않는다. 받지 못하면(빈·중복 `tool_call_id`) `TOOL_ERROR code=failed`.
3. 허용 확인(방어선). 그 stage 허용 목록 밖이면 `not_allowed`.
4. 연속 실패 차단 확인. 같은 도구가 연속 2회 실패했으면 실행하지 않고 `not_allowed`.
5. 인자 검사. 정의에 없는 인자, 타입·허용 값·범위 밖 값은 실행 전에 `invalid_argument`.
6. 실행(DB 조회).
7. 결과 처리: 자르기 → `call_id` 붙이기 → 구분자로 감싸기 → 장부에 넣기.
8. 레지스트리가 자르기 전 전체 결과와 성공·실패(오류 코드)를 기록기에 넘긴다. SDK의 `on_tool_end`는 모델에게 보낸 잘린 문자열을 받으므로, Agent Log `output`에는 레지스트리가 넘긴 전체를 쓴다.

근거 장부

- 장부 = `allowed_evidence_ids` + 성공한 도구 호출의 `agl_` + 모델에게 실제로 보여 준 `records` 결과의 `id_fields` 값(`alt_`·`evt_`).
- 오류로 끝난 호출과 차단된 호출의 `agl_`은 장부에 넣지 않는다. `TOOL_ERROR`에는 `call_id`를 붙이지 않는다. #209의 "도구 줄 `agl_`은 모두 장부"를 이렇게 바꾼다.
- 잘려서 보이지 않은 레코드의 id는 넣지 않는다.
- 결과 본문 속 ID 모양 문자열(예: `title`에 든 `alt_…`)은 넣지 않는다. 인용하면 `evidence_id_error`다.

결과 모양과 자르기

- 모델에게 보이는 모양: `<tool_result>` + JSON 본문 + `</tool_result>`. 본문 속 `<`·`>`는 `wrap_data`(#209)처럼 `<`·`>`로 바꿔 구분자를 닫지 못하게 한다.
- `records` 본문: `{"call_id": "agl_…", "records": […], "truncated": bool, "omitted": n}`. 레코드가 잘리면 `"truncated_fields"`도 붙는다.
- `max_tool_result_chars`는 감싸기 전 JSON 본문의 글자 수로 센다. 값은 `[agent.l1~l3]`에 6,000 / 8,000 / 8,000.
- `records` 결과는 JSON 중간을 자르지 않는다. 뒤의 레코드부터 빼서 한도 안에 맞추고 `"truncated": true`와 뺀 건수(`omitted`)를 붙인다.
- 레코드 하나만으로 한도를 넘으면 그 레코드 안의 긴 문자열 값부터 줄여 한도에 맞춘다. JSON은 유효하게 유지하고 줄인 경로는 `truncated_fields`에 적는다. 이 레코드는 모델에게 보인 것이므로 id를 장부에 넣는다. 줄여도 맞추지 못하면(예: 키가 너무 많음) 0건, `"truncated": true`, `"omitted": 1`을 돌려준다.
- `text` 결과는 글자 수로 자르고 잘렸다고 표시한다. 이 이슈의 도구 중 `text`는 없다(SSH 도구 #213이 쓴다).
- `summarize_http_flow`: 값마다 120자로 자르고 잘림을 표시한다. 그래도 한도를 넘으면 필드마다 건수가 적은 항목부터 빼고 `"truncated": true`를 붙인다. JSON 중간은 자르지 않는다. 장부에는 `call_id`만 넣는다.
- Agent Log `output`에는 자르기 전 전체를 넣는다(비밀 값 가림은 #209대로 쓰기 직전에 한다).

도구 오류

- 문구: `TOOL_ERROR tool=<이름> code=not_allowed|invalid_argument|unavailable|timeout|failed` + "다른 도구를 쓰거나 지금까지의 근거로 답하라"(이슈 본문 그대로). 예외 메시지, SQL, DB 주소는 모델과 `detail`에 보내지 않는다.
- DB 문장 시간 상한(`statement_timeout`)을 넘으면 `timeout`, 접속이 안 되거나 `AGENT_DATABASE_URL`이 없으면 `unavailable`이다. 실행은 계속된다.
- 오류 호출의 Agent Log 줄은 `outcome=error`, `details.failure=<code>`.
- 연속 실패는 도구 이름별로 센다. 다른 도구를 불러도 초기화되지 않고, 그 도구가 성공하면 초기화된다. 오류 코드 종류와 상관없이 센다. 2회 연속 실패하면 남은 턴에서는 실행하지 않고 `TOOL_ERROR code=not_allowed`를 돌려준다.
- 차단된 호출도 Agent Log 줄(`outcome=error`, `details.failure=not_allowed`, `details.blocked=true`)을 남기고 `usage.tool_errors`에 센다.
- `usage.tool_errors`는 `outcome=error`인 tool 줄 수다(#209의 0 고정을 바꾼다).

DB 접속

- `AGENT_DATABASE_URL`로 도구 호출마다 새로 연결한다. 세션 설정: `TimeZone=UTC`(#193 기록), `statement_timeout`, `default_transaction_read_only=on`, `connect_timeout`.
- SQL은 매개변수로만 넣는다. 컬럼 이름과 정렬은 허용 목록에서만 고르고, 모델이 만든 문자열을 SQL에 이어 붙이지 않는다. 자유 SQL 도구는 만들지 않는다.
- `redact.py`의 `_DATABASE_URL_ENVS`에 `AGENT_DATABASE_URL`을 더한다(#209 후속).

설정(`config/default.toml`)

- `[tools]`: `statement_timeout_ms = 5000`, `connect_timeout_seconds = 5`, `max_range_days = 7`, `default_limit = 20`, `max_limit = 100`.
- `[tools.allowed]`: `l1`·`l2`·`l3` 모두 `get_alert`, `get_event`, `query_records`, `query_http_flow`, `summarize_http_flow`. 키가 없거나 빈 목록이면 그 단계는 도구가 없다(기본 전부 거부).
- `[agent.l1~l3]`: `max_tool_result_chars` 6,000 / 8,000 / 8,000.
- `.env.example`에 `AGENT_DATABASE_URL` 이름만 더한다.

인자 정의

- 시간 범위 `start_ms`·`end_ms`(epoch 밀리초)는 `query_records`·`query_http_flow`·`summarize_http_flow`에서 필수다. `end_ms > start_ms`, 차이는 `max_range_days` 이하.
- `limit`: 기본 `default_limit`(20), 1~`max_limit`(100).
- 정렬 `sort`: `time_desc`(기본) 또는 `time_asc`.
- 포함 검색 문자열은 1~200자. `ILIKE`의 `%`·`_`·`\`는 이스케이프한다.
- 엔티티 필터는 `{type, value}` 하나(type은 엔티티 계약의 enum, value는 1~200자). `entities @> %s::jsonb` 매개변수로 넣는다.
- 그 밖의 인자나 범위 밖 값은 `invalid_argument`.

내부 데이터 도구(`internal.py`, `result_kind = records`, `id_fields = id`)

- `get_alert(id)`, `get_event(id)`: `alt_`·`evt_` ID 모양만 받는다. `ocsf`·`details`를 포함한 레코드 전체를 돌려준다. 없으면 0건.
- `query_records(kind, start_ms, end_ms, …)`: `kind`는 `alert` | `event`.
  - alerts 필터: 시간 범위, `severity_min`·`severity_max`(0~6), `rule_id`(일치), `title_contains`, 엔티티 하나.
  - events 필터: 시간 범위, `ocsf_class`(일치), `summary_contains`, 엔티티 하나.
  - `kind`와 맞지 않는 필터(예: event에 `severity_min`)는 `invalid_argument`.
  - 돌려주는 칸: `id`, `time`, `severity`(alert)·`ocsf_class`(event), `title`·`summary`, `rule_id`(alert), `entities`.

Web 도구(`web.py`)

- `events`에서 `ocsf_class = 4002`만 읽는다. ocsf JSON 경로는 상수로 둔다: 경로 `http_request.url.path`, 메서드 `http_request.http_method`, 응답 코드 `http_response.code`, User-Agent `http_request.user_agent`, 출발지 IP `src_endpoint.ip`.
- 공통 필터: 시간 범위, `src_ip`(일치), `method`(일치), `status_code`(100~599), `path_contains`, `user_agent_contains`.
- `query_http_flow`: `records`, `id_fields = id`. 돌려주는 칸: `id`, `time`, `summary`, `entities`, 위 5개 필드.
- `summarize_http_flow`: 전체 건수와 위 5개 필드별 상위 10개 값·건수만 돌려준다. 장부에는 `call_id`만.

DB 읽기 역할(마이그레이션 `0003`)

- 공통 대역(D-035)의 `0003`. NOLOGIN 그룹 역할 `soc_agent_reader`를 DO 블록으로 없을 때만 만들고, `alerts`·`events`에 SELECT만 준다.
- `raw_records`, `tickets`, `incidents`, `cases`, `agent_logs`, `hunts`, L3 테이블, `schema_migrations`에는 아무 권한도 주지 않는다.
- 접속용 LOGIN 역할과 비밀번호는 마이그레이션에 넣지 않는다. 운영자가 `CREATE ROLE <이름> LOGIN PASSWORD '…' IN ROLE soc_agent_reader`로 따로 만든다. 그 명령을 `docs/notes/`에 적고, 비밀번호 값은 어디에도 쓰지 않는다.
- 기록에 적을 것: 마이그레이션을 돌리는 계정에 CREATEROLE이 필요하다. PostgreSQL 16 이상에서는 운영자의 `IN ROLE soc_agent_reader`에 그 역할의 ADMIN 권한이 필요하다.

가짜 모델

- 한 응답에 도구 호출 여러 개를 내는 `{"tool_calls": [{"name", "arguments"}, …]}` step을 더한다. 바뀐 형식은 `docs/notes/`에 적는다.

## 바꿀 곳

- `docs/decisions.md`: 도구 구현 방식(D-023)을 확정으로, 기록 줄. 이 계획의 확정 커밋에서 함
- `src/soc/tools/`: `registry.py`(`ToolRegistry`·`ToolSpec`·SDK 어댑터·자르기·오류 문구), `internal.py`, `web.py`, DB 접속 도우미
- `src/soc/db/migrations/0003_agent_reader.sql`
- `src/soc/agent/runner.py`: `tools` → `registry`, 허용 목록, 장부, `usage.tool_errors`
- `src/soc/agent/agent_log.py`: `tool_call_id`별 열린 줄, 레지스트리가 넘기는 전체 output·오류 코드, 성공 호출 ID 목록
- `src/soc/agent/redact.py`: `_DATABASE_URL_ENVS`에 `AGENT_DATABASE_URL`
- `config/default.toml`: `[tools]`, `[tools.allowed]`, `[agent.l1~l3] max_tool_result_chars`
- `.env.example`: `AGENT_DATABASE_URL` 이름
- `tests/`: 레지스트리 테스트(가짜 모델·가짜 도구), `db` 마커 도구·역할 테스트, `tests/fixtures/`의 손으로 만든 Alert·Event(4002와 다른 클래스), 가짜 모델 `tool_calls` step, #209 테스트 6곳 수정

## 다른 코드와 맞물리는 곳

- **`run_task`의 `tools` 인자가 `registry`로 바뀐다.** #223(L3 헌팅, Pandyo)이 `run_task(tools=…)`로 가짜 도구를 넣는다고 계획했다. 가짜 도구는 `ToolSpec`으로 만들어 `ToolRegistry`에 넣고 `run_task(registry=…)`로 넘긴다. 사용 예시를 `docs/notes/211-tool-registry.md` "다음 사람이 알아야 할 것"에 적고, #223에 알린다.
- **#209 테스트 6곳**(`tests/test_agent_core.py`, `tests/test_agent_llm.py`, `tests/test_agent_log_db.py`의 `tools=[lookup_alert]`)을 레지스트리를 거치게 고친다. 지우거나 건너뛰지 않는다.
- **근거 장부 규칙이 바뀐다.** 오류·차단된 도구 호출의 `agl_`은 장부에 없다.
- **`usage.tool_errors`가 실제 값이 된다.** 파이프 담당이 쓰면 알린다.
- **#214(Cloud 도구)의 완료 기준 "기본 설정에서는 `not_allowed`"는 이 계획과 맞지 않는다.** "기본 설정에서는 도구가 등록되지 않는다(모델에게 보이지 않음). 레지스트리 함수를 목록 밖에서 직접 부르면 `not_allowed`"로 고친다(이슈 담당이 고침).
- **#212·#213·#214**는 이 레지스트리의 `ToolSpec`·결과 모양·오류 문구를 그대로 쓴다.
- **새 설정 키.** `[tools]`의 `statement_timeout_ms`·`connect_timeout_seconds`·`max_range_days`·`default_limit`·`max_limit`, `[tools.allowed]`, `[agent.l1~l3] max_tool_result_chars`. `[llm] strict_mode`를 처음 읽는다.
- **새 환경변수.** `AGENT_DATABASE_URL`.
- **새 DB 역할.** `soc_agent_reader`(클러스터 전체).

## 범위 밖

- SIEM·SSH·Cloud 도구 → #212·#213·#214
- MCP 노출 → 필요해질 때 레지스트리 위에 얹는다
- 실제 제공자의 `strict` 수용 확인 → #215
- 접속용 LOGIN 역할 만들기와 비밀번호 관리 → 운영자(명령만 기록에 적는다)
- `entities` GIN 인덱스 등 조회 성능 → 필요해질 때

## 완료 기준

- [ ] 도구 구현 방식(D-023)이 `docs/decisions.md`에 확정으로 있다
- [ ] 허용 목록 밖 도구는 SDK에 등록되지 않는다(테스트 1)
- [ ] 레지스트리 함수를 허용 목록 밖에서 직접 부르면 `not_allowed` 문구다(테스트 2)
- [ ] 허용 목록에 레지스트리에 없는 이름이 있으면 `provider_error`다
- [ ] 잘못된 인자(정의에 없는 인자, 타입·허용 값·범위 밖) → 실행 전에 `invalid_argument` 문구
- [ ] 같은 도구 연속 2회 실패 뒤 차단(`not_allowed`, `details.blocked=true`). 다른 도구는 계속 쓸 수 있다
- [ ] 도구 결과의 `call_id`, Agent Log tool 줄의 `id`, 근거 장부의 ID가 같은 값이다. 한 응답에 도구 호출이 둘이어도 맞다
- [ ] `call_id`(`agl_`)를 인용한 Verdict가 장부 검사를 통과한다
- [ ] 오류·차단된 호출의 `agl_`을 인용하면 `evidence_id_error`. `TOOL_ERROR`에 `call_id`가 없다
- [ ] 결과 본문 속 `alt_…` 문자열을 인용하면 `evidence_id_error`
- [ ] 결과 자르기: 모델에는 잘린 결과(뒤 레코드부터 뺌, `truncated`·`omitted`), Agent Log `output`에는 전체. 잘려서 안 보인 레코드 id를 인용하면 `evidence_id_error`
- [ ] 레코드 하나가 한도를 넘으면 긴 문자열부터 줄이고 `truncated_fields`가 붙으며 그 id는 장부에 있다. 줄여도 못 맞추면 0건·`omitted: 1`
- [ ] 결과 본문의 `</tool_result>`가 구분자를 닫지 못한다
- [ ] 오류 호출의 Agent Log 줄은 `outcome=error`, `details.failure=<code>`. 예외 메시지·SQL·DB 주소가 모델 입력과 `detail`에 없다
- [ ] `usage.tool_errors`가 실제 오류 수다
- [ ] `strict_mode`가 도구 정의의 `strict_json_schema`에 들어간다
- [ ] 위 레지스트리 테스트는 모두 가짜 모델과 가짜 도구로 한다(DB 없음)
- [ ] `tests/fixtures/`의 손으로 만든 Alert·Event로 `get_alert`, `get_event`, `query_records`가 동작한다(`db` 마커)
- [ ] 결과의 `id`(`alt_`·`evt_`)가 근거 장부에 들어간다
- [ ] 계약에 없는 필터 인자, kind와 맞지 않는 필터는 `invalid_argument`
- [ ] 손으로 만든 4002 Event 샘플로 `query_http_flow`, `summarize_http_flow`가 동작한다. 다른 클래스의 Event는 결과에 나오지 않는다
- [ ] 집계 결과 크기에 상한이 있다(상위 10개, 값 120자, 넘으면 건수 적은 항목부터 뺌)
- [ ] `statement_timeout`을 넘으면 `timeout`, 접속이 안 되면 `unavailable`
- [ ] 읽기 역할(임시 LOGIN 역할, 끝나면 삭제)로 `alerts`·`events` 읽기는 되고, `raw_records` 읽기·`alerts` 쓰기·`agent_logs` 읽기는 권한 오류다
- [ ] 0003은 역할이 이미 있는 클러스터의 다른 DB에도 적용된다
- [ ] `AGENT_DATABASE_URL`의 비밀번호가 Agent Log에서 가려진다
- [ ] `.env.example`에 `AGENT_DATABASE_URL` 이름만 있다
- [ ] #209 테스트 6곳이 레지스트리를 거친다(지우거나 건너뛴 테스트 없음)
- [ ] `docs/notes/`에 LOGIN 역할 만드는 명령(비밀번호 값 없음), CREATEROLE·ADMIN 권한 메모, 가짜 도구를 레지스트리로 넣는 예시, 가짜 모델 `tool_calls` 형식을 적었다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록

## 토론으로 정한 것

이슈 본문과 달라진 점

- **도구 구현 방식(D-023)은 이 이슈에서 확정한다.** 본문의 "개발 레포 반영은 #209"는 틀렸다(#209 계획에서 이 이슈로 옮겼다). 팀 합의를 받았다(L1·L2·L3 담당, #211): MCP 서버 대신 파이썬 함수 도구 레지스트리를 Agents SDK 함수 도구로 감싸고, MCP 노출은 필요해지면 레지스트리 위에 얹는다.
- **`AGENT_DATABASE_URL`은 이 이슈에서 처음 넣는다.** 본문의 "#209에서 추가"는 틀렸다. `.env.example`에 이름만 더하고, `redact.py`의 DB 비밀번호 가림 대상에 더한다(#209 후속).
- **#210에서 넘어온 것.** `[llm] strict_mode`를 도구 정의(`strict_json_schema`)에 적용한다. `max_tool_result_chars`를 `[agent.l1~l3]`에 둔다(6,000 / 8,000 / 8,000). 도구 결과에 `call_id`를 붙인다.
- **마이그레이션 번호는 0003이다.** 0002는 #217(hunts)이 썼다.
- **`run_task`의 `tools` 인자는 레지스트리로 바꾼다.** 도구는 stage의 허용 목록으로만 붙는다. 테스트의 가짜 도구도 레지스트리를 거친다.
- **"허용 안 된 도구 → `not_allowed`"의 뜻.** 목록 밖 도구는 SDK에 등록되지 않는다(모델이 부르면 `format_error`). `not_allowed`는 레지스트리 함수가 목록 밖에서 불렸을 때의 방어선과 연속 실패 차단에서 나온다. 테스트 두 개로 나눠 확인한다.
- **충돌 처리.** #223의 `tools` 사용은 레지스트리로 바꾸고 사용 예시를 기록에 적어 알린다. #214 완료 기준은 이슈 담당이 고친다. #209 테스트 6곳은 레지스트리를 거치게 고친다.

미리 정한 답(사람이 검토 전에 정함)

- A. `agl_` ID는 한 호출에 하나. `call_id`, Agent Log tool 줄 `id`, 장부 ID가 같다.
- B. `[tools.allowed]` 단계별, 기본 전부 거부. 이 이슈 기본값은 l1·l2·l3 모두 5개 도구. 목록 밖은 등록하지 않음.
- C. 인자 모양 고정, 매개변수 SQL, 자유 SQL 없음, limit 20/100, epoch ms 시간 범위와 상한(7일).
- D. `query_records` 필터 허용 목록, 엔티티 `@>` 하나.
- E. Web 도구는 4002만, JSON 경로 상수, 요약은 필드별 상위 10개와 건수.
- F. records 결과는 뒤 레코드부터 빼서 자름, 보인 레코드 id만 장부, text는 글자 수로 자름, Agent Log에는 전체.
- G. TOOL_ERROR 문구, `statement_timeout` 5초, `timeout`·`unavailable`, 오류 줄, 연속 2회 차단, `usage.tool_errors`.
- H. NOLOGIN 그룹 역할, DO 블록, alerts·events SELECT만, LOGIN 역할·비밀번호는 운영자, 임시 LOGIN 역할 테스트, CREATEROLE 기록.
- I. 도구 결과는 구분자로 감싸고 탈출 방지, 본문 속 ID 모양 문자열은 장부에 넣지 않음.
- J. 레지스트리 테스트는 가짜 모델·가짜 도구, 도구 테스트는 `db` 마커와 손으로 만든 샘플.

검토에서 정한 것

- **ID는 기록기가 만들고 레지스트리가 받아 쓴다.** SDK 0.24.0은 `on_tool_start`를 도구 실행보다 먼저 부르고, 둘에 같은 `ToolContext`(`tool_call_id` 포함)를 넘긴다. 기록기는 `tool_call_id`별로 줄을 열고, 레지스트리는 그 줄의 `agl_`을 받는다. 자르기 전 전체 output은 레지스트리가 기록기에 넘긴다(`on_tool_end`는 잘린 문자열을 받기 때문).
- **질문 1: A.** 오류·차단된 호출의 `agl_`은 장부에 넣지 않고, `TOOL_ERROR`에 `call_id`를 붙이지 않는다. 실패한 조회는 근거가 아니다(근거 없는 판정은 없다, 원칙 3).
- **질문 2: A.** 레코드 하나가 한도를 넘으면 긴 문자열 값부터 줄여 맞추고 `truncated_fields`에 적는다. 그 id는 장부에 넣는다. 줄여도 못 맞추면 0건·`truncated: true`·`omitted: 1`.
- **질문 3: A.** `summarize_http_flow`는 값마다 120자로 자르고, 그래도 넘으면 필드마다 건수가 적은 항목부터 빼고 `truncated`를 붙인다. 장부에는 `call_id`만.
- **빈칸 기본값을 그대로 쓴다.** 역할 이름 `soc_agent_reader`, 테스트 순서(임시 LOGIN 역할은 `finally`에서 삭제, 두 번째 임시 DB에 0003 재적용), 호출마다 접속(`TimeZone=UTC`, `statement_timeout`, `default_transaction_read_only=on`, `connect_timeout` 5초), `[tools]` 설정 키, 허용 목록 오타는 `provider_error`, 인자 정의, 돌려주는 칸, 결과 모양, 연속 실패 세는 법, 차단 호출 기록, 가짜 모델 `tool_calls` step.
- **`FunctionTool`을 직접 만든다.** strict일 때 선택 인자는 "required + null 허용". PostgreSQL 16 이상의 ADMIN 권한 메모를 기록에 적는다.

## 바뀐 점

- 2026-11-04 · `ToolSpec.result_kind`에 `aggregate`를 더한다(`records` / `text` / `aggregate`). `summarize_http_flow`가 쓴다. 집계 결과(전체 건수 + 필드별 상위 값·건수)는 레코드 목록(`records`)도 문자열(`text`)도 아니고, 장부에는 `call_id`만 넣으며, 자를 때는 뒤 레코드나 글자가 아니라 필드마다 건수가 적은 항목부터 빼야 하기 때문이다. `aggregate` 핸들러는 집계 객체(dict)를 돌려주고, `CallContext.fits(결과)`(`call_id`를 포함한 JSON 본문 글자 수가 `max_tool_result_chars` 이하인지)로 확인하며 스스로 줄이고 `"truncated": true`를 붙인다. 레지스트리는 결과에 `call_id`를 붙이고 감싸기만 하며 `id_fields`를 보지 않는다(장부에는 `call_id`만). #212~#214 참고: 레코드를 돌려주는 도구는 `records` + `id_fields`, 명령 출력처럼 긴 글은 `text`(레지스트리가 글자 수로 자름), 건수·통계만 돌려주는 도구는 `aggregate`(핸들러가 `ctx.fits`로 한도를 맞춤, 인용은 `call_id`로만)를 쓴다. 사람이 확정함
