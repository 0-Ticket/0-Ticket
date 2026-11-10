---
issue: 284
date: 2026-11-10
owner: Pandyo
plan: 284-auth-roles.md
supersedes: []
---

# 사용자 계정·로그인과 권한을 만들고 기존 API에 적용했다

## 한 일

- `/api` 전체가 기본 거부가 됐다. 인증 없이 열리는 것은 `POST /api/auth/login`, `POST /api/auth/signup`뿐이고, 나머지는 서버 세션(HttpOnly·SameSite=Lax 쿠키, DB에는 토큰 SHA-256만)과 라우트별 권한(`require_permission`)을 요구한다.
- `python -m soc.api`가 시작할 때 사용자가 0명이면 `admin`을 만들고 임시 비밀번호를 터미널에 한 번만 낸다(advisory 락으로 동시 시작에도 하나). 이 계정은 비밀번호를 바꾸기 전에는 비밀번호 변경·로그아웃·내 정보 조회 외에 모두 403이다.
- 가입은 `pending`이고 승인 전에는 로그인할 수 없다. admin이 승인(역할 지정)·거절·비활성화·역할 변경·임시 비밀번호 재설정을 한다. 마지막 admin은 강등·비활성화할 수 없다.
- 권한 16개를 admin이 사용자별로 부여·회수한다(`PUT /api/users/{id}/permissions`). admin은 항상 전체 권한이다. analyst는 가입 승인 때 조회 권한 9개를 기본으로 받는다. 권한 변경은 다음 요청부터 적용된다(세션 만료 없음).
- 변경 요청(POST/PUT/PATCH/DELETE)은 `Origin`이 허용 목록(`[auth] allowed_origins`)에 있어야 한다.
- `/openapi.json`은 `/api/openapi.json`으로 옮겨 로그인해야 받을 수 있다.

## 계획과 달라진 점

- 가입 승인 때 analyst가 받는 기본 조회 권한은 승인한 사람이 그 권한을 갖고 있는지와 관계없이 시스템이 준다. 계획의 "권한은 부여자가 가진 것만 남에게 준다" 규칙은 `PUT /api/users/{id}/permissions`(명시적 부여)에 적용한다. 그러지 않으면 조회 권한을 일부 회수당한 사람이 승인한 analyst는 기본값을 못 받는다.
- **권한 `user.role`을 없애 17개가 16개가 됐다**(2026-11-10, 사용자 결정). 역할은 admin·analyst뿐이라, admin 대상 작업과 admin 역할 지정이 admin 전용인 이상 non-admin이 `user.role`로 할 수 있는 일이 없었다. 역할 변경(`PATCH /api/users/{id}`)은 권한이 아니라 admin 역할(`require_role("admin")`)이 필요하다. 이전 이슈 댓글·계획 본문의 "17개"는 이 변경 전 숫자다(계획 파일 "바뀐 점"에 적음).
- `GET /api/users`에 `limit`(기본 50, 최대 200)과 `cursor`를 더했다. 계획은 "상한 있는 전체 목록"이었는데 500명을 넘으면 조용히 잘렸다. 정렬은 만든 순서이고 `next_cursor`는 `<만든 시각 마이크로초>_<ID>`이다. 다른 목록 API와 같은 모양이다.
- 계획에 없던 오류 코드: 404 `not_found`(없는 사용자 ID), 409 `invalid_state`(상태가 맞지 않는 승인·거절·비활성화 등), 409 `invalid_target`(admin이나 비활성 사용자의 권한 행 변경).
- 새 응답 모델(`Me`, `UserItem`, `UserList`, `PermissionList`, `SignupResult`)은 TypeScript 생성 대상(`scripts/export_api_schemas.py`의 `NAMES`)에 넣지 않았다. 화면 이슈가 필요할 때 추가한다.
- `uv.lock`: 이 컴퓨터의 uv가 0.6.6이라 `uv add`가 락 파일 전체를 다시 썼다(revision 3 → 1, `upload-time` 삭제, 2천 줄 변경). 그 결과를 버리고 `argon2-cffi`·`argon2-cffi-bindings` 항목만 원래 형식으로 손으로 넣었다. URL·해시·크기는 uv가 만든 값이고 `upload-time`은 PyPI JSON에서 채웠다. `uv sync --locked`는 이 컴퓨터에서 통과한다. 새 uv가 있는 환경에서 `uv lock --check`로 한 번 확인한다.
- `require_role("admin")`은 이슈가 제공하라고 한 의존성이라 만들었지만 라우트에서는 쓰지 않는다(테스트만). SIEM 설정 API가 생기면 `require_permission`으로 권한을 더하는 쪽을 권한다.

