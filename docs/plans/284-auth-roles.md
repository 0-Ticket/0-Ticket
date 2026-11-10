---
issue: 284
date: 2026-11-10
owner: Pandyo
supersedes: []
---

# 사용자 계정·로그인 만들고 기존 API에 역할 권한 적용

## 목표

사용자 계정, 로그인·로그아웃, 회원가입과 관리자 승인, 비밀번호 변경, 역할(admin / analyst) 검사를 만든다.
여기에 admin이 사용자별로 권한을 부여·회수하는 IAM식 권한 층을 더한다. `/api` 전체를 기본 거부로 바꿔 기존 화면용 API 모두에 권한을 적용한다.
analyst는 가입 승인 때 조회 권한을 기본으로 받는다.
로그인 화면은 만들지 않고, 화면이 쓸 응답 모양을 `docs/notes/`에 정리한다.

## 방법

이슈 본문의 세션·최초 관리자·가입 승인·비밀번호 결정(이슈 "어떻게" 1~4)은 그대로 따른다. 아래는 계획에서 정한 것이다.

### 데이터

- 마이그레이션 `0005_auth.sql`(공통 대역 다음 빈 번호. 먼저 머지되는 쪽이 번호를 가져간다).
- `users`: `id`(UUID, `gen_random_uuid()`, 계약 밖), `username`(소문자 정규화, 3~64자, 영숫자와 `._-`, 유일), `display_name`, `password_hash`, `role`(`admin`/`analyst`, 승인 전에는 null), `status`(`pending`/`active`/`rejected`/`disabled`), `must_change_password`, 생성·승인 시각, 승인자.
- `user_sessions`: `token_hash`(토큰 SHA-256, PK), `user_id`, `created_at`, `last_seen_at`, `expires_at`(절대 만료). 로그인 때 그 사용자의 만료된 행을 지운다.
- `user_permissions`: `(user_id, permission)` PK, `granted_by`, `granted_at`. 권한 이름은 코드 상수 목록(카탈로그)에서만 받는다.
- `soc_agent_reader`에는 세 테이블 권한을 주지 않는다. 읽지 못하는 것을 테스트로 확인한다.

### 인증 흐름

- 비밀번호는 argon2-cffi(D-047). 최소 12자. 없는 아이디도 더미 해시를 검증한다.
- 로그인마다 새 토큰을 발급하고 쿠키(`soc_session`, HttpOnly, SameSite=Lax, `cookie_secure` 설정)에 담는다.
- 인증 의존성은 요청마다 `connect_write()`로 세션과 사용자의 권한을 읽고 `last_seen_at`을 갱신한다. 권한 변경은 세션 만료 없이 다음 요청부터 적용된다. 데이터 라우트의 읽기 연결(`connect()`, 읽기 전용)은 그대로 둔다.
- 유휴(`idle_timeout_seconds`)·절대(`absolute_timeout_seconds`) 만료를 모두 검사한다.
- 비밀번호 변경: 다른 세션을 전부 만료하고 현재 세션 토큰은 새로 발급한다.
- 비활성화·역할 변경: 그 사용자의 세션을 같은 트랜잭션에서 지운다. 역할 변경 때 권한도 초기화한다: analyst → admin이면 권한 행을 비우고(admin은 전체 권한), admin → analyst면 기본 조회 세트로 되돌린다.
- 관리자 재설정: 관리자가 임시 비밀번호를 본문에 넣는다(12자 이상). 해시를 바꾸고 `must_change_password`를 켜고 세션을 전부 지운다. 응답에는 비밀번호가 없다. 자기 자신에게도 쓸 수 있다.
- `must_change_password`가 켜진 계정은 비밀번호 변경·로그아웃·내 정보 조회 외 모든 API가 403 `password_change_required`다.

### 최초 관리자

