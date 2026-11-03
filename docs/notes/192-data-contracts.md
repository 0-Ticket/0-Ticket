---
issue: 192
date: 2026-11-03
owner: Pandyo
plan: 192-data-contracts.md
supersedes: []
---

# 공통 데이터 계약과 DB 테이블을 만들었다

## 한 일

- 단계끼리 주고받는 데이터 7가지(RawRecord, Alert, Event, Ticket, Incident, Case, Agent Log)와 공통 조각 3개(Entity, Asset, Verdict)의 계약을 `contracts/`에 JSON Schema(draft-07)로 만들었다.
- `scripts/generate_contracts.py`가 schema로 Pydantic v2 모델을 `src/soc/contracts/generated/`에 만든다. CI는 `--check`로 커밋된 생성 코드가 schema와 같은지 검사한다.
- `soc.contracts.validate_contract(name, data)`는 다음 순서로 검사한다.
  1. JSON Schema 검사
  2. schema로 쓸 수 없는 규칙(Event의 `ocsf_class`)
  3. 생성 모델로 변환

  틀리면 필드 경로와 어긴 규칙만 담은 `ContractError`를 낸다.
- `soc.ids.new_id(prefix)`는 접두사 + UUIDv7 ID를 만든다. `soc.contracts.to_datetime()`과 `to_epoch_ms()`는 계약의 밀리초와 DB의 `timestamptz`를 서로 바꾼다.
- `uv run python -m soc.db.migrate`는 `src/soc/db/migrations/`의 순번 SQL을 적용한다. 첫 파일 `0001_common_tables.sql`이 공통 테이블 7개를 만든다.
- CI에 생성 코드 차이 검사와 `db` job(PostgreSQL 17.6 서비스 컨테이너)을 추가했다. `docs/architecture.md`를 계획대로 고쳤다.

## 계획과 달라진 점

- 사람이 정한 변경 2건(jsonb의 JSON null 거부, OCSF 클래스별 검증은 정규화 이슈에서)은 계획 파일 "바뀐 점"에 있다.
- **공통 정의 파일 `contracts/common/types.schema.json`을 추가했다.** ID 패턴 9개, 시각, 심각도를 한 곳에 둔다. UUIDv7 정규식을 schema 20여 곳에 복사하지 않기 위해서다. 계약이 아니라서 `validate_contract()`의 이름으로는 쓸 수 없다.
- **생성 옵션을 이렇게 골랐다.**
  - `--use-type-alias`: 목록 안의 ID와 null 가능한 숫자가 RootModel 대신 일반 `str`·`int`로 나온다. 이 옵션이 없으면 `ticket.alert_ids[0]`이 RootModel이라 `.root`를 붙여야 했다.
  - `--enum-field-as-literal=all`: 목록 값이 Enum 클래스 대신 `Literal` 문자열로 나온다.
  - 생성 모듈 이름은 schema 파일 이름에서 나온다(예: `soc.contracts.generated.ticket_schema.Ticket`).
- **위반의 `rule` 이름은 JSON Schema 키워드다**(`required`, `enum`, `pattern`, `minItems` 등).
  - 상태 짝 규칙은 if/then으로 썼으므로, 어기면 `type`으로 나온다. 예: `pending`인데 verdict가 있으면 `triage.verdict: type`.
  - schema 밖 규칙의 이름은 `equals_ocsf_class`다.
- **함수 몇 개를 더 내보낸다.** `soc.contracts`는 `Violation`과 `CONTRACT_NAMES`도 내보낸다. 실행기에는 `find_migrations()`와 `MigrationError`가 있다.
- **테스트를 하나 더 넣었다.** 계약 밖 값을 DB CHECK 제약이 거부하는지 확인하는 `db` 테스트다. 완료 기준에는 없었다.

## 다음 사람이 알아야 할 것

