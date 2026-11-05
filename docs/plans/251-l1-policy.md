---
issue: 251
date: 2026-11-05
owner: uptime-zero
supersedes: []
---

# P04 — L1 실행 방식과 판정 결과 적용 조건 확정

## 목표

L1의 Alert 1차 판정과 Ticket 판정에 적용할 결과 조건(D-025)을 확정한다. 이 이슈는 정책 확정만 하며, L1 워커나 실행 코드는 만들지 않는다.

## 방법

### 기존 실행 구조

- D-022~D-024와 D-023의 도구 구조는 이미 확정되어 있으므로 다시 결정하지 않는다. OpenAI Agents SDK, `ToolRegistry` 함수 도구, 동기 `run_agent(AgentTask) -> AgentResult`, 코드에서 tracing 비활성화를 그대로 따른다.
- 현재 `[tools.allowed]`의 `l1` 목록(`get_alert`, `get_event`, `query_records`, `query_http_flow`, `summarize_http_flow`, `query_siem`)을 재사용한다. 내부 데이터와 SIEM 조회는 읽기 전용이다. SSH·쓰기 도구는 L1에 추가하지 않는다.
- L1 작업은 DB의 `alerts.triage.status = 'pending'`과 `tickets.status = 'new'`에서 찾는다. 후속 L1 워커는 #215의 `AgentWorker` 계약을 따르고, 실행기가 가져온 대상을 하나씩 처리한다.
- `run_agent`가 끝날 때까지 동기적으로 기다린다. 별도의 비동기 요청 큐나 메모리 결과 큐를 만들지 않는다. 실행기 설정과 워커 등록도 이 이슈에서 구현하지 않는다.
- 모델 호출은 DB 트랜잭션 밖에서 한다. 실행이 끝난 뒤 상태를 다시 확인하고 결과를 저장한다.

### 확신도와 상태 적용

임계값은 `[agent.l1]` 설정의 `confidence_threshold = 0.8`로 둔다. `confidence >= 0.8`만 확신도 조건을 통과한다. 구현 중 테스트가 기대한 상태 전이를 보이지 않으면 값을 다시 검토해 D-025와 이 계획을 함께 갱신한다.

| 대상 | Verdict | 상태 적용 | 저장할 Verdict |
|---|---|---|---|
| `triage=pending` Alert | `benign` | `held`, Ticket을 만들지 않는다. 확신도와 무관하다 | 유효한 Verdict를 저장한다 |
| `triage=pending` Alert | `malicious`, confidence ≥ 0.8 | `promoted`; `origin=l1`, `status=new` Ticket을 만든다 | 저장한다 |
| `triage=pending` Alert | `malicious`, confidence < 0.8 또는 `undetermined` | `held`, Ticket을 만들지 않는다 | 유효한 Verdict를 저장한다 |
| `status=new` Ticket | `benign`, confidence ≥ 0.8 | `closed` | 저장한다 |
| `status=new` Ticket | `malicious`, confidence ≥ 0.8 | `escalated` | 저장한다 |
| `status=new` Ticket | `benign` 또는 `malicious`, confidence < 0.8 또는 `undetermined` | `held` | 유효한 Verdict를 저장한다 |
| Alert 또는 Ticket | 최종 실행 실패 | `held` | Verdict는 null로 둔다 |

유효한 Verdict라도 `held` 결과일 수 있다. 출력 형식 오류, 근거 ID 오류, 예산 초과, 제공자 오류, Agent Log 기록 오류 등 `run_agent`가 실패를 돌려주면 결과를 적용하지 않는다. 도구 호출 하나가 실패해도 현재 레지스트리 계약대로 모델 실행은 계속한다. 전체 실행이 유효한 Verdict로 끝나면 그 결과를 위 표에 따라 적용하고, 근거가 부족하면 `undetermined` 또는 최종 실행 실패에 따라 보류한다.

### 재시도

- 한 작업의 워커 시도는 최초 실행을 포함해 총 3회다. 각 `handle`에서 `run_agent`가 실패하거나 처리 중 예외가 나면 한 번의 워커 시도로 센다. `run_agent` 내부의 형식 오류 재요청과 rate-limit 재시도는 워커 시도 수와 별개다.
- 세 번째 시도도 실패하면 대상 상태를 `held`로 바꾼다. 유효한 낮은 확신도 Verdict나 `undetermined`는 실패 재시도를 하지 않고 바로 표의 보류 상태로 저장한다.
- `cancelled`는 실패 횟수에 넣지 않고 대상은 `pending` 또는 `new`로 남겨 다음 실행에서 다시 가져오게 한다.
- 실패 횟수는 워커 재시작 뒤에도 유지해야 한다. 저장 위치와 구체 구현은 후속 구현 이슈에서 정한다. Agent Log만으로 세지 않는다. `log_error`에서는 Agent Log를 쓸 수 없기 때문이다.

### 근거 ID 확인 책임

- 후속 L1 워커는 DB에서 판정 대상과 실제 입력 자료를 읽고, 존재하는 근거 ID만 `AgentTask.allowed_evidence_ids`에 넣는다.
- ToolRegistry는 성공한 도구 호출 ID와 모델에게 실제로 보인 레코드 ID를 근거 장부에 넣는다. 오류 응답이나 모델에게 보이지 않은 잘린 레코드는 근거로 인정하지 않는다.
- `run_agent`가 최종 Verdict의 근거 ID가 입력·도구 근거 장부에 있는지 검사한다. 장부 밖 ID가 있으면 `evidence_id_error`다.
- Agent Log는 `run_agent`가 반환하기 전에 저장한다. 따라서 Verdict를 저장할 때 인용한 `agl_`이 `agent_logs`에 존재한다는 계약을 지킨다.

### 결과 저장과 중복 방지