- `python -m soc.api`가 `uvicorn.run` 전에 `ensure_first_admin()`을 부른다. 테스트의 `create_app()`은 부르지 않는다.
- `pg_advisory_xact_lock` 아래에서 사용자 수가 0일 때만 `admin`(아이디 `admin`, `must_change_password`)을 만들고 랜덤 임시 비밀번호를 `print`로 1회만 낸다. `logging`, DB, 파일에 평문을 두지 않는다.
- `users` 테이블이 없으면(마이그레이션 전) 안내 문구를 내고 종료 코드 2로 끝낸다.

### 마지막 admin 보호

강등·비활성화는 같은 advisory 락 아래에서 활성 admin 수를 세고, 마지막 한 명이면 거부한다. 두 admin이 동시에 서로를 내려도 0명이 되지 않는다.

### 권한 적용(기본 거부)

- `/api` 라우터에 `require_login` 의존성을 기본으로 건다. 공개 라우트는 `POST /api/auth/login`, `POST /api/auth/signup`만 별도 라우터에 둔다.
- 역할은 admin·analyst 둘이다. admin은 항상 모든 권한을 갖고 권한 행의 영향을 받지 않는다. analyst는 `user_permissions`에 있는 권한만 갖는다.
- 라우트마다 `require_permission("<권한>")`을 붙인다. 한 라우터에 권한이 둘 이상이면(alerts/events) 라우트 단위로 붙인다. 이슈가 제공하라고 한 `require_role("admin")`은 admin 전용 보조 의존성으로 두고, 사용자 관리 규칙(아래)에 쓴다.
- 권한 이름은 `<자원>.<동작>`이다. 목록은 17개다.

| 권한 | 적용 | analyst 기본 |
|---|---|---|
| `dashboard.read` | `GET /api/dashboard` | 지급 |
| `alert.read`, `event.read` | `GET /api/alerts`·`/{id}`, `/api/events`·`/{id}` | 지급 |
| `ticket.read`, `incident.read`, `case.read` | `GET /api/tickets`, `/api/incidents`, `/api/cases`(각 상세 포함) | 지급 |
| `hunt.read` | `GET /api/hunts`, `/{id}` | 지급 |
| `news.read` | `GET /api/threat-news` | 지급 |
| `policy.read` | `GET /api/ticketing-policy` | 지급 |
| `policy.update` | `PUT /api/ticketing-policy` | 없음 |
| `user.read` | `GET /api/users`, `GET /api/permissions` | 없음 |
| `user.approve` | 가입 승인·거절, 비활성화, 비밀번호 재설정 | 없음 |
| `user.role` | 역할 변경 | 없음 |
| `user.permission` | 권한 부여·회수 | 없음 |
| `incident.approve`, `incident.reject`, `incident.close` | 적용 라우트 없음. 이름만 정의(Case로 확정 / 반려·재분석 / 위협 아님 종결) | 없음 |

- 기본 지급: 가입 승인 때 조회 권한 9개(`dashboard`·`alert`·`event`·`ticket`·`incident`·`case`·`hunt`·`news`·`policy`의 `.read`)를 `user_permissions`에 복사한다. 이후 admin이 사용자별로 더하고 뺀다. 나중에 조회 API가 생기면 마이그레이션이 기존 analyst에게 기본 조회 권한을 넣어 준다(빠뜨리면 접근이 닫히는 쪽으로 실패한다).
- 권한 없이 로그인만 필요한 API: `/api/auth/me`, `/logout`, `/password`, `/api/openapi.json`.
- 승인류 3개는 후속 승인 API 이슈가 라우트에 `require_permission(...)`을 붙이면 효력이 생긴다. 그때까지 부여해도 할 수 있는 일이 없다는 점을 notes에 적는다.
- 권한 상승 방지(사용자 관리 규칙):
  1. admin 계정을 대상으로 하는 작업(비활성화·비밀번호 재설정·역할 변경)은 admin만 한다.
  2. admin 역할 지정(승인 때 포함)은 admin만 한다.
  3. 권한은 부여자가 가진 권한만 남에게 줄 수 있다.
  4. 자기 자신의 권한은 바꿀 수 없다.
  5. 마지막 admin 보호를 유지한다.
