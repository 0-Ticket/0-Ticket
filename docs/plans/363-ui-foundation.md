---
issue: 363
date: 2026-11-20
owner: Pandyo
supersedes: []
---

# UI 기반: App.tsx 화면별 분리, 공통 레이아웃·디자인 토큰, 심각도 라벨 통일

## 목표

pen.dev 디자인(22개 화면)을 기존 프런트 위에 얹기 전에 필요한 기반을 정리한다.

- `App.tsx`를 기능 단위 파일로 나눈다(동작은 그대로).
- 심각도 표시를 한 함수로 모아 0~6을 미상·정보·낮음·보통·높음·심각·치명으로 보인다.
- 디자인 원본(`design/`)과 화면 검사 방법을 정한다.

## 방법

작업은 `origin/main`(`53e0ea1`) 기준 별도 worktree `../0-Ticket-ui`의 브랜치 `refactor/363-ui-foundation`에서 한다.

1. **테스트 먼저(원칙 3).** `frontend/src/severity.test.ts`를 새로 쓴다. 0~6이 각각 미상·정보·낮음·보통·높음·심각·치명으로 나오고, `null`은 "—", 0~6 밖의 값은 오류 없이 폴백("미상")으로 나온다. 같은 값이 Ticket 목록 칩, 대시보드 막대, Top10, 목록·상세 배지에서 새 라벨로 보이는 기존 테스트도 고친다.
2. **심각도 라벨 함수.** `frontend/src/severity.ts`에 `severityLabel(value: number | null): string`과 `Severity` 컴포넌트를 둔다(지금 `App.tsx:128-143`의 `severityNames`·`Severity`를 옮긴다). 색은 지금 3단계 규칙(0 회색, 1~2 파랑, 3~4 호박, 5~6 빨강)을 그대로 쓴다. 쓰는 곳은 `App.tsx`의 `Bars risk`(163), Top10 `SmallList`(303), `RiskBars`(317), `DetailBody`(486), Ticket 위험도 칩(769), 목록 배지(820)이다.
3. **"위험도"·"Risk Level" 헤딩을 "심각도"로 바꾼다.** 디자인이 이미 이렇게 바뀌었다.
   - 대시보드 카드: `Tickets by Risk Level`(365) → `심각도별 Ticket`, `Incident Risk Top 10`(414) → `Incident 심각도 Top 10`, Top10 열 `위험도`(419) → `심각도`
   - 개요 카드: `위험도별 Ticket`(439) → `심각도별 Ticket`
   - Ticket 목록: 칩 라벨 `위험도`(764), 접근 이름 `위험도 필터`(765), 표 머리 `위험도`(802) → 심각도
   - aria: `Ticket 위험도 분포`(314) → `Ticket 심각도 분포`
   - 내부 이름(`RiskBars`, `risk` 프로퍼티, `.risk-*` 클래스)은 그대로 둔다. 화면에 안 보이고 바꿔도 얻는 것이 없다.
   - 접근 이름으로 조회하는 테스트(`App.test.tsx:155·724`, `auth.test.tsx:427·429`)도 같이 고친다.
4. **`App.tsx`를 기능 단위로 옮긴다.** 파일만 옮기고 코드는 바꾸지 않는다(라벨·헤딩 변경분 제외). 파일은 `frontend/src/` 아래 기존 방식(kebab-case)을 따른다.
   - `layout.tsx`: `Workspace`와 사이드바·푸터, 메뉴 상수
   - `dashboard.tsx`: `Bars`, `Normalization`, `SmallList`, `RiskBars`, `DashboardView`, `Overview`
   - `list-view.tsx`: `ListView`와 페이지 계산(`PAGE_SIZE`, `totalCount`)
   - `detail-panel.tsx`: `DetailBody`, `DetailPanel`, `internalLink`
   - `severity.ts`: 위의 라벨 함수와 `Severity`
   - `App.tsx`: 로그인 상태에 따른 분기만 남긴다(`App` 컴포넌트).
   - `ListView`·`DetailBody`의 리소스 분기는 그대로 둔다. 테스트 파일은 나누지 않는다.
   - 분리 중 순환 import가 생기면, 여러 파일이 같이 쓰는 상수(`colors`, `chartColors`, `statusNames`, `titles`, `resourcePermission` 등)를 `frontend/src/constants.ts` 같은 별도 파일로 빼도 된다. 값과 동작은 바꾸지 않는다.
