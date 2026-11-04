---
issue: 211
date: 2026-11-04
owner: Interludeal
plan: 211-tool-registry.md
supersedes: []
---

# 도구 레지스트리와 내부 데이터·Web 도구를 만들었다

## 한 일

- `src/soc/tools/`에 도구 레지스트리를 만들었다(도구 구현 방식, D-023). 도구 하나는 `ToolSpec`(이름, 설명, 핸들러, 묶음, 결과 종류, 장부에 넣을 id 칸, 인자 정의)이고, `ToolRegistry`가 이름으로 모은다. `run_task`는 실행마다 `config["tools"]["allowed"][stage]`에 있는 도구만 Agents SDK `FunctionTool`로 감싸 붙인다. 목록 밖 도구는 모델에게 보이지 않는다.
- `run_task`의 `tools` 인자를 `registry: ToolRegistry | None`으로 바꿨다. 기본은 운영 레지스트리(`soc.tools.default_registry()`)다. 레지스트리를 거치지 않고 도구를 붙이는 길은 없다.
- 도구 한 번 호출 순서: SDK `on_tool_start`에서 기록기(`LogRecorder`)가 `tool_call_id`별로 tool 줄(`agl_`)을 연다 → 레지스트리가 같은 `tool_call_id`로 그 `agl_`을 받는다 → 허용 확인 → 연속 실패 차단 확인 → 인자 검사 → 실행 → 자르기·`call_id` 붙이기·`<tool_result>` 감싸기·장부에 넣기 → 자르기 전 전체 결과와 성공·실패를 기록기에 넘긴다. 도구 결과의 `call_id`, Agent Log tool 줄 `id`, 장부 ID가 같은 값이다. 한 응답에 도구 호출이 여럿이어도 줄이 섞이지 않는다.
- 근거 장부 = 입력의 `allowed_evidence_ids` + 성공한 호출의 `agl_` + 모델에게 실제로 보인 `records` 결과의 `id` 값(`alt_`·`evt_`). 오류·차단된 호출의 `agl_`, 잘려서 안 보인 레코드의 id, 결과 본문 속 ID 모양 문자열은 들어가지 않는다(인용하면 `evidence_id_error`).
- 도구 오류는 `TOOL_ERROR tool=<이름> code=not_allowed|invalid_argument|unavailable|timeout|failed` + "다른 도구를 쓰거나 지금까지의 근거로 답하라" 한 가지 문구다. 예외 메시지·SQL·DB 주소는 모델과 `detail`에 가지 않는다. 같은 도구가 연속 2회 실패하면 남은 턴에서 실행하지 않고 `not_allowed`(`details.blocked=true`)다. `usage.tool_errors`는 `outcome=error`인 tool 줄 수다.
- 내부 데이터 도구 3개(`get_alert`, `get_event`, `query_records`)와 Web 도구 2개(`query_http_flow`, `summarize_http_flow`)를 만들었다. 모두 `AGENT_DATABASE_URL`로 도구 호출마다 새로 연결해 `alerts`·`events`만 매개변수 SQL로 읽는다. 세션은 `TimeZone=UTC`, `statement_timeout`, `default_transaction_read_only=on`, `connect_timeout`이다.
- 마이그레이션 `0003_agent_reader.sql`이 NOLOGIN 그룹 역할 `soc_agent_reader`를 없을 때만 만들고 `alerts`·`events`에 SELECT만 준다.
- 설정: `[tools]`(`statement_timeout_ms`, `connect_timeout_seconds`, `max_range_days`, `default_limit`, `max_limit`), `[tools.allowed]`(l1·l2·l3 모두 5개 도구), `[agent.l1~l3] max_tool_result_chars`(6,000 / 8,000 / 8,000). `[llm] strict_mode`가 도구 정의의 `strict_json_schema`로 들어간다. `.env.example`에 `AGENT_DATABASE_URL` 이름, `redact.py`의 DB 비밀번호 가림 대상에 `AGENT_DATABASE_URL`을 더했다.

## 계획과 달라진 점

