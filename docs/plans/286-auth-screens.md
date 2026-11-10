---
issue: 286
date: 2026-11-10
owner: Pandyo
supersedes: []
---

# 로그인·사용자 관리·Ticket 정책 화면 만들기

## 목표

#284로 `/api` 전체가 기본 거부가 돼 현재 화면이 모두 401이다. `frontend/`에 로그인 흐름, 공통 셸(사용자 영역, 오류 처리), 사용자 관리, Ticket 정책 설정 화면을 만들어 기존 14개 화면이 로그인 뒤 다시 동작하고 #284의 사용자 관리 API와 #246의 정책 API를 쓸 화면이 생기게 한다. 백엔드는 바꾸지 않는다. 위협 뉴스 화면은 이번 범위에서 뺀다(아래 "토론으로 정한 것").

## 방법

### 디자인 읽기

- AI가 pen.dev MCP로 `.pen`을 직접 읽어 구현한다(#274와 같다). `.pen`은 커밋하지 않는다. 디자인 원본은 레포 밖에 있고 담당자가 보관한다.
- **이 계획을 확정할 때 MCP가 VS Code 확장에 연결되지 않아 새 화면 디자인의 내용을 확인하지 못했다.** 개발을 시작할 때 가장 먼저 `.pen`을 읽는다. 로그인·회원가입·비밀번호 변경·사용자 관리·정책 화면이 없거나 이 계획과 크게 다르면 멈추고 사람에게 말한다. 디자인이 없는 화면을 기존 컴포넌트로 만들지는 사람이 정한다.

### 1. 로그인 흐름

- 로그인 `POST /api/auth/login` → `Me`. 회원가입 `POST /api/auth/signup` → 201, 완료 뒤 "관리자 승인 후 로그인할 수 있다"를 안내한다. 비밀번호 변경 `POST /api/auth/password` → `Me`.
- 오류 코드마다 다른 문구를 보인다: `invalid_credentials`, `account_pending`·`account_rejected`·`account_disabled`, `username_taken`, 422 `fields`(필드 이름으로 해당 입력 옆에 표시).
- 입력 규칙은 서버와 같게 검사한다: 아이디 `[a-z0-9._-]` 3~64자(대문자는 소문자로 바꿔 보낸다), 비밀번호 12~128자.
- 로그인 상태는 React Query `["me"]` 캐시에 둔다(`GET /api/auth/me`). 앱을 열 때 한 번 확인하고, 비로그인이면 `/login`으로 보낸다. 로그인 뒤에는 라우터 `location.state`에 담아 둔 원래 경로와 쿼리로 돌아간다(없으면 `/`). URL에는 담지 않는다.
- `must_change_password`가 true면 `/password` 강제 모드다. 다른 경로로 갈 수 없고 사이드바 메뉴도 숨기며 로그아웃만 된다. false면 사이드바에서 여는 변경 창이다.
- 비밀번호 입력값은 `useMutation`의 `variables`에 남지 않게 한다(`reset()`을 부르거나 쓰지 않는다). 비밀번호와 세션 토큰은 URL·콘솔·테스트 출력에 남기지 않는다. 세션 토큰은 HttpOnly 쿠키라 JS에서 읽지 않는다.

### 2. 공통 셸과 오류 처리

- 사이드바 하단의 "관리자" 텍스트와 동작 없는 설정 버튼(#274 임시 표시)을 사용자 영역으로 바꾼다: 표시 이름, 역할 배지, 비밀번호 변경, 로그아웃(`POST /api/auth/logout`, 204).
- 기존 메뉴 6개는 `Me.permissions`로 보인다(Dashboard `dashboard.read`, Alert/Event `alert.read` 또는 `event.read`, Ticket `ticket.read`, Incident `incident.read`, Case `case.read`, Hunting `hunt.read`). 그 아래 구분선을 두고 "Ticket 정책"(`/policy`, `policy.read`)과 "사용자 관리"(`/users`, `user.read`)를 권한이 있을 때만 보인다. 버튼도 권한이 없으면 숨기거나 비활성으로 둔다.
- `get()`을 `ApiError`(HTTP 상태, `error` 코드, `fields`)를 던지게 바꾼다. 변경 요청 공통 함수를 새로 만들고, 204는 본문을 읽지 않는다.
- 오류 처리:
  - 401 `unauthenticated`: `QueryClient` 생성 함수에 둔 `QueryCache` 오류 처리가 `["me"]`를 비우고 로그인 화면으로 보낸다. 생성 함수는 `main.tsx`와 테스트가 같이 쓴다.
  - 401 `invalid_credentials`: 로그인과 비밀번호 변경 폼에서 그 폼의 오류로만 보이고 세션 만료로 처리하지 않는다.
  - 403 `permission_denied`: 권한 없음 화면(상세 패널 안에서는 패널 안 "권한 없음").
  - 403 `password_change_required`: 비밀번호 변경 화면으로.
  - 403 `origin_not_allowed`, 503 `db_unavailable`: 오류 상태.
- 세션 만료는 다음 요청에서 401을 받을 때만 알아챈다. `/api/auth/me`를 주기적으로 부르지 않는다(서버가 요청마다 `last_seen_at`을 갱신해 유휴 만료를 늘리기 때문이다).
- 대시보드 집계 구조는 지금대로 둔다. 그래서 `dashboard.read`가 없는 사용자는 대시보드뿐 아니라 집계를 쓰는 모든 화면에서 권한 없음 화면을 본다(알려진 한계, 아래 "토론으로 정한 것"). `/`도 같다.
- 새 응답 모델을 TypeScript 생성 대상에 더한다. `scripts/export_api_schemas.py`의 `NAMES`에 `soc.api.auth_models`의 `Me`, `UserItem`, `UserList`, `PermissionList`, `SignupResult`와 `soc.api.models`의 `TicketingPolicyResponse`를 넣고 `pnpm contracts`로 만든다. 정책 저장 요청은 `TicketingPolicyBody`와 모양이 같아 `TicketingPolicyResponse` 타입을 같이 쓴다. 요청 본문 타입은 따로 생성하지 않는다.
- `pnpm dev`를 `--port 5173 --strictPort`로 고정한다. 5173이 사용 중일 때 Vite가 다른 포트로 떠서 모든 변경 요청이 `origin_not_allowed`로 막히는 것을 피한다.

### 3. 사용자 관리 (admin)

- 목록 `GET /api/users?status=&limit=&cursor=`(`user.read`). 상태 탭 `pending / active / rejected / disabled`, 페이지당 25건, 다음 페이지는 `next_cursor`다. 페이지 표기는 기존 목록과 같은 "N/-"이다. `ListView`의 cursor 이력 로직을 훅으로 빼서 사용자 목록이 같이 쓴다.
- 작업 패널(`user.approve`): 승인 `POST /api/users/{id}/approve {role}`, 거절 `/reject`, 비활성화 `/disable`, 임시 비밀번호 재설정 `/reset-password {temporary_password}`. 역할 변경 `PATCH /api/users/{id} {role}`은 admin 역할일 때만 보인다. 승인 때 admin 역할 선택지도 admin에게만 보인다.
- 권한 편집(`user.permission`): `GET /api/permissions`로 권한 16개와 analyst 기본 지급 여부를 읽고 `PUT /api/users/{id}/permissions {permissions: []}`로 저장한다. admin 대상, 자기 자신, 내가 갖지 않은 권한은 비활성으로 보인다. `PUT`은 전체 교체이므로 비활성 항목의 현재 값도 그대로 포함해 보낸다. `incident.approve`·`incident.reject`·`incident.close`는 적용할 API가 없어 "준비 중"으로 표시하고 현재 값은 그대로 보낸다.
- 오류 상태: `last_admin`, `invalid_state`, `invalid_target`(409), `forbidden`(403), 없는 사용자 404를 각각 다른 문구로 보인다. 마지막 admin, 자기 자신, admin 대상의 해당 동작은 미리 막아 둔다.
- 표시 이름 등 사용자가 입력한 문자열은 React 텍스트로만 표시한다(D-019).

### 4. Ticket 정책 설정

- `GET /api/ticketing-policy`(`policy.read`), `PUT /api/ticketing-policy` `{mode: "auto" | "scenario", scenario_rule_ids: []}`(`policy.update`). `policy.update`가 없으면 읽기 전용으로 보이고, 저장 성공·실패를 표시한다. 룰 ID는 밖에서 온 문자열이므로 텍스트로만 표시한다.

### 기타 동작

- 상세 패널의 다른 자원 링크는 대상 읽기 권한이 없어 403이 나면 패널 안에 "권한 없음"으로 표시한다.
- Incident 승인·반려, 헌팅 실행 버튼, SIEM 설정 같은 API가 없는 동작은 기존 비활성 버튼을 그대로 둔다.

### 테스트와 샘플

- 손으로 만든 `tests/fixtures/frontend/auth.json`(가짜 계정 이름, 비밀번호 값 없음)을 먼저 두고 테스트를 먼저 쓴다.
- 기존 `App.test.tsx`는 `onUnhandledFrame: "error"`라 `/api/auth/me` 핸들러가 없으면 모두 실패한다. 공용 `show()`와 MSW 서버 설정을 `test-utils.tsx`로 빼고 기본 `me` 핸들러(admin, 전체 권한)를 넣는다. 기존 테스트를 지우거나 건너뛰지 않는다. "profile text and settings button make no request or navigation"(`App.test.tsx:410`)은 새 사용자 영역 테스트로 대체한다.
- 새 테스트는 파일을 나눈다: 비로그인과 복귀, 로그인·가입·비밀번호 변경의 오류 코드별 문구, 강제 비밀번호 변경, 401과 403 처리(현재 비밀번호가 틀린 경우가 세션 만료가 아님), 권한별 메뉴 노출, 사용자 관리 승인 흐름과 오류, 권한 편집(비활성 항목 값 유지), 정책 읽기 전용과 저장, 외부 문자열 텍스트 표시.

### 순서와 커밋

1 → 2 → 3 → 4 순서로 만들고 1~2번이 먼저 쓸 수 있는 커밋이 되게 나눈다. 테스트를 먼저 쓰고 구현한다.

- docs(plans): add plan for auth screens (#286)
- feat(frontend): add login flow and auth shell (#286) — 1·2번과 생성 타입
- feat(frontend): add user management screen (#286) — 3번
- feat(frontend): add ticketing policy screen (#286) — 4번
- docs(notes): add notes for auth screens (#286)

## 바꿀 곳

- `scripts/export_api_schemas.py`: `NAMES`에 새 응답 모델 6개와 `auth_models` 모듈 키
- `frontend/src/api/generated/`: 생성 타입(손으로 고치지 않는다)
- `frontend/src/api/client.ts`: `ApiError`, 변경 요청 공통 함수
- `frontend/src/main.tsx`와 `QueryClient` 생성 함수 파일: 401 처리
- `frontend/src/App.tsx`: 셸과 라우팅 분리, 사이드바 사용자 영역과 권한 메뉴, `ListView`의 cursor 이력 훅 추출
- `frontend/src/`의 새 파일: 로그인·가입·비밀번호 변경, 사용자 관리, 정책, 권한 없음 화면(위치는 개발 중 정하고 기록에 적는다)
- `frontend/package.json`: `dev` 스크립트
- `frontend/src/App.test.tsx`, `frontend/src/test-utils.tsx`, 새 테스트 파일, `tests/fixtures/frontend/auth.json`
- `docs/notes/286-auth-screens.md`: 개발 기록

## 다른 코드와 맞물리는 곳

- `scripts/export_api_schemas.py`의 `NAMES`: `frontend/scripts/generate.mjs`와 CI의 `pnpm contracts:check`가 쓴다. 이름을 더하기만 하고 기존 항목은 바꾸지 않는다.
- `frontend/src/api/client.ts`의 `get()`: 오류를 `ApiError`로 던지게 바뀐다. 호출처는 `App.tsx`뿐이다.
- `frontend/package.json`의 `dev` 스크립트: 개발 포트를 5173으로 고정한다. 5173이 사용 중이면 실행이 실패한다.
- 백엔드·DB·계약(`contracts/`)·설정 키는 바꾸지 않는다.

## 범위 밖

- 백엔드 변경. 아래 알려진 문제는 별도 이슈로 한다.
  - `user.approve` 권한만 가진 사용자가 권한이 많은 non-admin의 비밀번호를 재설정해 권한을 얻을 수 있는 구멍(`docs/notes/284-auth-roles.md`)
  - 로그인 시도 제한, 가입 폭주 방어, admin 전원이 잠겼을 때의 복구 수단, `Cache-Control: no-store`(화면에서 확인한 결과만 기록한다)
- 위협 뉴스 화면. 디자인에서 뺐다. `GET /api/threat-news`는 이번에 화면에 연결하지 않으며, 만들려면 새 이슈가 필요하다.
- SIEM 설정 화면, Incident 승인·반려·종결 동작, 헌팅 실행 버튼(API가 없다).
- 기존 14개 화면의 디자인 변경.
- `/api/auth/me` 주기 호출 등 세션 만료 선제 감지.

## 완료 기준

- [ ] 로그인하지 않으면 로그인 화면이 열리고, 로그인하면 원래 가려던 경로로 돌아온다. 현재 14개 화면이 로그인 뒤 다시 정상 동작한다
- [ ] 로그인·회원가입·비밀번호 변경이 각 오류 코드(`invalid_credentials`, `account_pending` 등, `username_taken`, 422 필드 오류)를 다른 문구로 보여 준다
- [ ] `must_change_password`가 true인 계정은 비밀번호를 바꾸기 전에 다른 화면으로 갈 수 없다
- [ ] 비밀번호 변경 때 현재 비밀번호가 틀린 경우가 세션 만료로 처리되지 않는다
- [ ] 세션 만료(401)는 로그인 화면으로, 권한 없음(403)은 권한 없음 화면으로 간다
- [ ] 사이드바에 표시 이름·역할·로그아웃이 있고, 메뉴와 버튼이 `permissions`에 따라 보인다
- [ ] 사용자 관리: 목록 탭·다음 페이지, 승인(역할 지정), 거절, 비활성화, 임시 비밀번호 재설정, 역할 변경, 권한 편집이 동작하고 409·403 오류가 표시된다. 마지막 admin, 자기 자신, admin 대상은 동작하지 않게 막혀 있다
- [ ] 권한 편집이 비활성 항목의 현재 값을 잃지 않고 보낸다(테스트가 있다)
- [ ] Ticket 정책 설정을 읽고 저장할 수 있고, 변경 권한이 없으면 읽기 전용이다
- [ ] 새 응답 모델이 TypeScript 생성 대상에 추가됐고 `pnpm contracts:check`가 통과한다
- [ ] 사용자가 입력한 문자열(표시 이름 등)이 텍스트로만 표시되고, 비밀번호와 세션 토큰이 화면 상태·URL·콘솔·테스트 출력에 남지 않는다
- [ ] 화면 테스트: 비로그인, 권한별 메뉴 노출, 오류 코드별 표시, 사용자 관리 승인 흐름
- [ ] `pnpm lint`, `pnpm test`, `pnpm build`, `pnpm contracts:check` 통과
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록이 있다
- [ ] PR에 새 화면의 스크린샷이 있다(사람이 첨부)

## 토론으로 정한 것

이슈 본문과 달라진 점과 그 이유만 적는다.

- **위협 뉴스 화면을 뺀다.** 디자인에서 뉴스 목록을 지웠다(사람 결정). 이슈 4단계의 뉴스 부분, 완료 기준의 뉴스 항목, `NewsPage` 생성이 모두 빠진다. 뉴스 필터 질문은 없어졌다.
- **디자인 확인은 개발 시작 때로 넘긴다.** 확정 시점에 Pencil MCP가 VS Code에 연결되지 않아 새 화면(로그인·가입·사용자 관리·정책)이 `.pen`에 있는지 확인하지 못했다. 위 "디자인 읽기"의 조건으로 개발 첫 단계에서 확인한다.
- **로그인 상태는 React Query `["me"]` 캐시에 두고 401을 `QueryClient` 생성 함수에서 한 곳으로 처리한다.** 별도 컨텍스트나 화면별 처리보다 기존 쿼리 코드를 덜 건드린다.
- **복귀 경로는 `location.state`에 담는다.** URL 쿼리로 들고 가면 열린 리다이렉트 검증이 필요해서다.
- **세션 만료는 다음 요청의 401로만 안다.** 서버가 요청마다 `last_seen_at`을 갱신하므로 주기 확인이 유휴 만료를 무력화한다.
- **대시보드 집계 구조를 유지한다.** AI는 집계를 각 화면 안으로 옮겨 실패해도 목록이 동작하게 하는 쪽을 추천했으나 사람이 현재 구조 유지로 정했다. 그 결과 `dashboard.read`가 없는 사용자는 집계를 쓰는 모든 화면에서 권한 없음을 본다. `/`도 같다.
- **사이드바 새 메뉴는 기존 6개 아래 구분선을 두고 권한이 있을 때만 보인다**(정책, 사용자 관리 2개).
- **사용자 목록의 페이지 표기는 "N/-"**이고 `ListView`의 cursor 이력 로직을 훅으로 빼서 같이 쓴다.
- **사람이 확정한 보완**: 상세 패널의 교차 링크 403은 패널 안 "권한 없음", `get()`을 `ApiError`로 바꾸고 변경 요청 공통 함수가 204를 처리, 테스트는 공용 `test-utils.tsx`와 기본 `me` 핸들러·새 테스트 파일 분리·`tests/fixtures/frontend/auth.json`, `pnpm dev` 포트 고정(`--port 5173 --strictPort`), 권한 편집은 비활성 항목의 현재 값을 포함해 전체 교체로 보낸다.
- #274의 "관리자 텍스트와 동작 없는 설정 버튼은 D-020 전까지의 임시 표시"는 이 계획이 대체한다. 기존 `App.test.tsx`의 설정 무동작 테스트는 새 사용자 영역 테스트로 바꾼다. #274 계획·기록 파일은 고치지 않는다.
- 결정 목록(`docs/decisions.md`)에 올릴 새 도구나 방식은 없다. 새 라이브러리도 쓰지 않는다.

## 바뀐 점

- 2026-11-10: 개발 시작 때 `.pen`을 읽고 사람이 정했다. 비로그인은 계획대로 `/login`으로 보내고 디자인의 로그아웃 대시보드(프레임 17)는 만들지 않는다. 사이드바의 "설정"은 비밀번호 변경 창이 아니라 디자인대로 `/settings` 페이지(내 계정 정보 + 비밀번호 변경)로 만들고, 메뉴 묶음 이름 "관리"도 디자인을 따른다. 강제 변경 모드(`/password`)는 계획 그대로다.
