---
issue: 253
date: 2026-11-05
owner: uptime-zero
plan: 253-l1-ticket-db-l2.md
supersedes: []
---

# L1 판정과 DB 기반 L2 인계

## 한 일

- 기존 실행기에 L1 워커를 등록해 대기 Alert와 Ticket을 P04 상태표에 따라 판정한다.
- 실패 횟수는 `l1_attempts`에 보존한다. 세 번째 실패에서 보류하며 취소는 세지 않는다. 실패 원인은 대상 ID와 실패 코드·예외 종류만 로그에 남긴다.
- 대상 행의 상태를 다시 확인하고 Alert 승격과 Ticket 생성, Ticket 상태와 Verdict를 각각 원자적으로 저장한다.
- 입력·도구 근거 장부와 Agent Log 저장은 기존 에이전트 코어를 사용한다.

## 계획과 달라진 점

없음.

## 다음 사람이 알아야 할 것

- 개발 기준에 P04 확정 문서와 W04 PR head `34c56ec`을 로컬로 합쳤다. W04는 그 뒤 PR #255로 `main`에 squash 머지됐으므로, PR 전에 최신 `main`과 맞추고 중복된 W04 커밋이 diff에 남지 않는지 확인한다.
- 실행기 여러 프로세스가 같은 대상을 모델에 중복 요청할 수 있다. 이미 적용된 대상에 늦은 결과를 저장하지 않는다.
- DB 장애나 프로세스 종료로 실패 횟수 저장이 커밋되지 않으면 해당 시도는 횟수에 남지 않을 수 있다.
- 보류된 대상을 사람이 `pending`/`new`로 되돌릴 때는 `l1_attempts` 행도 지운다. 지우지 않으면 되돌린 뒤 첫 실패에서 바로 다시 보류된다.
- 실제 조직 ELK와 실제 모델은 이 작업에서 확인하지 않았다.

## 확인 방법

- 2026-11-05 마무리: `uv run ruff format .`은 235개 파일 변경 없음, `uv run ruff check .` 통과.
- `uv run pytest`: 1,144개 통과, 332개 제외. 기존 `FakeSshServer`의 pending-task 경고가 출력됐다.
- 격리된 PostgreSQL에서 `uv run pytest -m db -q`: 328개 통과, 1,148개 제외.
- 2026-11-05 리뷰 수정 뒤: `uv run pytest` 1,144개 통과, DB 테스트 329개 통과(보류 대상 되돌림 테스트 추가), `ruff check` 통과.
- 2026-11-05 인수 점검(같은 코드): `tests/test_l1_judge.py`, `tests/test_ticketing.py`, `tests/test_api.py` 62개 통과. 임시 PostgreSQL 17 컨테이너에서 `tests/test_l1_judge_db.py`, `tests/test_ticketing_db.py` 36개 통과.

## 전체 흐름과 코드 경로

다른 담당자가 코드를 읽기 전에 보는 정리다. 계획의 결정은 `docs/plans/253-l1-ticket-db-l2.md`가 기준이고, 아래는 구현이 실제로 그렇게 움직이는 순서다. 함수 위치는 `파일:줄`이다.

### 1. 전체 연결

```text
W02 정규화 Alert (normalize_status = succeeded)
   │
   ▼  W04 분기: src/soc/l1/ticketing.py run() → _process_alert()
   ├─ mode = auto 이거나 rule_id가 scenario_rule_ids에 있음
   │     → Ticket 생성 (status=new, origin=auto|scenario, alert_ids=[alert])
   └─ 그 밖 (scenario 모드)
         → Alert.triage = {status: pending, verdict: null}
   │
   ▼  L1 실행기: [executor.l1] workers = ["soc.l1.judge:build_worker"]
   │  L1Worker.poll() → pending Alert ID + new Ticket ID
   │  L1Worker.handle(id)
   │     → run_agent(AgentTask) → 검증된 Verdict 또는 실패
   │     → 실패 횟수 또는 상태 적용
   │
   ▼  결과 상태
   Alert: promoted (+ origin=l1 Ticket 생성) | held
   Ticket: closed | escalated | held
   │
   ▼  L2 (범위 밖): status=escalated Ticket과 alert_ids·근거를 DB에서 읽음
```

승격으로 만든 Ticket(`origin=l1`)은 다음 실행에서 `new` Ticket으로 다시 잡혀 Ticket 판정을 받는다. 따라서 scenario 모드에서는 한 Alert가 Alert 판정과 Ticket 판정을 모두 거칠 수 있다.

