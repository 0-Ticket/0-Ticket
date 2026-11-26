---
issue: 380
date: 2026-11-26
owner: Pandyo
plan: 380-incident-graph-interactive.md
supersedes: []
---

# Incident 관계 그래프가 확대·이동·끌기·필터·검색이 되고 Entity 보기가 동작한다

## 한 일

- "관계 그래프" 탭의 그래프를 다시 만들었다. 노드 위치는 d3-force(D-079)로 계산하고 노드는 HTML, 선은 SVG로 그린다. 배경을 끌면 이동하고, 노드를 끌면 옮겨지며, 확대·축소·화면에 맞추기 버튼과 Ctrl(⌘)+휠 확대가 있다. 종류 필터(엔티티 종류 칩)와 검색이 있고, 검색에 걸리지 않는 노드는 흐려진다.
- Ticket 보기: Incident → Ticket 구성이고 Alert는 Ticket에 접혀 있다. Ticket 노드의 `+n` 버튼을 누르면 Alert 노드가 펼쳐지고 엔티티가 Alert로 옮겨 붙는다. 접힌 Ticket에는 그 Ticket의 엔티티가 직접 붙는다.
- Entity 보기("연결된 엔티티", 주소 `?tab=graph&view=entity`): Alert·Ticket의 엔티티 노드를 같은 Alert에 함께 나온 것끼리 잇고, 같은 Alert 안의 `src` → `dst` role만 화살표로 그린다. 선 라벨은 없고 범례는 "화살표는 Alert에 기록된 출발→목적지 방향이며 공격 순서가 아님"이다. 연결 수 상위 60개만 보이며 종류 필터를 켜면 그 종류만 다시 상위 60개, 검색은 60 밖의 일치 노드를 더한다.
- 노드를 고르면(클릭·Enter·Space) 그 노드와 직접 이웃만 남고 선도 그 노드에 닿는 것만 보인다. 옆 패널에 판정 칩·연결 수·자산 중요도(있을 때만)가 나오고 "선택 해제"(또는 Esc)로 돌아온다. 노드 위치는 페이지 메모리에 있어 탭을 옮겼다 와도 유지되고 새로고침하면 초기화된다.
- 저장된 탐색 경로·탐색 상태는 그래프에서 빠지고 접힌 "분류 근거(고급)"(`incident/basis.tsx`)에만 남았다. 화면용 응답, `contracts/`, DB는 바뀌지 않았다.

## 계획과 달라진 점

- 계획 파일 "바뀐 점"에 적을 것은 없다. 작은 선택만 아래에 둔다.
- Ticket 보기의 엔티티에는 상한이 없다. 이슈가 상한 60을 Entity 보기에만 두었기 때문이다. Alert 14개짜리 샘플에서는 엔티티 노드가 100개 넘게 보인다. 종류 필터로 줄일 수 있다.
- 종류 필터 칩은 두 보기에서 모두 엔티티 종류다. Ticket 보기에서는 엔티티만 숨기고 Incident·Ticket·Alert는 그대로 둔다. 보기를 바꾸면 필터가 초기화된다.
- 휠 확대는 Ctrl(⌘)을 누를 때만 된다. 그냥 휠은 페이지 스크롤이다(계획의 "휠이 페이지 스크롤을 막지 않는다"). React의 `onWheel`은 passive라 네이티브 리스너로 붙였다.
- 화면에 맞추기는 뷰포트를 측정하지 않고 900×560으로 가정한다(`graph-layout.ts`의 `fit`, 코드에 `shortcut:` 주석).
- 배치는 렌더 중에 동기로 300틱을 돌린다(`graph-layout.ts`, `shortcut:` 주석). 한 번 놓인 노드는 끌거나 필터·검색·선택·펼침이 바뀌기 전에 위치를 기억해(핀) 움직이지 않는다. 새로 나타나는 노드만 기존 노드를 고정한 채 배치된다. 노드가 수백 개를 넘으면 워커로 옮긴다.
- 선 밀집 대비안(계획 "선 밀집")은 `incident-graph.tsx`의 `PLAIN_LINES_BY_DEFAULT`(지금 `true`) 한 곳이다. `false`로 바꾸면 기본 화면에는 `src`→`dst` 화살표만 그리고 나머지 선은 노드를 골랐을 때만 보이며 범례에 그 안내가 나온다. 배치·연결 수 순위는 그대로다.
- 그래프 컴포넌트의 props가 `incident`·`ticketGraphs`·`titles`·`decisions`·`criticality`에서 `detail`·`view`·`onView`·`memory`·`onMemory`로 바뀌었다. 부르는 곳은 `incident/page.tsx` 하나다. 위치 기억은 `incident/graph-memory.ts`의 `useGraphMemory(id)`가 페이지에 둔다.
- 순수 함수(`graph-model.ts`의 `buildGraph`·`neighbourhood`·`facts`, `graph-layout.ts`)와 그리기(`incident-graph.tsx`)를 나눴다. `buildGraph`의 `limit`(기본 60)은 테스트에서 전체 선을 세려는 것이다.
- 엔티티 키는 `JSON.stringify(["entity", type, value])`이고 일반 객체의 키로 쓰지 않는다. 값이 `__proto__`인 엔티티 테스트가 있다.
- 기존 `incident-graph.test.tsx`는 새 동작으로 다시 썼다. 분류 근거 테스트 3건은 `ClassificationBasis`로 옮겼고, 이전 그래프 구조(열 배치·소속선·경로선·선 라벨·호버 흐림)를 확인하던 테스트는 새 구조에 맞는 테스트로 바꿨다. `App.test.tsx`와 `incident-page.test.tsx`의 그래프 관련 단언도 새 구조에 맞췄다(Entity 버튼은 이제 활성이고 "준비 중"이 없다). 지우거나 건너뛴 테스트는 없다.

