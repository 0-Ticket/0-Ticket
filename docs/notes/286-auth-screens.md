---
issue: 286
date: 2026-11-10
owner: Pandyo
plan: 286-auth-screens.md
supersedes: []
---

# 로그인·사용자 관리·Ticket 정책 화면을 만들었다

## 한 일

- 비로그인이면 `/login`으로 가고, 로그인하면 `location.state`에 담아 둔 원래 경로·쿼리로 돌아온다. 로그인 상태는 React Query `["me"]` 캐시(`frontend/src/auth/session.ts`)이고 앱을 열 때 한 번만 읽는다. 로그인·회원가입·비밀번호 변경은 오류 코드마다 다른 문구를 보이고, `must_change_password`이면 `/password`에 갇힌다(`auth/pages.tsx`).
- `get()`이 `ApiError`(상태, 코드, `fields`)를 던지고 변경 요청용 `send()`가 있다(`api/client.ts`). 401 `unauthenticated`만 `QueryClient` 생성 함수(`api/query-client.ts`)에서 `["me"]`를 비워 로그인으로 보낸다. `invalid_credentials`는 폼 오류다. 403 `password_change_required`는 `["me"]`를 다시 읽게 한다.
- 사이드바에 표시 이름·역할·설정·로그아웃이 생겼고 메뉴는 `permissions`로 보인다. 6개 메뉴 아래 "관리" 묶음에 Ticket 정책(`/policy`)과 사용자 관리(`/users`)가 있다. 403 `permission_denied`, 503 `db_unavailable`, 403 `origin_not_allowed`는 `error-state.tsx`가 각자 문구로 보인다.
- `/users`(`users/users-page.tsx`): 상태 탭, 25건 페이지(N/-), 작업 패널에서 승인·거절·중지·임시 비밀번호 재설정·역할 변경·권한 편집. 권한 편집은 전체 교체이므로 편집할 수 없는 항목의 현재 값도 그대로 보낸다.
- `/policy`(`policy-page.tsx`): 정책을 읽고 `policy.update`가 있으면 저장한다. 없으면 읽기 전용이다.
- 새 응답 모델 6개를 `scripts/export_api_schemas.py`에 더하고 `pnpm contracts`로 TypeScript 타입을 만들었다. `pnpm dev`는 5173 포트로 고정했다.

## 계획과 달라진 점

