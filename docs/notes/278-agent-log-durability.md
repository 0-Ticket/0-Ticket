---
issue: 278
date: 2026-11-10
owner: Interludeal
plan: 278-agent-log-durability.md
supersedes: ["211-tool-registry.md"]  # "Agent Log tool 줄 output은 자르기 전 전체 결과다"를 records 도구에 한해 바꾼다
---

# Agent Log를 호출마다 쓰고, 시작 전 실패도 남기고, 저장 크기를 줄였다

## 한 일

- **호출이 끝날 때마다 줄을 쓴다.** 강제 종료·종료 대기 초과·쓰기 실패가 나도 끝난 호출의 줄이 DB에 남는다. 도구 호출이 없는 최종 답 model 줄만 다음 호출이 시작되거나 `finalize`가 돌 때까지 보류한다(그 줄에 `validation`·`failure`를 붙이기 위해서다). 줄 하나 쓰기가 실패하면 그 run은 쓰기를 멈추고, `finalize`가 안 쓴 줄을 한 번 더 시도하고, 그래도 실패하면 `log_error`다(출력은 살리지 않는다).
- **쓰기는 줄마다 새 데몬 스레드로 한다.** `asyncio.wrap_future` + `wait_for`로 클라이언트 쪽 마감(`[agent] log_connect_timeout_seconds` + `log_statement_timeout_ms`, 기본 약 10초)을 둔다. 멈춘 DB가 훅과 프로세스 종료를 붙잡지 않는다. 줄마다 짧은 연결을 연다. `INSERT`는 `ON CONFLICT DO NOTHING`이다.
- **시작 전 실패도 줄을 남긴다.** 설정 읽기·LLM 연결·프롬프트 합성·도구 설정 오류는 `kind=model`, `outcome=error`, `details.failure`, `details.sent=false`인 줄 하나를 남긴다. 돌려준 `run_id`와 줄의 `run_id`가 같다. 예산 초과 줄과 종료 줄도 같은 모양이다(`LogRecorder.add_unsent`).
- **저장 크기를 줄였다.** model 줄 `input`은 새로 더해진 항목만 저장하고, `records` 도구 줄 `output`은 모델에게 보인 결과(뺀 건수 포함)만 저장한다. L2 예산 최대 시나리오(레코드 100건 × 약 2,000자, 10턴에서 `budget_exceeded`)의 model 줄 `input` + 도구 줄 `output` 합계가 2,353,208자에서 123,667자로 줄었다(상한 160,000자).
- **읽는 쪽을 맞췄다.** `summarize_runs`는 끝났다는 표시가 없는 run을 `incomplete`로 보이고, L3 `last_attempt_started_at`은 그런 run을 시도로 세지 않는다.
- D-036 문장을 고쳤다(`docs/decisions.md`).

### Agent Log 읽는 규칙 (D-036 메모에도 있다)

- 끝난 run에는 `details.validation` 또는 `details.failure`가 있는 model 줄이 있다. 그런 줄이 없으면 진행 중이거나 강제 종료된 run이다.
- `details.sent=false` 줄은 모델에 보낸 호출이 아니다(예산 초과, 시작 전 실패, 종료 줄). `usage.turns`와 입력 복원에서 뺀다.
- 입력 복원: 같은 `run_id`의 model 줄(`sent=false` 제외)을 `seq` 순으로 본다. 첫 줄은 `input = {"system", "input"}`이고 이후 줄은 `input = {"input_from": k, "input": [...]}`다. k번째 호출의 전체 입력은 앞 호출의 전체 입력 앞 `input_from`개 + 이 줄의 `input`이다. 앞 입력의 접두가 아니면 `input_from = 0`이고 `details.input_reset = true`다. system 지시는 첫 줄에만 있고 이후 줄은 `details.prompt_version`이 가리킨다.
- 줄은 호출이 끝날 때 쓰므로 호출 중에 죽은 run은 그 호출의 줄이 없다. 마지막 줄이 `outcome=ok`여도 끝난 것이 아니다.

## 계획과 달라진 점

