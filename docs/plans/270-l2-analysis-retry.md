---
issue: 270
date: 2026-11-10
owner: Juhyeok0603
supersedes: [261-l2-incident-analysis.md]
---

# L2 분석 횟수 제한을 없애고 실패 재시도를 별도로 센다

## 목표

`analyzing` Incident는 지난 분석 횟수와 관계없이 새 입력을 분석한다. 실패는 별도의 연속
카운터로 세고, 최초 실행 포함 3회 실패하면 `held`로 옮긴다. `held`는 1시간 뒤 Ticket
추가 없이도 다시 분석 대상이 된다. 분석 중 Ticket이 붙어도 그 Ticket의 재분석 기회를 남긴다.

## 방법

### 횟수와 실패

- `max_analysis_rounds`와 라운드 한도에 따른 poll·handle 분기를 없앤다.
- `analysis_round`는 성공·실패마다 1씩 증가하는 기록용 순번으로 유지한다. 실패한
  순번에 Artifact가 없는 것은 D-045대로 허용한다. `cancelled`는 순번과 실패 카운터
  어느 쪽에도 넣지 않는다.
- `details.l2_analyze.failure_streak`에 연속 실패를 둔다. 없으면 0으로 읽고
  `[l2.analyze] max_failures = 3`을 기본값으로 쓴다. 조사 run 실패 또는 보고 run의
  최종 실패를 1회로 센다. 보고 run 안에서 허용한 재호출은 별도로 세지 않는다.
- 성공하면 `failure_streak`를 0으로 되돌린다. 기존 `failures[]` 진단 기록은 남긴다.
  세 번째 연속 실패를 저장하는 같은 트랜잭션에서 `status = held`와
  `details.l2_analyze.held_at`을 쓴다. `held_at`은 모델 호출 전이 아니라 실패 저장
  시점의 epoch 밀리초다.

### 쿨다운과 Ticket 연결

- `[l2.analyze] failure_retry_cooldown_ms = 3_600_000`으로 둔다. poll은 `analyzing`과
  `held_at`으로부터 쿨다운이 지난 `held`를 고른다. Ticket 연결 때도 바뀌는
  `updated_at`은 쿨다운 기준으로 쓰지 않는다.
- handle은 쿨다운이 지난 `held`를 행 잠금 아래 원자적으로 `analyzing`으로 돌리고
  `failure_streak`를 0으로 초기화한 뒤 분석한다. 이미 다른 실행기가 바꿨거나 아직
  쿨다운 중이면 처리하지 않는다.
- `held`는 L2 분류의 열린 Incident 상태다. 새 Ticket이 연결되어도 즉시
  `analyzing`으로 바꾸지 않고 쿨다운을 기다린다. 기존 분류 후보 24시간 창은 유지한다.
  따라서 새 Ticket 연결 자체를 복귀 수단으로 가정하지 않는다.

### 분석 중 Ticket 추가

- 성공 저장 직전에 잠근 Incident의 `ticket_ids`를 분석 문맥에서 읽은 목록과 비교한다.
- 같으면 Artifact·Proposal을 저장하고 판정에 따라 `dismissed` 또는
  `awaiting_review`로 옮긴다.
- 다르면 읽었던 입력으로 만든 Artifact·Proposal은 저장하되 Incident는
  `analyzing`으로 유지한다. 다음 poll이 새 Ticket을 포함해 다시 분석한다. 두 경우
  모두 성공이므로 `failure_streak`를 0으로 되돌린다. 저장은 잠근 최신 Incident 행에서
  시작해 새 Ticket의 ID를 보존한다.

### 기존 데이터, 계약, 화면

- 새 `0201_incident_held.sql`에서 `incidents.status` CHECK에 `held`를 추가한다.
  적용된 `0001`은 고치지 않는다. 기존 `details.l2_analyze.stopped = "round_limit"`을
  제거해 해당 `analyzing` Incident가 다시 poll되게 한다. 기존 `analysis_round`와
  `failures[]`는 보존한다.
- `contracts/incident.schema.json`에 `held`를 추가하고 Python·TypeScript 생성물을
  생성 명령으로 갱신한다. 생성 코드는 직접 고치지 않는다.
- 손으로 쓴 화면 API `IncidentStatus`, 대시보드의 열린 Incident 조회, 화면의
  Incident 상태 필터에 `held`를 추가한다. 화면의 기존 `held` 이름·스타일을 쓴다.
- 재분석 횟수 한도 대신 실패 소진·쿨다운·`human_handling` 유지 규칙을 D-028에 쓰고
  결정 기록을 추가한다.

## 바꿀 곳

- `src/soc/db/migrations/0201_incident_held.sql`: 상태 CHECK와 기존 `stopped` 제거
- `src/soc/l2/analyze/worker.py`, `store.py`: poll·복귀·실패 카운터·성공 저장 경쟁
- `src/soc/l2/config.py`, `config/default.toml`: 분석 설정 두 키로 교체
- `src/soc/l2/branch/read.py`, `store.py`: `held` 후보 조회·Ticket 연결
- `contracts/incident.schema.json`, `src/soc/contracts/generated/`,
  `frontend/src/api/generated/`: 상태 계약과 생성 결과