- 개발 시작 때 `.pen`을 읽었다(프레임 15~40). 로그인·가입·강제 비밀번호 변경·사용자 관리·권한 편집·정책·오류 화면이 모두 있다. 프레임 17(로그아웃 대시보드)은 사람이 구현하지 않기로 했고, 설정은 비밀번호 변경 창이 아니라 `/settings` 페이지로 만들기로 했다(계획 "바뀐 점").
- **설정은 페이지다.** 계획의 비밀번호 변경 창 대신 디자인대로 `/settings`(내 계정 + 비밀번호 변경)다. 강제 변경(`/password`)은 계획 그대로다.
- **비밀번호 입력은 `disabled`가 아니라 `readOnly`로 잠근다.** `FormData`가 disabled 입력을 빼서 요청 본문이 비었다. 비밀번호는 uncontrolled 입력에서 `mutationFn`이 읽어 가고 `mutate()`의 변수로 넘기지 않는다(임시 비밀번호 재설정도 같다).
- 회원가입 화면에 비밀번호 확인 입력이 있다(디자인). 서버로 보내지 않고 화면에서만 맞춰 본다.
- 기존 테스트 둘을 고쳤다(지우거나 건너뛰지 않았다): `error retries and empty data are distinct`는 503 `db_unavailable`에 디자인의 새 문구("서버에 일시적으로 연결할 수 없어요")를 기대한다. "profile text and settings button…"는 계획대로 새 사용자 영역 테스트로 바꿨다. `ticket origin and case status…`가 `staleTime` 때문에 깨져서 테스트용 `show()`는 운영 값(30초) 대신 기본 `staleTime`(0)을 쓴다.
- 파일 위치: 로그인·가입·비밀번호·설정은 `auth/pages.tsx`, 세션 훅은 `auth/session.ts`, `ErrorState`는 `App.tsx`에서 `error-state.tsx`로 옮겼고, `ListView`의 cursor 이력 로직은 `pager.ts`의 `usePager`로 뺐다. 테스트용 `Where`는 lint(react-refresh) 때문에 `where.tsx`로 분리했다.
- 사용자 관리와 정책 화면은 컴포넌트를 먼저 쓰고 테스트를 이어서 썼다(순서 위반). 테스트는 구현 뒤에 처음 돌렸을 때 통과했으므로 "먼저 실패" 확인은 하지 못했다. 로그인 흐름(1~2번)은 테스트를 먼저 썼고 실패를 확인했다.
- 로그인·가입·강제 변경의 왼쪽 패널 배경을 `.pen` 15 - Login의 fill(검정 + 오른쪽 위 steel 광택 + 왼쪽 아래 accent 광택, 색은 `style.css` 변수)대로 고쳤다. 처음에는 디자인을 읽지 않고 단색 남색을 넣었다. 폼 카드·플레이스홀더도 디자인대로 맞췄다. 가입 화면(16)은 광택 두 겹의 쌓는 순서만 로그인과 다르고 하나의 공통 스타일을 쓴다.
- 15~30 프레임 디자인 맞춤 작업(2차): 속성 기록과 비교 결과는 `286-auth-screens-design-values.md`에 있다. 가입 완료 안내 문장이 디자인의 상태 배지로 바뀌었다.
- 정책 화면의 시나리오 규칙 목록: 디자인은 규칙 6개 체크 목록을 보이지만 API에는 규칙 목록 조회가 없고 선택된 ID만 돌려준다. 저장된 ID를 체크 목록으로 보이고, 규칙 ID를 직접 입력해 더하게 했다.

## 다음 사람이 알아야 할 것

- **실제 백엔드·브라우저로 손으로 확인하지 못했다.** 확인한 것은 MSW 가짜 응답 테스트뿐이다. 스크린샷은 사람이 첨부한다. 쿠키·`Origin` 허용(5173 포트)·`Cache-Control: no-store` 여부는 화면에서 확인한 결과가 없다.
- 정책 화면: API에 규칙 목록 조회가 없어 저장된 규칙 ID만 체크 목록으로 보이고 새 ID는 직접 입력해 더한다. 규칙 목록 API가 생기면 목록을 거기서 읽게 바꾼다.
- 사용자 관리의 "마지막 admin" 사전 차단은 지금 보이는 한 페이지의 활성 admin 수로 판단한다. 다른 페이지의 admin은 모른다. 서버가 `last_admin`으로 막고 화면이 그 오류를 보인다.
- `dashboard.read`가 없는 사용자는 집계를 쓰는 모든 화면(Alert/Event, Ticket, Incident, Case, Hunting, 대시보드)에서 권한 없음을 본다(계획의 알려진 한계). `/settings`, `/users`, `/policy`는 집계를 읽지 않는다.
- 세션 만료는 다음 요청의 401로만 안다. `news.read` 권한은 목록에 보이지만 뉴스 화면은 없다.
- 로그인 직후 `removeQueries`로 이전 사용자의 캐시를 비운다. 새 쿼리 키를 `["me"]`로 시작하게 만들면 지워지지 않는다.
- 범위 밖으로 남긴 백엔드 문제(`reset-password` 권한 상승, 로그인 시도 제한 등)는 계획 "범위 밖"과 `docs/notes/284-auth-roles.md`에 있다.

## 확인 방법

- `cd frontend && pnpm lint && pnpm test && pnpm build && pnpm contracts:check`: 64개 테스트 통과(`auth.test.tsx` 19, `users.test.tsx` 17, `policy.test.tsx` 6, 기존 `App.test.tsx` 22).
- `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`: 통과(1375개).
- 샘플: `tests/fixtures/frontend/auth.json`(가짜 계정, 비밀번호 값 없음).
