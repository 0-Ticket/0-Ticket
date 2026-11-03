---
issue: 192
date: 2026-11-03
owner: Pandyo
plan: 192-data-contracts.md
supersedes: []
---

# 공통 데이터 계약과 DB 테이블을 만들었다

## 한 일

L1·L2·L3를 여러 사람이 동시에 개발하기 전에, 단계끼리 주고받는 데이터를 모두 같은 이름과 모양으로 쓰도록 공통 기반을 만들었다.

- 단계끼리 주고받는 데이터 7가지(RawRecord, Alert, Event, Ticket, Incident, Case, Agent Log)와 공통 조각 3개(Entity, Asset, Verdict)의 계약을 `contracts/`에 JSON Schema(draft-07)로 만들었다.
- `scripts/generate_contracts.py`가 schema로 Pydantic v2 모델을 `src/soc/contracts/generated/`에 만든다. CI는 `--check`로 커밋된 생성 코드가 schema와 같은지 검사한다.
- `soc.contracts.validate_contract(name, data)`는 다음 순서로 검사한다.
  1. JSON으로 바꿀 수 있는지(`json.dumps`)
  2. JSON Schema 검사
  3. schema로 쓸 수 없는 규칙(Event의 `ocsf_class`)
  4. 생성 모델로 변환

  틀리면 필드 경로와 어긴 규칙만 담은 `ContractError`를 낸다.
- 계약 규칙 중 몇 가지: benign·malicious 판정은 근거 ID가 1개 이상이어야 한다. DB `integer` 컬럼에 대응하는 정수는 int32 상한을, 시각은 9999-12-30T23:59:59.999Z 상한을 둔다. SIEM 프로필·문서 참조·자산 엔티티 값은 빈 문자열을 거부한다. ID 목록(`alert_ids`, `ticket_ids`, `evidence_ids`)은 중복을 거부한다. Agent Log에서 도구 호출은 토큰이 null이고, `subject_id`는 `subject_type`에 맞는 ID여야 한다.
- `soc.ids.new_id(prefix)`는 접두사 + UUIDv7 ID를 만든다. `soc.contracts.to_datetime()`과 `to_epoch_ms()`는 계약의 밀리초와 DB의 `timestamptz`를 서로 바꾼다.
- `uv run python -m soc.db.migrate`는 `src/soc/db/migrations/`의 순번 SQL을 적용한다. 첫 파일 `0001_common_tables.sql`이 공통 테이블 7개를 만든다. DB CHECK는 최상위 목록 값, triage의 모양과 status, jsonb 칸의 모양(객체·목록), ID 목록(`alert_ids`, `ticket_ids`)의 NULL 원소와 개수까지 확인한다. 안쪽 필드는 validate_contract()가 확인한다. jsonb 칸은 JSON null도 거부한다. 이미 적용한 번호의 파일 이름이 바뀌었거나 그 파일이 없으면 실행기가 멈춘다.
- Ticket 생성 모드(`auto`/`scenario`)는 동작 없이 필드(`Alert.rule_id`, `Alert.triage`, `Ticket.origin`)와 설정 키 이름(`[ticketing] mode`, `scenario_rule_ids`)만 정했다.
- CI에 생성 코드 차이 검사와 `db` job(PostgreSQL 17.6 서비스 컨테이너)을 추가했다. `docs/architecture.md`를 계획대로 고쳤다.

## 계획과 달라진 점

- 사람이 정한 변경(JSON null 거부, OCSF 클래스별 검증 위치, 근거 필수, 정수·시각 상한과 시각 상한 조정, 빈 문자열 거부, `raw_id` 인덱스, 실행기의 파일 이름 비교, triage·jsonb 모양 제약, JSON이 아닌 값 거부, 실행기의 빠진 파일 확인, ID 목록 제약, 중복 ID 거부, 도구 호출 토큰, 대상 ID 모양)은 계획 파일 "바뀐 점"에 있다.
- **공통 정의 파일 `contracts/common/types.schema.json`을 추가했다.** ID 패턴 9개, 시각, 심각도를 한 곳에 둔다. UUIDv7 정규식을 schema 20여 곳에 복사하지 않기 위해서다. 계약이 아니라서 `validate_contract()`의 이름으로는 쓸 수 없다.
- **생성 옵션을 이렇게 골랐다.**
  - `--use-type-alias`: 목록 안의 ID와 null 가능한 숫자가 RootModel 대신 일반 `str`·`int`로 나온다. 이 옵션이 없으면 `ticket.alert_ids[0]`이 RootModel이라 `.root`를 붙여야 했다.
  - `--enum-field-as-literal=all`: 목록 값이 Enum 클래스 대신 `Literal` 문자열로 나온다.
  - 생성 모듈 이름은 schema 파일 이름에서 나온다(예: `soc.contracts.generated.ticket_schema.Ticket`).
