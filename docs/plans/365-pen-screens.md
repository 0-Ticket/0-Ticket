---
issue: 365
date: 2026-11-20
owner: Pandyo
supersedes: []
---

# pen.dev 디자인대로 전체 화면 구현하고 API와 연결

## 목표

`design/0-Ticket.pen`의 화면 24개를 현재 화면과 나란히 놓고 차이를 고친다. 화면이 쓰는 값 중 API에 없는 것(Ticket 상세의 원본 Alert 요약, Incident 상세의 소속 Ticket 제목)을 채우고, Incident 승인·반려를 만든다. 승인은 Case를 만들고 반려는 `analyzing`으로 되돌린다. PR 한 개이고 커밋만 화면 그룹별로 나눈다.

## 방법

### 디자인 읽기와 근거

- 기준 파일은 저장소의 `design/0-Ticket.pen`이다. 2026-11-20에 pen.dev MCP가 연 문서의 SHA-1이 `origin/main:design/0-Ticket.pen`과 같음을 확인했다(`ff0e8fda…`, 1,508,068바이트). 암호화돼 있어 내용은 MCP로만 읽는다.
- 이 계획의 "디자인 확인" 근거(MCP 텍스트·노드 이름 읽기. 간격·색은 읽지 않았다):
  - CSV 등록: Ticket 정책 화면의 버튼 "CSV로 등록하기" 하나. 업로드 창·열 형식·결과 화면 없음.
  - Hunting 심각도: 목록의 심각도 열이 전 행 "—".
  - 근거 검토: Ticket 상세 "근거 검토 · N개 신호 일치", 근거별 "강한 근거/보조 근거", "최종 판정 · MALICIOUS · 신뢰도 92%".
  - 엔티티 그래프: "Incident 관계 그래프"(Ticket·Alert·Entity, 노드 패널에 연결 Ticket·관련 Alert·자산 중요도)와 "Entity 공격 경로"(4단계 서술) 두 모드.
  - Case: 승인 대기 Incident 탭은 목록과 안내문뿐이고 버튼·입력칸이 없다. 승인·반려 버튼은 Incident 상세의 "검토 대기" 상태에만 있고 입력칸은 없다. Case 상세 패널과 상태 변경 버튼은 디자인에 없다.
  - 사람 종결(`dismissed`)·`human_handling` 처리 화면은 없다. 목록 필터 칩만 있다.
  - Top 10 카드의 5개 샘플 행은 상태가 승인/확인됨·승인 대기·위협 아님·분석 중·사람 처리다(확정·기각 포함).
- 열린 문서의 심각도 라벨은 한국어(치명…미상)이고 "N Level"은 0곳이다. D-074가 기준이고 디자인 쪽이 틀린 것으로 본다.

### 커밋 순서(화면 그룹별)

테스트를 먼저 쓰고 구현한다. 각 커밋은 `pnpm contracts:check`·`pnpm lint`·`pnpm test`·`pnpm build`와 `uv run` 3종이 통과한 상태로 둔다.

1. `docs(plans): add plan for pen screens (#365)` — 이 계획과 `docs/decisions.md`(D-076, D-077)
2. `feat(api): approve and reject incidents (#365)` — 쓰기 API, 권한 `UNUSED` 정리, 테스트
3. `feat(api): add alert summaries to ticket detail and ticket titles to incident detail (#365)` — 응답 모델 두 곳, `pnpm contracts`로 생성 타입 갱신
4. `feat(frontend): align layout and auth screens with the design (#365)` — 사이드바·사용자 영역·403·로그인·가입·가입 완료·비밀번호 변경 차이
5. `feat(frontend): align dashboard with the design (#365)` — "승인 대기" 이름, Top 10 기준 테스트
6. `feat(frontend): align alert and event screens with the design (#365)`
7. `feat(frontend): align ticket screens with the design (#365)` — 원본 Alert 요약 한 번에, 근거 검토(판정·신뢰도·이유·근거 목록)
8. `feat(frontend): align incident screens and add approve and reject (#365)` — 소속 Ticket 제목, 가장 최근 라운드 제안만, 승인·반려 버튼, 그래프 대조
9. `feat(frontend): align case screens with the design (#365)`
10. `feat(frontend): align hunting screens with the design (#365)`
11. `feat(frontend): align policy, user and settings screens with the design (#365)` — CSV 버튼은 지금처럼 동작 없음, 권한 편집기에서 `incident.approve`·`incident.reject` 변경 가능
12. `docs(notes): record development of pen screens (#365)` — `/soc-done`에서