## 다음 사람이 알아야 할 것

- **브라우저로 확인하지 못했다.** 테스트는 jsdom이라 좌표·간격·줌 감각·선 밀집을 보지 못한다. 노드 크기(168×44), 선 길이(150), 충돌 반경(96)은 눈으로 맞춘 값이 아니다. 엔티티 100개 이상 샘플 화면의 스크린샷으로 사람이 선 밀집을 판단한다(계획 "선 밀집").
- **디자인과 다른 곳 확인.** `design/0-Ticket.pen`의 새 프레임 7개를 pen MCP로 다시 읽었다. "관계 그래프" 프레임은 Ticket 보기·Entity 보기 전환 버튼, 필터 칩, 검색, 왼쪽 확대 컨트롤, 오른쪽 검사 패널을 보여 준다. **Entity 보기가 그려진 프레임은 없다.** Entity 보기 모양은 같은 레이아웃에서 구현했다.
- d3-force는 `3.0.1`, `@types/d3-force`는 `3.0.10`으로 `pnpm add --save-exact`했다(D-079). 함께 들어온 패키지는 `pnpm-lock.yaml`로 고정된다.
- 뷰포트에 `touch-action: none`을 줬다. 터치 화면에서 그래프 위에서는 페이지가 스크롤되지 않는다.
- 노드 이동은 포인터만 지원한다. 키보드로는 노드 고르기·펼치기·선택 해제·확대 버튼까지다. 노드가 많으면 Tab 순서가 길다.
- 엔티티가 한 Alert에 많으면 완전연결이라 선이 많다(9개 → 36쌍). 상위 60 노드에서는 최대 약 1,770개다.
- Alert 노드는 시각·엔티티 수로만 표시한다(제목·심각도 없음, 계획 질문 2). Alert 상세로 가는 링크는 만들지 않았다.
- 이 그래프는 `ticket_graphs`의 Hunt 노드와 저장 경로 선을 그리지 않는다. Hunt 출신 Ticket은 Ticket 노드로만 보인다.
- 로컬 `origin/main`이 오래돼 있어서 브랜치를 만들기 전에 `git fetch`를 했다(읽기 전용).
- `pnpm lint`의 경고 1건(`flow-chart.tsx`)은 이 이슈 전부터 있다. `vitest run`을 기본 병렬로 돌리면 `ticket-detail.test.tsx`가 부하로 시간 초과가 한 번 났고 단독 실행과 `--maxWorkers=2 --testTimeout=30000`에서는 통과했다(기록 379와 같은 방식).

## 디자인과 다른 곳 (PR에 적을 것)

- Entity 보기는 프레임이 없어 Ticket 보기와 같은 레이아웃으로 만들었다.
- 디자인의 역할 설명("IP · 공격 출발지" 같은 노드 부제)과 위험 경로·선 라벨은 만들지 않았다. 화살표 범례는 "Alert에 기록된 출발→목적지 방향이며 공격 순서가 아님"이다(계획 379의 범위 밖 결정과 같은 이유).
- Ticket 보기는 Incident → Ticket → (펼치면) Alert → 엔티티 구조이고 디자인의 Ticket/Alert/엔티티 계층 표현은 노드 모양(카드형)으로 단순화했다. Alert 노드는 제목 대신 시각·엔티티 수다.
- 노드를 고르면 이웃만 남기고 나머지를 숨긴다(디자인은 흐리게 두는 쪽에 가깝다).
- 휠 확대는 Ctrl(⌘)과 함께 쓴다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과.
- `uv run pytest`: 2696건 통과(이번 변경은 Python을 바꾸지 않았다).
- `pnpm contracts:check`(36개 일치), `pnpm lint`(경고 1건은 기존), `pnpm build`: 통과. `pnpm exec vitest run --maxWorkers=2 --testTimeout=30000`: 179건 통과.
- 주요 테스트: `incident/graph-model.test.ts`(12건: 상위 60·동률 순서·화살표·선 중복 없음·Hunt 엔티티·종류 필터·검색 추가·`__proto__`·Alert 접기·이웃만), `incident/graph-layout.test.ts`(4건), `incident-graph.test.tsx`(보기 전환·접기·범례·선 라벨 없음·필터·검색·선택·키보드·확대·이동·끌기와 위치 기억·텍스트·중요도·판정 칩·분류 근거), `incident-page.test.tsx`의 `view` 주소와 탭 이동 뒤 위치 유지. 샘플은 `tests/fixtures/frontend/incident_graph_entities.json`(Alert 14개, 엔티티 104개, 공유 `src` IP 3개, Alert 2개짜리 Ticket 1개, Alert 없는 Ticket 1개, 값이 `__proto__`인 엔티티 1개)이다.
- 손으로 확인한 것은 아직 없다. 전·후 스크린샷은 사람이 붙인다(D-075).
