---
issue: 253
date: 2026-11-05
owner: uptime-zero
supersedes: []
---

# W05 — L1 판정과 DB 기반 L2 인계

## 목표

W04의 판정 대기 Alert와 Ticket을 L1이 처리하고 결과와 근거를 DB에 저장한다. L2는 승격된 기존 Ticket을 DB에서 읽는다.

## 방법

- P04(#251)의 상태표와 `[agent.l1] confidence_threshold = 0.8`을 따른다. 기존 `AgentWorker`, `run_agent`, L1 읽기 전용 도구 허용 목록과 실행기 등록 방식을 재사용한다. 워커는 `triage.status = pending` Alert와 `status = new` Ticket을 선택한다.
- Alert의 유효한 `malicious` Verdict가 임계값 이상이면 `triage=promoted`와 `origin=l1`, `status=new` Ticket 생성을 한 트랜잭션으로 저장한다. `benign`, 임계값 미만 `malicious`, `undetermined`는 유효한 Verdict와 함께 `held`로 둔다. 생성된 Ticket도 이후 Ticket 판정을 받는다.
- Ticket의 유효한 `benign` 또는 `malicious` Verdict가 임계값 이상이면 각각 `closed` 또는 `escalated`로, 낮은 확신도 또는 `undetermined`는 `held`로 Verdict와 함께 저장한다.
- L1 전용 내부 상태 테이블에 Alert 또는 Ticket별 실패 횟수를 유지한다. 최초 실행 포함 총 3회 실패하면 `held`와 null Verdict를 저장한다. `cancelled`는 횟수에 넣지 않는다. 낮은 확신도와 `undetermined`는 유효한 결과이므로 재시도하지 않는다. `normalize_status`나 Agent Log로 L1 시도를 세지 않는다.
- 모델 호출은 트랜잭션 밖에서 수행한다. 저장할 때 대상 행을 잠그고 여전히 pending/new인지 재확인한다. 실패 횟수 증가와 세 번째 실패의 보류 전이는 원자적으로 수행한다. 이미 처리된 대상에 오래된 결과를 적용하지 않는다.
- 존재하는 입력 근거 ID만 `AgentTask.allowed_evidence_ids`에 넣고, 도구 결과와 최종 근거 검사는 기존 근거 장부를 따른다. Agent Log 저장이 실패한 결과는 판정에 적용하지 않는다.
- 한 실행기에서는 L1을 순차 처리한다. 여러 실행기가 동시에 돌면 모델 호출이 중복될 수 있으며, 상태 재확인은 오래된 결과의 저장을 막는다. DB 장애나 프로세스 종료로 실패 횟수를 커밋하지 못한 시도는 횟수에 남지 않을 수 있다.

## 바꿀 곳

- `src/soc/l1/`: L1 워커, 입력·프롬프트 구성, 상태 및 재시도 저장.
- `src/soc/db/migrations/`: W04 이후 번호의 L1 재시도 상태 테이블.
- `config/default.toml`: L1 확신도와 기존 실행기의 워커 등록.
- `tests/fixtures/`, 관련 단위·DB 테스트: 두 경로와 L2 인계 검증.
- `docs/notes/253-l1-ticket-db-l2.md`: 개발 기록.

## 다른 코드와 맞물리는 곳

- W04(#246)의 Alert 분기, Ticket 생성과 Alert별 유일성 제약에 의존한다. 구현과 통합 전에 W04 및 P04 문서가 작업 기준에 반영되어야 한다.
- Alert·Ticket·Verdict·Agent Log 공통 계약을 재사용한다. L2는 `escalated` Ticket과 참조된 Alert 및 근거를 DB에서 읽는다.
- `[agent.l1] confidence_threshold`와 `[executor.l1] workers`를 사용한다. 재시도 상태는 L1 내부 테이블에 둔다.

## 범위 밖

- ELK 수집, 정규화, 정책 API와 W04 구현, L2 Incident·L3 구현, 메시지/ACK, 대응 실행.
- 여러 실행기 사이의 중복 모델 호출을 막는 claim·임대 방식과 실제 ELK 필드 검증.

## 완료 기준

- [ ] Alert와 Ticket의 P04 상태표 및 확신도 0.79/0.8 경계가 맞다.
- [ ] 첫 두 실패는 대기 상태를 유지하고 세 번째 실패는 보류한다. 재시작 후 횟수가 유지되고 `cancelled`는 세지 않는다.
- [ ] 반복·동시 실행에서 오래된 결과가 적용되지 않고 실패 횟수 갱신이 유실되지 않는다. Alert 승격과 Ticket 생성이 원자적이다.
- [ ] 형식·근거 오류, 호출·Agent Log 실패, 공격자 입력과 비밀 가림을 확인한다.
- [ ] 승격된 Ticket을 기존 L2 reader에서 읽어 Alert 참조, entities, Verdict, 시각과 근거를 확인한다.
- [ ] 손으로 만든 fixture, 관련 단위·DB 테스트와 저장소 공통 검사를 통과한다.

## 토론으로 정한 것

- 원래 이슈의 Ticket 전용 범위를 Alert 1차 판정과 Ticket 판정으로 넓힌다. W04의 두 출력 경로를 P04와 연결하기 위해서다.
- L1 실패 횟수는 공통 Alert·Ticket 계약을 바꾸지 않는 별도 내부 테이블에 보존한다.

## 바뀐 점