디자인에 없는 화면(Alert·Event·Case·Hunting 상세, 빈 상태, 로딩, 오류)은 기존 화면 스타일에 맞춰 최소한으로 만들고 PR에 적는다.

### Incident 승인·반려 API (D-076)

- `POST /api/incidents/{incident_id}/approve`(권한 `incident.approve`), `POST /api/incidents/{incident_id}/reject`(권한 `incident.reject`). 요청 본문은 없다(반려 사유 없음). ID 형식 검사는 기존 `check_id(…, ("inc",))`를 쓴다.
- 승인: 한 트랜잭션에서 Incident 행을 `FOR UPDATE`로 잠그고 `status = 'awaiting_review'`일 때만 진행한다. `incidents.status`를 `confirmed`로 바꾸고 `updated_at`을 갱신하며 `cases`에 행을 하나 만든다.
  - `id`는 `cas_` + UUIDv7(`soc.ids`), `incident_id`는 그 Incident, `title`·`entities`는 Incident에서 복사, `summary`는 Incident `summary`를 그대로 복사(분석 전 null 허용).
  - `severity`는 `assessed_severity`, 없으면 Incident `severity`. `confirmed_by`는 로그인 사용자의 `username`, `confirmed_at`은 현재 시각, `status`는 `open`, `assignee`·`resolved_at`은 null, `details`는 `{}`.
- 반려: 같은 조건(`awaiting_review`)에서 `incidents.status`를 `analyzing`으로 바꾸고 `updated_at`만 갱신한다. 기존 L2 분석 워커가 `analyzing`을 집어 재분석한다(`src/soc/l2/analyze/worker.py`). `review_round` 증가, 한도 처리, 반려 사실의 모델 입력 전달은 하지 않는다(별도 이슈).
- 같은 Incident에 요청이 겹치면 잠금 때문에 하나만 통과하고 나머지는 409다. 승인 중복은 `cases.incident_id UNIQUE`가 마지막 방어선이다.
- 응답: 성공은 200이고 갱신된 Incident를 담는다(승인은 만든 Case의 ID도 담는다). 상태가 `awaiting_review`가 아니면 409와 현재 상태(`code: incident_not_awaiting_review`)를 돌려준다. 없는 ID는 404, 권한 없음은 기존 403 형식이다. 응답 모델은 `ui_models.py`에 두고 TypeScript는 `pnpm contracts`로 생성한다(D-003).
- 변경 요청이므로 기존 `Origin` 검사(`docs/security.md` "로그인과 권한")를 그대로 받는다. 에이전트나 L2 입력에 사람이 쓴 문자열이 새로 들어가지 않는다.

### 권한

- `incident.approve`, `incident.reject`는 admin에게만 기본 부여한다. admin은 항상 전부 가지므로 마이그레이션이 없다. `ANALYST_DEFAULT`(조회 9개)는 바꾸지 않는다.
- 사용자 관리에서 개별 부여가 되는지 확인한 결과: 백엔드는 이미 `PUT /api/users/{id}/permissions`(권한 `user.permission`)로 가능하다. 부여자가 가진 권한만 줄 수 있고(규칙 3), admin 계정은 대상이 아니며, 자기 권한은 바꿀 수 없다(`src/soc/auth/store.py` `set_permissions`). 다만 화면의 권한 편집기가 `incident.approve`·`incident.reject`를 `NOT_READY`로 막고 있다(`frontend/src/users/users-page.tsx`). 이 두 개를 `NOT_READY`에서 빼서 개별 부여가 되게 한다. `incident.close`는 라우트가 없어 그대로 둔다.
- `src/soc/auth/permissions.py`의 `UNUSED`를 `{"incident.close"}`로 줄이고, 이를 확인하는 `tests/test_auth.py`의 두 테스트를 고친다. 라우트 권한 검사는 기존 `require_permission` 방식을 그대로 쓴다.

### 응답 모델 변경(화면용 API, 생성 타입 갱신)

- `TicketDetail`: 원본 Alert 요약 목록을 더한다(Alert ID, 제목, 시각, 심각도). 조회는 Ticket의 `alert_ids`에 대한 한 번의 쿼리이고, 화면은 Alert를 하나씩 부르지 않는다. 요약 문자열은 밖에서 온 데이터라 텍스트로만 표시한다.
- `IncidentDetail`: 소속 Ticket을 ID만이 아니라 제목과 함께 준다. 제목은 #352(D-070)의 `tickets.title`을 쓴다. 기존 `ticket_ids`는 유지한다.
- 대응·탐지 제안: API는 그대로 두고, 화면이 `artifacts[0]`(분석 라운드 내림차순 첫 항목)의 `id`와 같은 `artifact_id`의 제안만 보여 준다. `priority`·`rationale`이 null이어도 깨지지 않게 한다(D-072).
- `contracts/`의 JSON Schema(Ticket, Incident, Case 등 데이터 계약)는 바꾸지 않는다.

