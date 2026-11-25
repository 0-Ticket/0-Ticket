---
issue: 297
date: 2026-11-25
owner: Interludeal
plan: 297-default-mode.md
supersedes: []
---

# Ticket 생성 모드 auto를 default로 바꿨다 (모드 값만, origin은 그대로)

## 한 일

Ticket 생성 정책의 기본 모드 이름이 `auto`에서 `default`가 됐다. 설정(`[ticketing] mode`), 백엔드(`POLICY_MODES`, `l1/ticketing.py`의 분기), 정책 API(`TicketingPolicyBody.mode`), DB(`ticketing_policy`), 정책 화면(라벨 "기본 (default)")이 모두 `default`를 쓴다. 동작은 그대로다. 판단 없이 모든 Alert를 Ticket으로 만든다(D-033).

DB는 새 마이그레이션 `0110_ticketing_policy_default.sql` 하나로 바꾼다. `LOCK TABLE` → 모드 CHECK 제거 → `UPDATE ... WHERE mode = 'auto'` → 새 CHECK 추가 순서다. 실행기(`soc.db.migrate`)와 적용한 0104·0001은 고치지 않았다.

옛 값 `auto`는 거부한다. 설정 파일·`parse_policy`는 `ConfigError`로, API는 422로, DB는 CHECK로 거부한다. `python -m soc.l1.ticketing`은 이제 `ConfigError`의 고정 문구("[ticketing] mode는 default 또는 scenario여야 한다(옛 값 auto는 default로 바꾼다)")를 stderr로 보여 주고 종료 코드 2로 끝난다. `OSError`·`TOMLDecodeError`는 지금처럼 타입 이름만 보여 준다.

Ticket 출처 `origin = 'auto'`(D-026)는 바꾸지 않았다. default 모드가 만든 Ticket의 `origin`은 계속 `auto`다.

## 계획과 달라진 점

- 계획의 `rg` 허용 목록에는 `l1/ticketing.py`의 "origin 결정"만 있었는데, `_existing_ticket`의 `origin IN ('auto', 'scenario', 'l1')`(208줄)도 origin이라 남는다. 같은 종류라서 목록을 고치지 않고 여기에 적는다.
- `tests/test_lab_cycle_db.py`의 상수 `AUTO`를 `DEFAULT_POLICY`로 바꿨다(값이 `default`라서).
- 옛 값 `auto`를 가진 로컬 설정 테스트는 처리할 Alert 1건 + 활성 DB 정책 행 없음 + `local.toml`의 `mode = "auto"`로 만들었다(`test_one_shot_command_tells_to_replace_the_old_auto_mode_in_local_toml`). `run()`은 후보가 있고 활성 DB 정책이 없을 때만 TOML을 읽기 때문이다.
- 옛 값 `local.toml`의 `main()` 테스트는 계획에는 `tests/test_ticketing.py`로 적었지만 DB가 필요해서 `tests/test_ticketing_db.py`에 있다.
- 계획 6번의 "Alert는 정책 오류로 집계된다"는 `soc.l1.ticketing` CLI에는 맞지 않는다. 활성 DB 행이 옛 값이면 CLI는 집계 없이 `ConfigError`로 종료 코드 2가 된다(아래 "다음 사람이 알아야 할 것"). 동작은 바꾸지 않았고 설명만 정정한다.
- 그 밖에는 없음.

## 다음 사람이 알아야 할 것

- **배포 순서.** 파이프·API·`python -m soc.l1.ticketing`을 멈춘다 → pull → `uv run python -m soc.db.migrate` → 재시작. 새 코드가 DB의 `auto`를, 옛 코드가 `default`를 읽으면 `ConfigError`가 난다. 이때 Ticket은 만들어지지 않고 Alert는 다음 실행에서 다시 집힌다(데이터는 안전하다). 아래 "DB에 옛 `auto` 행이 남으면"을 본다. 0110은 `ticketing_policy`를 ACCESS EXCLUSIVE로 잠그므로 실행 중인 정책 읽기·쓰기를 기다리게 한다.
- 기존 DB에서는 0110이 가장 큰 적용 번호(0306 등)보다 작아서 실행기가 "작지만 적용한다" 경고를 stderr에 낸다. 해롭지 않다(D-035).
- **DB에 옛 `auto` 행이 남으면**(0110을 적용하지 않은 채 새 코드를 돌리면) `read_active_policy`가 `parse_policy`의 `ConfigError`를 낸다. 두 경로가 다르다. (1) `python -m soc.l1.ticketing`처럼 정책을 넘기지 않고 후보가 있으면 `run()`이 루프 앞(`l1/ticketing.py` 111줄)에서 `read_active_policy`를 불러 `ConfigError`가 `main()`까지 올라가고, 안내 문구와 종료 코드 2로 끝난다. Ticket은 만들어지지 않는다. (2) 정책(`fallback`)을 넘겨 호출하거나 실행 도중 행이 바뀌면 Alert별 `except`가 잡아 `failures["policy_error"]`로 집계하고 종료 코드는 1이다. 후보가 0건이면 어느 쪽도 정책을 읽지 않는다. 이 동작은 코드를 읽고 정리한 것이고 DB 테스트로 확인하지 않았다.
- **`run()`은 후보가 0건이면 TOML을 읽지 않는다.** 그래서 옛 `local.toml`이 있어도 처리할 Alert가 없는 동안에는 오류가 나지 않고, 처음 Alert가 생긴 실행에서야 종료 코드 2와 안내 문구가 나온다. 활성 DB 정책 행이 있으면 `local.toml`은 읽지 않으므로 옛 값이 있어도 오류가 없다.
- 팀원은 `config/local.toml`(git에 올라가지 않음)에 `mode = "auto"`가 있으면 `"default"`로 고쳐야 한다. PR 본문에서 사람이 전달한다.
- `GET /api/ticketing-policy`가 옛 값이 든 `local.toml`에서 500이 될 수 있다. 코드를 읽고 짐작한 것이고 실행해 확인하지 않았다. 범위 밖이라 고치지 않았다.
- `design/0-Ticket.pen`의 모드 라벨 두 곳(14445, 14481줄 근처, "자동 (auto)")은 사람이 같은 PR에서 "기본 (default)"로 고친다. 전·후 스크린샷도 사람이 붙인다(D-075). `.pen`은 건드리지 않았다.
- Ticket `origin = 'auto'`를 `default`로 바꾸는 것은 별도 이슈다. 공통 계약, `tickets` 테이블 잠금과 CHECK, 부분 유일 인덱스 이름, L1 판정 입력(`l1/judge.py`), 샘플, D-026 변경이 따라오고 L1·L2·L3 담당 전원 승인이 필요하다.
- 새 DB 테스트(`tests/test_ticketing_policy_migration_db.py`)는 CHECK 이름 `ticketing_policy_mode_check`와 정의 `CHECK ((mode = ANY (ARRAY['default'::text, 'scenario'::text])))`를 정확히 비교한다. 정의 문자열은 사람이 PostgreSQL에서 확인한 `pg_get_constraintdef` 출력이다. 이 환경에서는 실행하지 못했다.
- `test_ticketing_db.py::test_migration_refuses_existing_multi_alert_w04_ticket_without_rewriting`는 0104뿐 아니라 0110도 빼고 복사한다. 0110은 `ticketing_policy`가 있어야 적용된다.
- Windows에서 `uv run pytest`는 `read_text()`에 인코딩이 없는 테스트 때문에 수집에서 cp949 오류가 난다. `PYTHONUTF8=1`을 붙이면 통과한다(이번 변경과 무관, 이미 있던 것).
- 이 PC에서 `pnpm lint`의 `prettier --check .`는 CRLF 때문에 건드리지 않은 파일 51개도 지적했다. `--end-of-line auto`로 보면 내 변경 파일만 서식 문제가 있었고 고쳤다. CI(LF)에서는 영향이 없을 것으로 본다.

