---
issue: 363
date: 2026-11-20
owner: Pandyo
plan: 363-ui-foundation.md
supersedes: []
---

# UI 기반: App.tsx를 기능 단위 파일로 나누고 심각도 표시를 한 곳으로 모았다

## 한 일

- `frontend/src/App.tsx`(1,140줄)를 `layout.tsx`, `dashboard.tsx`, `list-view.tsx`, `detail-panel.tsx`, `badges.tsx`, `constants.ts`, `severity.ts`로 나눴다. `App.tsx`에는 로그인 상태 분기(`App`)만 남았다. 코드는 옮기기만 했고, 옮긴 직후 기존 테스트 86개가 그대로 통과했다.
- 심각도 라벨은 `severity.ts`의 `severityLabel` 한 곳에서 나온다(D-074). 1~6은 `N Level`, 0과 0~6 밖의 값은 "미상", `null`은 "—"이다. 색은 3단계 규칙 그대로다. 화면에 보이는 문구는 이 이슈 전과 같다.
- 화면 검사 방법을 `AGENTS.md` 완료 기준에 적었다(D-075): 프런트 4개 명령과 디자인이 바뀐 PR의 스크린샷.
- `design/0-Ticket.pen`과 `design/images/logo-mark.png`를 커밋했다.

## 계획과 달라진 점

- **심각도 한국어 라벨은 했다가 되돌렸다.** 같은 날 라벨을 정보·낮음·보통·높음·심각·치명으로 바꾸고 "위험도" 제목을 "심각도"로 바꿨다가(`d291393`, 테스트 `4e3c8ec`), 사람이 `N Level`과 "위험도"를 유지하기로 정해 `4a4b8ba`에서 되돌렸다. 계획 파일 "바뀐 점"과 `docs/decisions.md`의 D-074·기록에 같은 내용을 적었다. 함수 한 곳으로 모으는 구조와 새 테스트(`severity.test.ts`)는 남겼고 기대값만 `N Level`로 맞췄다. 열린 `.pen`의 텍스트도 원래 문구로 되돌렸고 저장은 사람이 한다.
- **커밋 순서.** 계획은 test → refactor였는데 refactor → test로 했다. 파일 이동을 기존 테스트 그대로 통과시켜 동작 불변을 확인하려면 새 테스트가 뒤에 와야 한다.
- **`Severity` 컴포넌트 위치.** JSX는 `.ts`에 쓸 수 없어서 라벨 함수 `severityLabel`은 `severity.ts`, `Severity`와 `Status` 배지는 `badges.tsx`에 뒀다.
- **`constants.ts`.** `resourcePermission`, `titles`, `statusNames`, `states`를 담았다. `layout.tsx`가 `list-view.tsx`·`detail-panel.tsx`를 부르는데 둘 다 `titles`·`resourcePermission`을 `layout.tsx`에서 가져오면 순환이 되고, `statusNames`는 배지·대시보드·목록이 같이 쓴다. 계획이 허용한 범위다. `colors`·`chartColors`는 대시보드만 써서 `dashboard.tsx`에 뒀다.
- **`test-utils.tsx`의 `dashboard()`.** Top10을 채울 수 있게 두 번째 인자 `topIncidents`(기본 `[]`)를 더했다. 기존 호출은 그대로 동작한다.
- **사이드바 글자 굵기.** 디자인 Sidebar를 읽어 현재 CSS와 비교했더니 `.avatar`·`.role-badge`·`.menu-group`만 `font-weight: 650`이고 디자인은 600이었다. 번들한 Inter는 400·500·600·800뿐이라 650은 브라우저가 800(더 굵은 쪽)을 고를 것으로 보여(△ 화면으로는 확인하지 못했다) 600으로 고쳤다(`5f3856e`).

## 다음 사람이 알아야 할 것