5. **Sidebar·Footer.** 디자인의 `Sidebar`(224px)·`Workspace Footer`와 현재 `layout.tsx`의 사이드바·푸터를 비교해 차이만 고친다. 차이가 없으면 "변경 없음"으로 `docs/notes/`에 적는다.
6. **디자인 토큰.** 디자인의 색 변수(`app-*`)와 `style.css` `:root`를 비교해 달라진 값만 반영한다. 이미 같은 값은 두고, 비교 결과를 기록에 적는다. 폰트는 D-046을 유지한다(Noto Sans KR은 번들하지 않는다). 간격 토큰은 디자인에 없어서 다루지 않는다.
7. **디자인 원본.** `design/0-Ticket.pen`과 `design/images/`를 커밋한다(약 1.5MB). 파일을 앱에서 저장해 그 경로에 두는 것은 사람이 한다. AI는 `.pen` 내용을 읽지 않고, 파일이 생기면 `git add`만 한다. 이후 `.pen`은 마일스톤에만 커밋한다. 디자인 변경이 있는 PR에는 스크린샷을 붙인다(`.pen`은 암호화돼 git diff로 못 본다). 복사한 `.pen`이 `images/`를 올바른 경로로 참조하는지는 사람이 앱에서 열어 확인하고, 문제가 있으면 알려준다.
8. **화면 검사 방법.** 새 도구 없이, 화면 작업이 끝났다는 기준을 아래 둘로 확정한다.
   - 프런트 4개 명령: `pnpm contracts:check`, `pnpm lint`, `pnpm test`, `pnpm build`(CI `frontend` job과 같다)
   - 디자인이 바뀐 PR에 사람이 전·후 스크린샷을 붙인다.
   - `AGENTS.md` 완료 기준 2번의 "(화면 명령은 첫 화면 이슈에서 정한다)"를 이 내용으로 고친다. 스크린샷 비교 도구(Playwright 등)는 별도 안건으로 미룬다고 적는다.
9. **결정 기록.** `docs/decisions.md`에 D-074(심각도 UI 라벨)와 D-075(화면 검사 방법)를 추가하고, "기록"에 한 줄을 남긴다. 계획 확정 때 함께 적었다.

### 커밋

- `docs(plans): add plan for ui foundation (#363)`
- `test(frontend): add severity label cases (#363)`
- `refactor(frontend): split app into feature files (#363)`
- `feat(frontend): unify severity labels and headings (#363)`
- `docs(harness): record screen check method (#363)`
- `chore(harness): add pen design files (#363)`

## 바꿀 곳

- `frontend/src/App.tsx`: `layout.tsx`, `dashboard.tsx`, `list-view.tsx`, `detail-panel.tsx`, `severity.ts`(필요하면 `constants.ts`)로 나눈다.
- `frontend/src/severity.test.ts`: 새로 쓴다.
- `frontend/src/App.test.tsx`, `frontend/src/auth.test.tsx`: 라벨·헤딩이 바뀐 줄만 고친다.
- `frontend/src/style.css`: 디자인 토큰 차이가 있으면 `:root` 값만 고친다. 레이아웃 CSS는 이번에 바꾸지 않는다.
- `design/0-Ticket.pen`, `design/images/`: 추가한다.
- `docs/decisions.md`: D-074, D-075와 기록(확정 때 적음).
- `AGENTS.md`: 완료 기준 2번의 화면 검사 문구.
- `docs/plans/363-ui-foundation.md`, `docs/notes/363-ui-foundation.md`.

## 다른 코드와 맞물리는 곳

- 백엔드 API, `contracts/`, 생성 타입(`frontend/src/api/generated/`)은 바꾸지 않는다.
- `severityNames`와 `Severity`는 `App.tsx` 안에서만 쓴다(내보내지 않음). 옮긴 뒤 다른 파일이 가져다 쓰게 되는 것은 의도한 변경이다.
- 심각도 라벨은 "N Level"에서 새 라벨로 바뀌어 화면 문구가 달라진다. 이 문구를 직접 조회하는 테스트는 위에서 같이 고친다.
- `AGENTS.md`는 모든 AI 도구가 읽는 지침이라 바꾸면 팀에 알려야 한다.

## 범위 밖