## 확인 방법

- 테스트를 먼저 바꾸고 구현 전에 실패를 확인했다. `tests/test_ticketing.py`(기본 정책이 `default`가 아님으로 실패), `frontend/src/policy.test.tsx` 2건 실패.
- `uv run ruff format .`, `uv run ruff check .`: 통과.
- `PYTHONUTF8=1 uv run pytest`: 2696 passed(기본 실행, `db` 마커 제외).
- `frontend/`: `pnpm contracts`로 `TicketingPolicyResponse.ts`만 다시 생성(`Mode`가 `"default" | "scenario"`). `pnpm contracts:check` 36개 일치, `pnpm test` 10개 파일 131건 통과, `pnpm build` 성공. `eslint .` 오류 0(경고 1건은 `flow-chart.tsx`의 기존 경고).
- **`uv run pytest -m db`는 이 PC에서 돌리지 않았다**(PostgreSQL이 없고 Docker Desktop도 실행되지 않는다). 사람이 외부 환경(PostgreSQL 16, 커밋 `a53dbce` 기준)에서 돌렸다. 결과는 673 passed, 2 failed다. 실패 2건은 `tests/test_l2_branch_db.py`의 qdrant 마커 테스트(`test_branch_reindex_detects_missing_point_and_recovers`, `test_vector_candidate_uses_current_incident_and_rejects_stale_payload`)이고 원인은 `QDRANT_URL` 없음이다. 이 브랜치는 그 파일과 `src/soc/l2`, `src/soc/store`를 바꾸지 않았다. `tests/test_ticketing_policy_migration_db.py` 5건, `tests/test_ticketing_db.py`, `tests/test_db_tables.py`는 115건이 모두 통과했고 CHECK 이름·정의 정확 비교도 통과했다. 0110 SQL과 바꾼 DB 테스트, `legacy_dir` 계열 테스트가 이 결과에 들어 있다. 이 기록을 쓰는 사람이 직접 확인한 것이 아니라 그 결과를 받아 적은 것이다.
- **CI에서 최종 확인한다.** CI(PostgreSQL 17.6, `db or qdrant`)에서 위 qdrant 2건을 포함해 다시 확인한다. 외부 환경의 PostgreSQL은 16이고 CI는 17.6이라 `pg_get_constraintdef` 출력이 달라지지 않는지도 CI에서 본다.
- 마무리 때 이 PC에서 다시 돌린 것: `uv run ruff format --check .`, `uv run ruff check .`, `PYTHONUTF8=1 uv run pytest`(2696 passed, 716 deselected), 프론트 `pnpm contracts:check`(36개 일치), `eslint .`(오류 0), `pnpm test`(131건), `pnpm build`. `prettier`는 CRLF 때문에 이 PC에서 전체 검사가 의미 없어 내가 바꾼 8개 파일만 `--end-of-line auto`로 확인했고 통과했다. 생성 파일을 `git checkout`으로 되돌리면 CRLF가 되어 `contracts:check`가 실패하는 일이 이 PC에서 있다(`pnpm contracts`로 다시 만들면 일치한다).
- `rg -n "\"auto\"|'auto'" src frontend/src config` 결과는 계획의 허용 목록과 같다: `0001`·`0104`(적용한 파일), `0110`(옛 값을 바꾸는 SQL), 생성 코드의 origin, `l1/ticketing.py`의 origin 결정과 `_existing_ticket`, `ui_models.py`, `list-view.tsx`. 모드를 뜻하는 `auto`는 없다. `tests`에 남은 것은 origin 값과, 옛 값을 거부하는지 확인하는 테스트뿐이다.
