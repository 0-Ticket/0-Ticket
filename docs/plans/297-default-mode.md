---
issue: 297
date: 2026-11-25
owner: Interludeal
supersedes: []
---

# Ticket 생성 모드 auto → default 명칭 변경

## 목표

Ticket 생성 정책의 기본 모드 이름을 `auto`에서 `default`로 바꾼다. 설정·백엔드·DB·API·UI의 모드 값과 표시 이름이 모두 `default`가 되고, 동작은 그대로다(판단 없이 모든 Alert를 Ticket으로 만든다, D-033). Ticket 출처 `origin = 'auto'`는 이번에 바꾸지 않는다.

## 방법

1. **테스트 먼저.**
   - 기존 테스트의 모드 값을 `default`로 바꾸고, 바꾸기 전에 실패하는 것을 확인한다(`tests/test_ticketing.py`, `tests/test_ticketing_db.py`, `tests/test_auth.py`, `tests/test_auth_db.py`, `tests/test_lab_cycle_db.py`, `tests/test_ticket_title_db.py`, `tests/normalize/test_alert_skeleton_db.py`, `frontend/src/policy.test.tsx`, `App.test.tsx`, `test-utils.tsx`). 샘플은 기존 `tests/fixtures/ticketing/alerts.json` 등을 그대로 쓴다.
   - `tests/test_ticketing_db.py:213,215`는 `'auto'`로 넣고 CheckViolation을 기대한다. 마이그레이션 뒤에도 통과하지만 id·NULL 원소 CHECK가 아니라 모드 CHECK 때문이 된다. `'default'`로 바꾸고, `'manual'` 옆에 `'auto'` 거부 케이스를 더한다.
   - 새 DB 테스트(`tests/test_ticketing_policy_migration_db.py`). 0110만 빼고 적용한 DB(`tests/test_ticket_title_db.py`의 `legacy_database` 방식)에 `auto` 행을 넣고 0110을 적용해, 그 행이 `default`가 되는지, `scenario` 행이 그대로인지, `auto` 삽입이 CheckViolation인지 확인한다. 적용 후 `pg_constraint`에서 `ticketing_policy` 모드 CHECK의 이름(`ticketing_policy_mode_check`)과 정의(`CHECK (mode IN ('default', 'scenario'))`)를 고정한다.
   - `tests/test_ticketing.py`에 `main()`이 옛 값 `auto`가 든 `local.toml`에서 오류 문구(default 안내)를 stderr로 내는 테스트를 더한다.
2. **백엔드.**
   - `config/default.toml`: `mode = "default"`.
   - `src/soc/ticketing.py`: `POLICY_MODES = frozenset({"default", "scenario"})`. 오류 문구는 "[ticketing] mode는 default 또는 scenario여야 한다(옛 값 auto는 default로 바꾼다)".
   - `src/soc/l1/ticketing.py`: `_process_alert`의 모드 비교를 `"default"`로 바꾼다. 만드는 Ticket의 `origin`은 계속 `"auto"`이고, 한 줄 주석으로 "origin auto는 default 모드가 만든 Ticket이다(D-026)"를 남긴다. `main()`은 `ConfigError`만 따로 잡아 고정 문구를 출력한다(`OSError`·`TOMLDecodeError`는 지금처럼 타입 이름만 출력한다. 경로나 값이 섞일 수 있다).
   - `src/soc/api/models.py`: `Literal["default", "scenario"]`.
3. **DB.** 새 `src/soc/db/migrations/0110_ticketing_policy_default.sql`(L1 대역 마지막 번호 0109의 다음). 실행기(`soc.db.migrate`)는 고치지 않고 SQL 파일 하나로 끝낸다. 0110이 아래 순서로 한다.
   1. `LOCK TABLE ticketing_policy IN ACCESS EXCLUSIVE MODE;`
   2. `ALTER TABLE ticketing_policy DROP CONSTRAINT ticketing_policy_mode_check;`
   3. `UPDATE ticketing_policy SET mode = 'default' WHERE mode = 'auto';`
   4. `ALTER TABLE ticketing_policy ADD CONSTRAINT ticketing_policy_mode_check CHECK (mode IN ('default', 'scenario'));`

   CHECK 이름은 마이그레이션한 DB의 `pg_constraint`에서 확인한 값이다. 이름이 다른 DB를 위한 분기는 만들지 않고, 새 DB 테스트가 0110 적용 후의 이름과 정의를 고정한다. 실행기가 파일마다 한 트랜잭션으로 적용하므로 1~4가 함께 적용되거나 함께 되돌려진다. 이미 적용한 0104와 0001은 고치지 않는다.
4. **프론트.**
   - `policy-page.tsx`: 라벨 "기본 (default)", 설명문 "수집된 모든 Alert를 Ticket으로 만들어요.", 값 `"default"`.
   - `flow-chart.tsx`·`dashboard.tsx`: `mode: "default" | "scenario"`와 주석.
   - `layout.tsx`: `policy.data?.mode ?? "default"`와 주석.
   - `frontend/src/api/generated/TicketingPolicyResponse.ts`는 API 모델에서 생성한다. `pnpm contracts`(`scripts/export_api_schemas.py`)로 다시 만든다.