- 화면별 디자인 적용(Ticket·Incident·Dashboard·Case 등)은 이후 이슈에서 한다.
- Event 심각도("—")와 Ticket 목록의 위험도 열·필터 정리(Ticket 화면 이슈), Ticket 상세 원본 Alert 행의 색
- Noto Sans KR 번들, 간격 토큰
- 스크린샷 비교 도구 도입, 테스트 파일 분할, `ListView`·`DetailBody`의 리소스별 분리
- 백엔드, API 계약

## 완료 기준

- [ ] `App.tsx`가 위 파일들로 나뉘고 분리 전과 동작이 같다(기존 프런트 테스트 통과, 라벨·헤딩 변경분만 수정)
- [ ] 심각도 라벨 함수가 `severity.ts` 한 곳에 있고 모든 표시가 이를 쓴다. 0~6이 미상·정보·낮음·보통·높음·심각·치명으로 보인다. `null`은 "—", 범위 밖은 폴백이다
- [ ] 0~6 라벨이 모두 보이는 테스트(`severity.test.ts`)가 있다
- [ ] "위험도"·"Risk Level" 화면 문구가 "심각도"로 바뀌고, 접근 이름으로 조회하는 테스트가 통과한다
- [ ] Sidebar·Footer는 디자인과 차이만 고쳤고, 확인은 사람이 한다. 차이가 없으면 "변경 없음"이 기록에 있다
- [ ] 디자인 토큰 차이가 `style.css`에 반영됐거나 차이 없음이 기록에 있다. 폰트는 D-046 그대로다
- [ ] `docs/decisions.md`에 D-074, D-075가 있고 D-074 메모에 "계획 274의 'N Level' 규칙을 대체"가 적혀 있다
- [ ] `AGENTS.md`에 화면 검사 방법이 적혀 있다
- [ ] `design/0-Ticket.pen`과 `design/images/`가 있고, 사람이 앱에서 열어 이미지 참조가 정상임을 확인했다
- [ ] `pnpm contracts:check`, `pnpm lint`, `pnpm test`, `pnpm build` 통과, `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과
- [ ] PR에 화면 전·후 스크린샷이 있다(사람이 첨부)

## 토론으로 정한 것

- **`.pen` 커밋.** 이슈대로 `design/`에 커밋한다. 계획 274의 "`.pen`은 레포에 커밋하지 않는다"를 이 계획이 대체한다. 이유는 1인 보관의 위험을 없애기 위해서이다. `.pen`은 diff를 못 보니 디자인이 바뀐 PR에는 스크린샷을 붙인다. 파일은 마일스톤에만 커밋한다. 파일 배치(`design/0-Ticket.pen`, `design/images/`)는 가정대로 가고, 이미지 참조 경로는 사람이 앱에서 열어 확인한다.
- **분리 범위.** 기능 단위 파일 이동만 한다. 리소스 분기는 각 화면 이슈가 가져간다. 이유는 동작 불변을 확인하기 쉽기 때문이다. 테스트는 나누지 않는다. 순환 import가 생기면 공통 상수를 `constants.ts` 같은 별도 파일로 빼는 것을 허용한다.
- **토큰과 폰트.** 이미 같은 색은 두고 차이만 반영한다. D-046을 유지한다. 간격 토큰은 디자인에 없어서 뺀다.
- **화면 검사.** 새 도구 없이 기존 4개 명령과 PR 스크린샷으로 확정한다(D-075). 비교 도구는 별도 안건이다.
- **헤딩 낱말.** 이슈는 0~6 라벨만 다뤘지만 "위험도"·"Risk Level" 헤딩도 이번에 바꾼다. 디자인이 이미 "심각도"로 바뀌어 있기 때문이다.
- **이슈 근거 삭제.** 이슈의 "L2 영향 문장 '높음(4)'과 일치한다"는 근거는 뺀다. `l2_report.md:6`이 라벨 어휘를 지정하지 않아 일치가 보장되지 않는다.
- **작업 위치.** 원래 폴더의 #362 미커밋 변경을 건드리지 않으려고 `../0-Ticket-ui` worktree(`origin/main` 기준)에서 작업한다.
- **심각도 라벨 결정(D-074).** `0 미상, 1 정보, 2 낮음, 3 보통, 4 높음, 5 심각, 6 치명`. OCSF `severity_id`(0~6) 값의 UI 표기이다. 색은 3단계 규칙을 유지한다.
- **D-075는 별도 결정으로 올린다.** 화면 검사 방법을 `AGENTS.md` 문구뿐 아니라 결정 목록에도 남긴다.

## 바뀐 점

(없음)