### 2. 상태 결정표 (`judge.decide`, `src/soc/l1/judge.py:32`)

| 대상 | Verdict | 상태 | Ticket |
|---|---|---|---|
| Alert (`alt_`) | `malicious`, 확신도 ≥ 0.8 | `promoted` | `origin=l1`, `status=new` 생성 |
| Alert | 그 밖의 유효 Verdict (`benign`, 낮은 확신도 `malicious`, `undetermined`) | `held` | 없음 |
| Ticket (`tkt_`) | `benign`, 확신도 ≥ 0.8 | `closed` | 없음 |
| Ticket | `malicious`, 확신도 ≥ 0.8 | `escalated` | 없음 |
| Ticket | 그 밖의 유효 Verdict | `held` | 없음 |
| 대상 | 세 번째 실패 | `held`, Verdict `null` | 없음 |

임계값은 `config/default.toml`의 `[agent.l1] confidence_threshold = 0.8`이다. 경계는 `>=`로 비교하며 `0.79`는 보류, `0.8`은 통과다(`tests/fixtures/l1_judge/decisions.json`).

### 3. 한 번의 실행 흐름

**A. 실행기 기동** (`src/soc/agent/executor.py`)
1. `Executor`가 `[executor.l1]`을 읽고 `resolve_factory("soc.l1.judge:build_worker")`로 함수를 찾는다.
2. `build_worker(config)`(`judge.py:264`)가 `DATABASE_URL` 환경변수와 `config["agent"]["l1"]["confidence_threshold"]`로 `L1Worker`를 만든다. 두 값 중 하나라도 없으면 기동이 실패한다.
3. 단계 스레드 `_StageThread._round()`(`executor.py:170`)가 워커마다 `poll(poll_limit)`을 부르고, 받은 ID마다 `handle(id)`를 부른다. 라운드가 끝나면 `interval_seconds`(10초)만큼 쉰다. 예외는 실행기가 잡아 워커 이름과 ID, 예외 종류만 로그에 남긴다.

**B. poll** (`judge.py:173`)
- 읽기 전용 autocommit 연결로 `alerts.triage->>'status' = 'pending'`과 `tickets.status = 'new'`를 `created`, `id` 순으로 `limit`개 뽑는다.
- 잠금은 걸지 않는다. 여기서 고른 ID는 힌트이고, 실제 확인은 `handle`에서 다시 한다.

**C. handle 1단계: 대상 확인과 작업 만들기** (`judge.py:187`)
1. `_subject_type`이 접두사로 `alert` 또는 `ticket`을 고른다. 다른 접두사면 `ValueError`로 전체가 실패 경로에 들어간다.
2. `_read_subject`(`judge.py:58`)가 잠금 없이 행을 읽는다. Alert는 `triage.status = pending`, Ticket은 `status = new`일 때만 대상이다. 아니면 아무것도 하지 않고 끝난다.
3. `l1_attempts`에서 실패 횟수를 읽어 `attempt = failures + 1`로 둔다. 행이 없으면 1이다.
4. `_task`(`judge.py:90`)가 `AgentTask`를 만든다.
   - Alert: `data = {alert: ...}`
   - Ticket: `alert_ids`로 `alerts`를 읽고 `data = {ticket: {id, origin, entities}, alerts: [...]}`. 없는 Alert가 있으면 `LookupError`다.
   - 공통: `window_start_ms = 가장 이른 시각 - 6일`, `window_end_ms = 가장 늦은 시각 + 1일`. `output_contract="verdict"`, `cited_ids=output["evidence_ids"]`, `allowed_evidence_ids=`대상 Alert ID들이다.
   - 이 시점에 DB 잠금은 없다.