### Dashboard와 "승인 대기"

- "내 승인 대기"는 "승인 대기"로 이름을 바꾸고 `incident_status.awaiting_review` 수로 정의한다(담당자 개념 없음). 사이드바·흐름 카드·툴팁 문구와 테스트(`App.test.tsx`, `auth.test.tsx`)를 함께 고친다.
- Incident 심각도 Top 10은 지금 코드 기준(`analyzing`·`awaiting_review`·`human_handling`·`held`, 확정·기각 제외)을 유지한다. 기준을 D-077로 적고 이를 확인하는 테스트(확정·기각이 빠지는지)를 더한다.

### 승인·반려 화면

- Incident 상세에서 상태가 `awaiting_review`일 때만 버튼이 보이고, 권한이 있는 버튼만 보인다(`useCan`). 권한이 없으면 숨긴다. "승인·반려 기능은 아직 제공하지 않습니다." 문구는 구현에서 뺀다.
- 성공하면 상세와 목록·대시보드 집계를 다시 불러온다. 409는 "이미 처리된 Incident예요(현재 상태: …)"로 보여 주고 다시 불러온다. 반려 사유 입력칸은 없다.

### 근거 검토

Ticket 상세에 판정(`decision`), 신뢰도(`confidence`), 이유(`reason`), 근거 ID 목록(`evidence_ids`)만 보여 준다. "N개 신호 일치"와 근거별 강도, 디자인의 근거 문장은 표시하지 않는다(판정 계약에 원천이 없다). 모두 텍스트로만 표시한다.

### 엔티티 그래프

