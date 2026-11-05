---
issue: 246
date: 2026-11-05
owner: uptime-zero
supersedes: []
---

# W04 — 외부 관리 정책에 따른 Alert 분기와 직접 Ticket 생성 구현

## 목표

W02가 DB에 저장한 정규화 Alert를 읽어 현재 Ticket 정책에 따라 직접 Ticket을 만들거나 L1 1차 판정 대상으로 표시한다. 정책은 관리자 API로 바꾸고, 변경은 이후 평가하는 Alert에 적용한다.

## 방법

### 정책 공급과 저장

- `config/default.toml`에 `[ticketing] mode = "auto"`, `scenario_rule_ids = []`를 둔다. D-002에 따라 `config/local.toml`이 이를 덮어쓴다.
- 관리자 API는 `GET /api/ticketing-policy`와 `PUT /api/ticketing-policy`를 제공한다. 두 경로 모두 관리자 인증을 요구하며 D-020 계정 인증 계약을 사용한다. 인증을 적용하기 전에는 두 경로를 공개하지 않는다. 응답과 요청은 `mode`, `scenario_rule_ids`로 구성한다.
- `PUT`은 `mode`가 `auto` 또는 `scenario`인지, `scenario_rule_ids`가 문자열 목록인지 확인한 뒤 두 값을 한 트랜잭션에서 전체 교체한다. 빈 목록은 허용한다. 잘못된 요청은 거부하며 활성 정책을 바꾸지 않는다.
- PostgreSQL의 `ticketing_policy`에는 `id = 1`만 허용하는 단일 키, 허용값을 제한한 `mode`, `scenario_rule_ids text[] NOT NULL`을 둔다. 유효한 행이 있으면 TOML보다 우선하고, 없으면 TOML 설정을 쓴다. 정책 해시와 변경 이력은 저장하지 않는다.
- `[ticketing]` 설정 읽기와 정책 검증은 API와 분기 명령이 함께 쓰는 `soc.ticketing`에 둔다. API는 같은 정책 형식으로 전체 값을 교체한다.
- 기존 API 읽기 연결은 `default_transaction_read_only=on`을 유지한다. 정책 저장은 별도의 명시적인 쓰기 트랜잭션 경로를 사용한다.

### Alert 소비와 정책 분기

- 한 번 실행하고 끝나는 `uv run python -m soc.l1.ticketing` 명령을 만든다. W01·W02와 같이 주기 실행은 cron에 맡긴다.
- 처리 후보는 실행 시작 때 한 번 조회한다. `normalize_status.status = 'succeeded'`이고 `result_kind = 'alert'`인 행의 `result_id = alerts.id`로 연결되는 레코드 중 `triage IS NULL`이고 어떤 Ticket의 `alert_ids`에도 들어 있지 않은 것만 포함한다. `kind=event` 결과와 정규화 실패는 대상이 아니다.
- 후보 Alert마다 짧은 트랜잭션에서 Alert 행을 `FOR UPDATE SKIP LOCKED`로 잠그고 조건을 다시 확인한 뒤 정책 한 벌을 읽고 결과를 저장한다. 실행 중 새로 정규화된 Alert는 다음 실행에서 처리한다. 각 후보는 한 실행에서 한 번만 시도하며, 실패한 건은 롤백하고 다른 후보를 계속 처리한 뒤 종료 코드 `1`을 반환한다. 별도 분기 임대·실패 상태 테이블은 만들지 않으므로 미완료 Alert는 다음 실행에서 다시 시도한다.
- Alert마다 정책을 한 번 읽는다. 정책 갱신이 해당 읽기보다 먼저 커밋됐으면 새 정책을, 그렇지 않으면 이전 정책을 적용한다. 이미 Ticket 또는 `triage=pending`이 저장된 Alert는 다시 분기하지 않는다. 결과 저장 전 트랜잭션이 실패한 Alert는 재시도 시점의 활성 정책을 읽는다.
- `mode = "auto"`이면 모든 대상 Alert에 `origin = "auto"` Ticket을 만든다. `mode = "scenario"`이고 `Alert.rule_id`가 목록에 있으면 `origin = "scenario"` Ticket을 만든다. 두 경우 모두 Ticket은 `id = new_id("tkt")`, `status = "new"`, `alert_ids = [Alert.id]`, `hunt_id = null`, `entities = Alert.entities`, `verdict = null`, `details = {}`로 만든다. `created_at`과 `updated_at`은 생성 시각(epoch ms)으로 두고 Alert의 `triage`는 null로 둔다.
- `scenario`에서 일치하지 않거나 `rule_id`가 null이면 Ticket을 만들지 않고 Alert의 `triage`를 `{"status":"pending","verdict":null}`로 저장한다. 빈 룰 목록은 모든 Alert가 이 경로로 간다.
- 이미 해당 Alert의 Ticket이 있으면 기존 Ticket을 그대로 반환한다. `origin`, 상태, 판정은 정책 변경이나 재시도로 바꾸지 않는다.

### Alert별 Ticket 유일성

- P03의 생성 단위에 맞춰 `auto`, `scenario`, `l1` Ticket의 `alert_ids`는 Alert 하나만 담도록 계약에 `maxItems = 1`을 추가한다. `l3` 계약은 바꾸지 않는다.
- 마이그레이션에서 `auto`, `scenario`, `l1` Ticket의 Alert 개수를 하나로 제한하고, 첫 Alert ID에 부분 유일 인덱스를 둔다. L3의 기존 `hunt_id` 유일성과 빈 `alert_ids` 동작은 유지한다.
- Ticket 삽입이 유일성 제약과 충돌하면 해당 Alert의 기존 Ticket을 읽어 반환한다. 기존 상태를 갱신하지 않는다.

