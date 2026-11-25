---
issue: 379
date: 2026-11-25
owner: Pandyo
plan: 379-incident-detail-page.md
supersedes: []
---

# Incident 상세가 전용 페이지(`/incidents/:id`)로 열리고 탭·표로 정리됐다

## 한 일

- Incident를 누르면 슬라이드 패널 대신 `/incidents/:id` 페이지가 열린다. 사이드바는 그대로이고, 탭(개요·관계 그래프·Ticket·엔티티·분석 이력)은 `?tab=`에 남는다. 옛 `/incidents?selected=inc_…` 링크는 새 주소로 리다이렉트한다. Ticket 상세·Case·대시보드의 Incident 링크도 새 주소로 간다.
- 고정 헤더에 제목·ID(복사)·상태·심각도, 승인·반려, 요약 숫자(Ticket·Alert·엔티티, 판정 분포), 진행 단계, 이전/다음, "목록으로"가 있다. 승인·반려는 기존 `ReviewActions`를 옮겼고 권한과 `awaiting_review` 조건은 그대로다. 처리 뒤에는 상세에 머물고, 승인되면 `case.read` 권한이 있을 때 "Case 보기" 링크가 뜬다.
- Ticket 표(검색·판정 필터·정렬·10개씩 페이지)와 엔티티 표(검색·종류 필터·정렬·20개씩 페이지, 연결 Ticket·Alert 수, 최초 관측)를 클라이언트에서 처리한다. 긴 값은 말줄임과 복사 버튼이 있다.
- 분석 이력은 최신 라운드만 펼쳐지고, 권고 조치는 "왜 필요한가" 라벨 없이 문단과 구분선으로 나뉜다. 관계 그래프 탭은 기존 그래프를 옮겼고, 저장된 연결 경로와 탐색 상태는 접힌 "분류 근거(고급)"로 옮겼다. Entity 버튼은 "준비 중" 비활성 그대로다.
- `GET /api/incidents/{id}`에 `tickets[].severity·created_at·evidence_count·alert_ids·entities`와 `alerts[]`(`id`·`time`·`entities`)를 더했다(D-080). 기존 필드와 `contracts/`는 그대로다.

## 계획과 달라진 점

- 계획 파일의 "바뀐 점"에 적을 것은 없다. 작은 선택만 아래에 둔다.
- `ui_read.entity_criticality`가 Alert를 직접 읽지 않고 `incident_alerts`가 읽은 행을 받는다. 같은 쿼리 하나로 자산 중요도·시각·엔티티를 모두 읽어 쿼리 수를 늘리지 않으려는 것이다. 함수 인자가 바뀌었지만 부르는 곳은 `workflow.py` 하나다.
- 슬라이드 패널의 링크 만드는 코드를 `frontend/src/links.tsx`(`useLink`)로 옮겨 패널과 새 페이지가 함께 쓴다. Incident는 `/incidents/:id`, 나머지는 기존 `?selected=`다.
- `IncidentGraph` 안의 제목·상태·Ticket 수 머리 줄을 없앴다. 페이지 헤더가 같은 내용을 보이기 때문이다. 그 머리 줄을 확인하던 옛 테스트는 보기 전환 테스트로 바꿨다.
- 표 정렬은 같은 열을 다시 누르면 방향이 뒤집히고, 다른 열을 누르면 오름차순으로 시작한다. 기본은 Ticket이 최신순, 엔티티가 연결 Ticket 수 많은 순이다.
- 판정 필터에 "판정 전"(`decision`이 null) 칩을 더했다. 판정 분포의 "판정 전"과 맞추려는 것이다.
- 옛 패널 기준 테스트(`review.test.tsx`, `App.test.tsx`, `ticket-detail.test.tsx`)는 새 페이지 기준으로 옮겼다. 승인 뒤 "목록·대시보드를 다시 읽는다"는 테스트는, 상세 페이지에서는 그 쿼리가 열려 있지 않아서 "목록으로 돌아갔을 때 다시 읽는다"로 바꿨다. 코드는 전과 같이 모든 쿼리를 무효화한다.

## 다음 사람이 알아야 할 것

