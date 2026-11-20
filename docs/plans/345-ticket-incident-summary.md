---
issue: 345
date: 2026-11-20
owner: Pandyo
supersedes: []
---

# Ticket 조회 API에 연결된 Incident 요약 포함

## 목표

Ticket 목록·상세 API 응답에 연결된 Incident 요약 `incident`(`TicketIncident`)를 더한다. Incident에 붙은 Ticket이면 값이, 붙지 않았으면 `null`이다. 목록은 Ticket 수와 관계없이 조회 횟수가 일정하다. 화면은 따로 고친다.

## 방법

1. **샘플과 테스트 먼저.** `tests/fixtures/api/ui_seed.json`을 쓴다. Ticket `…05`는 Incident `…0001`·`…0004`, `…06`은 `…0002`·`…0005`에 중복으로 붙어 있어 대표 하나 규칙을 확인한다. 붙지 않은 Ticket도 이미 있다.
2. **응답 모델 (`src/soc/api/ui_models.py`).** `TicketIncident {id, title, status, severity, assessed_severity, display_severity}`를 새로 둔다(`IncidentItem`과 같은 이름·같은 계산). `TicketItem.incident`와 `TicketDetail.incident`(최상위, `severity`·`seed_source` 옆)에 `TicketIncident | None`을 필수 키로 더한다. 계약 `contracts/ticket.schema.json`과 `Ticket` 모델은 건드리지 않는다.
3. **조회 (`src/soc/api/ui_read.py`, `routes/workflow.py`).** 페이지(또는 상세) Ticket id 목록으로 `incidents`를 한 번에 가져온다.
   - 조건은 `ticket_ids && %s::text[]`(GIN 인덱스 `incidents_ticket_ids_idx`), 정렬은 `ORDER BY id DESC`.
   - 컬럼은 기존 `INCIDENT_COLUMNS`를 재사용해 `display_severity`가 `IncidentItem`과 같은 계산이다.
   - Python에서 Ticket마다 처음 나온 Incident 하나(가장 큰 id, 곧 가장 최근)만 쓴다. 없으면 `None`.
   - 연결의 기준은 `incidents.ticket_ids`이고 `tickets.status`는 보지 않는다.
   - 목록은 쿼리 2번(페이지 + Incident), 상세는 1번 추가다. Ticket마다 따로 조회하지 않는다.
4. **권한.** 기존 `ticket.read`만 요구한다. `incident.read`는 요구하지 않는다.
5. **프론트.** `pnpm contracts`로 `frontend/src/api/generated/`(`TicketPage`·`TicketDetail` 등)를 다시 만들고, 타입 검사가 깨지는 Ticket 모의 데이터를 보정한다. 화면 수정은 하지 않는다.
6. **기록.** `docs/notes/`에 아래를 적는다.
   - 운영 코드에는 Incident에서 Ticket을 빼거나 다른 Incident로 옮기는 동작이 없다(테스트는 `ticket_ids`를 직접 UPDATE해 확인).
   - 대표 하나 규칙이 필요한 중복 연결은 현재 시드에만 있고 `save_branch`는 만들지 않는다.

## 바꿀 곳

- `src/soc/api/ui_models.py`: `TicketIncident`, `TicketItem.incident`, `TicketDetail.incident`
- `src/soc/api/ui_read.py`: Incident 일괄 조회 함수
- `src/soc/api/routes/workflow.py`: 목록·상세에서 호출
- `frontend/src/api/generated/*`: 생성 타입 갱신
- 프론트 테스트의 Ticket 모의 데이터 보정(`App.test.tsx` 등)
- `tests/test_api_ui.py`(또는 `tests/test_api_db.py`): 새 테스트
- `docs/plans/345-ticket-incident-summary.md`, `docs/notes/345-ticket-incident-summary.md`

## 다른 코드와 맞물리는 곳

다른 코드가 읽는 응답 모양을 바꾼다(필드를 더하기만 한다).

- **`GET /api/tickets`·`GET /api/tickets/{id}` 응답**: `incident` 키 추가. 필수(null 가능)라 생성 TS 타입이 바뀌고, 이를 쓰는 프론트 코드와 테스트 모의 데이터가 영향을 받는다(UI 담당 확인 대상).
- 계약 `Ticket`, `tickets`·`incidents` 테이블, 마이그레이션, 설정 키: 바꾸지 않는다.