## 다음 사람이 알아야 할 것

- **로그인 화면이 없다.** 이 이슈를 머지하면 현재 화면(`frontend/`)은 모든 API가 401이라 동작하지 않는다. 로그인 화면 이슈와 머지 순서를 맞춘다.
- **승인류 권한 3개(`incident.approve`, `incident.reject`, `incident.close`)는 이름만 있다.** 적용할 승인 라우트가 아직 없어, 부여해도 할 수 있는 일이 없다. 승인 API를 만드는 이슈가 라우트에 `require_permission(...)`을 붙이고 승인자를 기록한다. 구조 테스트(`test_every_permission_but_the_approval_ones_guards_a_route`)는 이 3개만 "라우트에 안 쓰여도 됨"으로 둔다. 라우트에 붙이면 `src/soc/auth/permissions.py`의 `UNUSED`에서 뺀다.
- **새 조회 API를 만들면** `src/soc/auth/permissions.py`에 `.read` 권한을 더하고, 기존 analyst에게 기본 조회 권한을 넣는 마이그레이션을 같이 만든다(가입 승인 때 복사하는 방식이라 기존 사용자는 자동으로 받지 않는다). 빠뜨리면 접근이 닫히는 쪽으로 실패한다. 새 라우트를 만들고 `tests/test_auth.py`의 `PERMISSION_TABLE`에 넣지 않으면 테스트가 실패한다.
- **권한 상승 방지 규칙**은 `src/soc/auth/store.py`에 있다: ①admin 계정을 대상으로 하는 작업은 admin만, ②admin 역할 지정과 역할 변경은 admin만, ③권한은 부여자가 가진 것만 부여(줄이는 것은 누구나), ④자기 권한은 바꿀 수 없음, ⑤마지막 admin 보호.
- **요청 중에 권한이 바뀌는 경우**: 인증 의존성이 요청 시작에 읽은 사용자·권한으로 그 요청이 끝까지 처리된다. 같은 순간에 강등된 사용자의 진행 중인 요청 하나는 이전 권한으로 끝날 수 있다. 사용자 관리 작업은 advisory 락으로 직렬화되어 마지막 admin 보호는 지켜진다(동시 강등 테스트).
- **요청마다 DB 쓰기 연결을 하나 더 연다**(세션 `last_seen_at` 갱신). 데이터 라우트의 읽기 전용 연결은 그대로다. 요청당 연결이 둘이다.
- 가입한 표시 이름은 임의의 출력 가능한 문자열이다. 화면은 텍스트로만 표시한다(D-019). 아이디는 `[a-z0-9._-]{3,64}`로 정규화한다.
- 세션 만료 행은 그 사용자가 다음에 로그인할 때 지운다. 로그인하지 않는 사용자의 만료 행은 남는다.
- admin이 한 명도 없는 상태(전원 비활성화 등)에서는 시작 때 admin이 다시 만들어지지 않는다(사용자가 0명일 때만 만든다). 개발 DB는 `DELETE FROM users` 후 다시 시작한다.
- 새 환경변수는 없다. 설정은 `config/default.toml`의 `[auth]`이다(`idle_timeout_seconds`, `absolute_timeout_seconds`, `cookie_name`, `cookie_secure`, `allowed_origins`).
- `argon2-cffi` 25.1.0과 `argon2-cffi-bindings` 26.1.0의 라이선스는 설치된 패키지의 LICENSE 파일 기준 MIT다(Apache-2.0 레포와 호환). PyPI 메타데이터의 license 필드는 비어 있다.

### 배포 전에 정해야 할 것

