---
issue: 379
date: 2026-11-25
owner: Pandyo
supersedes: []
---

# Incident 상세를 전용 페이지로 전환하고 탭·표로 정리

## 목표

Incident를 누르면 슬라이드 패널 대신 전용 페이지(`/incidents/:id`)가 열린다. 상단 고정 헤더(승인·반려, 요약 숫자)와 탭(개요·관계 그래프·Ticket·엔티티·분석 이력)으로 나뉘고, Ticket·엔티티는 검색·정렬·페이지가 되는 표로 보인다. 그래프를 새로 만드는 일(확대·이동·끌기·필터·Entity 보기)은 이 이슈에서 하지 않는다.

## 방법

### Incident 상세 응답 확장 (D-080)

`GET /api/incidents/{id}`의 응답 모델(`ui_models.py`)에 필드를 더한다. 기존 필드는 바꾸지 않는다. `contracts/`의 JSON Schema, DB 스키마, 마이그레이션은 바꾸지 않는다.

- `IncidentDetail.tickets[]`(`IncidentTicket`)에 더한다.
  - `severity`(0~6): 목록 API(`TicketItem.severity`)가 쓰는 계산을 재사용한다. 새 계산을 만들지 않는다.
  - `created_at`(밀리초), `evidence_count`(`verdict.evidence_ids` 개수, 판정 전이면 0), `alert_ids`, `entities`(`type`·`value`·`role`).
- `IncidentDetail.alerts[]`를 새로 둔다. 항목은 `id`·`time`·`entities`이다. 소속 Ticket의 `alert_ids`를 모아 `alerts`를 한 번의 쿼리로 읽는다. 이미 있는 자산 중요도 쿼리(`ui_read.entity_criticality`)와 합칠 수 있으면 합친다. 쿼리 수는 Ticket·Alert 수와 상관없이 일정해야 한다.
- 화면이 이 값으로 계산한다(서버는 집계하지 않는다).
  - 헤더 요약: Ticket 수, Alert 수(`alerts[]` 개수), 엔티티 수(`incident.entities` 개수, 엔티티 탭 숫자와 같은 값), 판정 분포(`malicious`·`undetermined`·`benign`·판정 전, D-078 원문 유지).
  - 엔티티 표의 "연결": 엔티티 키 `(type, value)`가 같은 값을 가진 Ticket 수와 Alert 수. 값 비교는 자산 중요도 매칭과 같이 정규화된 값끼리 정확히 비교한다.
  - 엔티티 표의 "최초 관측": 그 엔티티를 가진 Alert 시각 중 가장 이른 값. Alert가 없으면(Hunt 출신) 그 엔티티를 가진 Ticket의 생성 시각 중 가장 이른 값.
- Alert 제목·심각도·판정은 더하지 않는다(그래프 이슈에서 필요하면 담당 승인을 다시 받는다).
- TypeScript 타입은 `pnpm contracts`로 생성한다(D-003).

### 주소와 이동

- 라우트 `/incidents/:id`. `Workspace`가 `pathname.slice(1)`로 리소스를 고르는 방식을 고쳐 이 주소를 받는다. 사이드바는 그대로 두고 Incident 메뉴가 활성이다. 권한은 `incident.read`이고, 없으면 지금의 권한 없음 화면이다.
- 탭은 `?tab=`에 둔다(`overview`·`graph`·`tickets`·`entities`·`history`). 없거나 모르는 값이면 `overview`이다.
- 옛 `/incidents?selected=inc_…`는 `/incidents/inc_…`로 보낸다(`inc_` ID 형식일 때만). 다른 리소스(Ticket·Alert·Case·Hunt)의 `?selected=` 슬라이드 패널은 그대로다. Ticket 상세의 "Incident 보기", Case의 "원본 Incident", 대시보드, `/cases?tab=waiting` 목록의 Incident 링크는 새 주소로 간다.
- 목록에서 열 때 라우터 `state`에 목록의 쿼리(`status`·`cursor`·`trail` 등)와 현재 페이지의 Incident ID 배열을 싣는다.
  - "목록으로"는 그 쿼리를 되돌려 필터·페이지를 유지한다. state가 없으면(직접 링크) 기본 목록으로 간다.
  - 이전/다음은 그 ID 배열 안에서만 이동한다. state가 없으면 비활성이다. 서버 API는 더하지 않는다.