- `src/soc/api/ui_models.py`, `src/soc/api/routes/dashboard.py`, `frontend/src/App.tsx`:
  API 타입·대시보드·화면 필터
- `docs/decisions.md`: D-028과 결정 기록
- `tests/fixtures/`의 손으로 만든 Incident 샘플과 관련 계약 fixture,
  `tests/test_l2_branch_db.py`, `tests/test_l2_config.py`, `tests/test_l2_worker.py`,
  `tests/test_lab_cycle_db.py`, API·화면 테스트: 새 상태·복귀·경쟁 조건

## 다른 코드와 맞물리는 곳

- `incidents.status`는 L1·L2·L3·화면이 쓰는 공통 계약이다. `held` 추가에 대한 각 담당
  승인을 이슈에 기록해야 한다.
- 로컬 설정에서 제거되는 `max_analysis_rounds`를 쓰고 있으면 `max_failures`와
  `failure_retry_cooldown_ms`로 바꿔야 한다.
- 분석 중 Ticket이 추가되면 성공한 분석도 `analyzing`에 남는다. Ticket 변경이 없을
  때만 성공 직후 `dismissed` 또는 `awaiting_review`로 간다.
- 반복 장애가 오래 지속되면 보존하는 `failures[]`와 Incident `details`가 계속 커진다.

## 범위 밖

- 사람 검토·반려·`review_round`·Case 생성과 `human_handling`의 자동 재분석
- 새 수동 재시작 명령과 Ticket 0장 Incident의 기존 큐 순서 문제
- 분류 후보 시간 창, 분석 조회 구간, Incident 병합·Ticket 재배정
- 새로운 화면 작업 흐름, 대응 기능, 새 라이브러리

## 완료 기준

- [ ] `analyzing` Incident가 `analysis_round` 상한 없이 분석된다.
- [ ] `analysis_round`는 성공·실패 순번을 유지하고 `cancelled`에는 증가하지 않는다.
- [ ] 연속 실패를 별도로 세며 3회째에 `held`와 실패 저장 시점의 `held_at`을 원자적으로 기록한다.
- [ ] 쿨다운 중에는 재시도하지 않고 1시간 뒤 Ticket 추가 없이도 다시 분석한다.
- [ ] Ticket 연결로 `updated_at`이 바뀌어도 `held_at` 기준 복귀 시각은 밀리지 않는다.
- [ ] 성공 시 실패 카운터가 초기화된다.
- [ ] 분석 중 Ticket이 추가되면 현재 Artifact를 저장하고 `analyzing`을 유지해 새 Ticket을 다시 분석한다.
- [ ] Ticket 추가가 없으면 성공 결과가 `dismissed` 또는 `awaiting_review`로 간다.
- [ ] 기존 `round_limit` Incident가 마이그레이션 뒤 다시 poll된다.
- [ ] `held`에 Ticket을 연결할 수 있고 API·대시보드·화면에서 상태가 보인다.
- [ ] 공통 계약 변경에 대한 L1·L2·L3·화면 담당 승인이 이슈에 기록된다.
- [ ] 손으로 만든 fixture와 테스트로 실패·취소·쿨다운·Ticket 경쟁을 확인한다.
- [ ] 정상적으로 읽히는 Ticket을 같은 Incident에 여섯 번 순차 연결해 여섯 번 재분석한다.
- [ ] 연속 실패 뒤 환경 복구 시 쿨다운을 거쳐 분석되는지 확인한다.
- [ ] `max_analysis_rounds`가 설정과 코드에서 사라지고 D-028·결정 기록이 갱신된다.
- [ ] Python·TypeScript 계약 생성 검사, 백엔드 포맷·린트·전체 테스트,
  DB·Qdrant 테스트, 화면 린트·테스트·빌드가 통과한다.

## 토론으로 정한 것

- 실패 소진 상태를 `held`로 하고 `human_handling`과 구별한다.
- 실패는 최초 실행 포함 3회로 제한하고, L2에는 `held_at` 기준 1시간 자동 복귀를 둔다.
  분류 후보 24시간 창 때문에 새 Ticket 연결만으로는 복귀가 보장되지 않는다.
- `failure_streak`와 `held_at`은 `details.l2_analyze`에 두고 기존 실패 기록을 보존한다.
- `analysis_round`는 실패에도 증가하는 기존 순번으로 유지한다.
- 분석 중 Ticket이 추가되면 이미 만든 Artifact는 저장하고 다음 분석 기회를 남긴다.
- 기존 `round_limit`은 제거해 재개한다.
- Ticket 0장 큐 순서 문제는 이번 변경이 만들지 않으므로 별도 이슈로 둔다.
- 이슈의 `tests/test_l2_analyze_db.py`는 현재 없어 L2 공용 DB 테스트 파일을 쓴다.

## 바뀐 점

