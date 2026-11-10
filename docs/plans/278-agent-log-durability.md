---
issue: 278
date: 2026-11-10
owner: Interludeal
supersedes: []
---

# Agent Log 기록이 사라지지 않게 하고 크기 줄이기

## 목표

Agent Log가 실행 도중 멈추거나, 쓰기에 실패하거나, 실행 시작 전에 실패해도 끝난 호출의 줄이 DB에 남게 한다. 한 실행이 저장하는 크기를 L2 예산 최대 시나리오 기준 160,000자 이하로 줄인다. 실행이 끝났는지는 읽는 쪽이 줄만 보고 판단할 수 있어야 한다.

## 방법

기준 커밋 `5a9ab2d` 이후 `src/soc/agent`·`src/soc/tools`는 바뀐 것이 없다(확정 시점 `b0e4dd1`). 이슈 재현(C2 줄 0개 / `log_error`일 때 `output=None`, C3 줄 0개, C5 합계 약 235만 자)은 현재 main에서도 그대로였다.

### C2. 호출이 끝날 때마다 줄을 쓴다

- `LogRecorder`가 model·tool 호출이 끝날 때마다 그 줄을 쓴다. 도구 호출이 없는 최종 답 model 줄만 다음 호출이 시작되거나 `finalize`가 돌 때까지 보류한다. `finalize`가 그 줄에 `validation`·`failure`를 붙여야 하기 때문이다.
- **줄은 훅이 전달한 순간부터 내용을 고정한다.** `seq`는 줄을 만들 때 정해진다. 이미 전달한 줄에는 `validation`·`failure`를 붙이지 않는다. 붙일 수 없는 경우(`MaxTurnsExceeded`, 도구 실행 중 취소, 모델이 없는 도구를 불러 `ModelBehaviorError`)는 종료 줄을 덧붙인다.
- **`sent=false` 줄 한 가지로 모은다.** 예산 초과 줄(`add_budget_exceeded`), 시작 전 실패 줄(C3), 종료 줄이 같은 모양이다: `kind=model`, `outcome=error`, `details.failure`, `details.sent=false`. 종료 줄에는 필요하면 `details.validation`도 붙인다. 같은 함수로 만든다.
- 쓰기: `INSERT ... ON CONFLICT DO NOTHING`. 먼저 쓴 줄이 남는다. 줄마다 `redact`·`validate_contract`를 거친다(지금은 끝에 한꺼번에 하던 것을 줄마다 한다). 계약 검사가 실패한 줄을 어떻게 다룰지는 개발 때 정한다(이 계획의 변경이 아님, 제안은 쓰기 실패와 같게 다루기).
- **줄 하나 쓰기가 실패하면** 그 run은 쓰기를 멈춘다. `finalize`가 안 쓴 줄을 한 번 더 시도하고, 그래도 실패하면 `log_error`로 끝낸다(`output=None`, `prior=` 유지). 이미 쓴 줄은 남긴다. `log_error`일 때 검증을 통과한 출력은 살리지 않는다. 파이프가 결과를 저장하는 곳도 같은 PostgreSQL이라 얻는 것이 작고, 근거 `agl_` 줄이 없는 판정이 나갈 수 있기 때문이다(`docs/architecture.md` 원칙 3).
- **쓰기 방식**
  - 훅 안에서는 줄을 쓸 때마다 **새 데몬 스레드**를 만든다. 쓰기 스레드 하나를 계속 쓰지 않는다. 한 스레드가 얼어 있는 쓰기에 걸리면 같은 프로세스의 다음 run 쓰기가 그 뒤에 줄을 서기 때문이다. `concurrent.futures.Future`를 `asyncio.wrap_future`로 감싸 `wait_for`로 기다린다.
  - `asyncio.to_thread`는 쓰지 않는다. 기본 실행기 스레드는 프로세스가 끝날 때 합류되어 멈춘 쓰기가 종료를 막는다(8초짜리 모의 작업을 0.5초에 포기해도 프로세스가 8.4초 뒤에 끝나는 것을 확인했다).
  - **마감** = `[agent] log_connect_timeout_seconds` + `[agent] log_statement_timeout_ms`(기본 5초 + 5초 = 약 10초). 클라이언트 쪽 마감이다. `finalize`(이벤트 루프가 끝난 동기 코드) 재시도도 같은 마감을 쓴다. 마감이 지나면 쓰기 실패로 본다. 그 줄은 "쓰였을 수 있음"이라 고정 규칙과 `DO NOTHING`으로 재시도가 안전하다.
  - 줄마다 짧은 연결을 열고, run 동안 연결을 열어 두지 않는다. 접속 인자: `connect_timeout`, `options='-c statement_timeout=<ms>'`.
  - 설정을 읽지 못하는 경우(C3)는 같은 값의 코드 기본값을 쓴다.
  - 최악의 지연: DB가 얼면 훅 쪽 마감 한 번 + `finalize` 재시도 한 번 ≈ 20초. `shutdown_timeout_seconds`(30초) 안이다.