- 승인·반려 후에는 상세에 머문다. 기존 `ReviewActions`의 동작(성공·실패 뒤 전체 쿼리를 다시 읽음, 409 처리)을 그대로 쓰고 헤더로 옮긴다. 버튼은 지금처럼 권한이 있고 `awaiting_review`일 때만 보인다. 승인되면 헤더에 Case 링크를 더하고, `case.read` 권한이 없으면 링크를 내지 않는다.

### 화면

- 헤더(고정): 제목, ID(복사), 상태, 심각도(`N Level`, D-074), 승인·반려, 이전/다음, 요약 숫자, 진행 단계. 진행 단계(분석 중 → 승인 대기 → 확정/기각)는 `analyzing`·`awaiting_review`·`confirmed`·`dismissed`일 때만 해당 단계를 강조하고, `held`·`human_handling`은 상태 배지만 보인다.
- 개요 탭: 사건 요약, 영향, 소속 Ticket 요약(전체 보기 → Ticket 탭), 권고 조치. 권고 조치는 "왜 필요한가" 라벨을 없애고 `rationale`이 있으면 문단과 구분선으로 나눠 보인다. 우선순위는 높음·중간·낮음(D-072)이고 최신 라운드 것만 보인다(지금과 같음).
- Ticket 탭: 표. 열은 제목, 판정(`decision` 원문), 심각도, 시각, 근거 수, 분류 탐색. 검색(제목·ID), 정렬(심각도·시각·근거 수·판정), 페이지, 판정 필터. ID는 말줄임과 복사를 둔다. 분류 탐색은 `ticket_graphs`의 coverage·reason을 지금의 문구(`statusText`)로 보인다. 행에서 Ticket 상세로 가는 링크는 `ticket.read` 권한이 있을 때만 낸다.
- 엔티티 탭: 표. 종류 칩(계약의 `type` 값별 개수), 검색, 열은 종류·값·role·연결(Ticket n · Alert n)·최초 관측. 긴 값(URL·해시)은 말줄임과 복사를 둔다. 값은 텍스트로만 보이고 링크로 바꾸지 않는다. 페이지 크기는 디자인의 줄 수에 맞춰 개발 중 정한다.
- 분석 이력 탭: 라운드가 많아도 최신 라운드만 펼치고 이전 라운드는 접는다. 각 라운드는 접힌 상태에서 라운드 번호와 시각을 보이고, 펼치면 지금의 보고서 내용을 보인다. 분석·검토 라운드 수, 생성·갱신 시각 표는 그대로 둔다.
- 관계 그래프 탭: 기존 그래프(`incident-graph.tsx`)를 그대로 옮긴다. "저장된 연결 경로"와 "Ticket별 분류 당시 탐색 상태"는 기본 화면에서 빼고 접힌 "분류 근거(고급)" 영역으로 옮긴다. Entity 버튼은 지금처럼 "준비 중" 비활성이다.
- 빈 상태(Ticket 없음): "연결된 Ticket이 없습니다" 안내와 "분석 상태 새로고침"(상세를 다시 읽을 뿐 대응을 실행하지 않는다). 로딩: 상세를 불러오는 중 표시. 오류: 기존 `ErrorState`(재시도 포함). 디자인에 오류 프레임이 없어 기존 컴포넌트를 쓴다. 엔티티가 없는 경우도 표의 빈 상태로 보인다.
- 슬라이드 패널(`detail-panel.tsx`)에서 Incident 분기를 걷어 낸다. Ticket·Alert·Event·Case·Hunt 패널은 그대로다.
- 코드 나누기: `detail-sections.tsx`의 `IncidentSections`를 Incident 페이지용 파일들로 옮긴다(헤더, 탭별 파일, 표). `incident-graph.tsx`는 옮기기만 하고 고치는 것은 "분류 근거" 이동과 위 판정·중요도 표시 유지뿐이다.
- 밖에서 온 문자열(제목, 엔티티 값, 보고서 본문)은 텍스트로만 표시한다(`docs/security.md` "화면"). 복사 버튼은 클립보드에 텍스트만 넣는다.