- SIEM 설정 API는 만들지 않는다(권한도 만들지 않는다). 그 이슈가 `require_permission`으로 권한을 더한다.
- `FastAPI(openapi_url=None)`로 앱 바로 아래 `/openapi.json`을 없애고, `/api/openapi.json`(`include_in_schema=False`)을 로그인만 요구하는 라우트로 둔다. 타입 생성은 HTTP로 가져오지 않으므로 영향이 없다.
- CSRF: 앱 전체 미들웨어가 POST/PUT/PATCH/DELETE의 `Origin`을 허용 목록과 비교하고 없거나 다르면 403 `origin_not_allowed`로 거부한다(로그인·가입 포함).

### API 경로

- 인증: `POST /api/auth/login`, `/logout`, `/signup`, `/password`, `GET /api/auth/me`.
- 사용자 관리(권한별, 위 표): `GET /api/users`(상한 있는 전체 목록, `status` 거르기, `permissions` 포함), `POST /api/users/{id}/approve`(역할 지정)·`reject`·`disable`·`reset-password`, `PATCH /api/users/{id}`(역할), `PUT /api/users/{id}/permissions`(전체 교체), `GET /api/permissions`(권한 목록). `GET /api/auth/me`에도 `permissions`를 담는다. 알 수 없는 권한 이름은 422 `invalid_body`다.
- 오류 코드(`errors.py`에 추가): 401 `unauthenticated`·`invalid_credentials`, 403 `forbidden`·`permission_denied`·`password_change_required`·`origin_not_allowed`·`account_pending`·`account_rejected`·`account_disabled`, 409 `username_taken`·`last_admin`.
- 로그인 실패는 아이디 없음과 비밀번호 틀림에서 같은 401 `invalid_credentials`다. 비밀번호가 맞을 때만 계정 상태 코드를 낸다.
- 가입 때 이미 있는 아이디(거절·비활성 포함)는 409 `username_taken`이고, 거절된 아이디는 재신청할 수 없다.

### 설정

`config/default.toml`에 `[auth]`를 더한다: `idle_timeout_seconds = 3600`, `absolute_timeout_seconds = 43200`, `cookie_name = "soc_session"`, `cookie_secure = false`, `allowed_origins = ["http://127.0.0.1:5173", "http://localhost:5173"]`. `ApiSettings`에 값을 더하고 범위를 검사한다. 새 환경변수는 없다.

### 테스트

- 샘플은 `tests/fixtures/`에 손으로 만든다. 테스트 비밀번호는 `test-only-…` 같은 명백한 가짜 값이다. 임시 비밀번호는 표준 출력 캡처에서 변수로만 쓰고 단언 메시지에 넣지 않는다.
- DB 없는 기존 API 테스트는 `current_user` 의존성을 오버라이드해 사용자와 권한을 주입한다.
- 인증·세션·승인·권한·동시 시작·마지막 admin 동시성은 `db` 마커 테스트에서 실제 로그인으로 검증한다. 권한별 200/403 표, 부여·회수의 즉시 반영, admin의 암묵적 전체 권한, 기본 지급(조회 9개), 역할 변경 때 권한 초기화, 권한 상승 방지 5규칙을 확인한다.
- 승인 라우트가 없으므로 `require_permission`은 테스트 전용 임시 라우트로도 검증한다.
- 모든 `APIRoute`가 공개 허용 목록에 있거나 `require_login`/`require_permission`을 가졌는지, 카탈로그의 모든 권한이 어떤 라우트에 쓰이는지(승인류 3개만 예외 목록) 보는 구조 테스트(DB 없음)를 둔다.
- `tests/test_api.py`의 라우트 목록 테스트는 의도(조회 라우터는 읽기 전용)를 유지하면서 hunts·threat-news·UI 조회 라우터 범위로 좁히고, 앱 전체 경로 집합과 OpenAPI 경로의 기대값을 새 라우터를 포함하도록 고친다. `/openapi.json` 예외 단언을 `/api/openapi.json`으로 바꾼다. 405를 기대하는 테스트는 로그인한 클라이언트와 허용 `Origin` 헤더로 보낸다. 테스트를 지우거나 건너뛰지 않는다.