**D. run_agent 호출** (`src/soc/agent/runner.py:52`, `run_task` `:77`)
1. 설정을 읽고 모델을 만들고, Agent Log를 PostgreSQL에 쓰는 `PostgresLogSink`를 붙인다.
2. `compose_instructions`가 `prompts/l1.md`를 포함한 지시를 만든다. `LogRecorder`가 실행 기록을 모은다.
3. 도구 세션은 `[tools.allowed] l1`만 붙인다: `get_alert`, `get_event`, `query_records`, `query_http_flow`, `summarize_http_flow`, `query_siem`. 쓰기 도구는 없다.
4. `_execute`(`runner.py:163`)
   - Agent에 `RetryingModel`(429 재시도)과 `check_budget`(입력 `max_input_chars`=32000 초과면 호출 안 함)을 붙인다. `max_turns`=6.
   - 입력은 `wrap_data`로 `<data>` 구분자에 감싼다. 데이터 속 `<`, `>`는 `<`, `>`로 바꾼다.
   - `_check_output`(`runner.py:242`)이 최종 출력을 JSON으로 파싱하고 `verdict` 계약으로 검사한다. `decided_at`은 모델 값을 버리고 서버 시각으로 덮는다.
   - 형식이 틀리면 남은 턴 안에서 한 번 더 요청한다. 그래도 틀리면 `format_error`다.
   - 근거 장부 = 입력의 Alert ID + 성공한 도구 호출이 낸 ID + 모델에게 실제 보인 레코드 ID. `cited_ids`가 장부 밖이면 `evidence_id_error`다.
5. 모든 기록 행을 `_redacted`로 가린 뒤 `validate_contract("agent_log")`를 하고 `log_sink.write`로 쓴다. 쓰기가 실패하면 `log_error`로 바꾼다. 이 경우 Verdict는 적용되지 않는다.
6. `AgentResult(ok, output, failure, ...)`를 돌려준다. 예외는 밖으로 내보내지 않는다.

**E. 결과 분기** (`judge.py:200`)
- `failure == "cancelled"`: 아무것도 하지 않는다. 횟수에도 넣지 않고 대상은 pending/new로 남는다.
- `not ok`: `_failure`로 간다.
- `ok`: `_apply`로 간다.
- `handle` 안의 예외 전체: 새 연결로 `_failure`를 부른다.

**F. 실패 기록** (`_failure`, `judge.py:212`)
1. 트랜잭션을 연다.
2. 대상 행을 `FOR UPDATE`로 잠그고 여전히 pending/new인지 확인한다. 아니면 아무것도 하지 않는다.
3. `l1_attempts`에 `INSERT ... ON CONFLICT DO UPDATE failures = failures + 1 RETURNING failures`를 한다.
4. 결과가 3 이상이면 `_save(held, None)`으로 보류한다. 같은 트랜잭션이므로 횟수 증가와 보류가 함께 저장되거나 함께 실패한다.

**G. 판정 적용** (`_apply`, `judge.py:227`)
1. `validate_contract("verdict")`를 트랜잭션 밖에서 한다.
2. 트랜잭션을 연다. 대상 행을 `FOR UPDATE`로 잠그고 여전히 대기 중인지 다시 확인한다. 아니면 오래된 결과이므로 버린다. 횟수도 올리지 않는다.
3. `_evidence_exists`가 `alt_`, `evt_`, `agl_` ID를 DB 테이블에서 확인한다. 없으면 `ValueError`로 트랜잭션을 롤백하고 실패 경로(F)로 간다.
4. `decide`로 상태를 고르고 `_save`로 저장한다.
5. 상태가 `promoted`면 W04의 `_make_ticket(subject, "l1", now)`로 Ticket을 만들고 계약을 검사한 뒤 `_insert_ticket`으로 넣는다. 같은 트랜잭션이다.

**H. 저장** (`_save`, `judge.py:243`)
- Alert: `UPDATE alerts SET triage = {status, verdict}`. Verdict는 `triage` JSON 안에 들어간다. `alerts`에는 verdict 열이 없다.
- Ticket: `UPDATE tickets SET status, verdict(JSON 또는 NULL), updated_at`.

### 4. 트랜잭션과 동시성

| 상황 | 동작 |
|---|---|
| 모델 호출 | DB 잠금 없이 한다. 긴 호출이 행 잠금을 잡지 않는다. |
| 결과 저장 | 행을 잠그고 상태를 다시 확인한다. 이미 바뀌었으면 아무것도 쓰지 않는다. |
| 실패 횟수와 세 번째 보류 | 한 트랜잭션이다. |
| Alert 승격과 Ticket 생성 | 한 트랜잭션이다. Ticket 삽입이 실패하면 Alert 변경도 롤백된다. |
| 실행기 여러 개 | 같은 대상의 모델 호출이 중복될 수 있다. 적용은 한 번만 되고, 늦은 결과는 버린다. |
| 취소 | 횟수에 넣지 않는다. 다음 실행에서 다시 잡힌다. |
| DB 장애·프로세스 종료 | 횟수 커밋 전에 죽으면 그 시도는 횟수에 남지 않는다. |