디자인의 "Incident 관계 그래프" 모드만 현재 구현(#321)과 대조해 차이를 고친다. 노드 패널의 자산 중요도는 Alert의 `assets[].criticality`(1~5)를 쓰고 값이 없으면 "—"다. "Entity 공격 경로" 모드는 만들지 않는다.

## 바꿀 곳

- `src/soc/api/routes/workflow.py`: 승인·반려 라우트
- `src/soc/api/ui_models.py`, `src/soc/api/ui_read.py`: 응답 모델(승인·반려 결과, `TicketDetail`·`IncidentDetail`)과 읽기 쿼리
- `src/soc/auth/permissions.py`: `UNUSED` 축소
- `frontend/src/api/generated/`: `pnpm contracts`로 생성(손으로 고치지 않는다)
- `frontend/src/`: `layout.tsx`, `dashboard.tsx`, `flow-chart.tsx`, `list-view.tsx`, `detail-panel.tsx`, `incident-graph.tsx`, `policy-page.tsx`, `users/users-page.tsx`, `auth/pages.tsx`, `style.css`와 해당 테스트
- `tests/`: `test_auth.py` 수정, 승인·반려·상세 응답 테스트(`db` 표시 포함), `tests/fixtures/`의 손으로 만든 샘플
- `docs/decisions.md`: D-076, D-077과 기록
- `docs/plans/365-pen-screens.md`, `docs/notes/365-pen-screens.md`

## 다른 코드와 맞물리는 곳

- **공통 계약 변경이라 L1·L2·L3 담당 승인이 필요하다. 이 계획의 이슈 댓글로 알리고, 늦어도 PR 전에 받는다(받은 사람은 PR에 적는다).**
  - 쓰기 API: Incident 상태 `awaiting_review`→`confirmed`/`analyzing`을 화면이 바꾼다. `cases` 행이 이 경로로 처음 만들어진다.
  - `TicketDetail`·`IncidentDetail` 응답 변경(화면용 응답 모델).
  - 반려의 `analyzing` 복귀는 L2 분석 워커가 바로 재분석을 돌리게 한다(LLM 호출 발생, 같은 Incident의 `analysis_round`가 늘어난다).
  - Case가 생기면 유사 사례 검색 도구(D-053)의 `decided_by`가 그 Incident의 Ticket에서 `human`으로 바뀐다. L1·L2 담당 확인.
- `contracts/`의 데이터 계약(Ticket, Incident, Case 등)과 DB 스키마·마이그레이션은 바꾸지 않는다.
- `UNUSED`를 바꾸므로 `tests/test_auth.py`의 두 테스트와 `users-page.tsx`의 `NOT_READY`가 같이 바뀐다.
- 원칙 5(대응은 제안까지)와 부딪히지 않는다. 승인은 Incident를 Case로 확정하는 일이고 차단·격리 같은 조치를 실행하지 않는다.

## 범위 밖

- L2의 반려 재분석 보강(`review_round` 증가, 한도 도달 시 `human_handling`, 반려 사실 전달): 별도 이슈
- 반려 사유 입력과 저장
- Case 상태 변경 API·화면, `assignee` 지정
- CSV 등록 동작: 버튼만 둔다. 별도 이슈
- 근거별 강도와 "N개 신호 일치"(판정 계약 변경 필요)
- "Entity 공격 경로" 모드, 엔티티 그래프 가독성 개선
- 사람 종결(`dismissed`)·`human_handling` 처리 화면과 API(`incident.close`)
- `design/0-Ticket.pen` 수정. 아래 "디자인과 다른 곳"은 PR에 표시만 한다

## 디자인과 다른 곳 (PR에 표시)

- 심각도 라벨: 디자인은 치명·심각·높음·보통·낮음·정보·미상, 구현은 D-074(`N Level`·미상·"—")
- "내 승인 대기": 구현은 "승인 대기"
- "승인·반려 기능은 아직 제공하지 않습니다." 문구: 구현은 뺀다(승인·반려가 동작한다)
- Top 10 카드의 승인/확인됨·위협 아님 행: 구현은 확정·기각을 제외한다(D-077)
- Ticket 상세 "N개 신호 일치"·근거별 강도·근거 문장: 구현은 표시하지 않는다
- Incident 영향 문장의 "높음(4)"은 L2가 쓴 텍스트라 화면이 바꾸지 않는다
- "Entity 공격 경로" 모드, CSV 등록 동작: 구현하지 않는다
- 디자인에 없는 화면(상세, 빈 상태, 로딩, 오류)은 기존 화면 스타일에 맞춰 최소한으로 만든 것이다

## 사람이 직접 확인할 시나리오

1. admin으로 승인 대기 Incident를 승인한다 → Incident가 `confirmed`가 되고 Case가 열림 상태로 하나 생기며 Case 목록·대시보드 집계에 반영된다.
2. admin으로 다른 승인 대기 Incident를 반려한다 → `analyzing`이 되고 L2 재분석이 도는지 로그로 본다(재분석 비용이 드는 것을 알고 한다).
3. 이미 처리된 Incident에 승인 또는 반려를 다시 요청한다(두 창에서 동시에 눌러 본다) → 하나만 성공하고 나머지는 "이미 처리된 Incident예요" 안내가 보이며 Case가 둘 생기지 않는다.
4. analyst 계정으로 Incident 상세를 연다 → 승인·반려 버튼이 보이지 않는다.
5. admin이 사용자 관리에서 analyst에게 `incident.approve`만 부여한다 → 그 계정에는 승인 버튼만 보인다.
6. 분석 중·승인 대기가 아닌 Incident 상세에서는 버튼이 없다.
7. Ticket 상세를 열어 원본 Alert 요약이 한 번의 요청으로 보이는지 네트워크 탭으로 확인한다.
8. 로그인, 가입, 가입 완료, 비밀번호 변경, 로그아웃, 403 화면을 로컬에서 연다.
9. `pnpm --dir frontend dev`로 모든 화면을 열어 디자인과 나란히 본다.

## 완료 기준

- [ ] 구현할 화면 목록의 화면을 모두 디자인과 나란히 놓고 확인했고, 다른 부분은 PR의 "디자인과 다른 곳"에 이유와 함께 적었다
- [ ] 변경 전·후 스크린샷을 화면별로 PR에 붙였다(사람이 첨부, D-075)
- [ ] 심각도 표시가 모든 화면에서 `N Level`·미상·"—" 규칙을 따른다(테스트 포함, D-074)
- [ ] Ticket 상세가 원본 Alert 요약을 요청 한 번으로 보여 준다(Alert 수와 무관한 조회 횟수 테스트)
- [ ] Incident 상세가 소속 Ticket의 제목을 보여 주고, 가장 최근 라운드의 제안만 보여 주며, `priority`·`rationale`이 비어 있어도 깨지지 않는 테스트가 있다
- [ ] Dashboard Top 10(확정·기각 제외)과 "승인 대기"(`awaiting_review` 수)의 기준이 `docs/decisions.md`(D-077)에 있고 테스트가 있다
- [ ] 승인·반려 API: 권한 없는 요청 403, `awaiting_review`가 아니면 409와 현재 상태, 동시·중복 요청에서 Case가 하나만 생기는 `db` 테스트, 승인 시 Case 필드(제목·요약·엔티티 복사, `severity`, `confirmed_by`, `open`)와 반려 시 `analyzing` 복귀를 확인하는 테스트가 있다
- [ ] `incident.approve`·`incident.reject`가 admin에게만 기본으로 있고, 사용자 관리에서 개별 부여·회수가 되는 테스트가 있다(`test_auth.py`·`users.test.tsx`)
- [ ] 추가·변경한 응답 모델과 생성 코드가 맞다(`pnpm contracts:check`)
- [ ] 승인·반려가 동작하는 화면에서 "아직 제공하지 않습니다" 문구가 없고, 권한 없는 계정에는 버튼이 없다(테스트)
- [ ] "사람이 직접 확인할 시나리오"를 사람이 확인해 결과를 `docs/notes/`에 적었다
- [ ] 빈 상태, 로딩, 오류 상태가 화면마다 있다
- [ ] 로컬 개발 서버로 모든 화면을 직접 열어 확인했다(`pnpm --dir frontend dev`)
- [ ] 키·비밀 값이 코드, 테스트, 로그, notes, PR에 없다
- [ ] `pnpm contracts:check`, `pnpm lint`, `pnpm test`, `pnpm build` 통과
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run pytest -m "db or qdrant"` 통과
- [ ] L1·L2·L3 담당 승인이 PR 전에 있다(승인한 사람은 PR에 적는다)
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록, 별도 이슈 두 개(L2 반려 재분석, CSV 등록)의 초안을 PR에 적었다

## 토론으로 정한 것

이슈 본문과 달라진 점이다.

- **디자인 기준 파일 확인.** 이슈는 `design/0-Ticket.pen`을 기준으로 한다. pen.dev MCP가 읽은 문서와 저장소 파일이 같은 내용임을 체크섬으로 확인했다.
- **심각도 라벨.** 이슈 본문의 `N Level`을 따른다. 디자인 파일의 한국어 라벨은 틀린 것으로 보고 PR에 표시만 한다(D-074). `.pen`은 이번에 수정하지 않는다.
- **PR은 한 개.** 이슈 본문의 선택지 중 "한 PR"으로 정했고, 커밋만 화면 그룹별로 나눈다.
- **승인·반려의 범위.** 상태 변경과 Case 생성만 만든다. 반려는 `analyzing` 복귀까지이고 L2 워커가 이미 재분석한다. 한도·`review_round`·반려 사실 전달은 별도 이슈다. 이유: L2 쪽 코드와 담당이 달라 한 PR에 넣으면 리뷰가 어렵다. 반려 사유는 받지 않는다(디자인에도 입력칸이 없다).
- **승인 방식.** 조건부 UPDATE(`awaiting_review`일 때만)와 409. 이미 처리된 Incident에 같은 요청이 와도 성공으로 보이지 않게 한다.
- **권한.** `incident.approve`·`incident.reject`는 admin 기본, analyst 기본 없음. 개별 부여는 이미 되는 기능을 열어 준다(`NOT_READY` 해제).
- **"내 승인 대기".** 담당자 개념이 없어 "승인 대기"로 이름을 바꾸고 `awaiting_review` 전체 수로 정의한다.
- **Top 10.** 코드 기준(확정·기각 제외)을 유지하고 D-077에 적는다. 디자인의 확정·기각 행은 무시한다.
- **Case 상태 변경.** 디자인에 버튼이 없어 이번 범위에서 뺀다(API도 만들지 않는다).
- **근거 검토.** 판정 계약에 있는 값만 보여 준다. 이유: "N개 신호 일치"와 근거별 강도는 데이터 원천이 없어, 보이려면 L1 판정 계약을 바꿔야 한다.
- **CSV 등록.** 버튼만 두고 동작은 별도 이슈.
- **엔티티 그래프.** "Incident 관계 그래프"만 대조하고 "Entity 공격 경로"는 뺀다. 가독성 개선은 이슈 본문대로 제외.
- **제안 라운드 필터.** 이슈 본문대로 화면이 가장 최근 `artifact_id`만 보여 주고 API는 바꾸지 않는다.
- **Ticket·Incident `title`.** #352·#353·#355가 머지돼 있어 그 값을 쓴다(이슈의 "정하지 못함" 해소).
- **인증 화면(#286)과 엔티티 그래프(#321).** 이미 구현돼 있어 구현이 아니라 대조와 차이 수정이다.
- 결정 목록에 올린 안건: D-076(Incident 승인·반려), D-077(화면 집계 기준).

## 바뀐 점