### 문서

- `docs/security.md`: "비밀 값" 절의 해시 라이브러리·최초 관리자 전달 두 줄을 확정 내용으로 바꾸고, "화면" 절에 인증·세션·CSRF·역할을 적는다.
- `docs/decisions.md`: D-020(권한 층 포함), D-047, D-042, D-043, 기록을 고쳤다.
- `docs/notes/284-auth-roles.md`: 개발 기록, 권한 목록과 기본 지급, 화면용 응답 모양(로그인, 내 정보와 `permissions`, 오류 코드), 승인류 권한은 적용 라우트가 생기기 전까지 효력이 없다는 설명, "배포 전 결정 사항"(로그인 시도 제한, 가입 폭주, 아이디 열거, 표준 출력 수집으로 임시 비밀번호가 로그 시스템에 남는 위험, 프록시 뒤 `Origin`·`Secure`, admin 전원 잠김 복구).

## 바꿀 곳

- `pyproject.toml`, `uv.lock`: `argon2-cffi==25.1.0`
- `src/soc/db/migrations/0005_auth.sql`: `users`, `user_sessions`, `user_permissions`
- `src/soc/auth/`(새 폴더): 비밀번호 해시, 사용자·세션·권한 SQL, 권한 카탈로그, 최초 관리자 생성
- `src/soc/api/auth.py`(새 파일): `require_login`, `require_permission`, `require_role`(admin 전용), CSRF 미들웨어
- `src/soc/api/routes/auth.py`, `src/soc/api/routes/users.py`(새 파일), 요청·응답 모델
- `src/soc/api/app.py`: 공개·보호 라우터 조립, `openapi_url=None`, CSRF 미들웨어, 머리말
- `src/soc/api/routes/{dashboard,records,workflow,hunts,threat_news,ticketing_policy}.py`: 라우트마다 `require_permission`. `ticketing_policy.py` 머리말과 docstring의 "인증 없음" 문구는 정리한다
- `src/soc/api/__main__.py`: `ensure_first_admin()` 호출
- `src/soc/api/config.py`, `config/default.toml`: `[auth]`. `[api] host` 주석 갱신
- `src/soc/api/errors.py`: 인증 오류 코드와 본문 검증 오류 처리
- `src/soc/api/db.py`: 머리말 갱신
- `tests/`: 기존 API 테스트의 인증 주입, 라우트 목록 테스트, 새 테스트, `tests/fixtures/`
- `docs/security.md`, `docs/notes/284-auth-roles.md`
- 새 응답 모델이 TypeScript 생성 대상이면 `frontend/src/api/generated/`(개발 첫 단계에서 확인)

## 다른 코드와 맞물리는 곳

- 공통 영역: API 앱 조립(`app.py`), 마이그레이션 `0005`, `ApiSettings`·`[auth]` 설정 키, `errors.py` 오류 코드. 팀원 전원이 승인한다.
- 화면용 API 전체가 로그인 없이는 401이다. 현재 화면(`frontend/`)은 로그인 화면이 생기기 전까지 동작하지 않으므로 로그인 화면 이슈와 머지 순서를 팀과 맞춘다.
- `/openapi.json` 경로가 `/api/openapi.json`으로 바뀌고 인증이 필요하다.
- 권한 이름 17개는 후속 이슈(승인 API, SIEM 설정 등)가 `require_permission`으로 쓰는 약속이다. 이름을 바꾸거나 더할 때는 카탈로그와 기본 지급을 함께 고친다.
- 데이터 계약(`contracts/`), `ids.py`, 에이전트 DB 읽기 역할은 바꾸지 않는다.

## 범위 밖