### 테스트(먼저 쓴다)

- `tests/fixtures/`에 손으로 만든 샘플: 판정 전 Ticket, Alert가 없는 Ticket, 같은 엔티티가 여러 Ticket·Alert에 있는 경우, Alert 시각이 서로 다른 경우. IP는 문서용 대역을 쓴다.
- API 테스트: 새 필드 값, `evidence_count`(판정 전 0), 엔티티 연결에 쓰는 데이터, Alert·Ticket 수가 늘어도 쿼리 수가 늘지 않음, 기존 필드가 그대로임.
- 프런트 테스트: 주소 직접 열기, 옛 `?selected=` 연결, 탭 주소 유지, 목록 복귀 시 필터 유지, 이전/다음(state 있음·없음), 승인·반려 버튼 표시 조건과 후속 동작(기존 `review.test.tsx` 이전), Ticket 30개·엔티티 100개 샘플의 검색·정렬·페이지·필터, 분석 이력 접힘, 권고 조치에 "왜 필요한가"가 없음, 분류 근거가 접혀 있음, 빈·로딩·오류 상태.
- 기존 테스트 중 패널로 Incident를 여는 것(`App.test.tsx`, `review.test.tsx`, `ticket-detail.test.tsx`)은 새 동작에 맞게 옮긴다. 지우거나 건너뛰지 않는다.

## 바꿀 곳

- `src/soc/api/ui_models.py`: `IncidentTicket`의 새 필드, `IncidentDetail.alerts[]`와 항목 모델
- `src/soc/api/routes/workflow.py`, `src/soc/api/ui_read.py`: `incident()`가 새 값을 채움(읽기 쿼리는 늘리지 않거나 한 번만 더함)
- `frontend/src/api/generated/`: `pnpm contracts`로 생성(손으로 고치지 않는다)
- `frontend/src/layout.tsx`, `frontend/src/App.tsx`: `/incidents/:id` 라우트, 옛 `?selected=` 연결
- `frontend/src/list-view.tsx`, `frontend/src/detail-panel.tsx`, `frontend/src/dashboard.tsx`: Incident 링크와 state, 패널에서 Incident 분기 제거
- `frontend/src/detail-sections.tsx`, `frontend/src/review-actions.tsx`, `frontend/src/incident-graph.tsx`, 새 Incident 페이지 파일들, `style.css`
- `frontend/src/*.test.tsx`와 새 테스트, `tests/`, `tests/fixtures/`
- `docs/decisions.md`: D-080과 기록
- `docs/plans/379-incident-detail-page.md`, `docs/notes/379-incident-detail-page.md`

## 다른 코드와 맞물리는 곳

- 화면용 응답 모델 `IncidentDetail`·`IncidentTicket`에 필드를 더한다. 기존 필드는 바꾸지 않는다. 이 응답을 읽는 곳은 프런트의 Incident 상세·그래프뿐이다. 이 변경은 L1·L3 담당이 승인했고 L2는 사용자가 직접 승인했다(2026-11-25 계획 토론에서 사용자가 알림. 담당자 이름과 승인 시각은 확인하지 못함).
- `contracts/`의 JSON Schema, DB, L1·L2·L3 코드와 프롬프트는 바꾸지 않는다.
- 프런트에서 Incident로 가는 링크를 만드는 곳(`detail-panel.tsx`의 `internalLink`, Case·대시보드·Case 대기 목록)과 `Workspace`의 라우팅이 바뀐다. 다른 리소스의 `?selected=` 동작은 그대로다.
- 새 환경변수, 새 도구, 새 라이브러리는 없다. 표는 직접 만든다.
- 원칙 3·4·5와 부딪히지 않는다. 판정·엔티티는 저장된 값을 읽어 텍스트로만 보여 주고, 승인·반려는 기존 사람 승인 API를 그대로 쓴다.