- **로그인 시도 제한**(무차별 대입 방어)을 만들지 않았다. 아이디·IP별 제한이나 지연이 필요하다.
- **가입 폭주**: 가입은 인증 없이 `pending` 행과 Argon2 계산을 만든다. 속도 제한이나 가입 차단 스위치가 필요하다.
- **아이디 열거**: 가입 때 이미 있는 아이디는 409 `username_taken`으로 알려 준다. 이메일 확인이 없어서 불가피하게 허용했다.
- **임시 비밀번호의 표준 출력**: 컨테이너나 프로세스 매니저가 표준 출력을 수집하면 평문 임시 비밀번호가 로그 시스템에 남는다. 배포 방식에 맞는 전달 방법을 정한다.
- **프록시 뒤 배포**: `Origin` 허용 목록과 `cookie_secure = true`를 `config/local.toml`에서 배포 주소에 맞춘다. 프록시의 X-Forwarded 헤더는 읽지 않는다.
- **admin 전원이 잠겼을 때의 복구 수단**(콘솔 CLI 등)이 없다.
- **세션 정리**: 오래된 만료 세션을 주기적으로 지우는 작업이 없다.

## 화면용 응답 모양

모든 오류 본문은 `{"error": "<코드>"}`이고 422만 `fields`(필드 이름 목록)가 더 있다. 입력값은 담기지 않는다. 쿠키 이름은 `soc_session`이다.

| 요청 | 성공 | 본문 |
|---|---|---|
| `POST /api/auth/login` `{username, password}` | 200 + 쿠키 | `Me` |
| `POST /api/auth/signup` `{username, display_name, password}` | 201 | `{username, status: "pending"}` |
| `GET /api/auth/me` | 200 | `Me` |
| `POST /api/auth/logout` | 204 + 쿠키 삭제 | 없음 |
| `POST /api/auth/password` `{current_password, new_password}` | 200 + 새 쿠키 | `Me` |
| `GET /api/users?status=&limit=&cursor=` | 200 | `{items: UserItem[], next_cursor}` |
| `GET /api/permissions` | 200 | `{permissions: [{name, analyst_default}]}` |
| `POST /api/users/{id}/approve` `{role}` | 200 | `UserItem` |
| `POST /api/users/{id}/reject`, `/disable` | 200 | `UserItem` |
| `POST /api/users/{id}/reset-password` `{temporary_password}` | 200 | `UserItem`(비밀번호 없음) |
| `PATCH /api/users/{id}` `{role}`(admin 역할 필요) | 200 | `UserItem` |
| `PUT /api/users/{id}/permissions` `{permissions: []}` | 200 | `UserItem` |

- `Me`: `{id, username, display_name, role: "admin"|"analyst", must_change_password, permissions: string[]}`. 화면은 `permissions`로 버튼을 숨긴다. `must_change_password`가 true면 비밀번호 변경 화면으로 보낸다.
- `UserItem`: `Me`에 `status`(`pending|active|rejected|disabled`), `created_at`, `approved_at`(밀리초 epoch, 없으면 null)을 더하고 `role`은 승인 전이면 null이다.
- 비밀번호는 12~128자다.

| 상태 | `error` | 뜻 |
|---|---|---|
| 401 | `unauthenticated` | 세션이 없거나 만료됨(유휴 1시간·절대 12시간). 로그인 화면으로 |
| 401 | `invalid_credentials` | 로그인 실패(아이디 없음과 비밀번호 틀림이 같음), 비밀번호 변경 때 현재 비밀번호 틀림 |
| 403 | `account_pending` / `account_rejected` / `account_disabled` | 비밀번호가 맞을 때만. 계정 상태 안내 |
| 403 | `password_change_required` | 임시 비밀번호 상태. 비밀번호 변경 화면으로 |
| 403 | `permission_denied` | 이 라우트의 권한이 없음 |
| 403 | `forbidden` | 권한 상승 방지 규칙에 걸림 |
| 403 | `origin_not_allowed` | 변경 요청의 `Origin`이 허용 목록에 없음 |
| 404 | `not_found` | 없는 사용자 ID 등 |
| 409 | `username_taken`, `last_admin`, `invalid_state`, `invalid_target` | 중복 아이디, 마지막 admin 보호, 상태가 맞지 않음, 권한 행을 바꿀 수 없는 대상 |
| 422 | `invalid_body` / `invalid_query` + `fields` | 형식 오류 |
| 503 | `db_unavailable` | DB 연결 실패 |