### 5. 실패 종류별 처리

| 원인 | 횟수 +1 | 결과 |
|---|---|---|
| `format_error` (형식 재요청 뒤에도 위반) | 예 | 3회째 `held` |
| `evidence_id_error` (장부 밖 ID, 출력 근거 추출 실패) | 예 | 3회째 `held` |
| `budget_exceeded` (입력 예산, max_turns) | 예 | 3회째 `held` |
| `rate_limited`, `provider_error` | 예 | 3회째 `held` |
| `log_error` (Agent Log 쓰기 실패) | 예 | 3회째 `held`, Verdict 미적용 |
| DB 근거 확인 실패, Ticket의 Alert 없음, 예외 | 예 | 3회째 `held` |
| `cancelled` | 아니오 | 대기 상태 유지 |
| 낮은 확신도, `undetermined` | 아니오 | 유효한 결과로 바로 저장 |

### 6. 파일 맵

| 파일 | 출처 | 역할 |
|---|---|---|
| `src/soc/l1/judge.py` | #253 | L1 워커: poll, handle, 상태 결정, 실패 횟수, 저장 |
| `src/soc/l1/ticketing.py` | #246 (W04, 재사용) | 정책 분기 `run`, `_make_ticket`, `_insert_ticket` |
| `src/soc/ticketing.py` | #246 | 정책 로드(TOML, DB 활성 행) |
| `src/soc/db/migrations/0104_l1_ticketing.sql` | #246 | 정책 테이블, Alert당 W04 Ticket 하나 유일성 |
| `src/soc/db/migrations/0105_l1_attempts.sql` | #253 | `l1_attempts(subject_id, subject_type, failures ≥ 1)` |
| `src/soc/agent/prompts/l1.md` | #253 | Alert·Ticket 공용 판정 프롬프트로 수정 |
| `config/default.toml` | #253, #246 | `[agent.l1] confidence_threshold`, `[executor.l1] workers`, `[ticketing]` |
| `contracts/ticket.schema.json` | #246 | `origin`이 auto/scenario/l1이면 `alert_ids`는 정확히 하나 |
| `src/soc/api/routes/ticketing_policy.py` | #246 | 정책 GET/PUT API (아래 한계 참고) |
| `tests/test_l1_judge.py`, `tests/test_l1_judge_db.py` | #253 | 단위·DB 테스트 |
| `tests/fixtures/l1_judge/decisions.json`, `tests/fixtures/ticketing/alerts.json` | #253, #246 | 손으로 만든 샘플 |

### 7. 알려진 한계 (다음 사람이 알아야 할 것)

- **W04 정책 API(`PUT /api/ticketing-policy`)에 인증이 없다.** 이 코드는 #246으로 이미 `main`에 있고 #253이 바꾸지 않았다. D-043은 관리자 인증 API를 요구하므로 D-020 후속 작업에서 막아야 한다. 기본 바인딩은 `127.0.0.1`이며 `[api] host`를 넓히면 외부에서 쓸 수 있다.
- W04(#246, PR #255)는 `main`에 머지됐다. 이 브랜치는 머지 전 W04 커밋(`34c56ec`)을 합쳐 두었으므로, PR 전에 최신 `main`과 맞춘다.
- **보류된 대상을 사람이 되돌릴 때는 `l1_attempts` 행도 지운다.** 지우지 않으면 횟수가 이어져 되돌린 뒤 첫 실패에서 바로 다시 보류된다(`failures`는 1 이상이면 허용, 테스트로 확인).
- **`_insert_ticket`의 충돌 반환값을 `_apply`가 무시한다.** 충돌하면 기존 Ticket이 있어도 Alert는 `promoted`가 된다. 정상 흐름에서 pending Alert에는 Ticket이 없어 충돌이 나지 않지만, 방어는 없다.
- `l1_attempts`는 보류·종결 뒤에도 행이 남는다. 정리 작업은 없다.
- 여러 실행기가 같은 대상의 모델 호출을 중복으로 낼 수 있다. 비용이 늘지만 결과 적용은 한 번만 된다. claim·임대 방식은 범위 밖이다.
- 실제 조직 ELK와 실제 모델 연결은 확인하지 않았다.