- **이슈 본문과 확정 댓글은 옛 계획이다.** 둘 다 한국어 라벨과 "위험도"→"심각도" 변경을 적고 있다. 실제 구현과 D-074는 `N Level` 유지다.
- **Sidebar·Footer 비교 결과.** 디자인 컴포넌트(`Sidebar`, `Workspace Footer`)의 크기·패딩·간격·글꼴·색을 속성으로 읽어 CSS와 비교했다. 위 글자 굵기 3곳 말고는 모두 같았다. 비교하지 않은 것: Ticket 메뉴 아이콘 크기(CSS에 `a:nth-child(3) svg { 26.5px }`가 있고 디자인은 20×20이다. SVG 안쪽 여백 때문일 수 있어 손대지 않았다), 호버·활성 상태(디자인 컴포넌트에 없음), 관리자가 아닌 역할 배지 색(디자인에 없음). 사람이 화면으로 확인한다.
- **디자인 색 토큰 비교 결과.** 디자인의 `app-*` 색 변수 20개가 `style.css`의 `:root` 값과 모두 같다. 단 `app-heading`(#162841)은 `:root` 변수가 아니라 CSS 여러 곳에 직접 적혀 있어 그대로 뒀다. 디자인에는 `app-*` 말고 `bg`·`surface`·`ink`·`ink-2`·`muted`·`line`·`good`(7개)도 있는데 쓰이는지 확인하지 못했고 반영하지 않았다. 폰트 변수 `font-ui`(Noto Sans KR)는 D-046대로 번들하지 않았다. 간격 토큰은 디자인에 없다.
- **`font-weight: 650`은 `style.css`에 8곳 더 있다**(1674, 1703, 1773, 1803, 1808, 1840, 1852, 1873줄 부근). 사이드바가 아닌 화면이라 이번에 안 고쳤다. 화면별 이슈에서 디자인 값과 비교한다.
- **`.pen` 파일.** git이 `design/0-Ticket.pen`을 텍스트로 세어 35,290줄 추가로 보인다. 그래도 MCP 도구 설명대로 암호화된 파일이라 내용은 열어 보지 않았고 `git add`만 했다. `design/images/`에는 `logo-mark.png` 하나뿐이다. 이미지 참조 경로(`images/logo-mark.png`)가 앱에서 정상으로 열리는지는 사람이 확인한다(계획 완료 기준). 라벨을 되돌린 뒤 `df5e99b`에서 파일을 교체했다(크기 1,508,056 → 1,508,068바이트, 31줄 변경 = 라벨 23개와 제목 8개). 처음 저장한 파일은 되돌리기가 빠진 채 이전과 같은 해시로 나와서, pencil `save` 도구로 다시 저장한 파일을 썼다.
- **Top10에 confirmed·dismissed가 없다.** 백엔드 `top_incidents`는 `analyzing/awaiting_review/human_handling/held`만 뽑는데 디자인 Top10에는 승인/확인됨과 위협 아님도 있다. 이번 범위 밖이다(Dashboard 이슈).
- **`origin/main`이 앞서 있다.** 이 브랜치는 `53e0ea1` 기준이고 `origin/main`은 `7f5e332`(#364, L2 후보 요약)다. 겹치는 파일은 없고 시험 병합(`git merge-tree`)도 충돌이 없었다. 리베이스는 하지 않았다.
- **프런트 린트 경고 1건**(`flow-chart.tsx:17`, `react-refresh/only-export-components`)은 이전부터 있던 것이다.

## 확인 방법

- `frontend/`: `pnpm contracts:check`(35개 일치), `pnpm lint`(오류 0, 기존 경고 1), `pnpm test`(90개 통과: 기존 86 + 새 4), `pnpm build` 통과.
- 루트: `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`(2,652 통과, 660 deselected) 통과. `db`·`qdrant` 마커 테스트는 돌리지 않았다(이번 변경은 백엔드를 건드리지 않았다).
- 새 테스트(`frontend/src/severity.test.ts`, 샘플 `tests/fixtures/frontend/severity_labels.json`): 0~6 라벨(`N Level`), `null`·범위 밖 값, Ticket 목록(배지 7종, 칩 순서 6→0, 표 머리 "위험도"), 대시보드(막대 라벨 순서, 카드 제목, Top10 열 제목과 배지).
- 손으로 확인하지 않은 것(사람이 한다): 화면 모양(Sidebar·Footer, 심각도 배지), `.pen` 이미지 참조, PR 스크린샷.
