---
issue: 386
date: 2026-11-26
owner: Pandyo
supersedes: []
---

# [UI] Incident 상세 Ticket·엔티티 탭 열 너비 정리 (글자 겹침·줄바꿈 해결, sticky 탭 줄 수정)

## 목표

`/incidents/:id`의 Ticket 탭과 엔티티 탭에서 글자가 겹치거나 꺾이지 않고, 스크롤해도 탭 줄이 상단에 붙는다. 1024px 이상에서 두 표가 가로 스크롤 없이 들어가고, 1024px 아래는 가로 스크롤이다. 계획 384가 완료 기준으로 잡았지만 배포 화면에서 지켜지지 않은 부분(열 너비, "복사" 줄바꿈, sticky)을 CSS로 바로잡는다. `contracts/`와 화면용 응답은 바꾸지 않는다.

## 방법

### 원인

- `style.css`의 `.table-scroll th:first-child {width: 50%}`, `nth-child(2) {15%}`, `nth-child(3) {13%}`가 `table-layout: fixed`와 함께 모든 `.table-scroll` 표에 걸려 있다(목록 화면 `list-view.tsx`도 쓴다). Ticket 표는 시각·근거 수·분류 탐색·상세 4열이 남은 22%를 나눠 약 40px씩 받아 겹치고, 엔티티 표는 `종류`가 50%, `값`이 15%다.
- 이 전역 규칙은 고치지 않는다(목록 화면 보호). `.incident-table-card` 아래에서만 덮어쓴다.
- `.incident-tabs`의 sticky는 부모 `.incident-page`가 `display: grid`라서 grid 영역(자기 칸) 안에서만 움직여 붙지 못하는 것으로 본다(가설. 브라우저에서 확인한다).

### 표 열 너비

- 두 표에 열별 폭을 명시한다(`<colgroup>` 또는 CSS 클래스). 제목 열(Ticket)과 값 열(엔티티)만 남는 폭을 받고 나머지는 고정 폭이다. 1024px에서 표 영역은 약 704px이다. 시작 값은 아래이고 브라우저에서 맞춘 값을 기록에 남긴다.
  - Ticket: 판정 70, 위험도 64, 시각 110, 근거 수 56, 분류 탐색 120, 상세 72, 제목 나머지(약 210px 이상)
  - 엔티티: 종류 64, role 64, 연결 130, 최초 관측 110, 작업 96, 값 나머지(약 240px 이상)
- 표 `min-width`를 제목·값 열이 이 폭 아래로 줄지 않는 값으로 둔다. 1024px 미만은 `.table-scroll`의 가로 스크롤이다.
- 시각 열이 110px보다 넓게 나오면 시각 표기는 줄이지 않고 표 `min-width`를 올려 가로 스크롤로 둔다(사람이 정함).
- 이 표 안에서는 `.incident-clip .clip`의 `max-width: 420px` 상한을 풀어 열 폭만큼 보인다. 긴 값은 말줄임이고 전체 텍스트는 `title`에 있다. 다른 화면의 `.incident-clip`은 바꾸지 않는다.

### 줄바꿈 정리

- "복사", 시각, 개수(`근거 수`, `Ticket N · Alert N`), 버튼·링크 라벨(`상세 보기`, `그래프에서 보기`)은 `white-space: nowrap`이다.
- `분류 탐색` 셀은 한 줄 + 말줄임이고 전체 문구는 `title`에 둔다. `statusText` 문구는 바꾸지 않는다.
- 제목은 한 줄 말줄임 + `title`이고 Ticket ID(`Clip`)는 제목 아래 줄에 둔다. 모두 텍스트로만 쓴다(`docs/security.md` "화면").

### 첫 열 잘림

- 1080px, admin 계정에서 Ticket 탭 첫 열 앞글자가 잘려 보였다. 코드만으로는 원인을 알 수 없다(말줄임은 끝을 자른다). 열 폭을 고친 뒤 브라우저에서 같은 폭으로 재현한다. 남아 있으면 원인을 찾아 고치고, 재현되지 않으면 기록에 "재현 안 됨"과 확인한 폭을 적는다.

### sticky

- `.incident-page`를 `display: grid`에서 세로 flex(`display: flex; flex-direction: column; gap: 16px`)로 바꾼다. 부르는 곳은 `incident/page.tsx` 하나다. 브라우저에서 원인이 다르면 멈추고 말한다.

### 확인

- 개발 서버(`?sample=graph`, 긴 제목·긴 URL·긴 해시 값 샘플)에서 두 탭을 1024/1280/1440/1920px로 본다. 1024px에서는 가로 스크롤이 없어야 하고, 1024px 아래는 표만 스크롤되는 것을 확인한다. 스크롤해도 탭 줄이 붙는지 본다. 전·후 스크린샷은 사람이 PR에 붙인다(D-075).
- 화면 확인은 AI가 개발 서버와 브라우저 도구로 하고, 백엔드를 띄울 수 없으면 사람이 확인한다.
- 긴 값 샘플은 `tests/fixtures/`에 손으로 만든다(IP는 문서용 대역, 도메인은 `example.com`). 샘플 모드(`incident/dev-sample.ts`)가 읽는 기존 샘플에 필요한 만큼만 더한다.

### 테스트(먼저 쓴다)