- **형식 오류 재요청의 입력도 앞 입력의 접두다.** 계획은 접두가 아닌 예로 형식 오류 재요청을 들었지만, SDK의 재요청 입력(`to_input_list()` + 사용자 메시지)은 앞 호출의 입력을 그대로 잇는다(테스트로 확인). 그래서 `input_reset`은 지금 SDK 실행에서는 나오지 않고, 기록기에 접두가 아닌 입력을 직접 넣는 테스트로만 확인한다. SDK 버전이 바뀌어 항목 모양이 달라지면 나타날 수 있다.
- **`tests/test_agent_log_db.py::test_partial_write_is_rolled_back`를 바꿨다.** 이 테스트는 같은 `(run_id, seq)`가 이미 있으면 유일 제약 오류로 묶음 전체가 롤백되는 것을 봤다. 계획대로 `ON CONFLICT DO NOTHING`을 쓰면 같은 `(run_id, seq)`는 오류가 아니라 건너뛰므로, 같은 뜻(한 번에 쓰는 묶음은 한 트랜잭션)을 `seq = 0` 검사 위반으로 확인하게 고쳤다. 같은 `(run_id, seq)`를 건너뛰는 것은 `test_agent_log_durability_db.py`가 따로 본다.
- **API 샘플의 끝난 run에 `"validation": "ok"`를 더했다**(`tests/fixtures/api/seed.json` 4건, `ui_seed.json` 1건). 읽는 규칙이 생겨 표시가 없으면 `incomplete`로 보이기 때문이다. `ui_seed.json`은 개발 DB 시드(`python -m soc.api.dev_seed`)의 원본이다. 이미 시드한 개발 DB에서는 그 Agent Log 행이 샘플과 달라 시드가 전체를 되돌린다. 해당 행(`seed_source = dev-seed-ui`인 `agent_logs`)을 지우거나 개발 DB를 다시 만든 뒤 시드한다.
- **테스트를 두 db 파일로 나눴다.** 호출마다 쓰기는 `tests/test_agent_log_durability_db.py`, L3 시도 계산은 `tests/test_l3_attempts_db.py`다.
- **계약 검사에 실패한 줄은 쓰기 실패와 같게 다룬다**(계획의 "개발 때 정함"). 줄마다 가림·`validate_contract`가 `RowWriter.prepare`에서 돌고, 예외는 첫 실패로 센다.
- **시작 전 실패 줄의 `input`은 `{}`, `name`은 `model_name`(없으면 `unknown`)이다.** 프롬프트를 만들기 전에 실패하면 `details.prompt_version`이 없다("개발 때 정함").
- **`run_task`에 선택 인자 `run_id`를 더했다.** `run_agent`가 시작 전 실패의 줄과 같은 `run_id`를 쓰려고 넘긴다. 기본(없음)은 지금까지와 같다.
- **`records` 도구 줄의 `output`이 목록에서 본문 객체로 바뀌었다**(`{"call_id", "records", "truncated", "omitted", ...}`). 그 줄 `id`와 `call_id`가 같다. 이 줄을 읽는 코드는 레포 안에 없다(읽는 곳은 줄이 있는지만 본다).

## 다음 사람이 알아야 할 것

- **#215 측정 SQL(`runs_l1.sql`, `summary_l1.sql`)을 고쳐 써야 한다.** 지난 기록은 고치지 않는다. 바뀐 점만 적는다.
  - `turns`: `count(*) FILTER (WHERE kind = 'model' AND (details->>'sent') IS DISTINCT FROM 'false')`. `sent=false` 줄을 뺀다.
  - `max_model_input_len`: model 줄 `input`이 새로 더해진 항목뿐이라 한 줄로는 입력 크기를 알 수 없다. 마지막 입력의 크기는 `sum(length((input->'input')::text)) FILTER (WHERE kind = 'model' AND (details->>'sent') IS DISTINCT FROM 'false')`로 근사한다(system 지시는 첫 줄 `input->'system'`에 한 번만 있다).
  - `runs`·`validation`: 끝났다는 표시가 없는 run(강제 종료)과 시작 전 실패 run도 센다. `validation = 'ok'`와 `failure`로 나눠 본다.
  - `empty_responses`: `outcome = 'ok'` 조건이 `sent=false` 줄을 이미 뺀다.