권한 이름(16개), analyst 기본 지급(`*`)은 `GET /api/permissions`와 `src/soc/auth/permissions.py`가 기준이다.

| 권한 | 적용 |
|---|---|
| `dashboard.read`*, `alert.read`*, `event.read`*, `ticket.read`*, `incident.read`*, `case.read`*, `hunt.read`*, `news.read`*, `policy.read`* | 각 조회 API(`GET /api/ticketing-policy` 포함) |
| `policy.update` | `PUT /api/ticketing-policy` |
| `user.read` | `GET /api/users`, `GET /api/permissions` |
| `user.approve` | 가입 승인·거절, 비활성화, 비밀번호 재설정 |
| `user.permission` | 권한 부여·회수 |
| `incident.approve`, `incident.reject`, `incident.close` | 적용 라우트 없음 |

## 확인 방법

- 테스트를 먼저 썼다. 구현 전 `tests/test_auth.py`와 `tests/test_auth_db.py`는 `soc.api.auth`·`soc.auth`가 없어 수집 오류로 실패했다.
- `tests/test_auth.py`(DB 없음 63건): 권한 16개·기본 지급 9개, 권한 라우트 쓰임 검사, Argon2id 해시, `[auth]` 설정 검사, 모든 라우트가 로그인 없이는 401(로그인·가입 제외), 권한 표 23개 라우트가 정확히 자기 권한만 요구, 임시 비밀번호 403, CSRF `Origin`, 본문 422가 필드 이름만 담음, 역할 변경은 모든 권한을 가진 analyst도 403, 사용자 목록 쿼리 422.
- `tests/test_auth_db.py`(`db` 마커 24건, 임시 로컬 PostgreSQL 16.14): 최초 admin 하나·임시 비밀번호 1회 출력·로그에 없음, 8개 스레드 동시 시작, 마이그레이션 전 시작 종료 코드 2, 임시 비밀번호 흐름, 가입→승인→로그인, 사용자 목록 페이지 나누기(빠짐·중복 없음), 거절·비활성화·중복 가입, 역할 변경 시 세션 만료·권한 초기화, 마지막 admin 보호와 두 admin 동시 강등, 유휴·절대 만료와 갱신, 비밀번호 변경 시 다른 세션 만료·현재 토큰 교체, 로그아웃, 쿠키 속성(HttpOnly, SameSite=lax, Max-Age, Secure 설정)과 토큰 해시 저장, 실제 로그인에서의 Origin 검사, 관리자 재설정, 기존 라우트의 권한 부여·회수, 권한 상승 방지 5규칙, 권한 변경의 즉시 반영, `soc_agent_reader`가 세 테이블을 읽지 못함, 비밀번호·토큰이 로그·응답·DB에 없음.
- 기존 테스트를 고쳤다(지우거나 건너뛴 테스트 없음): `tests/test_api.py`(라우트 목록 테스트를 읽기 전용 라우터 범위로 좁히고 앱 전체 경로 집합과 OpenAPI 경로·메서드 기대값에 인증 라우트를 더함, `/openapi.json` 예외 단언을 "앱 바로 아래 라우트 없음"으로, 설정 테스트에 `[auth]`, `main` 테스트에 최초 admin 모킹과 출력·로그 확인), `tests/test_api_ui.py`·`test_api_db.py`·`test_api_seed.py`·`test_ticketing.py`·`test_ticketing_db.py`(인증된 테스트 클라이언트, `tests/auth_support.py`), `tests/test_db_tables.py`(마이그레이션 13개와 새 테이블 3개).
- `uv run ruff format --check .`, `uv run ruff check .` 통과. `uv run pytest` 1,375건 통과. `uv run pytest -m db` 411건 통과(임시 로컬 PostgreSQL 16.14, 약 87초). CI의 PostgreSQL 17.6 결과는 push 뒤 사람이 확인한다.
- 실제 서버를 띄워 `curl`로 확인했다: 세션 없는 조회 401, `Origin` 없는 로그인 403, 임시 비밀번호로 로그인 200(쿠키 HttpOnly·SameSite=lax·Max-Age), 비밀번호 변경 전 조회 403, 내 정보에 admin의 전체 권한 목록.
