---
issue: 209
date: 2026-11-04
owner: Interludeal
plan: 209-agent-core.md
supersedes: []
---

# 에이전트 코어 run_agent와 Agent Log 저장을 만들었다

## 한 일

- `soc.agent.run_agent(AgentTask) -> AgentResult`(동기)를 만들었다. Agents SDK `Runner.run_sync`로 모델을 돌리고, 결과 처리는 다음 순서다: JSON 파싱 → `decided_at` 덮어쓰기 → `validate_contract` → 형식 오류면 1회 재요청 → 근거 장부 검사. 어떤 실패에도 예외 대신 `AgentResult`를 돌려준다.
- failure는 7종이다(`log_error` 추가). L1 처리에서 `log_error`는 `provider_error`와 같다: 다시 하고, 재시도 한도를 넘으면 `held`.
- 모델·도구 호출마다 Agent Log 한 줄을 SDK 훅(`RunHooks`)으로 모은다. 비밀 값을 가리고 `validate_contract("agent_log")`를 거친 뒤 반환 전에 한 트랜잭션으로 `agent_logs`에 쓴다. 쓰지 못하면 `log_error`이고, 그 실행의 줄은 하나도 남지 않는다.
- 트레이싱은 진입점에서 `set_tracing_disabled(True)`로 끈다(에이전트 프레임워크, D-022).
- 설정은 `config/default.toml` 위에 `config/local.toml`을 덮어쓴다. `[llm]`·`[agent]`·`[tools]`만 읽는다.
- 운영 모델은 아직 없다. `run_agent`를 부르면 `provider_error`("LLM 연결 설정이 없다")를 돌려준다. 실제 연결은 #210에서 붙인다.

## 계획과 달라진 점