- **위반의 `rule` 이름은 JSON Schema 키워드다**(`required`, `enum`, `pattern`, `minItems` 등).
  - 상태 짝 규칙은 if/then으로 썼으므로, 어기면 `type`으로 나온다. 예: `pending`인데 verdict가 있으면 `triage.verdict: type`.
  - schema 밖 규칙의 이름은 `equals_ocsf_class`다.
  - JSON으로 바꿀 수 없는 값은 `(root): json`이다. 어느 칸인지는 나오지 않는다.
  - 정의된 숫자 필드의 NaN(예: `verdict.confidence`)은 JSON Schema 검사를 지나 Pydantic 변환 단계에서 걸린다. 이때 `rule`은 Pydantic 오류 이름(`less_than_equal`)이다.
- **함수 몇 개를 더 내보낸다.** `soc.contracts`는 `Violation`과 `CONTRACT_NAMES`도 내보낸다. 실행기에는 `find_migrations()`와 `MigrationError`가 있다.
- **테스트를 하나 더 넣었다.** 계약 밖 값을 DB CHECK 제약이 거부하는지 확인하는 `db` 테스트다. 완료 기준에는 없었다.
- **hunt 대상 Agent Log 올바른 샘플(`l3_hunt_tool_call`)을 더했다.** 리뷰가 요청한 것은 틀린 샘플뿐이지만, hunt 갈래가 빈 문자열 말고는 거부하지 않는지 확인하려고 넣었다.

## 다음 사람이 알아야 할 것