- jsdom은 CSS 레이아웃을 못 본다. 테스트로 지키는 것: 열 폭을 정하는 요소·클래스가 두 표에 있다, 긴 값이 말줄임 요소에 들어 있고 `title`에 전체 텍스트가 있다, `분류 탐색`이 `title`을 가진다, 라벨이 `nowrap` 클래스를 쓴다, 샘플 값에서 HTML이 해석되지 않는다. 겹침·줄 수·sticky는 브라우저 확인으로만 본다고 기록에 적는다.

## 바꿀 곳

- `frontend/src/style.css`: `.incident-table-card` 아래 열 폭·`nowrap`·말줄임 규칙, `.incident-page` flex
- `frontend/src/incident/ticket-table.tsx`, `entity-table.tsx`: 열 폭 정의, `분류 탐색` 셀 `title`, 클래스
- `frontend/src/incident/kit.tsx`: 필요하면 `Clip` 한 곳(이 표에서만 쓰는 클래스로 구분)
- `frontend/src/` 아래 `incident-page.test.tsx`와 `tests/fixtures/frontend/`의 긴 값 샘플
- `docs/plans/386-incident-table-layout.md`, `docs/notes/386-incident-table-layout.md`

## 다른 코드와 맞물리는 곳

- 전역 `.table-scroll` 규칙과 `list-view.tsx`는 바꾸지 않는다. `.incident-page`는 `incident/page.tsx`에서만 쓴다.
- 화면용 응답, `contracts/`, DB, L1·L2·L3 코드는 바꾸지 않는다. 새 의존성·환경변수·도구는 없다(결정 목록에 올릴 것 없음).
- 계획 384의 완료 기준 중 열 너비·줄바꿈·sticky를 이 계획이 마무리한다. 계획·기록 384는 고치지 않는다.

## 범위 밖

- 1024px 미만에서 사이드바가 접히는 구간과 모바일 레이아웃.
- `statusText` 문구 변경.
- 개요·분석 이력·그래프 탭의 레이아웃, 다른 화면의 표.
- 스크린샷 비교 도구 도입(D-075).

## 완료 기준

- [ ] 1024/1280/1440/1920px에서 Ticket 탭 `시각`·`근거 수`·`분류 탐색`·상세 링크가 겹치지 않고 각각 한 줄이다(1024px에서 가로 스크롤 없음)
- [ ] Ticket 탭 첫 열의 제목·ID가 잘리지 않고 시작부터 보인다(1080px에서 재현해 확인, 재현 안 되면 기록)
- [ ] 엔티티 탭 `최초 관측`과 `작업`이 겹치지 않고 `값` 열이 `종류` 열보다 넓다
- [ ] "복사", 시각, 개수, 버튼·링크 라벨이 줄바꿈되지 않는다. 긴 값·긴 URL·긴 해시는 말줄임이고 전체가 `title`에 있으며 텍스트로만 표시된다
- [ ] 스크롤해도 탭 줄이 상단에 고정된다
- [ ] 1024px 미만에서는 표가 가로 스크롤이고 겹치지 않는다(1024px 아래 확인은 스크롤만 본다)
- [ ] 목록 화면 표(`list-view.tsx`)가 바뀌지 않았다
- [ ] `contracts/`와 화면용 응답이 바뀌지 않았다
- [ ] `pnpm contracts:check`, `pnpm lint`, `pnpm test`, `pnpm build`와 `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`가 통과한다
- [ ] 화면 확인 결과(폭별, 최종 열 폭 값)가 기록에 있고 전·후 스크린샷은 사람이 PR에 붙인다(D-075)

## 토론으로 정한 것

이슈 본문과 달라진 점:

- **지원 최소 폭 1024px를 추가했다.** 이슈는 1280/1440/1920px만 확인했다. 1024/1280/1440/1920px에서 확인하고 1024px에서는 가로 스크롤이 없어야 한다. 1024px 아래는 가로 스크롤이다. 사용자가 정함.
- **폭이 모자랄 때는 가로 스크롤이다(질문 2 A).** 이슈의 "아래 줄로 내림" 대안은 쓰지 않는다. 표 구조와 정렬 헤더를 건드리지 않기 위해서다.
- **시각 열이 110px보다 넓으면 표기를 줄이지 않고 표 `min-width`를 올려 스크롤로 둔다.** 사용자가 정함.
- **sticky는 `.incident-page`를 flex로 바꿔 고친다(질문 3 A).** 계획 384가 의심한 overflow 조상은 CSS에서 찾지 못했고, grid 안 sticky가 원인이라고 본다. 브라우저에서 다르면 멈추고 말한다.
- **`분류 탐색` 문구는 그대로 두고 한 줄 + 말줄임 + `title`이다(질문 4 A).** 상태 문구 테스트를 건드리지 않는다.
- **화면 확인은 AI가 개발 서버와 브라우저 도구로 하고 사람이 스크린샷을 붙인다(질문 1 A).** 백엔드를 띄울 수 없으면 사람이 확인한다.
- **첫 열 잘림은 1080px, admin 계정에서 본 증상이다(질문 5 A).** 열 폭 수정 뒤 재현한다.
- **전역 `.table-scroll` 규칙은 고치지 않는다.** 목록 화면이 같은 규칙을 써서 `.incident-table-card` 아래에서만 덮어쓴다.
- 결정 목록에 올린 안건은 없다.

## 바뀐 점