- 모델 실행 중에는 행 잠금이나 트랜잭션을 유지하지 않는다.
- 저장 트랜잭션에서 Alert가 여전히 `pending`인지, Ticket이 여전히 `new`인지 조건부 갱신으로 확인한다. 상태가 이미 바뀌었다면 오래된 결과를 적용하지 않는다.
- Alert 승격은 `triage=promoted` 갱신과 L1 Ticket 삽입을 한 트랜잭션으로 처리한다. Ticket 삽입이 실패하면 Alert 갱신도 롤백한다. 조건부 갱신이 0행이면 Ticket을 만들지 않는다.
- Ticket 결과도 `status=new`일 때만 Verdict와 최종 상태를 함께 저장한다. 이미 처리된 Ticket은 다시 변경하지 않는다.
- 이 방식으로 #215의 `handle` 멱등성 요구를 만족한다. 별도의 유일성 계약이나 새 DB 테이블은 이 정책 이슈에서 추가하지 않는다.

### 보안 및 검증 계획

- 현재 L1 허용 도구를 재사용하고 읽기 전용 제한을 유지한다. 도구·SDK·환경변수 방향은 바꾸지 않는다.
- 후속 구현 테스트는 손으로 만든 fixture로 두 L1 경로, `0.79`/`0.8` 경계, 세 번 실패 후 보류, `cancelled` 제외, 근거 ID 오류, 중복 실행과 원자적 Ticket 생성을 확인한다.
- tracing 비활성화(`tests/test_agent_core.py::test_tracing_disabled_without_env`), 비밀 값 가림(`tests/test_agent_redact.py`), DB 읽기 전용 제한(`tests/test_tools_db.py`)은 기존 테스트를 재사용한다. LLM 확인은 기본 테스트·CI와 분리한 `uv run pytest -m llm <파일>` 경로로 한다.
- 이 이슈는 정책 확정이므로 테스트 실행이나 코드 변경을 완료 조건으로 삼지 않는다.

## 바꿀 곳

- `docs/decisions.md`: D-025를 확정으로 옮기고 임계값, 상태 적용, 재시도 정책을 기록한다.
- `docs/plans/251-l1-policy.md`: 이 정책과 후속 구현 검증 기준을 기록한다.

## 다른 코드와 맞물리는 곳

- D-022~D-024, `AgentTask`, `AgentResult`, `AgentWorker`, Verdict·Alert·Ticket 계약은 바꾸지 않는다.
- 후속 구현은 `[agent.l1]`에 `confidence_threshold`를 추가하고, 기존 `[executor.l1]` 설정과 #215의 워커 계약을 사용한다.
- Verdict 상태와의 세부 대응은 단계 코드에서 검사한다. 공통 JSON Schema나 DB CHECK 변경은 하지 않는다.

## 범위 밖

- L1 워커 구현·실행기 등록·코드·마이그레이션·fixture 테스트
- SDK, 도구 레지스트리, 비동기 요청 큐, 별도 큐 서비스
- L2·L3 동작, 대응 실행, 새 데이터 계약
- 실제 LLM 호출과 모델 품질 평가

## 완료 기준

- [ ] D-025가 확정으로 기록되고 임계값이 0.8이다.
- [ ] Alert 1차 판정과 Ticket 판정의 상태표, 확신도 경계, 실패 후 보류가 이 계획에 명시돼 있다.
- [ ] 워커 시도는 총 3회이며 `cancelled`는 세지 않는다는 기준이 기록돼 있다.
- [ ] 근거 ID 확인 책임과 Agent Log 저장 순서가 명시돼 있다.
- [ ] 결과 저장은 현재 상태를 재확인하고, Alert 승격과 Ticket 생성을 원자적으로 해 멱등성을 지킨다는 기준이 있다.
- [ ] tracing·비밀 값·읽기 전용 도구 제한을 검증할 기존 테스트와 후속 구현 테스트 계획이 명시돼 있다.
- [ ] 이 이슈에서 코드나 실행 동작을 바꾸지 않았다.

## 토론으로 정한 것

1. **기존 실행 구조를 따른다.** D-022~D-024와 #215 워커 계약을 다시 논의하지 않는다. DB 상태를 작업 큐로 쓰고, 동기 `run_agent` 결과를 하나씩 적용한다. 별도 비동기 결과 큐는 두지 않는다.
2. **확신도 임계값은 0.8이다.** 설정으로 두고 `>= 0.8`을 통과로 본다. 테스트에서 상태 적용을 확인하고, 값 변경이 필요하면 사람이 D-025를 다시 정한다.
3. **실패는 최초 실행을 포함해 총 3회 시도한다.** 세 번째 실패 뒤 보류하고, `cancelled`는 시도 횟수에 넣지 않는다. 실패 횟수는 재시작을 견디도록 보존하되 저장 방식은 구현 이슈에서 정한다.
4. **Alert 승격과 Ticket 저장은 원자적·멱등적으로 한다.** LLM 호출은 트랜잭션 밖에서 하고, 결과 적용 시 현재 상태를 다시 확인한다. Alert 갱신과 Ticket 삽입은 한 트랜잭션으로 한다.
5. **이 이슈는 정책만 확정한다.** L1 워커, 설정 코드, 테스트는 구현하지 않는다.

### 이슈 본문과 달라진 점

- 이슈는 D-022·D-023이 후보이고 D-024가 미확정이라고 설명하지만, 현재 `docs/decisions.md`에서 이미 확정된 결정이다(#209, #211). 이 계획은 그 결정을 다시 열지 않는다.
- 이슈의 확신도 `0.8` 예시는 사용자가 확정한 설정값으로 정했다.
- 이슈 완료 기준을 정책 확정으로 한정했다. 구현은 후속 이슈로 둔다.

## 바뀐 점