- **DB에 쓰기 전에 `validate_contract()`를 거친다.** 생성 모델을 직접 만들면 if/then 규칙(상태 짝, `alert_ids` 개수)과 `ocsf_class` 비교를 검사하지 않는다. 모델이 있으면 `validate_contract(name, model.model_dump(mode="json"))`로 다시 확인한다. 반환 타입은 `BaseModel`이다.
- **DB가 JSON null을 거부하므로 SQL NULL을 넣어야 한다.** null이 될 수 있는 `alerts.triage`, `tickets.verdict`, `agent_logs.output`에 None을 쓸 때 psycopg `Jsonb(None)`을 넘기면 JSON null(`'null'::jsonb`)이 되어 CHECK 위반으로 거부된다. 값 None을 그대로 넘겨 SQL NULL로 넣는다. NOT NULL인 객체·목록 jsonb 컬럼도 JSON null을 거부한다. `agent_logs.input`만 JSON null을 받는다(계약상 JSON 값 전체). 변환 예시는 `tests/test_db_tables.py`의 `to_row()`에 있다.
- **schema를 고치면 생성 코드도 같이 커밋한다.** `uv run python scripts/generate_contracts.py`를 실행한 결과를 함께 올린다. 공통 계약 변경이라 L1·L2·L3 담당자 전원의 승인이 필요하다.
- **마이그레이션 실행기에는 잠금이 없다.** 같은 대역에서 두 사람이 같은 번호를 쓰면 실행기는 아무것도 실행하지 않고 실패한다. 머지 전에 번호를 확인한다. 실행기 두 개를 동시에 돌리면 막지 못한다.
- **마이그레이션 명령은 `.env`를 읽지 않는다.** `uv run --env-file .env python -m soc.db.migrate`처럼 환경변수를 넘긴다.
- **`db` 테스트에는 DB 생성 권한이 필요하다.** `DATABASE_URL` 계정으로 `soc_test_<랜덤>` DB를 만들고, 끝나면 `DROP DATABASE ... WITH (FORCE)`로 지운다. compose 계정과 CI 계정은 이 권한이 있다.
- **`validate_contract()`는 레포 루트 `contracts/`를 읽는다.** 레포 없이 wheel로만 설치하면 schema가 없어 `RuntimeError`가 난다. 배포 형태가 정해지면 바꾼다.
- **`new_id()`의 순서 보장은 한 프로세스 안에서만이다.** 프로세스끼리는 밀리초 단위까지만 맞는다.
- **`types.schema.json`이 생성 코드에 빈 별칭을 남긴다.** 정의만 있는 파일이라 아무도 쓰지 않는 `Types` 별칭이 생긴다. 무시해도 된다.
- **TypeScript 생성 코드는 아직 없다.** 첫 화면 이슈에서 붙인다.
- **OCSF 클래스별 검증은 정규화 이슈에서 반드시 한다.** 이 계약은 `ocsf`를 자유 객체로 두고 Alert의 `class_uid = 2004`와 Event의 `ocsf_class = ocsf.class_uid`만 검사한다. 정규화 결과의 `ocsf`는 해당 class_uid의 OCSF 1.9.0 공식 JSON Schema로 검증해야 하며, 쓰는 클래스마다(최소 Detection Finding 2004, Base Event 0, 매핑하는 이벤트 클래스) 공식 스키마 파일을 생성해 레포에 두고 검증한다(OCSF 정규화, D-007).
- **uv 버전에 주의한다.** `uv.lock`은 revision 3 형식이다. uv 0.12.23은 lock을 revision 5로 올려서, revision 3을 유지하는 uv 0.12.0(`uvx --from 'uv==0.12.0' uv lock`)으로 lock했다. 최신 uv(0.13.7)의 `uv lock --check`도 통과한다. 0.6처럼 오래된 uv로 `uv add`·`uv lock`을 하면 형식이 바뀔 수 있다.
- **예전 브랜치의 `__pycache__` 폴더가 import를 방해할 수 있다.** git이 무시하는 `src/soc/*/__pycache__`만 남은 폴더가 있으면, 소스가 없어도 `soc.l1` 같은 이름이 namespace package로 import된다. 이상하게 import되면 확인한다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run pytest`: 131개 통과(`db` 28개 제외). 주요 테스트:
  - `tests/test_contracts.py`: 올바른 샘플 33개가 통과하고, 모델로 바꿔도 필드가 빠지지 않는다. 틀린 샘플 47개는 기대한 경로·규칙으로 거부된다.
  - `tests/test_ids.py`, `tests/test_times.py`, `tests/test_migrate.py`
- `DATABASE_URL=<로컬 postgres:17.6 trust 컨테이너> uv run pytest -m db`: 28개 통과(`tests/test_db_tables.py`). 끝난 뒤 남은 임시 DB 0개. JSON null 거부 테스트는 CHECK를 넣기 전 SQL에서 실패하는 것을 확인했다
- `DATABASE_URL` 없이 `uv run pytest -m db`: 28개 오류(건너뛰지 않음)
- `uv run python scripts/generate_contracts.py --check`: 차이 없음. 생성 파일에 한 줄을 더하면 exit 1
- 빈 DB에 `uv run python -m soc.db.migrate`를 두 번 실행: 1개 적용 → "적용할 마이그레이션이 없다"