- **접속 인자(코드 고정값, 새 설정 키 없음)**

  | 인자 | 값 | 근거 |
  |---|---|---|
  | `keepalives` | 1 | 끊긴 상대를 감지하기 위해 켠다 |
  | `keepalives_idle` | 10 | 유휴 10초 뒤부터 확인한다 |
  | `keepalives_interval` | 5 | 5초 간격으로 보낸다 |
  | `keepalives_count` | 2 | 2번 응답이 없으면 닫는다 → 유휴 연결은 약 20초 안에 감지 |
  | `tcp_user_timeout` | 10000 (ms) | 마감(10초)과 같게 두어, 클라이언트가 포기할 때 맞춰 연결을 닫는다 |

  - **한계.** 이 인자들은 상대 호스트가 사라졌거나 네트워크가 끊긴 경우에만 닫는다. DB 프로세스만 멈추고 커널은 응답하는 경우에는 작동하지 않는다(libpq에 클라이언트 읽기 제한이 없고, `statement_timeout`은 서버가 멈추면 동작하지 않는다). 그때 마감 뒤에도 그 스레드는 남는다.
  - 그래서 스레드 누적은 막는 것이 아니라 **줄이고 제한**하는 것이다. run마다 최대 2개(훅의 첫 실패 쓰기 1개 + `finalize` 재시도 1개)이고, DB가 얼면 워커가 `run_agent` 전에 DB를 읽다가 먼저 멈춰 새 run이 시작되지 않는다.
  - `tcp_user_timeout`은 libpq 문서상 `TCP_USER_TIMEOUT`을 지원하는 시스템(Linux)에서만 적용된다. Windows·맥에서는 무시될 수 있다(미확인). 번들 libpq 18이 모든 인자 이름을 받는 것은 확인했다. 동작은 시험하지 못하고, 접속 인자가 `psycopg.connect`에 넘어가는지만 테스트로 고정한다.
- 설정 키: `config/default.toml`의 `[agent]` 바로 아래 `log_connect_timeout_seconds = 5`, `log_statement_timeout_ms = 5000`.

### C3. 시작 전 실패도 줄로 남긴다

