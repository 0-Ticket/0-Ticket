---
issue: 274
date: 2026-11-09
owner: Pandyo
supersedes: []
---

# UI 개선: pen.dev 디자인 14개 화면으로 교체

## 목표

#266에서 실제 조회 API에 연결한 화면을 pen.dev 디자인(`0-Ticket.pen`)의 14개 화면 모양으로 바꾼다.
API 호출, 상태 관리, 라우팅, 데이터 형식은 그대로 두고 기존 동작(조회, 필터, 페이지 이동, 상세,
원본 이동, 로딩·빈 상태·오류 재시도)을 모두 유지한다.

## 방법

### 디자인 읽기

- AI가 pen.dev MCP로 `.pen`을 직접 읽어 구현한다. 사람이 내보낸 코드는 받지 않는다.
- `.pen`은 레포에 커밋하지 않는다. 디자인 원본은 레포 밖에 있고 담당자가 보관한다.
  MCP는 VS Code의 pen.dev 확장에 열린 문서만 읽는다.

### 화면 대응

| # | 디자인 | 경로 | API |
|---|---|---|---|
| 01 | Dashboard | `/` | `GET /api/dashboard` |
| 02·03 | Alert·Event list | `/alerts`, `/events` | `/api/dashboard`(정규화 현황), `/api/alerts`, `/api/events` |
| 04 | Ticket list | `/tickets` | `/api/dashboard`(위험도), `/api/tickets` |
| 05 | Incident list | `/incidents` | `/api/dashboard`(상태), `/api/incidents` |
| 06·07 | Awaiting approval·Approved cases | `/cases?tab=waiting`, `/cases` | `/api/incidents?status=awaiting_review`, `/api/cases` |
| 08 | Hunting list | `/hunts` | `/api/dashboard`(헌팅), `/api/hunts` |
| 09~14 | 상세 패널 | 각 목록의 `?selected=<id>` | 각 `/{id}` 상세 |

- 디자인의 재사용 컴포넌트를 React 컴포넌트로 옮긴다: 사이드바, 페이지 제목, 푸터, 목록 카드,
  필터 칩, 상태·위험도 배지, 페이지 이동, 상세 패널, JSON 필드표.
- 메뉴·화살표 아이콘은 디자인의 SVG 경로를 그대로 쓴다. 차트는 Recharts와 CSS 막대로 만든다.
- 사이드바 224px는 고정하고 본문은 창 폭에 맞춰 늘린다(디자인은 960px 한 폭).

### 동작

- 필터는 칩으로 한 값만 고른다. 고른 칩을 다시 누르면 해제한다. 바꾸면 cursor와 페이지를 처음으로 되돌린다.
- 페이지 이동은 이전/다음과 "N 페이지"다. 지나온 cursor는 브라우저(URL)에 쌓아 둔다.
  API가 전체 건수를 주지 않으므로 전체 페이지 수는 표시하지 않는다.
- JSON 필드표: 객체를 펼쳐 `키 = 값` 행으로 보이고 "원본 JSON"으로 전환한다. 키와 값 모두 텍스트로만 표시한다(D-019).
- 대시보드 04번 카드는 디자인 문구에 `ticket_status.escalated`를 쓴다. 전체 Ticket 수(`flow.tickets`)는
  위험도 카드 제목의 "전체 N건"으로 옮긴다. "Risk Sum" 열 이름은 실제 값(`display_severity`)에 맞춰 "위험도"로 쓴다.
- 상태는 기존 이름표를 쓰고 위험도는 "N Level", 0은 "미상"으로 표시한다. 디자인 견본의 없는 상태값은 쓰지 않는다.
- 사이드바의 "관리자"는 고정 텍스트, "설정"은 누를 수 있지만 동작이 없는 버튼이다.
  D-020 전까지의 임시 표시이며 인증·권한과 관계없고 API를 부르지 않는다.
- 로고는 받은 PNG를 2배 크기(112×156)로 줄여 `frontend/src/assets/o-ticket-mark.png`에 둔다.
- 폰트는 `@fontsource/{inter,roboto-mono,michroma,jura}` 5.3.0으로 번들한다(D-046). 한글은 시스템 폰트로 대체한다.

### 디자인에 없지만 살리는 기능

대시보드 "분석 결과가 있는 Incident" 카드, 집계 새로고침 버튼, 범위 안내 문구(전체 보관 자료 기준·개발 시드
포함·시간대), Ticket 출처 필터, Case 상태 필터, Alert·Event 위험도 열, 목록의 개발 시드 표시(제목 옆 배지),
정규화 실패 코드·결과 없음, 대응 방안 제안, L3 Ticket의 원본 Hunt 이동, Hunt 실행 요약 목록,
ID 형식 검사 뒤 내부 이동, URL 쿼리(`selected`·`status`·`origin`·`severity`·`cursor`)로 상태 유지,
Incident 상세의 비활성 승인·반려와 안내 문구, Case 대기 탭의 "아직 Case가 아님" 안내.