- **작업 검사는 `AgentTask`를 만들 때 한다.** 잘못된 stage·계약 이름·subject_id 모양·근거 ID 모양·domains·attempt는 `ValueError`다. failure 7종 중 "파이프가 잘못 만든 작업"에 맞는 값이 없다. 계획의 "예외 없음"은 실행 중 실패에 대한 약속이라, 실행 전 프로그래밍 오류는 만들 때 바로 알리게 했다. `run_agent` 자체는 예외를 내지 않는다.
- **내부 함수 이름은 `soc.agent.runner.run_task`다.** 계획의 "model과 log_sink를 받는 내부 함수"에 해당한다. 도구를 넘기는 `tools` 인자도 받는다. 도구 레지스트리(#211)가 생기기 전까지 테스트용 함수 도구를 넣는 자리다.
- **`AgentResult.output`은 검증을 통과한 JSON 값(dict)이다.** 생성된 Pydantic 모델이 아니다. 파이프가 그대로 DB에 쓸 수 있게 했다.
- **`ModelBehaviorError`는 `format_error`로 보낸다.** 모델이 없는 도구를 부르는 경우처럼 SDK가 모델 출력을 처리하지 못한 경우다.
- **로그 쓰기 실패는 앞의 실패를 덮는다.** 예를 들어 `provider_error`로 끝났는데 Agent Log도 못 썼으면 `log_error`로 돌려준다. 기록이 없는 실행이라는 점이 더 중요하기 때문이다. 원래 failure 종류는 `detail` 끝에 `; prior=<failure>`로 남긴다(예: `Agent Log를 쓰지 못했다(LogWriteError); prior=format_error`). DB 주소·비밀 값·예외 메시지는 넣지 않는다. 앞의 실패가 없으면 `prior=`를 붙이지 않는다.
- **담당자 확인 작업은 #210으로 옮겼다.** 크레딧 구독의 "Sold by Azure" 표시, 배포 리전, TPM 확인이 대상이다. 기본 LLM 결정(D-009)을 #210으로 옮겼으므로, Foundry를 쓸 수 있는지 확인하는 일도 그쪽에 있어야 한다. #210 계획 때 다룰 항목이다. 계획 파일은 고치지 않았다(원칙 8).
- **재요청에 남은 턴이 없으면 `budget_exceeded`다.** 이때 마지막 model 줄의 `details.validation`은 `format_error`다. 재요청도 `max_turns` 안에서 센다는 계획에 따른 것이다.

## 다음 사람이 알아야 할 것

- **가짜 모델 시나리오 형식** (`tests/fixtures/agent/*.json`, `tests/fake_model.py`). `steps`를 앞에서부터 하나씩 내놓고, 모델이 한 번 불릴 때 한 step을 쓴다.
  - `{"tool_call": {"name": "...", "arguments": {...}}}`: 함수 도구 호출
  - `{"final": {...}}`: JSON으로 바꾼 최종 답
  - `{"final_text": "..."}`: JSON이 아닌 최종 답(형식 오류용)
  - `{"raise": "rate_limited" | "provider_error"}`: openai `RateLimitError` / `APIConnectionError`를 낸다
  - 각 step에 `"usage": {"input_tokens": n, "output_tokens": m}`을 붙일 수 있다(기본 10/5)
  - steps를 다 쓴 뒤 또 불리면 `AssertionError`다
  - `FakeModel.calls`에 호출마다 받은 system·input·model_settings·tools·output_schema가 남는다
- **openai 3.x는 `httpx`가 아니라 `httpx2`를 쓴다.** 가짜 모델이 openai 예외를 만들 때 `httpx2.Request`/`Response`가 필요하다. `httpx2`는 openai가 끌어오는 의존성이라 따로 넣지 않았다.
- **트레이싱 끄기는 전역 스위치(`set_tracing_disabled`)가 본체다.** `RunConfig(tracing_disabled=True)`도 함께 두었지만, 시험해 보니 전역 스위치만 빼도 테스트가 실패하고, `RunConfig`만 빼면 그대로 통과한다. 진입점의 호출을 지우면 안 된다.
- **구분자 탈출 방지.** `data`는 JSON으로 바꾼 뒤 `<`·`>`를 `<`·`>`로 바꿔 `<data>…</data>` 안에 넣는다. 데이터 속 `</data>`로 구분자를 닫을 수 없다.
- **근거 장부.** `allowed_evidence_ids`와 이 실행의 도구 줄 `agl_` ID로 이뤄진다. 도구 결과에 `call_id`를 붙여 모델에게 알려 주는 일과 `records` 결과의 `id`를 장부에 넣는 일은 도구 레지스트리(#211)가 한다. 그전까지 모델은 `agl_` ID를 알 방법이 없다.
- **`decided_at` 판단에 비공개 이름을 쓴다.** 출력 계약 최상위에 `decided_at`이 있는지 보려고 `soc.contracts.validate._CONTRACTS`의 생성 모델 필드를 읽기만 한다. 계약 모듈(#192)에 계약 최상위 필드를 조회하는 공개 함수가 생기면 바꾼다. 계약 담당에게 그 함수를 요청했다.
- **`AgentTask`를 만들 때 `ValueError`가 나는 조건(파이프 담당이 알아야 함).** `run_agent`를 부르기 전, 작업을 만드는 순간 거부된다. 메시지에 입력 값은 넣지 않는다.
  - `stage`가 `l1`/`l2`/`l3`이 아니다
  - `task`가 문자열이 아니거나 비어 있다
  - `prompt`가 `TaskPrompt`가 아니다. `TaskPrompt`는 `text`가 비어 있거나(공백만 포함) `version`이 비어 있으면 만들 때 거부된다
  - `output_contract`가 계약 이름(`soc.contracts.CONTRACT_NAMES`)이 아니다
  - `cited_ids`가 함수가 아니다
  - `subject_type`이 `alert`/`ticket`/`incident`/`hunt`가 아니다
  - `subject_id`가 비어 있다. `alert`·`ticket`·`incident`는 각각 `alt_`·`tkt_`·`inc_` + UUIDv7 모양이어야 한다. `hunt`는 빈 문자열만 거부한다
  - `allowed_evidence_ids`에 `alt_`/`evt_`/`agl_` + UUIDv7 모양이 아닌 값이 있다
  - `domains`에 `web`/`cloud` 밖의 값이 있다
  - `attempt`가 1 이상의 정수가 아니다(bool도 거부)
- **비밀 값 가림 규칙.** 4글자보다 짧은 환경변수 값은 평범한 낱말까지 지워서 가리지 않는다. DB 비밀번호는 `DATABASE_URL`에서만 꺼낸다. `AGENT_DATABASE_URL`이 생기면(#211) `redact.py`의 `_DATABASE_URL_ENVS`에 더한다.
- **줄의 outcome.** 실패한 실행은 마지막 model 줄에 `outcome=error`와 `details.failure`를 남긴다. 모델 호출 자체가 예외로 끝난 줄은 `output`이 SQL NULL이고 토큰이 null이다. 도구 줄의 오류 처리(`TOOL_ERROR` 문구, `outcome=error`)는 #211이 한다. 지금은 도구 줄이 항상 `ok`다.
- **`config/default.toml`의 `[agent.*]`에는 `max_turns`만 있다.** 나머지 예산 값과 `[llm]` 연결은 #210, `[tools]`의 허용 목록은 #211에서 더한다.
- **db 테스트 실행.** `tests/test_agent_log_db.py`는 `db` 마커라 CI의 db job이 돌린다(이미 있는 단계).

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run pytest`: 326건 통과
- `DATABASE_URL=… uv run pytest -m db`: 80건 통과(로컬 PostgreSQL 16.15. CI는 17.6)
- `uv run python scripts/generate_contracts.py --check`: 통과
- 주요 테스트
  - `tests/test_agent_core.py`: 정상 Verdict, 형식 오류 재요청, `format_error`, `evidence_id_error`, `budget_exceeded`, `rate_limited`·`provider_error`, `log_error`(`prior=` 포함), `decided_at`, 트레이싱 꺼짐, Agent Log 줄, 비밀 값 가림, AgentTask 검사
  - `tests/test_agent_log_db.py`: 커밋 확인, SQL NULL, 접속 실패 → `log_error`, 중간 실패 시 롤백
  - `tests/test_agent_redact.py`, `tests/test_agent_config.py`
- 트레이싱 테스트를 확인했다: 진입점의 `set_tracing_disabled(True)`를 빼면 실패한다.
- 담당자 확인 작업(Sold by Azure 표시, 리전, TPM)은 #210으로 옮겨 이 이슈에서는 하지 않았다.