- **결과 종류에 `aggregate`를 더했다(확정(계획 "바뀐 점")).** 계획의 `result_kind`는 `records`/`text` 둘이다. `summarize_http_flow`의 결과는 레코드 목록도 문자열도 아니고(건수 + 필드별 상위 값), 장부에 `call_id`만 넣고, 자르기를 "필드마다 건수가 적은 항목부터 뺀다"로 해야 해서 세 번째 종류로 두었다. `aggregate` 핸들러는 `CallContext.fits(결과)`로 한도(`call_id` 포함)를 확인하며 스스로 줄이고, 레지스트리는 id를 장부에 넣지 않는다. 동작은 계획 그대로이고 `ToolSpec`의 허용 값만 하나 늘었다. #212~#214가 `ToolSpec`을 그대로 쓰므로 알린다.
- **`ToolSpec`에 `check`를 더했다.** 인자 사이의 조건(시간 범위 상한, `kind`와 맞지 않는 필터, 엔티티 type·value 짝)을 실행 전에 검사해 `invalid_argument`로 돌려주는 자리다. 계획의 "인자 정의"를 구현하는 방법이다.
- **#209·#192 테스트에서 고친 곳이 계획의 "6곳"보다 많다**(지우거나 건너뛴 것은 없다).
  - `tests/test_agent_core.py`: `run()` 도우미, `run_task`를 직접 부르는 `test_retry_counts_toward_max_turns`·`test_unexpected_exception_does_not_escape`도 `registry=REGISTRY`를 넘긴다. 기본 운영 레지스트리에는 테스트용 `lookup_alert`가 없어 허용 목록 오타(`provider_error`)가 되기 때문이다.
  - `tests/test_agent_llm.py`: `run()` 도우미와 실제 openai 클라이언트를 쓰는 테스트 2곳도 같은 이유로 `registry=REGISTRY`.
  - `tests/test_agent_log_db.py`: 4곳.
  - `test_log_rows_for_ok_run`의 tool 줄 `output` 기대값이 레코드 목록이 되었다(`records` 도구는 목록을 돌려준다).
  - `tests/test_db_tables.py`의 적용 목록·건수에 `0003_agent_reader.sql`을 넣었다(#217·#221이 마이그레이션을 더할 때 한 것과 같다).

## 다음 사람이 알아야 할 것

- **에이전트 DB 접속 계정 만들기(운영자).** 마이그레이션은 그룹 역할만 만든다. 접속용 계정은 따로 만들고, 비밀번호는 `.env`의 `AGENT_DATABASE_URL`에만 둔다.

  ```sql
  CREATE ROLE <이름> LOGIN PASSWORD '<비밀번호>' IN ROLE soc_agent_reader;
  ```

  - `0003`을 적용하는 계정(`DATABASE_URL`)에는 CREATEROLE이 필요하다.
  - PostgreSQL 16 이상에서 CREATEROLE 계정이 `IN ROLE soc_agent_reader`를 쓰려면 그 역할의 ADMIN 권한이 있어야 한다. 역할을 만든 계정은 자동으로 ADMIN을 갖는다. 다른 계정이 만든다면 `GRANT soc_agent_reader TO <운영 계정> WITH ADMIN OPTION`이 먼저다.
  - 역할은 클러스터 전체에 하나다. 같은 클러스터의 다른 DB에 `0003`을 적용해도 역할을 다시 만들지 않고 그 DB의 `alerts`·`events` 권한만 준다.
- **가짜 도구를 넣는 법(#223 등).** `ToolSpec`을 만들어 `ToolRegistry`에 넣고 `run_task(registry=…)`로 넘긴다. 테스트 설정의 `[tools.allowed]`에 이름을 넣어야 붙는다. `config["agent"][stage]["max_tool_result_chars"]`와 `config["llm"]["strict_mode"]`도 있어야 한다(없으면 `provider_error`).

  ```python
  from soc.tools import Arg, ToolRegistry, ToolSpec

  def _lookup(args, ctx):  # ctx: CallContext(call_id, tools_config, ...)
      return [{"id": args["alert_id"], "title": "..."}]

  LOOKUP = ToolSpec(
      name="lookup_alert",
      description="Alert 하나를 읽는다(테스트용).",
      handler=_lookup,
      bundle="test",
      result_kind="records",   # records | text | aggregate
      id_fields=("id",),       # 이 칸의 값이 장부에 들어간다
      args=(Arg("alert_id", "string", required=True), Arg("note", "string")),
  )
  config = {..., "tools": {..., "allowed": {"l3": ["lookup_alert"]}}}
  run_task(task, model=..., model_name=..., log_sink=..., config=config,
           registry=ToolRegistry([LOOKUP]))
  ```

  - 핸들러가 실패를 알릴 때는 `raise ToolError("unavailable")`처럼 코드만 준다. 다른 예외는 모두 `failed`가 된다.
  - 도구를 모델 없이 직접 부르는 테스트 도우미는 `tests/tool_helpers.py`의 `Caller`다.
- **가짜 모델 step 형식이 늘었다**(`tests/fake_model.py`).
  - `{"tool_calls": [{"name": ..., "arguments": "..."}, ...]}`: 한 응답에 도구 호출 여러 개. SDK `call_id`는 `call_<모델 호출 번호>_<순서>`다(한 개짜리 `tool_call`은 그대로 `call_<번호>`).
  - `{"final_fn": f}`: 테스트 코드 안에서만 쓴다. `f`가 지금까지의 도구 결과 문자열 목록을 받아 최종 JSON 값을 만든다. 실행 중에 정해지는 `agl_`을 인용하는 Verdict를 만들 때 쓴다. JSON 파일 시나리오에는 넣을 수 없다.
- **SDK 0.24.0 순서에 기대고 있다.** `on_tool_start`가 도구 실행보다 먼저 불리고, 둘이 같은 `ToolContext.tool_call_id`를 받는다. SDK를 올리면 `test_call_id_is_the_tool_log_row_id_and_can_be_cited`, `test_two_tool_calls_in_one_response_keep_their_own_ids`가 먼저 확인한다. `tool_call_id`가 비었거나 겹치면 레지스트리는 `agl_`을 받지 못해 `TOOL_ERROR code=failed`를 돌려준다.
- **Agent Log tool 줄 `output`은 자르기 전 전체 결과다.** 오류면 `TOOL_ERROR` 문구다. SDK `on_tool_end`가 받는 잘린 문자열은 쓰지 않는다. 비밀 값 가림은 #209대로 쓰기 직전에 한다.
- **근거 장부가 바뀌었다(파이프·L1~L3 담당).** #209의 "도구 줄 `agl_`은 모두 장부"가 아니다. 오류·차단된 호출의 `agl_`을 인용하면 `evidence_id_error`다. `LogRecorder.tool_log_ids`는 남아 있지만 장부에는 `ToolSession.evidence_ids`를 쓴다.
- **`usage.tool_errors`가 실제 값이다.** 0 고정이 아니다.
- **#214 완료 기준 문장**은 "기본 설정에서는 도구가 등록되지 않는다(모델에게 보이지 않음). 레지스트리 함수를 목록 밖에서 직접 부르면 `not_allowed`"로 고쳐야 한다(이슈 담당).
- **`strict` 수용은 확인하지 않았다(#215).** strict일 때 선택 인자는 "required + null 허용"으로 정의하고 null이면 기본값을 쓴다. 실제 제공자가 strict 도구 정의를 거부하면 `strict_mode = false`로 둔다. 인자 검사는 strict와 상관없이 우리 코드가 한다.
- **`entities` 필터는 인덱스가 없다.** `entities @> %s::jsonb`는 지금 순차 조회다. 데이터가 커지면 GIN 인덱스를 L1 또는 공통 대역 마이그레이션으로 더한다(범위 밖).
- **`.serena/`는 커밋하지 않았다.** 개인 도구 설정이다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run pytest`: 558건 통과(`db`·`llm`·`qdrant` 마커 제외). Linux에서 실행했다
- `DATABASE_URL=… uv run pytest -m db`: 153건 통과. PostgreSQL 16, 테스트마다 임시 DB
- 새 테스트
  - `tests/test_tools_registry.py`(DB 없음, 가짜 모델·가짜 도구): 목록 밖 도구 미등록과 그것을 모델이 부르면 `format_error`, 목록 밖에서 레지스트리 함수를 부르면 `not_allowed`, 빈 허용 목록, 허용 목록 오타 `provider_error`, 이름 중복, `strict_json_schema`, 인자 검사(정의 밖·타입·enum·범위·길이·pattern), 핸들러 예외 메시지 숨김, 연속 2회 실패 차단과 성공 시 초기화, `usage.tool_errors`, `call_id` = tool 줄 id = 장부(한 응답 두 호출 포함), 오류·차단 `agl_`·본문 속 ID·잘려서 안 보인 id 인용 거부, 뒤 레코드부터 빼기와 Agent Log 전체, 긴 레코드의 문자열 줄이기·못 맞추면 0건, text 자르기, `</tool_result>` 탈출 방지, tool 줄 계약 검사, 운영 레지스트리 5개, `AGENT_DATABASE_URL` 없음·접속 불가 `unavailable`(비밀번호·주소가 결과와 기록에 없음)
  - `tests/test_tools_db.py`(`db` 마커, `tests/fixtures/tools/records.json`의 손으로 만든 Alert·Event): 읽기 역할로 `alerts`·`events` 읽기, `raw_records` 읽기·`alerts` 쓰기·`agent_logs` 읽기 권한 오류, 역할이 이미 있는 클러스터의 다른 DB에 `0003` 적용, 그룹 역할은 NOLOGIN, `get_alert`·`get_event`(없는 id 0건), `query_records` alert·event 필터와 kind에 맞지 않는 필터, LIKE 와일드카드 그대로 찾기, `query_http_flow`는 4002만, `summarize_http_flow` 상위 10개·120자·건수 적은 것부터 빼기, `statement_timeout` → `timeout`, 읽기 전용 세션
  - `tests/test_agent_redact.py`: `AGENT_DATABASE_URL`의 비밀번호 가림(고치기 전에는 실패)
- 실제 LLM 제공자로 도구를 부르지 않았다(#215).