- 로그인·회원가입·비밀번호 변경 화면
- 로그인 시도 제한, 가입 폭주 방어(노트의 "배포 전 결정 사항"으로 남긴다)
- SIEM 설정 화면과 그 API
- 외부 로그인(SSO), 다단계 인증
- 헬스체크 라우트
- 승인 API(Incident 승인·반려·종결 라우트와 상태 전이, Case 생성), SIEM 설정 권한
- admin 전원이 잠겼을 때의 복구 수단(콘솔 CLI 등)

## 완료 기준

- [ ] 최초 시작 때 admin이 하나만 만들어지고 임시 비밀번호는 콘솔에만 1회 나온다(동시 시작 테스트 포함, `db` 마커)
- [ ] 임시 비밀번호로 로그인하면 비밀번호 변경 전까지 다른 API가 403이고, 변경 후에는 정상 동작한다
- [ ] 가입 → pending 상태에서 로그인 불가 → admin 승인(역할 지정) → 로그인 가능. 거절·비활성화·역할 변경·관리자 재설정이 동작한다
- [ ] 마지막 admin의 강등·비활성화가 거부되고, 두 admin이 동시에 서로를 내려도 admin이 0명이 되지 않는다(`db` 마커)
- [ ] 유휴·절대 만료, 비밀번호 변경 시 다른 세션 만료, 비활성화·역할 변경 시 세션 즉시 만료가 테스트로 확인된다
- [ ] 쿠키 속성(HttpOnly, SameSite=Lax)과 Origin 검사(없음·불일치 거부, 허용 시 통과) 테스트가 있다
- [ ] 로그인 실패 응답이 아이디 없음과 비밀번호 틀림에서 같고, 계정 상태 안내는 비밀번호가 맞을 때만 나온다
- [ ] 권한 테스트: 비로그인 401, analyst는 기본 지급에 없는 권한의 API(정책 변경, 사용자 관리)가 403, analyst가 L3 조회 200, admin은 전부 200 (L3 조회, 정책 API, 사용자 관리 각각)
- [ ] admin이 사용자별로 권한을 부여·회수하면 다음 요청부터 바로 적용된다(조회 권한 회수 포함). 승인류 3개도 부여·회수할 수 있다
- [ ] 권한 상승 방지 5규칙이 테스트로 확인된다(admin 대상 작업은 admin만, admin 역할 지정은 admin만, 가진 권한만 부여, 자기 권한 변경 불가, 마지막 admin 보호)
- [ ] 가입 승인 때 analyst가 기본 조회 권한 9개를 받고, 역할 변경 때 권한이 초기화된다
- [ ] 모든 라우트가 공개 목록에 있거나 인증·권한 의존성을 가졌고, 카탈로그의 권한이 라우트에 쓰이는지(승인류 3개만 예외) 보는 구조 테스트가 있다
- [ ] 라우트 목록 테스트가 hunts·threat-news 범위로 좁혀진 채 통과하고, 지우거나 건너뛴 테스트가 없다
- [ ] `soc_agent_reader`가 `users`·`user_sessions`·`user_permissions`를 읽지 못한다
- [ ] 비밀번호·세션 토큰이 로그, 응답, 테스트 출력, notes, PR에 없다
- [ ] 결정 목록(D-020 확정, D-047 추가, D-042·#246 기록 정리)과 `docs/security.md`가 갱신됐다
- [ ] `docs/notes/`에 권한 목록·기본 지급, 화면용 응답 모양(로그인, 내 정보와 `permissions`, 오류 코드), "배포 전 결정 사항"이 있다
- [ ] 공통 영역(API 앱, 마이그레이션, 설정 키, 오류 코드)을 건드리므로 팀원 전원이 승인한다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `db` 테스트 통과
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록

## 토론으로 정한 것

원래 이슈와 달라지거나 이슈가 정하지 않아 계획에서 정한 것이다.

- 이슈 권한 표에 없던 기존 조회 라우트(dashboard, alerts, events, tickets, incidents, cases)도 조회 권한을 갖고 analyst 기본 지급에 들어간다. 이슈 표는 hunts·threat-news·ticketing-policy만 적었는데, #266·#274로 앱에 이 라우트들이 붙어 있다. 기본 거부에서 권한이 없으면 개발할 수 없다.
- 정책 조회(`GET /api/ticketing-policy`)는 기본 조회 권한(`policy.read`)에 들어간다. 이슈는 변경만 admin이라고 적었다.
- **권한 층을 더했다(이슈 본문에 없던 확장).** admin이 사용자별로 권한을 부여·회수한다(IAM식). 역할 위계 검사(`require_role("analyst")` = analyst 이상) 대신 라우트마다 `require_permission`을 쓰고, analyst는 가입 승인 때 조회 권한 9개를 기본으로 받는다. 조회 권한도 회수할 수 있다.
- **위임 범위는 구현된 API 전부다.** 사용자 관리·정책 변경까지 권한으로 쪼개 위임한다. 계획 작성자의 추천은 승인류만 위임하는 안이었다(사용자 관리 권한을 받은 사람이 스스로 권한을 키울 수 있기 때문). 사용자가 전부 위임을 정했고, 위험은 권한 상승 방지 5규칙으로 줄인다.
- 승인류 권한 `incident.approve`·`incident.reject`·`incident.close` 이름을 지금 정의한다. 적용할 승인 라우트가 아직 없어 라우트는 후속 이슈가 붙인다. 제안 채택·기각(`proposal.decide`)은 기능이 없어 넣지 않는다. "케이스 승인"은 Incident를 Case로 확정하는 `incident.approve`로 본다.
- 로그인 화면 없이 머지하면 현재 화면이 전부 401이다. 인증을 끄는 개발 모드는 만들지 않고, 로그인 화면 이슈와 머지 순서를 팀과 맞춘다.
- 사용자 식별자는 `username` + `display_name`이다(이메일 아님). `users.id`는 계약 밖 UUID이고 `ids.py`·`contracts/`는 바꾸지 않는다.
- 비밀번호 분실 복구는 관리자 재설정 API다. 관리자가 임시 비밀번호를 본문에 넣고 응답에는 비밀번호가 없다(완료 기준 "응답에 비밀번호 없음"과 맞추기 위해). admin 전원이 잠기는 경우는 범위 밖이다.
- `/openapi.json`은 `/api/openapi.json`으로 옮겨 인증을 건다.
- 가입 중복 아이디는 409 `username_taken`이고 거절된 아이디는 재신청할 수 없다. 아이디 열거 위험은 노트에 남긴다.
- 기존 API 테스트는 DB 없는 쪽은 의존성 오버라이드, 인증 동작은 `db` 마커 실제 로그인으로 나눈다.
- 이슈가 "계획에서 제안"하라고 한 항목: 기본 거부 + 공개 라우트 목록 방식, 허용 Origin 기본값(Vite 개발 서버 두 주소), 쿠키 이름 `soc_session`, API 경로 모양, 라우트 목록 테스트를 좁히는 방식.
- D-042의 "인증이 생기면 다시 정한다"는 기본 바인딩 127.0.0.1을 유지하고 설정으로 바꾸는 것으로 닫았다.
- 이슈는 라우트 목록 테스트가 "GET 이외 메서드가 앱에 없다"를 본다고 썼지만, 현재 테스트는 이미 `ticketing-policy`의 PUT을 예외로 두고 앱 전체 경로 집합과 OpenAPI 경로를 정확히 비교한다. 새 라우터가 생기면 이 비교가 깨지므로 기대값을 함께 고친다.

## 바뀐 점

- 2026-11-10 · 권한 17개에서 `user.role`을 뺀 16개로 바꿨다. 역할 변경(`PATCH /api/users/{id}`)은 권한이 아니라 admin 역할 전용이다(non-admin이 `user.role`로 할 수 있는 일이 없었다). 사용자 결정.
- 2026-11-10 · `GET /api/users`는 "상한 있는 전체 목록" 대신 `limit`·`cursor`로 나눠 준다(500명 초과 시 조용히 잘리는 것을 막는다).