## 범위 밖

- 그래프 재작성(확대·축소·이동·노드 끌기, 필터·검색, Alert를 Ticket에 접기, 노드 선택 시 해당 연결만 보기), Entity 보기, 그래프 상태를 주소에 남기기, 그래프 라이브러리 확정(D-079는 비워 둔다). 모두 새 이슈(번호 미정, 올라오면 이 계획에 적는다)에서 한다.
- Alert 제목·심각도·판정을 응답에 더하는 일(그래프 이슈가 필요하면 담당 승인을 다시 받는다).
- 디자인의 근거 없는 요소: 위험 경로 단계와 "공격 출발지·최초 진입·도착 서버" 같은 역할 서사, 선 라벨(`SQLi 진입` 등), 노드 설명 문구.
- 반려 이력(사유·시각)과 라운드 간 변화량(Ticket +n·엔티티 +n·판정 변경). #375 등 후속에서 한다.
- 개요의 "핵심 엔티티" 카드. 선정 기준이 데이터에 없다. 엔티티 탭에서 연결 수로 정렬해 본다.
- 엔티티 표의 "그래프에서 보기" 열(Entity 보기가 없다).
- 서버 쪽 페이지·정렬 API, 이전/다음용 서버 API.

## 완료 기준

- [ ] Incident를 누르면 전용 페이지(`/incidents/:id`)가 열리고, 사이드바가 유지되며, 주소로 바로 열린다. 옛 `?selected=inc_…` 주소도 새 주소로 간다
- [ ] 목록으로 돌아가면 필터·페이지 상태가 유지된다. 직접 링크로 열면 기본 목록으로 간다
- [ ] 이전/다음은 목록 state가 있을 때 그 안에서 이동하고, 없으면 비활성이다
- [ ] 상단 고정 헤더에 승인·반려가 있고, 권한과 `awaiting_review` 조건이 기존과 같다. 승인·반려 뒤 상세에 머물러 상태가 갱신된다(테스트가 있다)
- [ ] 헤더에 Ticket·Alert·엔티티 수, 판정 분포, 진행 단계가 보이고 엔티티 수가 엔티티 탭 숫자와 같다
- [ ] 탭 5개가 `?tab=`으로 열리고 새로고침·링크 공유 뒤에도 유지된다
- [ ] Ticket 30개, 엔티티 100개 규모의 샘플로 Ticket 표·엔티티 표가 검색·정렬·페이지·필터로 읽을 수 있고, 긴 값은 말줄임과 복사가 된다
- [ ] 분석 이력은 최신 라운드만 펼쳐지고 이전 라운드는 접혀 있다
- [ ] 권고 조치에 "왜 필요한가" 라벨이 없고 문단·구분선으로 나뉜다
- [ ] 관계 그래프 탭은 기존 그래프를 그대로 보이고, 연결 경로와 탐색 상태는 기본 화면에서 빠져 접힌 "분류 근거"에만 있다. Entity 버튼은 "준비 중"이다
- [ ] 엔티티가 없거나 Ticket이 없는 Incident의 빈 상태, 로딩, 오류 상태가 깨지지 않는다
- [ ] 응답 확장의 값과 계산 기준(판정 전 근거 0, 쿼리 수 고정, 기존 필드 불변)을 확인하는 테스트가 있고 `tests/fixtures/`의 샘플을 쓴다
- [ ] `pnpm contracts:check`로 생성 타입이 응답 모델과 맞다. `contracts/`의 JSON Schema는 바뀌지 않았다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`와 `frontend/`의 `pnpm contracts:check`, `pnpm lint`, `pnpm test`, `pnpm build`가 통과한다
- [ ] 디자인과 다른 곳을 PR에 적었다(심각도·판정·우선순위 표기, 오류 상태, 빼 둔 요소, 분류 근거 위치). 전·후 스크린샷은 사람이 붙인다(D-075)
- [ ] 새 그래프 이슈가 올라가 있고 그 번호가 PR 본문과 이 계획에 적혀 있다

## 토론으로 정한 것

이슈 본문과 달라진 점:

- **이슈를 둘로 나눴다.** 라우팅·탭·표·응답 확장·페이지 구조는 이 이슈에서, 그래프 재작성과 Entity 보기는 새 이슈에서 한다. 한 PR에 라우팅 변경, 응답 확장, 새 그래프 엔진이 함께 들어가면 리뷰가 어렵고, 새 라이브러리 결정의 위험을 따로 보기 위해서다. 이슈 본문의 그래프 조작·필터·Alert 접기·Entity 보기·노드 선택 시 연결만 보기 완료 기준은 새 이슈로 간다.
- **응답 확장이 필요하다.** 이슈의 "정하지 못함"이던 표 데이터는 기존 응답으로 부족했다(`tickets[]`에 `id`·`title`·`decision`만 있고, 엔티티에는 어느 Ticket·Alert에서 왔는지가 없다). 화면용 응답 모델에 필드를 더하는 것으로 정했다(D-080). 담당 승인은 위 "맞물리는 곳"에 적었다.
- **표 처리는 클라이언트에서 한다.** 한 Incident의 Ticket 수는 `max_incident_tickets` 설정(기본 10)으로 막혀 있어(D-027) 완료 기준의 Ticket 30개는 표본 규모이고 실환경은 10개 이하로 본다. 엔티티는 수백 개까지 한 응답으로 충분하다고 본다. 엔티티가 수천 개로 늘면 서버 페이지로 올린다.
- **목록 복귀·이전/다음은 서버 API 없이 라우터 state로 한다.** 직접 링크로 열면 기본 목록 이동만 되고 이전/다음은 비활성이다.
- **승인·반려 뒤에는 상세에 머문다.** 기존 동작(전체 쿼리 재조회)을 그대로 쓰고, 승인되면 Case 링크를 더한다.
- **디자인에서 뺀 것.** 데이터에 근거가 없는 서사(위험 경로, 역할 설명, 선 라벨)는 원칙 3과 이슈의 "공격 순서로 읽히지 않게"에 맞춰 뺐다. 반려 이력과 라운드 간 변화량은 저장된 데이터가 없어(D-076은 반려 사유·이벤트를 저장하지 않는다) 후속으로 뒀다. 개요의 "핵심 엔티티"는 선정 기준이 없어 이번에 만들지 않는다.
- **확정된 결정이 디자인과 다르면 결정을 따른다.** 심각도는 `N Level`(D-074), 판정은 `decision` 원문(D-078), 권고 우선순위는 높음·중간·낮음(D-072)이다.
- **디자인 파일.** 새 프레임 7개(개요·관계 그래프·Ticket·엔티티·분석 이력·빈 상태·로딩)는 사람이 `design/0-Ticket.pen`에 커밋한 뒤 알려 준다. 개발 시작 전에 pen MCP로 그 파일을 다시 확인하고, 이 계획을 쓸 때 읽은 활성 문서와 다르면 알린다. 오류 상태 프레임은 없다.
- **Entity 보기와 그래프 이슈의 입력.** Entity 보기는 같은 Alert에 함께 나온 엔티티를 잇고 같은 Alert 안의 `src`→`dst` role만 화살표로 그리며, 이름은 "연결된 엔티티", 처음에는 연결 수 상위 60개만 보인다. 그래프 라이브러리는 d3-force로 배치만 계산하고 SVG·HTML 노드를 직접 그리는 안(D-079 후보)이다. 이 안은 새 이슈에서 확정하며 이 이슈에서는 만들지 않는다.
- **계획 376과의 관계.** 계획 376의 "Entity 모드 범위 밖"은 이 이슈에서도 이어지고 새 이슈가 이어받는다. 계획 376은 고치지 않는다.
- 결정 목록: D-080. D-079는 그래프 이슈의 안건용으로 비워 둔다.

## 바뀐 점