- **끝났다는 표시는 `finalize`가 붙인다. 이미 전달한 줄은 바꾸지 않는다.** 마지막 model 줄이 이미 전달됐으면(도구 호출을 낸 줄 뒤에 `MaxTurnsExceeded`·도구 실행 중 취소·`ModelBehaviorError`로 끝난 경우) 그 줄에 `failure`를 붙이지 않고 `sent=false` 종료 줄을 덧붙인다. 마지막 줄이 도구 호출을 낸 `outcome=ok` 줄이어도 `summarize_runs`가 `error`로 보는 이유다. 테스트가 세 경우를 고정한다(`test_failure_after_a_written_model_row_adds_an_unsent_closing_line`).
- **줄 내용은 첫 전달 때 고정한다.** 마감을 넘기거나 취소돼 결과를 못 본 줄은 `finalize`가 같은 내용으로 다시 쓴다(`DO NOTHING`이 중복을 막는다). 줄을 만든 뒤에 내용을 바꾸는 코드를 더하면 다시 쓰는 줄과 먼저 쓴 줄이 달라질 수 있다. `test_rewritten_rows_are_identical_to_the_first_write`가 지킨다.
- **접속 인자(`keepalives*`, `tcp_user_timeout`)는 상대 호스트가 사라진 경우에만 연결을 닫는다.** DB 프로세스만 멈추고 커널이 응답하는 경우에는 마감 뒤에도 쓰기 스레드가 남는다(libpq에 클라이언트 읽기 제한이 없다). 남는 스레드는 run마다 최대 2개(훅의 첫 실패 쓰기 + `finalize` 재시도)이고 DB가 얼면 워커가 `run_agent` 전에 DB를 읽다가 먼저 멈춰 새 run이 시작되지 않는다. `tcp_user_timeout`은 Linux에서만 적용된다고 알려져 있다(이 PC는 Windows라 확인하지 못했다). 번들 libpq 18이 인자 이름을 받는 것과, `PostgresLogSink`가 인자를 `psycopg.connect`에 넘기는 것만 테스트한다. 값과 근거는 계획 파일에 있다.
- **`asyncio.to_thread`는 쓰지 않는다.** 기본 실행기 스레드는 프로세스가 끝날 때 합류돼서 멈춘 쓰기가 종료를 막는다(8초 걸리는 작업을 0.5초에 포기해도 프로세스가 8.4초 뒤에 끝났다). 전용 데몬 스레드를 줄마다 새로 만든다.
- **DB에 쓸 수 없는 실패는 줄이 없다.** `DATABASE_URL`이 없으면 `run_agent`는 줄 없이 `log_error`를 돌려주고 실행기 로그(`soc.agent.runner`)에 경고만 남긴다(주소·비밀 없음). DB에 접속할 수 없으면 시작 전 실패도 줄을 못 쓰고 `log_error`(`prior=` 포함)다. 테스트가 고정한다.
- **L3 동작이 바뀐다(L3 담당 알림).** 시작 전 실패(설정 오류 등)도 `last_attempt_started_at`에서 시도로 세므로 다음 생성이 `generate_interval_seconds`만큼 늦어진다. 끝났다는 표시가 없는 run(강제 종료)은 시도로 세지 않는다(#245의 `cancelled` 취급과 같다).
- **`usage.turns`가 줄었다.** `sent=false` 줄은 세지 않는다. `budget_exceeded`로 끝난 run은 값이 1 줄어든다(예산 초과 줄을 세던 것이 바뀌었다).
- **화면(화면 담당 알림):** `RunSummary.outcome`에 `"incomplete"`가 생겼다. 화면은 값을 그대로 보여 준다. 한글 표시는 후속이다.
- **`agent_log` 계약의 `details` 설명("다른 단계는 읽지 않는다")은 #278 이전부터 `hunts.py`·`store.py`가 읽는 것과 어긋난다.** 이 이슈에서 계약은 고치지 않았다(계약 담당 알림, 후속 이슈 초안).
- **#279·#280은 #278이 머지된 뒤 리베이스한다.** 같은 `runner.py`·`registry.py`를 고친다. #280 C4(동기 도구가 이벤트 루프를 막음)는 이 이슈 범위 밖이다. 이 이슈의 쓰기 스레드는 그 문제를 고치지 않는다.
- **워커의 DB 접속에는 시간 제한이 없다**(예: `soc/l1/judge.py`의 `psycopg.connect`). 범위 밖이고 #280에서 본다.
- **확인하지 못한 것:**
  - 이 PC에 PostgreSQL·Docker가 없어 `db` 마커 테스트는 돌리지 못했다(CI의 db 단계에서 돈다). 호출마다 커밋, `ON CONFLICT`, 묶음 롤백, L3 시도 쿼리, 실제 접속 인자는 그 테스트가 본다.
  - 프런트엔드 의존성(`pnpm install`)을 설치하지 않아 `pnpm lint`·`pnpm test`·`pnpm build`, `pnpm contracts:check`를 돌리지 못했다. 생성 TS(`HuntDetail.ts`)의 `Outcome` 한 줄은 직접 고쳤다. `scripts/export_api_schemas.py`가 내보내는 enum(`ok`, `error`, `incomplete`)과 같은 값이다.
  - 실제 PostgreSQL이 얼었을 때의 동작은 시험하지 못했다. 가짜 기록기가 멈추는 경우만 본다.
- `tests/test_migrate.py::test_name_ending_in_newline_is_not_a_migration`는 Windows가 줄바꿈이 든 파일명을 만들지 못해 실패한다. #273 기록에도 같은 내용이 있다(이 변경과 무관).
- 이 PC(Windows, cp949)에서는 `tests/test_api_seed.py`·`test_api_ui.py`가 `ui_seed.json`을 인코딩 없이 읽어 수집 단계에서 실패한다. `PYTHONUTF8=1`을 주면 통과한다(원래 파일에서도 같다).

## 확인 방법

- `PYTHONUTF8=1 uv run ruff format --check .`: 통과
- `PYTHONUTF8=1 uv run ruff check .`: 통과
- `PYTHONUTF8=1 uv run python scripts/generate_contracts.py --check`: 통과
- `PYTHONUTF8=1 uv run pytest`: 1,403건 통과, 1건 실패(위 `test_migrate` Windows 줄바꿈 파일명, 변경과 무관)
- 테스트를 먼저 썼다. 구현 전 새 테스트 29개 중 25개가 실패했다(통과한 4개는 동작이 같은 회귀 테스트).
- 주요 테스트
  - `tests/test_agent_log_durability.py`: 호출마다 쓰기, 최종 답 줄 보류, 첫 실패에서 중단·재시도, 재시도 실패 시 `log_error`와 남은 줄, 다시 쓰는 줄이 같은 내용, 종료 줄 3가지(`MaxTurnsExceeded`·도구 실행 중 취소·없는 도구 호출)와 `summarize_runs`의 `error`, 강제 종료 run의 `incomplete`, 멈춘 DB(마감 안에 풀림·데몬 스레드·다음 run은 정상), 접속 인자, 시작 전 실패 5가지, `usage.turns`, 입력 복원(재요청 입력은 접두, 접두가 아닌 입력은 `input_reset`으로 직접 확인), `records` 줄이 모델이 본 결과, L2 최대 시나리오 160,000자 이하
  - `tests/test_api_run_summary.py`: `summarize_runs`의 `ok`/`error`/`incomplete`
  - `tests/test_agent_log_durability_db.py`, `tests/test_l3_attempts_db.py`(db 마커, 이 PC에서는 돌리지 못함)
  - 고친 기존 테스트: `test_agent_core`·`test_agent_llm`(`run_agent`가 `DATABASE_URL`을 먼저 읽음), `test_tools_registry`·`test_tools_db`(`records` 줄 `output`), `test_agent_log_db`(묶음 롤백)
- 손으로 잰 값(가짜 모델, 실제 `l2_investigate` system 3,585자·UUID ID·레코드 100건 × 약 2,000자): 변경 전 합계 2,353,208자(model `input` 328,122 + 도구 `output` 2,024,000) → 변경 후 123,667자(model `input` 61,927 + 도구 `output` 61,740, 도구 줄 하나 최대 6,174). 10턴에서 `budget_exceeded`로 끝난다.