- **DB에 쓰기 전에 `validate_contract()`를 거친다.** 생성 모델을 직접 만들면 if/then 규칙(상태 짝, `alert_ids` 개수, 도구 호출 토큰, `subject_id` 접두사), 중복 ID(`uniqueItems`), `ocsf_class` 비교, JSON이 아닌 값을 검사하지 않는다. 모델이 있으면 `validate_contract(name, model.model_dump(mode="json"))`로 다시 확인한다. 반환 타입은 `BaseModel`이다.
- **계약은 모양만 검사한다.** 근거 ID(`evidence_ids`)가 실제로 있는지, Incident `severity` 계산(소속 Alert 최대, 없으면 0), Case가 Incident 값을 그대로 복사했는지는 각 단계 코드가 확인한다.
- **계약 통과 ≠ INSERT 가능.** 로그에서 온 문자열의 NUL(`\u0000`)과 자유 객체 안의 NaN·Infinity는 계약이 막지 않지만 PostgreSQL은 거부한다. 공격자가 일부러 넣어 저장을 실패시킬 수 있으므로, 바꿔 넣을지 그 레코드만 거부하고 다음으로 진행할지는 수집·정규화 이슈에서 반드시 정한다. SIEM 응답을 `json.loads`로 읽을 때 NaN이 섞여 들어올 수 있다.
- **`validate_contract()`는 JSON으로 바꿀 수 없는 값을 거부한다.** 자유 객체(`details`, `ocsf`, `original`, `input`, `output`)에 bytes·datetime·set이나 순환 참조가 있는 dict를 넣으면 `(root): json`으로 거부되고, 어느 칸인지는 나오지 않는다. `json.dumps`의 `TypeError`와 `ValueError`를 모두 `ContractError`로 바꾼다. 시각은 `to_epoch_ms()`로, bytes는 문자열로 바꿔 넣는다.
- **Hunt 대상 Agent Log의 `subject_id`는 빈 문자열만 거부한다.** Hunt ID 형식이 아직 없어서다. L3 이슈에서 Hunt ID를 정할 때 `agent_log.schema.json`의 `hunt` 갈래(`minLength: 1`)를 그 ID 패턴으로 바꾼다. 공통 계약 변경이라 L1·L2·L3 담당자 전원의 승인이 필요하고, 접두사를 새로 만들면 `soc.ids.new_id()`와 `types.schema.json`에도 더한다.
- **DB는 ID 목록의 NULL 원소와 개수만 확인한다.** 중복과 접두사는 `validate_contract()`만 검사하고, 가리키는 행이 실제로 있는지는 각 단계 코드가 확인한다. 2차원 배열은 `array_position`이 CHECK 위반이 아닌 `feature_not_supported`(0A000) 오류를 내서 들어가지 않는다.
- **L1이 1차 판정 대기 알럿을 찾을 때는 `triage ->> 'status' = 'pending'`으로 쓴다.** 이 식이어야 식 인덱스 `alerts_triage_status_idx`를 탄다. `triage -> 'status' = '"pending"'`처럼 다른 식으로 쓰면 인덱스를 타지 않는다.
- **DB에 접속하는 코드는 세션 시간대를 UTC로 둔다**(예: 연결 옵션 `-c TimeZone=UTC`). psycopg는 timestamptz를 세션 시간대로 바꿔 돌려주므로, UTC가 아니면 시각이 바뀌어 보이고 상한 근처 값은 읽기에서 실패할 수 있다.
- **DB가 JSON null을 거부하므로 SQL NULL을 넣어야 한다.** null이 될 수 있는 `alerts.triage`, `tickets.verdict`, `agent_logs.output`에 None을 쓸 때 psycopg `Jsonb(None)`을 넘기면 JSON null(`'null'::jsonb`)이 되어 CHECK 위반으로 거부된다. 값 None을 그대로 넘겨 SQL NULL로 넣는다. 객체·목록 칸은 모양(객체·목록)까지 확인하므로 JSON null도 거부된다. `agent_logs.input`만 JSON null을 받는다(계약상 JSON 값 전체). 변환 예시는 `tests/test_db_tables.py`의 `to_row()`에 있다.
- **schema를 고치면 생성 코드도 같이 커밋한다.** `uv run python scripts/generate_contracts.py`를 실행한 결과를 함께 올린다. 공통 계약 변경이라 L1·L2·L3 담당자 전원의 승인이 필요하다.
- **마이그레이션 실행기에는 잠금이 없다.** 같은 대역에서 두 사람이 같은 번호를 쓰면 실행기는 아무것도 실행하지 않고 실패한다. 머지 전에 번호를 확인한다. 이미 적용한 번호의 파일 이름을 바꾸거나, 그 번호의 파일이 없어도 멈춘다. 개발 DB 하나를 여러 브랜치에서 같이 쓰면 다른 브랜치에서 적용한 번호의 파일이 없어 멈출 수 있으니, 그때는 새 DB를 쓴다. 실행기 두 개를 동시에 돌리면 막지 못한다.
- **마이그레이션 명령은 `.env`를 읽지 않는다.** `uv run --env-file .env python -m soc.db.migrate`처럼 환경변수를 넘긴다.
- **`db` 테스트에는 DB 생성 권한이 필요하다.** `DATABASE_URL` 계정으로 `soc_test_<랜덤>` DB를 만들고, 끝나면 `DROP DATABASE ... WITH (FORCE)`로 지운다. compose 계정과 CI 계정은 이 권한이 있다.
- **`validate_contract()`는 레포 루트 `contracts/`를 읽는다.** 레포 없이 wheel로만 설치하면 schema가 없어 `RuntimeError`가 난다. 배포 형태가 정해지면 바꾼다.
- **`new_id()`의 순서 보장은 한 프로세스 안에서만이다.** 프로세스끼리는 밀리초 단위까지만 맞는다.
- **`types.schema.json`이 생성 코드에 빈 별칭을 남긴다.** 정의만 있는 파일이라 아무도 쓰지 않는 `Types` 별칭이 생긴다. 무시해도 된다.
- **TypeScript 생성 코드는 아직 없다.** 첫 화면 이슈에서 붙인다.
- **Ticket 생성 모드는 키 이름만 있다.** 설정을 읽는 코드, `config/default.toml`, 시나리오 일치 판단, Ticket 생성은 수집·정규화 이슈가 만든다.
- **CI의 새 단계는 아직 돌지 않았다.** 생성 코드 차이 검사와 `db` job은 push 후 처음 돈다. 로컬에서는 같은 조건(`postgres:17.6`, trust 인증)의 임시 컨테이너로 확인했다.
- **OCSF 클래스별 검증은 정규화 이슈에서 반드시 한다.** 이 계약은 `ocsf`를 자유 객체로 두고 Alert의 `class_uid = 2004`와 Event의 `ocsf_class = ocsf.class_uid`만 검사한다. 정규화 결과의 `ocsf`는 해당 class_uid의 OCSF 1.9.0 공식 JSON Schema로 검증해야 하며, 쓰는 클래스마다(최소 Detection Finding 2004, Base Event 0, 매핑하는 이벤트 클래스) 공식 스키마 파일을 생성해 레포에 두고 검증한다(OCSF 정규화, D-007).
- **uv 버전에 주의한다.** `uv.lock`은 revision 3 형식이다. uv 0.12.23은 lock을 revision 5로 올려서, revision 3을 유지하는 uv 0.12.0(`uvx --from 'uv==0.12.0' uv lock`)으로 lock했다. 최신 uv(0.13.7)의 `uv lock --check`도 통과한다. 0.6처럼 오래된 uv로 `uv add`·`uv lock`을 하면 형식이 바뀔 수 있다.
- **예전 브랜치의 `__pycache__` 폴더가 import를 방해할 수 있다.** git이 무시하는 `src/soc/*/__pycache__`만 남은 폴더가 있으면, 소스가 없어도 `soc.l1` 같은 이름이 namespace package로 import된다. 이상하게 import되면 확인한다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run pytest`: 174개 통과(`db` 62개 제외). 주요 테스트:
  - `tests/test_contracts.py`: 올바른 샘플 35개(상한 경계값 포함)가 통과하고, 모델로 바꿔도 필드가 빠지지 않는다. 틀린 샘플 68개는 기대한 경로·규칙으로 거부된다. 자유 객체 5칸 × bytes·datetime·set·순환 참조 20개는 `(root): json`으로 거부된다.
  - `tests/test_ids.py`, `tests/test_times.py`, `tests/test_migrate.py`
- `DATABASE_URL=<로컬 postgres:17.6 trust 컨테이너> uv run pytest -m db`: 62개 통과(`tests/test_db_tables.py`). 상한 경계값 샘플(int32 최댓값, 상한 시각)도 테이블에 들어가고, 세션 시간대 Pacific/Kiritimati(+14)·Asia/Seoul(+9)에서도 읽힌다. 이 시간대 테스트는 이전 상한(9999-12-31)에서 `timestamp too large (after year 10K)`로 실패하는 것을 확인했다. 끝난 뒤 남은 임시 DB 0개. JSON null 거부 테스트는 CHECK를 넣기 전 SQL에서 실패하는 것을 확인했다
- `DATABASE_URL` 없이 `uv run pytest -m db`: 62개 오류(건너뛰지 않음)
- triage·jsonb 모양 테스트: 새 제약을 넣기 전 SQL에서 실패하는 것을 확인했다. 리뷰 원안 식(`jsonb_typeof(triage) = 'object' AND triage ->> 'status' IN (...)`)으로는 `{}`, status 없음, status null이 여전히 통과해서 `IS TRUE`로 감쌌다
- 두 번째 리뷰 반영(2026-11-04): 항목마다 새 테스트가 고치기 전에 실패하는 것을 확인했다.
  - JSON이 아닌 값 15개: `ContractError`가 나지 않아 실패
  - 순환 참조 5개(리뷰 뒤 사람이 추가로 정함): `json.dumps`의 `ValueError`가 그대로 올라와 실패. 고친 뒤에도 자유 객체 안의 NaN·Infinity는 지금처럼 이 검사를 지나는 것을 손으로 확인했다
  - 번호만 바꾼 마이그레이션(`IF NOT EXISTS`라 다시 실행돼도 오류 없음): `MigrationError`가 나지 않아 실패
  - ID 목록 거부 7개(NULL 원소 3, 빈 목록 4): CHECK 위반이 나지 않아 실패. 같은 값을 계약도 거부하는지 함께 확인한다. 허용 4개(L3 빈 목록, ID 여러 개)는 고치기 전후 모두 통과한다(제약이 너무 좁아지지 않았는지 지킨다)
  - 중복 ID 3개, 도구 호출 토큰 1개, 대상 ID 모양 4개(종류·접두사 불일치 3, hunt 빈 문자열 1): 거부되지 않아 실패
- 손으로 확인(임시 DB): 2차원 배열을 `alert_ids`·`ticket_ids`에 넣으면 `array_position`이 `feature_not_supported` 오류를 내서 들어가지 않는다
- 손으로 확인(커밋하지 않은 스크립트, 임시 DB): 문자열의 NUL, `details`의 NaN·Infinity가 계약을 통과한 뒤 INSERT에서 실패한다
- `uv run python scripts/generate_contracts.py --check`: 차이 없음. 생성 파일에 한 줄을 더하면 exit 1
- 빈 DB에 `uv run python -m soc.db.migrate`를 두 번 실행: 1개 적용 → "적용할 마이그레이션이 없다"
- 최신 uv로 `uv lock --check`: 통과