5. **문서.** `docs/decisions.md` D-033의 모드 값과 설정 키 설명을 `default`로 고치고, 이 모드가 만든 Ticket의 `origin`은 `auto`임을 덧붙인다. "기록"에 한 줄을 더한다. 지난 plans·notes는 고치지 않는다.
6. **배포 순서**(개발 기록에도 적는다). 파이프·API·`soc.l1.ticketing`을 멈춘다 → pull → `uv run python -m soc.db.migrate` → 재시작. 새 코드가 DB의 `auto`를, 옛 코드가 `default`를 읽으면 `ConfigError`가 나서 Alert는 정책 오류로 집계되고 다음 실행에서 다시 집힌다(데이터는 안전하다). 기존 DB에서는 0110이 가장 큰 적용 번호보다 작아 "작지만 적용한다" 경고가 stderr에 나온다. 해롭지 않다.

## 바꿀 곳

- `config/default.toml`
- `src/soc/ticketing.py`, `src/soc/l1/ticketing.py`, `src/soc/api/models.py`
- `src/soc/db/migrations/0110_ticketing_policy_default.sql`(새 파일)
- `frontend/src/`: `policy-page.tsx`, `flow-chart.tsx`, `dashboard.tsx`, `layout.tsx`, `api/generated/TicketingPolicyResponse.ts`(재생성)
- `docs/decisions.md`: D-033과 "기록"
- `tests/`:
  - 모드 값: `test_ticketing.py`, `test_ticketing_db.py`, `test_auth.py`, `test_auth_db.py`, `test_lab_cycle_db.py`, `test_ticket_title_db.py`, `normalize/test_alert_skeleton_db.py`
  - 새 DB 테스트: `test_ticketing_policy_migration_db.py`
  - `test_db_tables.py`: 적용 목록의 0109와 0200 사이에 0110
  - `test_ticketing_db.py`의 `test_migration_refuses_existing_multi_alert_w04_ticket_without_rewriting`: 0104만 빼고 복사하던 루프에서 0110도 뺀다(0110이 `ticketing_policy` 없이는 실패한다)
  - 같은 방식의 다른 테스트(`tests/ingest/db/test_original_text_migration_db.py`, `tests/ingest/db/test_quarantine_db.py`, `tests/test_incident_recommendations_db.py`, `tests/test_l2_branch_db.py`, `tests/test_ticket_title_db.py`)는 `uv run pytest -m db`로 영향이 없는지 확인한다
- `frontend/src/`: `policy.test.tsx`, `App.test.tsx`, `test-utils.tsx`

## 다른 코드와 맞물리는 곳

- 설정 키 값 `[ticketing] mode`가 `auto`에서 `default`로 바뀐다. 팀원의 `config/local.toml`(git에 올라가지 않음)에 `mode = "auto"`가 있으면 `default`로 고쳐야 한다. 옛 값은 거부한다. 안내는 PR 본문에 적고 사람이 전달한다.
- `GET`·`PUT /api/ticketing-policy`의 `mode` 값이 바뀐다. `PUT`에 옛 값 `"auto"`를 보내면 422 `invalid_body`(`fields: ["mode"]`)다. 백엔드와 프론트는 한 PR이다.
- DB `ticketing_policy.mode`의 CHECK와 기존 행이 바뀐다(0110).
- `soc.l1.ticketing`의 stderr 출력: 설정 오류 때 `ConfigError`의 고정 문구가 더해진다.
- 바뀌지 않는 것: Ticket 계약(`contracts/ticket.schema.json`)과 `tickets.origin`, `origin` 값 `auto`를 읽는 L1 판정(`l1/judge.py:113`), L2·L3 코드. 이 이슈에서는 L1·L2·L3 담당 승인이 필요한 변경이 없다.

## 범위 밖

- Ticket 출처 `origin = 'auto'`를 `default`로 바꾸는 것. 계약·`tickets` 테이블·인덱스·L1 판정 입력·샘플 30여 곳·D-026 변경이 걸려 L1·L2·L3 담당 전원 승인이 필요하다. 별도 이슈로 올린다.
- `origin` 설명을 "auto: 기본(default) 모드로 생성"으로 고치는 것. 계약 파일과 생성 코드 세 곳이 바뀌므로 계약 담당과 합의가 있을 때만 한다. 이번 PR에는 넣지 않는다.
- 옛 값 `auto`를 한동안 받아 주는 호환.
- `GET /api/ticketing-policy`가 옛 값이 든 `local.toml`에서 500이 될 수 있는 문제(처리하지 않는다).
- 마이그레이션 실행기(`soc.db.migrate`) 수정, 이름이 다른 CHECK를 찾는 분기.
- `design/0-Ticket.pen`: 사람이 같은 PR에서 라벨 두 곳(모드 "자동 (auto)")을 "기본 (default)"로 고친다. 구현을 맡은 쪽은 `.pen`을 건드리지 않는다.