### 순서와 커밋

계획 커밋 → 폰트·로고·공통 컴포넌트 → 페이지 교체. 테스트를 먼저 고치거나 추가하고 구현한다.

- docs(plans): add plan for ui redesign (#274)
- feat(frontend): redesign SOC pages from pen design (#274)

## 바꿀 곳

- `frontend/src/`: 화면 컴포넌트, 스타일, 로고, 화면 테스트
- `frontend/package.json`, `frontend/pnpm-lock.yaml`: 폰트 패키지
- `docs/decisions.md`: D-046
- `docs/notes/274-ui-redesign.md`: 개발 기록

## 다른 코드와 맞물리는 곳

없음. 백엔드, API 계약, 생성 타입(`frontend/src/api/generated/`)은 바꾸지 않는다.

## 범위 밖

로그인·SIEM 설정 화면, 승인·반려 동작, 전체 건수 API, 백엔드 변경, threat-news·ticketing-policy 화면 연결,
자동 주기 갱신, 서버 배포.

## 완료 기준

- [ ] 14개 화면이 디자인대로 보인다(사람이 확인)
- [ ] 위 "살리는 기능"과 #266의 조회·필터·페이지 이동·상세·원본 이동이 그대로 된다(사람이 확인)
- [ ] `frontend/src/api/generated/`를 손으로 고치지 않았다
- [ ] 외부 문자열이 JSON 필드표·원본 JSON 모두에서 텍스트로만 보이는 테스트가 있다
- [ ] 칩 필터, 이전/다음 페이지, 설정 버튼이 API를 부르지 않음을 확인하는 테스트가 있다
- [ ] pnpm lint, pnpm test, pnpm build, pnpm contracts:check 통과
- [ ] uv run ruff format --check ., uv run ruff check ., uv run pytest 통과
- [ ] D-046을 `docs/decisions.md`에 적었다
- [ ] PR에 바뀐 화면의 전·후 스크린샷이 있다(사람이 첨부)

## 토론으로 정한 것

- 이슈의 "사람이 내보낸 코드를 합친다" 대신 AI가 `.pen`을 MCP로 읽어 구현한다. `.pen`은 커밋하지 않는다.
- 이슈의 생성 타입 경로를 실제 경로 `frontend/src/api/generated/`로 바로잡았다.
- 이슈의 "승인·로그인·권한 유지"는 현재 기능이 없어 해당하지 않는다. 지킬 동작은 조회 계열이다.
- 사이드바: "관리자" 고정 텍스트, "설정"은 동작 없는 버튼. AI는 비활성을 추천했으나 사람이 누를 수 있는 버튼으로 정했다.
- 페이지 이동은 cursor를 쌓는 이전/다음과 "N 페이지"(전체 수 없음).
- 대시보드 04번은 `escalated` 수, 전체 Ticket 수는 위험도 카드 제목으로 옮긴다.
- 폰트는 @fontsource 번들(D-046). 상태는 기존 이름, 위험도는 "N Level".

## 바뀐 점

- 2026-11-10, 사람이 push 전에 정했다. 위 "살리는 기능" 중 아래를 뺀다. 개발 시드 구분은 더 쓰지 않는다.
  - 모든 화면: 범위 안내 문구(전체 보관 자료 기준·개발 시드 포함·시간대), 집계 새로고침 버튼,
    "개발 시드" 문구(목록 배지·상세 안내), "최신순 · 페이지당 N건"
  - 대시보드: "분석 결과가 있는 Incident" 카드
  - Alert·Event: 정규화 성공률 퍼센트
  - Ticket·Incident·Hunting 개요: 상태·위험도별 건수 문구(차트는 유지), Ticket의 "미상 N건"
  - Hunting 개요: "전체 가설 대비 승격 비율", 제목 구분자를 "·" 대신 "/"로 변경
- 2026-11-10, 사람이 정했다. 페이지 표기를 "N 페이지" 대신 "N/최대"로 바꾼다. 목록 API는 그대로이고(백엔드·계약 변경 없음)
  최대 페이지는 대시보드 집계 건수를 페이지 크기 25로 나눠 올림한다. 집계가 없는 조합(Ticket의 위험도·출처
  필터)은 "N/-"로 표시한다. 위 "전체 페이지 수는 표시하지 않는다"와 "전체 수 없음"을 이것으로 바꾼다.