## 바꿀 곳

- `config/default.toml`: 기본 `[ticketing]` 정책
- `src/soc/api/routes/ticketing_policy.py`, `src/soc/api/models.py`: 관리자 정책 조회·전체 교체 API
- `src/soc/api/db.py`: 읽기 전용 연결과 분리된 정책 쓰기 경로
- `src/soc/ticketing.py`: `[ticketing]` 설정 로드, 정책 검증·스냅샷 형식
- `src/soc/l1/ticketing.py`: 정규화 Alert 선택, Alert별 트랜잭션 분기와 단발 실행
- `src/soc/db/migrations/0104_l1_ticketing.sql`: 현재 정책 테이블과 Alert별 Ticket 유일성
- `contracts/ticket.schema.json`, `src/soc/contracts/generated/ticket_schema.py`: 비-L3 Ticket의 Alert 단일 소속
- `tests/fixtures/ticketing/`, 정책 API·분기·DB 테스트
- `docs/decisions.md`: D-033 소비 위치 갱신, D-043 추가

## 다른 코드와 맞물리는 곳

- W02(#234)의 `normalize_status(result_kind, result_id)`가 정규화 성공 여부와 Alert 결과 위치를 제공한다. RawRecord나 W01 `raw_links`를 직접 읽지 않는다.
- Ticket 정책의 의미와 TOML 우선순위는 P02(#235), Alert별 Ticket 생성·재사용은 P03(#242)을 따른다.
- 관리자 인증은 D-020 계정 인증 계약에 의존한다. W04에서 인증 방식을 별도로 만들지 않는다.
- `soc.api.db.connect()`의 읽기 전용 세션은 유지하고 정책 갱신에만 쓰기 연결을 쓴다.
- Ticket 조회자는 기존 `tickets.alert_ids` 배열을 계속 읽는다. 새 `origin` 값이나 새 Ticket 형식은 추가하지 않는다.
- Alert 룰 ID 비교는 정규화된 `Alert.rule_id`만 사용한다. SIEM 원본 필드 매핑은 W02 범위이며, 실제 ELK 검증 결과를 W04에서 가정하지 않는다.

## 범위 밖

- RawRecord 수집·OCSF 정규화·Asset 조회, Event Ticket 생성, Alert–Event 연결
- L1의 모델 판정과 Ticket 판정, L2 Incident 분류
- 정책 변경 이력·해시, 별도 관리 화면, 다중 SIEM
- D-020의 인증 방식 자체 구현. 인증 계약이 적용되기 전에는 정책 API 두 경로를 공개하지 않는다.
- 실제 ELK 환경의 `rule_id` 필드 검증

## 완료 기준

- [ ] 관리자만 정책 API를 읽고 바꿀 수 있으며, D-020 인증 연결 전에는 두 경로가 공개되지 않는다.
- [ ] 활성 DB 정책이 TOML 기본·로컬 설정보다 우선하고, 활성 행이 없으면 TOML을 사용한다.
- [ ] 전체 정책 교체가 원자적이며, 잘못된 정책 요청은 현재 값을 바꾸지 않는다.
- [ ] Alert별 정책 스냅샷 기준으로 갱신 전후 Alert가 각각 기대한 정책을 사용한다. 이미 저장된 Ticket 또는 `triage` 결과는 재분기하지 않는다.
- [ ] 미정규화·실패한 원본과 Event 결과는 건너뛰고, 성공한 Alert 결과만 실제 `alerts.id`를 참조해 처리한다.
- [ ] `auto`, 시나리오 일치, 불일치, null `rule_id`, 빈 목록의 `origin`·`status`·`triage` 결과가 맞다.
- [ ] Ticket의 `alert_ids`가 실제 Alert 하나를 가리키며, `entities`가 그 Alert에서 오고 `status = new`, `verdict = null`이다.
- [ ] 반복 실행·재시작·동시 실행에서도 Alert당 Ticket은 하나다. 실행 중 처리 실패는 롤백되고 다음 실행에서 재시도되며, 기존 Ticket 재사용 시 기존 필드는 바뀌지 않는다.
- [ ] Ticket 계약과 DB 제약이 `auto`·`scenario`·`l1`의 단일 Alert 규칙에 맞고, L3 Ticket 동작은 유지된다.
- [ ] 손으로 만든 fixture를 사용하는 API·정책·DB 테스트와 `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`가 통과한다.
- [ ] `docs/plans/`에 확정 계획이 있고, 개발 완료 후 `docs/notes/`에 기록한다.

## 토론으로 정한 것

- P02가 미정으로 남긴 실행 중 정책 관리 경로는 관리자 API로 정했다. API 인증은 D-020 계약을 사용한다.
- 활성 정책은 PostgreSQL 단일 행에 저장한다. 행이 없으면 TOML 기본·로컬 설정을 쓰며, 정책 이력은 남기지 않는다.
- 정책은 Alert마다 분기 직전에 읽는다. 갱신 커밋 이후 스냅샷을 읽는 Alert부터 새 정책을 쓰고, 이미 분기 결과가 저장된 Alert는 다시 평가하지 않는다.
- W02는 정규화와 저장을 맡고 Ticket 생성은 하지 않는다. W04는 W02가 성공 저장한 Alert 결과를 DB에서 읽는 별도 L1 Ticket 생성 단계다.
- P03에 따라 `auto`·`scenario`·`l1` Ticket은 Alert 하나를 담고, 재시도는 기존 Ticket을 변경 없이 재사용한다. 이를 계약과 DB에서 함께 강제한다.

## 바뀐 점
