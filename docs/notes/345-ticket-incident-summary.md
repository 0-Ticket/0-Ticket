---
issue: 345
date: 2026-11-20
owner: Pandyo
plan: 345-ticket-incident-summary.md
supersedes: []
---

# Ticket 목록·상세 응답에 연결된 Incident 요약이 들어간다

## 한 일

`GET /api/tickets`(목록 `TicketItem`)와 `GET /api/tickets/{id}`(상세 `TicketDetail`, 최상위)에 필수 키 `incident`를 더했다. 값은 `TicketIncident {id, title, status, severity, assessed_severity, display_severity}`(`IncidentItem`과 같은 이름·계산)이고, 어느 Incident에도 없으면 `null`이다. 연결의 원본은 `incidents.ticket_ids`이며 `tickets.status`는 보지 않는다. 한 Ticket이 여러 Incident에 있으면 id가 가장 큰(가장 최근) 하나만 준다. 목록은 페이지 쿼리 1번 + Incident 쿼리 1번(`ui_read.ticket_incidents`, `ticket_ids && %s::text[]`로 GIN 인덱스)이라 Ticket 수와 관계없이 일정하고, 상세는 1번이 더 든다. 권한은 기존 `ticket.read`만 요구한다. 계약 `Ticket`과 DB는 바꾸지 않았다.

## 계획과 달라진 점

- **프론트 `App.tsx`를 한 줄 고쳤다.** `DetailBody`가 `"incident" in data`로 Incident 상세를 가렸는데, `TicketDetail`에도 `incident`가 생겨 타입 검사가 깨졌다. `"artifacts" in data`(IncidentDetail만 가진 키)로 바꿨다. 계획의 "타입 검사가 깨지는 곳 보정"에 해당하고 화면 동작은 그대로다. `ticket_graphs`로 가르면 기존 테스트의 Incident 상세 모의 데이터에 그 키가 없어 깨진다.
- **프론트 Ticket 모의 데이터는 고치지 않았다.** `App.test.tsx`의 `/api/tickets` 모의 응답은 타입이 없어서 `incident` 키가 없어도 `pnpm build`·`pnpm test`가 통과한다. 화면이 `incident`를 쓰기 시작할 때 모의 데이터에 넣는다.
- **로그인·권한 거부 테스트는 새로 쓰지 않았다.** `tests/test_auth.py`가 `GET /api/tickets`·`/api/tickets/x`의 401·403을 이미 확인한다.

## 다음 사람이 알아야 할 것

- **운영 코드에는 Ticket을 Incident에서 빼거나 다른 Incident로 옮기는 동작이 없다.** `l2/branch/store.py:save_branch`는 `escalated` Ticket을 한 번만 붙이고, `incidents.ticket_ids`를 줄이는 코드는 없다. "빠지거나 옮겨지면 응답이 따라 바뀐다"는 테스트에서 `ticket_ids`를 직접 UPDATE해서 확인했다(`test_ticket_incident_follows_ticket_ids_and_ignores_ticket_status`).
- **한 Ticket이 두 Incident에 붙는 상태는 지금 시드에만 있다.** DB에는 이를 막는 제약이 없다. 대표 하나 규칙은 `tests/fixtures/api/ui_seed.json`의 Ticket `…05`(Incident `…0001`·`…0004`)·`…06`(`…0002`·`…0005`)로 확인한다. 시드를 정리하면 이 테스트를 새 시드로 옮겨야 한다.
- 대표 규칙은 `incidents.id`(UUIDv7, 문자열 정렬) 내림차순이다. 상태(활동 중인지)는 보지 않는다. 따라서 `dismissed` Incident가 활동 중인 옛 Incident보다 우선할 수 있다(시드 `…06` → `dismissed`).
- `ticket.read`만 있고 `incident.read`가 없어도 Incident의 제목·상태·심각도를 볼 수 있다(계획에서 정함). 권한을 개별로 나누는 운영을 하게 되면 다시 정한다.
- 분석 전 Incident의 제목은 첫 Alert 제목 같은 임시 값이다(`_new_incident`). `status`(`analyzing`)와 `assessed_severity`(null)로 구분한다.
- 생성 TS 타입은 `pnpm contracts`로 만든다. 새 타입 `TicketIncident`는 `TicketPage.ts`·`TicketDetail.ts` 안에 들어 있다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과.
- `uv run pytest`: 2581 통과.
- `uv run pytest -m "db or qdrant"`(`DATABASE_URL`은 `.env`의 서버에서 DB 이름만 `postgres`로 바꿈, `QDRANT_URL`은 로컬 컨테이너): 582 통과(경고 1건).
- `pnpm contracts:check`: 일치. `pnpm lint`: 오류 없음(기존 경고 1건 `flow-chart.tsx`). `pnpm test`: 86 통과. `pnpm build`: 통과.
- 새 테스트(`tests/test_api_ui.py`, `db`): `test_ticket_incident_summary_and_representative_incident`(시드 전체: 붙은 것·안 붙은 것·대표 하나·`display_severity` 0 폴백 안 함), `test_ticket_incident_follows_ticket_ids_and_ignores_ticket_status`(직접 UPDATE로 빠짐·옮김, 분석 전 Incident의 `assessed_severity` null, `escalated` Ticket도 `ticket_ids`에 있으면 붙음), `test_ticket_list_query_count_does_not_grow_with_tickets`(Ticket 11개와 38개에서 `execute` 호출이 2번으로 같고 `&&` 사용).
- 테스트 먼저: 세 테스트는 구현 전에 실패하는 것을 확인했다(`incident` 키 없음, 조회 1번).
- 로컬에서는 `.env`의 `DATABASE_URL`이 가리키는 DB 대신 같은 서버의 `postgres` DB로 바꿔 돌렸다(임시 DB를 만드는 관리자 연결용, #343 기록과 같다). 코드와 설정은 바꾸지 않았다.