- 설정 읽기·LLM 연결·프롬프트 합성·도구 설정 오류로 끝난 실행은 `sent=false` 줄 하나(`kind=model`, `outcome=error`, `details.failure`)를 남긴다. 계약(#193)은 바꾸지 않는다. 선례는 `add_budget_exceeded`다.
- `run_agent`는 `DATABASE_URL`을 설정 읽기보다 먼저 읽는다. `run_id` 하나를 `run_agent`·`run_task`·줄에 끝까지 쓴다(지금 `_failed()`와 `ToolConfigError` 경로는 새 `run_id`를 만든다).
- **DB에 쓸 수 없는 실패**(`DATABASE_URL` 없음, DB 접속 불가)는 줄을 남기지 못한다. 실행기 로그로만 남기고 `AgentResult`는 지금처럼 `log_error`다. 이 한계를 notes에 적고 테스트로 고정한다(로그에 주소·비밀이 없음).
- `usage.turns`는 `details.sent=false` 줄을 뺀다. 지금은 `budget_exceeded` 줄도 센다(바뀐 점).
- 시작 전 실패는 L3 시도로 센다(줄에 `details.failure`가 있으므로).
- 개발 때 정함(이 계획의 변경이 아님): 줄의 `input` 모양(고정 문장), `name`(`model_name` 또는 `unknown`), 프롬프트 합성 실패 시 `details.prompt_version`.

### C5. 저장 크기를 줄인다

- **model 줄 `input`**: 첫 줄은 `{"system": ..., "input": [...]}`, 이후 줄은 `{"input_from": k, "input": [새 항목...]}`. system 지시는 첫 줄에만 있고 이후 줄은 `details.prompt_version`이 가리킨다. 같은 `run_id`의 model 줄을 `seq` 순으로 이어 붙이면 그 호출의 전체 입력이 된다. 앞 호출 입력의 접두가 아니면(형식 오류 재요청 등) 전체를 저장하고 `details.input_reset=true`를 단다. `sent=false` 줄은 이어 붙이기에서 뺀다.
- **`records` 도구 줄 `output`**: 모델에게 보인 결과 본문(뺀 건수 `omitted` 포함)을 저장한다. 레지스트리가 `_shape_records`가 만든 본문을 기록기에 넘기고, 본문은 구조상 `max_tool_result_chars` 이하다. `aggregate` 도구는 이미 줄인 결과를 저장하므로 그대로다.
- 한 실행의 model 줄 `input` + 도구 줄 `output` 합계 상한은 **160,000자**다. 코드에서 자르지 않고 테스트로 확인한다. 모델 출력 줄은 상한 없이 두고 측정만 기록한다.
- 예상 크기(가짜 모델, 실제 `l2_investigate` system 3,585자, UUID ID, 레코드 100건 × 약 2,000자, 10턴에서 `budget_exceeded`로 끝남)

  | 조합 | model 줄 `input` 합 | 도구 줄 `output` 합 | 합계 |
  |---|---|---|---|
  | 현재(실측) | 328,122 | 2,024,000 | 2,353,208 |
  | A만 (system 반복) | ≈ 93,900 | 2,024,000 | ≈ 2,120,000 |
  | A+B | ≈ 61,700 | 2,024,000 | ≈ 2,090,000 |
  | C만 | 328,122 | ≤ 80,000 | ≤ 410,000 |
  | **A+B+C (채택)** | ≈ 61,700 | ≤ 80,000 | **≤ 143,000** |

  12턴까지 가는 최악은 입력 ≤ 64,000 + 도구 줄 11 × 8,000 = 152,000자 이하(모델 출력 제외)다.
- `docs/decisions.md` D-036 문장을 고쳤다(이 계획과 같은 커밋). 읽는 규칙도 D-036 메모에 있다.

### 읽는 쪽

- **읽는 규칙**: 끝난 run에는 `details.validation` 또는 `details.failure`가 있는 model 줄이 있다. `details.sent=false` 줄은 보낸 호출이 아니다.
- `src/soc/api/routes/hunts.py` `summarize_runs`: 규칙을 만족하는 줄이 없는 run은 `outcome="incomplete"`로 보인다. 있으면 마지막 model 줄의 결과를 그대로 쓴다. 쿼리가 `details.validation`을 더 읽는다.
- `src/soc/api/models.py` `RunSummary.outcome`에 `"incomplete"`를 더한다. 생성 TypeScript(`scripts/generate_contracts.py`)와 화면 테스트를 함께 고친다. 한글 표시는 화면 담당 후속이다.
- `src/soc/l3/hunt/store.py` `last_attempt_started_at`: `cancelled` 줄이 없고 `details.failure`나 `details.validation`이 있는 model 줄이 있는 run만 시도로 센다. 끝나지 않은 run(강제 종료)은 세지 않는다(#245의 `cancelled` 취급과 같다).
- #215 측정 SQL(기록 안의 문서): 새 기록에서 `sent=false` 줄을 빼고 `max_model_input_len`의 뜻이 바뀐 것을 반영해 고쳐 싣는다. 지난 기록은 고치지 않는다.

## 바꿀 곳

- `src/soc/agent/agent_log.py`: `LogRecorder`(즉시 쓰기, 보류, 줄 고정, 종료 줄, `sent=false` 한 함수, delta `input`), `PostgresLogSink`(`ON CONFLICT DO NOTHING`, 접속·시간 제한 인자, 선택 인자), 쓰기 스레드·마감 도우미
- `src/soc/agent/runner.py`: `run_agent` 순서(`DATABASE_URL` 먼저), `run_id` 하나, 시작 전 실패 줄, `finalize` 재시도, `_usage`가 `sent=false`를 뺌
- `src/soc/tools/registry.py`: `records` 도구가 기록기에 모델에게 보인 본문을 넘김
- `src/soc/api/routes/hunts.py`, `src/soc/api/models.py`, `frontend/src/api/generated/`(생성), 화면 테스트: `incomplete`
- `src/soc/l3/hunt/store.py`: `last_attempt_started_at`
- `config/default.toml`: `[agent]` 키 2개
- `tests/`, `tests/fixtures/`: 아래 완료 기준의 테스트와 샘플
- `docs/decisions.md`(이 계획과 같은 커밋), `docs/notes/278-agent-log-durability.md`(개발 기록)

## 다른 코드와 맞물리는 곳

다른 사람이 읽거나 쓰는 것 중 새로 만들거나 바꾸는 것이다. 모두 원칙 7에 해당하고 이 계획의 확정으로 승인받는다.

| 바꾸는 것 | 읽는 곳 · 담당 |
|---|---|
| `agent_logs` 줄을 호출마다 쓴다. model 줄 `input`이 delta 모양, `records` 줄 `output`이 모델에게 보인 결과, `sent=false` 줄·종료 줄이 생긴다 | `hunts.py`(화면), `store.py`(L3), #215 SQL(문서), `judge.py`·`l2/branch/read.py`·`l2/analyze/context.py`(`agl_` 존재 확인만, 줄이 더 일찍 생기는 쪽이라 영향 없음) |
| 읽는 규칙(끝난 run, `sent=false`) | 위와 같음. D-036 메모에 적음 |
| `RunSummary.outcome`에 `"incomplete"` 추가, 생성 TS 변경 | 화면 담당 |
| 개발 DB 시드 원본 `tests/fixtures/api/ui_seed.json`의 끝난 run에 `"validation": "ok"` 추가 | 화면 담당, 개발 DB를 시드한 사람 |
| `last_attempt_started_at` 쿼리 변경, 시작 전 실패를 시도로 셈 | L3 담당(`soc.l3.hunt.generate`) |
| `usage.turns`가 `sent=false` 줄을 뺌(`budget_exceeded` run은 값이 1 줄어듦) | `soc.agent.dev_l1` 출력, 파이프가 `AgentResult.usage`를 읽는 곳 |
| `[agent]` 설정 키 2개 | 설정 로더(`load_config`가 `agent` 절 전체를 넘김) |
| `PostgresLogSink` 생성자에 선택 인자, `LogSink.write`가 줄마다 불림 | 테스트의 가짜 기록기 |
| D-036 문장 | 팀 전체 |

**알림(사람이 올린다)**

- **L3 담당**: `store.py` `last_attempt_started_at` 쿼리, 시작 전 실패를 시도로 세는 것(`generate_interval_seconds`만큼 다음 생성이 늦어짐), 끝나지 않은 run은 시도가 아님.
- **화면 담당**: `RunSummary.outcome`의 `"incomplete"`, 생성 TS 변경, 한글 표시 후속. 개발 DB 시드 원본 `tests/fixtures/api/ui_seed.json`의 끝난 run에 `"validation": "ok"`를 더했다. 이미 시드한 개발 DB는 그 Agent Log 행을 지우고 다시 시드해야 한다(방법은 `docs/notes/278-agent-log-durability.md`).
- **팀 전체**: D-036 문장(저장 방식이 바뀜), 읽는 규칙, #211의 "자르기 전 전체 저장" 변경.
- **계약 담당**: `agent_log` 계약의 `details` 설명("다른 단계는 읽지 않는다")과 `hunts.py`·`store.py`가 이미 `details`를 읽는 것이 어긋난다(#278 이전부터). 계약 문구를 고치는 후속 이슈 초안이 있다.

## 범위 밖

- #280 C4(동기 도구가 이벤트 루프를 막아 취소가 늦음). 이 계획의 쓰기 스레드는 그 문제를 고치지 않는다.
- #279(외부 LLM으로 가는 비밀 값, 가림 범위). 이 계획은 줄마다 가림을 거치게 할 뿐이다.
- C3-A(`kind`를 늘리는 계약 변경).
- 워커의 DB 접속에 시간 제한이 없는 것(예: `soc/l1/judge.py`). #280 범위로 넘긴다.
- `log_error`를 L2 재시도 대상에서 빼기(`soc/l2/analyze/worker.py`). 후속 이슈 초안.
- `agent_log` 계약 `details` 설명 고치기. 후속 이슈 초안.
- 모델 출력 줄의 저장 상한, 한 실행의 합계를 코드에서 자르기.
- 화면의 한글 표시(`incomplete`)와 Agent Log 화면.
- #279·#280은 #278이 머지된 뒤 리베이스한다(같은 `runner.py`·`registry.py`를 고친다).

## 완료 기준

- [ ] (C2) 호출마다 커밋됨을 `db` 테스트에서 다른 연결로 실행 도중 읽어 확인한다.
- [ ] (C2) 쓰기 실패 시 첫 실패에서 중단하고, `finalize`가 재시도하며, 그래도 실패하면 `log_error`에 `output=None`이다. 이미 쓴 줄은 남는다.
- [ ] (C2) `MaxTurnsExceeded`·도구 실행 중 취소·없는 도구 호출마다 종료 줄이 붙고, `summarize_runs`는 `incomplete`가 아니라 `error`로 본다. `MaxTurnsExceeded` 직전의 마지막 줄 상태는 테스트로 고정한다.
- [ ] (C2) 강제 종료(`finalize` 건너뜀) run은 `summarize_runs`에서 `incomplete`이고 L3 시도로 세지 않는다.
- [ ] (C2) 같은 `(run_id, seq)`를 다시 쓰면 먼저 쓴 줄이 남고, 다시 쓰는 줄의 내용이 먼저 쓴 줄과 같다(`seq`가 결정적으로 정해짐).
- [ ] (C2) 멈춘 DB를 흉내 낸 기록기로 훅이 마감 안에 풀리고 run이 `log_error`로 끝난다. 멈춘 쓰기가 남아 있어도 프로세스 종료를 막지 않는다(데몬 스레드).
- [ ] (C2) 멈춘 DB에 걸린 쓰기가 있어도 같은 프로세스의 다음 run은 DB가 정상이면 줄을 쓴다.
- [ ] (C2) `PostgresLogSink`가 `psycopg.connect`에 시간 제한·keepalives·`tcp_user_timeout` 인자를 넘긴다(인자 확인).
- [ ] (C3) 도구 설정 오류·프롬프트 합성 실패·설정 읽기 실패·LLM 연결 실패의 줄을 `run_id`로 DB에서 찾을 수 있고, 돌려준 `run_id`와 줄의 `run_id`가 같다.
- [ ] (C3) `DATABASE_URL` 없음은 줄 없이 `log_error`와 실행기 로그만 남고, 로그에 비밀이 없다.
- [ ] (C3) `usage.turns`는 `sent=false` 줄을 뺀다. 시작 전 실패 run은 L3 시도로 센다.
- [ ] (C5) L2 최대 시나리오(12턴, 64,000자, 레코드 도구 100건)의 model 줄 `input` + 도구 줄 `output` 합계가 160,000자 이하이다. 이어 붙여 복원한 입력이 모델이 받은 입력과 같고, 접두가 아닌 경우(`input_reset`)도 확인한다.
- [ ] (C5) D-036 수정, 새 기록의 `supersedes`(`211-tool-registry.md`), #215 SQL 고침을 문서화한다.
- [ ] `summarize_runs`·`RunSummary`(생성 TS 포함)·`store.py`의 변화를 테스트로 확인한다.
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run python scripts/generate_contracts.py --check`, 화면 `pnpm lint`·`pnpm test`·`pnpm build`가 통과한다.
- [ ] 새 환경변수는 없다(`.env.example` 변경 없음).
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록이 있다.

## 토론으로 정한 것

이슈의 "정하지 못함" 네 개와 검토에서 나온 질문의 답이다.

**원래 이슈와 달라진 점**
- 이슈의 후보 중에서 골랐다: C2-A, C3-B, C5 A+B+C.
- 이슈에 없던 읽는 쪽 수정이 들어왔다: `summarize_runs`, `RunSummary.outcome`, `store.py`. 호출마다 쓰면 강제 종료된 run이 성공처럼 보이기 때문이다.
- 이슈에 없던 구현이 들어왔다: 종료 줄, 설정 키 2개, 줄마다 데몬 스레드와 마감, `ON CONFLICT DO NOTHING`.
- `usage.turns`가 `sent=false` 줄을 뺀다.

**질문과 답**
1. (C2) 쓰기 시점: **A 호출마다 쓰기.** 강제 종료·종료 대기 초과·쓰기 실패 중 A만 셋 모두에서 끝난 호출의 줄을 남긴다(B는 쓰기 실패만, C는 종료 대기 진입 시점까지만 고치고 강제 종료는 못 고침). 줄 하나 쓰기가 실패하면 첫 실패에서 멈추고 `finalize`에서 한 번 더 시도, 그래도 실패하면 `log_error`.
2. (C2) `log_error`일 때 출력: **살리지 않는다.** 결과 저장도 같은 PostgreSQL이라 얻는 것이 작고, 근거 없는 판정을 막는다(원칙 3). L2 재시도에서 `log_error`를 빼는 것은 후속 이슈 초안.
3. (C3) 시작 전 실패: **B(`sent=false` 줄).** 계약 변경 없이 되고 `add_budget_exceeded` 선례가 있다. 3-1: 시작 전 실패를 L3 시도로 센다(L3 담당 알림).
4. (C5) 줄이기: **A+B+C**, 상한 160,000자, 모델 출력은 상한 없이 측정만(4-1 A).
5. 미완료 run 표시: **`outcome="incomplete"`.** 진행 중인 run을 `error`로 말하면 사실과 다르다.
6. 이미 쓴 줄에 `failure`를 붙일 수 없을 때: **`sent=false` 종료 줄을 덧붙인다.** 모든 줄을 끝까지 보류하면 강제 종료 때 줄을 잃고, `UPDATE`는 줄이 바뀌지 않는다는 단순함을 잃는다.
7. 끝나지 않은 run을 L3 시도로 세는가: **세지 않는다.** #245의 `cancelled` 취급과 같고 현재 동작이 유지된다.
8. 설정 키: **두 키 모두**(`log_connect_timeout_seconds`, `log_statement_timeout_ms`). 연결 시간만으로는 연결된 뒤 멈추는 DB를 막지 못한다.
9. 로그 쓰기 스레드: **줄마다 새 데몬 스레드 + 클라이언트 마감.** `to_thread`는 멈춘 쓰기가 프로세스 종료를 막는다(실측). 접속 인자는 코드 고정값, 한계를 위에 적었다. 담당자 제안(`to_thread`)에서 바꾼 점: 스레드를 줄마다 새로 만들고 데몬으로 한다.
10. 읽는 규칙 기록 위치: **D-036 메모.** 계약 변경 없이 팀 결정 문서에 들어간다. 계약 `details` 설명과의 어긋남은 계약 담당 알림과 후속 이슈 초안.

**결정 목록에 올린 안건**: D-036(Agent Log 저장 방식)을 고쳤다. 팀 공유가 필요하다.

## 바뀐 점

- 2026-11-10 · 개발 중 `tests/fixtures/api/ui_seed.json`(개발 DB 시드 원본)의 끝난 run에 `"validation": "ok"`를 더하기로 사람이 정했다(읽는 규칙 때문에 표시가 없으면 `incomplete`로 보인다). 이미 시드한 개발 DB는 해당 행을 지우고 다시 시드한다. 화면 담당 알림에 넣었다.
