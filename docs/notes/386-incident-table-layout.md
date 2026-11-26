---
issue: 386
date: 2026-11-26
owner: Pandyo
plan: 386-incident-table-layout.md
supersedes: []
---

# Incident 상세 Ticket·엔티티 탭이 열 폭을 명시해 겹침과 줄바꿈 없이 보인다

## 한 일

- 두 표(`.incident-table`)가 `<colgroup>`으로 열 폭을 명시한다. Ticket 표는 제목 열, 엔티티 표는 값 열만 남는 폭을 받고 나머지는 고정 폭(px)이다. 폭 목록은 `ticket-table.tsx`·`entity-table.tsx`의 `WIDTHS`다.
- 셀은 모두 한 줄(`nowrap`) + 말줄임이다. 제목·분류 탐색 문구·긴 값은 `title`에 전체 텍스트가 있다. `.clip`의 `max-width: 420px` 상한은 이 두 표 안에서만 풀었다.
- 폭이 모자라면 `.table-scroll`의 가로 스크롤이다(표 `min-width`: Ticket 856px, 엔티티 680px).
- 전역 `.table-scroll` 규칙(`th:first-child 50%` 등)과 목록 화면(`list-view.tsx`)은 바꾸지 않았다. 두 표에서만 `.table-scroll .incident-table th {width: auto}`로 덮는다.

## 계획과 달라진 점

- **sticky 가설이 틀렸고 `.incident-page`는 grid 그대로다.** 계획은 grid 안의 sticky가 붙지 못한다고 봤다. 그러나 `.incident-page`가 `display: grid`인 채로(계산값 확인) Chrome 헤드리스 1280×900에서 500px 스크롤했을 때도 탭 줄은 `top: 0`에 붙었다. flex로 바꿔도 결과가 같아 효과 없는 변경이라 되돌렸다. 이슈의 "스크롤해도 탭 줄이 붙지 않는다"는 이 환경에서 재현하지 못했다(아래).
- **Ticket 표는 1024px에서 가로 스크롤이 생긴다.** `시각` 열이 110px에 들어가지 않고(`시각 ▼` 헤더까지 약 138px 필요) 사람이 "시각 표기는 줄이지 말고 `min-width`를 올려 스크롤로 두라"고 정했다. 그래서 1024px에서 Ticket 표는 약 150px 가로 스크롤이고 겹침·잘림은 없다. 엔티티 표는 1024px에서 스크롤이 없다(값 열 약 180px).
- 최종 폭(px): Ticket 판정 124, 위험도 84, 시각 138, 근거 수 56, 분류 탐색 130, 상세 110. 엔티티 종류 80, role 60, 연결 144, 최초 관측 138, 작업 100. 계획의 시작 값보다 판정(`undetermined`)·위험도·시각이 넓다.
- `<col>` 폭을 정하는 헬퍼 `Cols`를 `kit.tsx`에 더했다.

## 다음 사람이 알아야 할 것

- **sticky와 첫 열 앞글자 잘림은 재현하지 못했다.** 확인한 곳은 Chrome 헤드리스(1024·1280·1440·1920px, 높이 900, 가짜 로그인 응답 + `?sample=graph`)다. 사용자가 본 1080px는 열 폭과 잘린 셀만 쟀고(잘린 셀 없음), 첫 열 시작 위치(`firstCellLeft` 0)는 1280px 이상에서 확인했다. 1080px에서 앞글자가 잘리던 모습은 따로 확인하지 못했다. 배포 화면에서 다시 보이면 브라우저 폭, 스크롤 컨테이너(`document` 말고 다른 곳이 스크롤되는지), 데이터 건수를 먼저 확인한다. 이 기록에서는 원인을 모른다.
- 지난 확인은 `시각` 열 값 `2026. 11. 3. 오후 1:11:40`(`toLocaleString("ko-KR")`) 기준이다. 브라우저 로케일이나 시간대가 다르면 문구 폭이 달라질 수 있다.
- `incident-clip-cell` 클래스는 테스트가 표지로 쓰고, 스타일은 `.incident-table td` 공통 규칙이 준다.
- 판정 열 폭 124는 `undetermined` 칩 기준이다. 판정 문구가 더 길어지면 이 폭과 표 `min-width`를 같이 올린다.
- `pnpm exec vitest run` 한 번이 2건 실패했는데 이름을 확인하지 못했고 같은 명령 3회 재실행은 201건 모두 통과했다(워커 2개, `--testTimeout=30000`). 같은 일이 다시 보이면 어느 테스트인지 먼저 기록한다.
- 헤드리스 확인은 Python 가짜 서버(로그인 응답만)와 `pnpm dev`로 했고, 개발 DB와 `dev_seed`는 건드리지 않았다. 확인 스크립트는 저장소에 넣지 않았다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과. `uv run pytest`: 2696건 통과(Python은 바꾸지 않음).
- `pnpm contracts:check`(36개 일치), `pnpm lint`(경고 1건은 기존 `flow-chart.tsx`), `pnpm build`: 통과. `pnpm exec vitest run --maxWorkers=2 --testTimeout=30000`: 201건 통과.
- 새 테스트: `incident-page.test.tsx`의 "the Ticket table fixes a width for every column…"과 "the entity table fixes a width…". 열 폭 요소, `title`, 말줄임 표지를 본다. 겹침·줄 수는 jsdom이 못 보고 브라우저 측정으로만 확인했다.
- 브라우저 측정(Chrome 헤드리스, 두 탭, 모든 행): 1024/1280/1440/1920px 모두 잘린 셀 없음(`분류 탐색`의 말줄임은 의도). Ticket 표는 1024px에서만 가로 스크롤(약 154px), 1280px 이상은 스크롤 없음. 엔티티 표는 모든 폭에서 스크롤 없음. 값·제목 열은 1024px에서 각각 약 180·214px이고 1920px에서 약 1076·956px이다. 행 높이는 Ticket 74px·엔티티 56px로 줄바꿈 없음.
- 사람이 PR에 붙일 것: 전·후 스크린샷(D-075). 이 확인은 사람의 실제 브라우저를 대신하지 못한다.