## 범위 밖

- 화면 수정(목록 상태 열 배지, Ticket 상세의 Incident 카드).
- 여러 Incident를 목록으로 주는 것. 대표 하나만 준다.
- Ticket에서 Incident를 빼거나 옮기는 운영 기능.
- `incident.read` 권한에 따른 가림.

## 완료 기준

- [ ] Incident에 붙은 Ticket의 목록·상세 응답에 `incident`(id, title, status, severity, assessed_severity, display_severity)가 있고, 붙지 않은 Ticket은 `null`인 테스트(`db`). `display_severity`가 `IncidentItem`과 같은 값인 확인 포함
- [ ] 한 Ticket이 두 Incident에 붙은 시드(`…05`→`…0004`, `…06`→`…0005`)에서 id가 가장 큰 Incident 하나만 주는 테스트(`db`)
- [ ] 분석 전 Incident(`analyzing`, `assessed_severity` null)의 임시 제목이 그대로 나오고 `status`·`assessed_severity: null`로 구분되는 테스트
- [ ] `api_db.connect`를 감싸 `execute` 호출을 세고, Ticket 3개와 30개에서 목록 조회 횟수가 같은 테스트(`db`). Incident 조회는 `ticket_ids && %s::text[]`
- [ ] `incidents.ticket_ids`를 직접 UPDATE해 Ticket을 빼거나 다른 Incident로 옮기면 응답이 따라 바뀌는 테스트
- [ ] `tickets.status`와 관계없이 `ticket_ids`에 들어 있으면 연결로 보는 테스트
- [ ] 로그인하지 않은 요청과 권한이 없는 요청이 기존처럼 거부되는 테스트
- [ ] 프론트 생성 타입 갱신과 Ticket 모의 데이터 보정, `pnpm contracts:check`·`pnpm lint`·`pnpm test`·`pnpm build` 통과
- [ ] 응답 변경으로 영향받는 화면 코드가 있으면 PR 설명에 적었다
- [ ] 키·비밀 값이 코드, 테스트, 로그, notes, PR에 없다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run pytest -m "db or qdrant"` 통과
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록(위 6번 내용 포함)

## 토론으로 정한 것

이슈의 "정하지 못함" 세 가지와 부수 질문의 답이다.

- **여러 Incident에 붙은 Ticket**: `incidents.ticket_ids`에는 막는 제약이 없고 시드에도 있다(운영 코드 `save_branch`는 한 번만 붙인다). 대표 하나로 줄이고 id가 가장 큰(가장 최근) Incident를 준다. 목록으로 주지 않는다.
- **응답 모양**: 기존 응답에 `incident`를 필수(null 가능)로 더한다. 프론트 생성 타입 갱신과 모의 데이터 보정을 범위에 넣는다(#343 선례).
- **요약 필드와 임시 제목**: 이슈의 4개 필드(id, title, status, severity)에 `assessed_severity`·`display_severity`를 더해 `IncidentItem`과 같은 이름·같은 계산으로 맞춘다(이슈 본문과 달라진 점. Ticket 화면과 Incident 화면의 심각도가 어긋나지 않게). 분석 전 임시 제목은 그대로 주고 `status`와 `assessed_severity`(null)로 구분한다. 별도 분석 상태 필드는 없다.
- **권한**: `ticket.read`만 요구한다. 기본 analyst는 읽기 권한을 모두 받고, `null`로 가리면 "붙지 않음"으로 오해되기 때문이다.
- **연결의 기준**: `incidents.ticket_ids`가 원본이다. 이슈의 "상태 `linked`"는 `tickets.status`를 따로 보지 않는다.
- **연결 방식 확인**: 연결 테이블 없이 `incidents.ticket_ids text[]`(GIN 인덱스)다.
- **조회 횟수 테스트**: `api_db.connect`를 감싸 `execute` 호출을 세고 3개·30개 Ticket을 비교한다.
- **중복 연결 테스트**: 시드(`ui_seed.json`)의 중복 연결 Ticket으로 확인한다. 시드를 정리하면 이 테스트를 새 시드로 옮겨야 한다.
- **결정 목록**: 새 도구·방식이 없어 `docs/decisions.md`에는 올리지 않는다.
- **계약**: `contracts/ticket.schema.json`은 건드리지 않고 응답 모델(`ui_models.py`)만 바꾼다.

## 바뀐 점