## 완료 기준

- [ ] 정책 화면에 "기본 (default)"로 표시되고, 저장하면 `PUT /api/ticketing-policy` 본문이 `{"mode": "default", ...}`이다
- [ ] `GET /api/ticketing-policy`가 DB 행이 없을 때 `mode: "default"`를 돌려준다
- [ ] 0110 적용 뒤 기존 `ticketing_policy` 행의 `'auto'`가 `'default'`로 바뀌고 `'auto'` 삽입은 CHECK로 거부된다
- [ ] 0110 적용 후 `pg_constraint`의 모드 CHECK 이름이 `ticketing_policy_mode_check`이고 정의가 `mode IN ('default', 'scenario')`다(DB 테스트가 고정)
- [ ] `default` 모드에서 `python -m soc.l1.ticketing`이 모든 Alert를 Ticket으로 만든다(기존 auto 동작과 같음). 만든 Ticket의 `origin`은 `auto`다
- [ ] 옛 값 `auto`가 든 `local.toml`이면 `python -m soc.l1.ticketing`이 default 안내 문구를 출력하고 종료 코드 2다
- [ ] 모드를 뜻하는 `auto` 식별자·문자열이 백엔드·프론트·설정에 없다. `rg -n "\"auto\"|'auto'" src frontend/src config`에 남는 것은 다음뿐이다: 적용한 `0001`·`0104`, `0109`의 주석, `0110`(옛 값을 바꾸는 SQL), `src/soc/contracts/generated/`와 `frontend/src/api/generated/`의 origin 부분, `l1/ticketing.py`의 origin 결정, `ui_models.py`, `list-view.tsx`
- [ ] `TicketingPolicyResponse.ts`가 `pnpm contracts`로 다시 생성되고 `pnpm contracts:check`가 통과한다
- [ ] 질문 1·2·3의 결정과 배포 순서가 `docs/notes/`에 기록된다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run pytest -m db`가 통과한다
- [ ] `frontend/`에서 `pnpm contracts:check`, `pnpm lint`, `pnpm test`, `pnpm build`가 통과한다
- [ ] 사람이 전·후 스크린샷을 PR에 붙이고 `.pen` 라벨을 고친다(D-075)

## 토론으로 정한 것

이슈 본문에서 정하지 못한 것과 달라진 점이다.

- **origin 범위: 바꾸지 않는다(C).** 모드 값만 `default`로 바꾸고 origin `auto`는 둔다. 이유: origin까지 바꾸면 공통 계약, `tickets` 테이블 잠금, L1 판정 입력 변경, 샘플 30여 곳, D-026 변경(L1·L2·L3 전원 승인)이 따라와 "간단한 후순위"를 넘는다. 이 모드를 오해하는 문제는 모드 이름만 바꿔도 대부분 풀린다. 원하는 사람이 별도 이슈로 올린다. D-026은 이미 "`auto`(기본 모드)"라서 고치지 않는다.
- **옛 값 `auto`: 거부한다(a).** 이슈 본문에 없던 것: `main()`이 `ConfigError`의 고정 문구를 출력한다. 이유: 지금은 `main()`이 타입 이름만 출력하고 `run()`은 건수만 집계해서, 오류 문구에 안내를 넣어도 팀원에게 닿지 않는다. `ConfigError` 문구는 값이 없는 고정 문장이라 출력해도 안전하다. `(b)`는 코드와 생성 타입에 옛 값이 남고 제거 시점을 따로 정해야 한다.
- **`.pen`: 사람이 같은 PR에서 고친다.** 이유: 디자인 도구 밖에서 `.pen`을 손으로 고치는 것이 위험하고, 디자인과 화면이 어긋난 채 머지되는 것을 막는다.
- **0110 구현.** 사용자가 정했다: 실행기는 고치지 않고 SQL 파일 하나로 끝낸다. 순서는 `LOCK TABLE` → CHECK 제거 → `UPDATE` → CHECK 추가이고 CHECK 이름은 `ticketing_policy_mode_check`다. 이름이 다른 DB를 위한 `DO` 블록은 두지 않고 새 DB 테스트가 0110 적용 후의 이름과 정의를 고정한다.
- 이슈 본문의 테스트 목록에 `test_auth.py`, `test_auth_db.py`, `test_lab_cycle_db.py`, `test_ticket_title_db.py`, `normalize/test_alert_skeleton_db.py`, `test_db_tables.py`와 새 DB 테스트를 더했다(모드 값 사용처를 `rg`로 찾은 결과).
- 정책 화면 설명문은 "수집된 Alert에 대해 Ticket을 자동으로 만들어요."에서 "수집된 모든 Alert를 Ticket으로 만들어요."로 바꾼다. 라벨이 "기본"이 되면 "자동으로" 문구가 이름과 어긋난다.
- 완료 기준에 `pnpm contracts:check`(생성 타입), `rg` 검사의 허용 남는 곳, `pg_constraint` 고정, `.pen`과 스크린샷을 더했다.

## 바뀐 점