- **디자인 파일을 확인하지 못했다.** 새 프레임 7개는 `design/0-Ticket.pen`이 아니라 pen 앱의 활성 문서에서 읽었다. 사람이 이 프레임들을 `design/0-Ticket.pen`에 커밋하겠다고 했고 아직 확인하지 못했다. 화면을 브라우저에서 띄워 보거나 디자인과 나란히 비교하지 않았다. 고정 헤더가 실제 스크롤 영역에서 맞게 붙는지, 표 폭과 줄바꿈이 괜찮은지는 손으로 확인하지 못했다.
- **목록 상태는 라우터 state에만 있다.** "목록으로"의 복귀 경로와 이전/다음 ID 배열은 목록에서 눌러 들어올 때만 생기고, 주소를 직접 열거나 새로고침하면 사라진다(그때는 기본 목록으로 가고 이전/다음이 비활성이다). 탭을 바꿀 때는 `setSearchParams`에 `state`를 넘겨 이어 간다. 이 `state`를 빼면 탭을 한 번 바꾸는 순간 이전/다음이 사라진다. 테스트가 이를 지킨다.
- **승인 뒤 Case 링크도 새로고침하면 사라진다.** `case_id`는 승인 응답으로만 알 수 있고 상세 응답에는 없어서 화면 상태로만 들고 있다.
- **엔티티 연결 수는 값이 같아야 센다.** 엔티티 키는 `(type, value)`이고 Ticket·Alert의 엔티티 값과 Incident 엔티티 값을 정확히 비교한다. 정규화된 값끼리라고 가정하며, 어긋나면 연결이 `Ticket 0 · Alert 0`으로 보인다(자산 중요도 매칭과 같은 가정, 기록 376). 실제 ELK 데이터로는 확인하지 못했다. L2가 근거와 함께 찾은 엔티티는 Ticket·Alert에 없을 수 있어 `0`으로 나오고 "최초 관측"은 "—"다.
- **Hunt 출신 Ticket**은 Alert가 없어서 엔티티가 Ticket의 `entities`에서만 연결되고, 최초 관측은 그 Ticket 생성 시각이다.
- **응답 크기.** `alerts[]`는 Alert 수만큼 늘고 쿼리 수는 일정하다. Ticket은 `max_incident_tickets`(기본 10)로 막혀 있어 작다. 엔티티는 상한이 없어 수천 개가 되면 서버 페이지를 새 안건으로 올린다(D-080).
- **그래프는 손대지 않았다.** 확대·이동·끌기·필터·검색·Alert 접기·Entity 보기는 새 그래프 이슈(번호는 올라오면 이 줄에 적는다)로 갔다. 그 이슈가 Alert 제목·심각도·판정이 필요하면 응답 확장에 담당 승인을 다시 받아야 한다. D-079는 그 이슈의 라이브러리 안건용으로 비어 있다.
- 개요의 "핵심 엔티티" 카드, 위험 경로·선 라벨·노드 설명, 반려 이력, 라운드 간 변화량은 만들지 않았다(계획의 범위 밖).
- 로컬에서 `-m db` 테스트를 돌릴 때 `.env`의 `DATABASE_URL`이 가리키는 `zt_dev`가 없어서 그 명령에서만 `zt`로 바꾼 값을 환경변수로 줬다(`.env`는 고치지 않았다). 기록 376과 같다.
- `pnpm lint`의 경고 1건(`flow-chart.tsx`)은 이 이슈 전부터 있다.

## 디자인과 다른 곳 (PR에 적을 것)

- 심각도는 "심각·높음·보통·낮음"이 아니라 `N Level`(D-074)이다.
- 판정은 "악성·의심·정상"이 아니라 `malicious`·`undetermined`·`benign` 원문이다(D-078). 요약 숫자도 같다.
- 권고 우선순위는 P0~P2가 아니라 높음·중간·낮음(D-072)이다.
- 디자인에 있고 만들지 않은 것: 위험 경로 단계와 "공격 출발지·최초 진입·도착 서버" 같은 역할 설명, 선 라벨, 노드 설명, 반려 이력과 라운드 간 변화량, 개요의 "핵심 엔티티", 엔티티 표의 "그래프에서 보기" 열.
- "분류 근거(고급)"를 디자인은 개요에 두었지만 이 구현은 관계 그래프 탭의 접힌 영역에 있다.
- 디자인의 Ticket 표는 ID를 `T-1024` 꼴로 보이지만 실제 ID는 `tkt_…`라 말줄임과 복사 버튼으로 보인다.
- 디자인에 오류 상태가 없어서 기존 `ErrorState`(재시도)를 썼다.
- 디자인의 "엔티티 18"(헤더)과 "엔티티 100"(탭)은 같은 값으로 맞췄다.
- Entity 보기는 "준비 중" 비활성 그대로다(디자인은 동작한다).

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과.
- `uv run pytest`: 2696건 통과. `uv run pytest -m db`(`DATABASE_URL`은 `zt`로, `QDRANT_URL=http://127.0.0.1:6333`): 679건 통과. 주요 테스트는 `tests/test_api_detail.py`의 `test_incident_detail_tickets_carry_what_the_ticket_table_shows`, `test_incident_detail_lists_each_alert_once_with_time_and_entities`, `test_incident_detail_without_alerts_has_an_empty_alert_list`, 기존 `test_incident_detail_query_count_does_not_grow_with_tickets`. 샘플은 `tests/fixtures/api/incident_page.json`이다.
- `pnpm contracts:check`(36개 일치), `pnpm lint`(경고 1건은 기존), `pnpm build`: 통과. `pnpm exec vitest run`: 162건 통과. 주요 테스트는 `incident-page.test.tsx`(26건: 주소·리다이렉트·목록 복귀·이전/다음·승인/반려 조건·탭·Ticket 30개·엔티티 100개 표·분석 이력·권고 조치·분류 근거·빈/로딩/오류·권한·텍스트 표시)와 `incident/model.test.ts`(5건, 샘플 `tests/fixtures/frontend/incident_page.json`)다.
- 손으로 확인한 것은 아직 없다. 전·후 스크린샷은 사람이 붙인다(D-075).
