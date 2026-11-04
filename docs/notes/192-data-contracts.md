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
  1. JSON 사전 검사: `json.dumps(allow_nan=False)`로 JSON으로 나타낼 수 있는지(bytes·datetime·set·순환 참조·NaN·Infinity, `RecursionError`가 나는 깊은 중첩 거부) 본 뒤, 모든 dict 키가 문자열인지, 키와 문자열 값에 NUL(`\u0000`)과 짝 없는 서로게이트(U+D800~U+DFFF)가 없는지, 깊이가 100(`MAX_JSON_DEPTH`) 이하인지 본다
  2. JSON Schema 검사. pattern 끝의 `$`는 `\Z`로 바꿔 검사한다(끝에 `\n`이 붙은 값 거부). `integer`는 Python int만 받는다(bool과 `4.0` 같은 float 거부). 숫자 `const`·`enum`은 `type: integer`를 같이 두어 int만 받는다(Alert `ocsf.class_uid`의 `2004.0` 거부)
  3. schema로 쓸 수 없는 규칙(Event의 `ocsf_class`)
  4. 생성 모델로 변환

  틀리면 필드 경로와 어긴 규칙만 담은 `ContractError`를 낸다.
- 계약 규칙 중 몇 가지: benign·malicious 판정은 근거 ID가 1개 이상이어야 한다. DB `integer` 컬럼에 대응하는 정수는 int32 상한을, 시각은 9999-12-30T23:59:59.999Z 상한을 둔다. SIEM 프로필·문서 참조·자산 엔티티 값은 빈 문자열을 거부한다. ID 목록(`alert_ids`, `ticket_ids`, `evidence_ids`)은 중복을 거부한다. Agent Log에서 도구 호출은 토큰이 null이고, `subject_id`는 `subject_type`에 맞는 ID여야 한다.
- `soc.ids.new_id(prefix)`는 접두사 + UUIDv7 ID를 만든다. `soc.contracts.to_datetime()`과 `to_epoch_ms()`는 계약의 밀리초와 DB의 `timestamptz`를 서로 바꾼다. 정수가 아닌 밀리초와 datetime이 아닌 값은 `TypeError`로 거부한다.
- `uv run python -m soc.db.migrate`는 `src/soc/db/migrations/`의 순번 SQL을 적용한다. 첫 파일 `0001_common_tables.sql`이 공통 테이블 7개를 만든다. DB CHECK는 최상위 목록 값, triage의 모양과 status, jsonb 칸의 모양(객체·목록), ID 목록(`alert_ids`, `ticket_ids`)의 NULL 원소와 개수까지 확인한다. 안쪽 필드는 validate_contract()가 확인한다. 기준은 행 하나만 봐도 깨진 레코드인지 알 수 있는 것이고, 상태와 다른 칸이 맞는지(`resolved`↔`resolved_at` 등)는 DB에 두지 않는다. jsonb 칸은 JSON null도 거부한다. 실행기는 번호가 겹치거나, 파일 이름이 바뀌었거나, 적용한 파일이 없거나, 적용한 파일 내용이 바뀌면 아무것도 실행하지 않고 멈춘다. 내용은 `schema_migrations.checksum`에 적용할 때 기록한 해시(UTF-8로 읽어 `\r\n`을 `\n`으로 바꾼 뒤의 SHA-256 hex)와 비교한다. `.gitattributes`로 `*.sql`을 LF로 둔다. 기록된 가장 큰 번호보다 작은 미적용 파일(대역 사이 순서)은 멈추지 않고 적용하되 경고 한 줄을 낸다. UTF-8이 아니거나 UTF-8 BOM으로 시작하는 SQL 파일은 번호·파일 이름을 담은 `MigrationError`로 멈춘다. 파일은 DB에 접속하기 전에 모두 읽으므로 이때는 아무것도 적용하지 않는다. 실행기는 접속 직후 세션 단위 advisory lock을 잡고 모든 적용이 끝날 때까지 두므로, 같은 DB에 동시에 돌려도 파일마다 한 번만 적용된다. 다른 실행기가 60초 넘게 잡고 있으면 아무것도 적용하지 않고 멈춘다. 파일 이름의 번호는 ASCII 숫자 4자리이고 이름 전체를 비교한다.
- Ticket 생성 모드(`auto`/`scenario`)는 동작 없이 필드(`Alert.rule_id`, `Alert.triage`, `Ticket.origin`)와 설정 키 이름(`[ticketing] mode`, `scenario_rule_ids`)만 정했다.
- CI에 생성 코드 차이 검사와 `db` job(PostgreSQL 17.6 서비스 컨테이너)을 추가했다. `docs/architecture.md`를 계획대로 고쳤다.

## 계획과 달라진 점

- 사람이 정한 변경(JSON null 거부, OCSF 클래스별 검증 위치, 근거 필수, 정수·시각 상한과 시각 상한 조정, 빈 문자열 거부, `raw_id` 인덱스, 실행기의 파일 이름 비교, triage·jsonb 모양 제약, JSON이 아닌 값 거부, 실행기의 빠진 파일 확인, ID 목록 제약, 중복 ID 거부, 도구 호출 토큰, 대상 ID 모양, pattern 끝 `$` 처리, JSON 사전 검사 확장, 마이그레이션 내용 해시, 짝 없는 서로게이트 거부, JSON 깊이 한도, integer는 int만, 대역 사이 적용 순서 경고, UTF-8이 아닌 SQL 오류, 마이그레이션 파일 미리 읽기, 숫자 `const`의 integer 타입, BOM 거부, 실행기 잠금, 파일 이름 정규식, `to_epoch_ms()` 타입 검사, DB CHECK 범위)은 계획 파일 "바뀐 점"에 있다.
- **실행기 잠금의 대기 한도는 60초 상수이고, PostgreSQL `lock_timeout`으로 건다(2026-11-04).**
  - 방법: 잠금을 잡는 트랜잭션 안에서만 `set_config('lock_timeout', '60000ms', true)`를 두고 `pg_advisory_lock(LOCK_KEY)`를 부른다. 한도를 넘으면 PostgreSQL이 `lock_not_available`(55P03)을 내고, 실행기는 `다른 마이그레이션이 실행 중이다(60초 기다렸다). 끝난 뒤 다시 실행한다` `MigrationError`로 바꾼다.
  - `pg_try_advisory_lock` 반복 대신 이것을 고른 이유: 잠금이 풀리면 서버가 바로 깨우고 한도도 서버가 잰다. 반복하면 확인 간격만큼 늦고 sleep 코드가 필요하며, 기다리던 쪽이 새로 온 쪽에 계속 밀릴 수 있다. 한도는 트랜잭션 안에서만 쓰므로 마이그레이션 SQL이 테이블 잠금을 기다리는 데에는 걸리지 않는다(손으로 확인: 트랜잭션이 끝나면 `lock_timeout`이 0으로 돌아오고, 그 안에서 잡은 세션 단위 잠금은 남는다).
  - 상수로 둔 이유: 계획에 없는 설정(환경변수, `.env.example`)을 만들지 않으려는 것이다. 지금 마이그레이션은 1초 안에 끝나므로 60초면 동시에 띄운 실행기가 앞쪽을 충분히 기다리고, 오래 잡힌 잠금(예: psql에서 잡고 둔 세션)은 1분 안에 드러난다. 테스트는 `migrate(..., lock_wait_seconds=0.2)`처럼 키워드 인자로 짧게 넘긴다. `python -m soc.db.migrate`는 늘 60초다. 0 이하를 넘겨도 1ms로 둔다(`lock_timeout` 0은 한도 없음이라).
  - 키: `LOCK_KEY = -3383018492198273124`. `"soc.db.migrate"`의 SHA-256 앞 8바이트를 부호 있는 64비트 정수(big-endian)로 읽은 값이다. 다른 기능이 advisory lock을 쓸 때 겹치지 않게 1 같은 작은 수 대신 이름에서 만들었다.
- **Event `ocsf.class_uid = 4002.0`은 schema에서 막는다. rule은 `type`이다(2026-11-04).** 확인해 보니 `_extra_violations()`의 `!=` 비교는 `4002`와 `4002.0`을 같다고 본다. 하지만 `event.schema.json`의 `ocsf.class_uid`는 이미 `{"type": "integer"}`이고 integer 검사가 Python int만 받으므로, schema 검사에서 `ocsf.class_uid: type`으로 걸려 비교까지 가지 않는다. 그래서 코드는 바꾸지 않고, 비교가 schema의 integer 검사에 기댄다는 주석만 더했다. schema를 고른 이유: Alert의 `2004.0`, 다른 integer 필드와 같은 곳(schema `type`)에서 같은 rule 이름으로 거부되고, 규칙 코드에 타입 검사를 또 두면 같은 검사가 두 곳에 생긴다. 틀린 샘플 `ocsf_class_uid_float`은 고치기 전후 모두 통과하는 보호용이다.
- **schema에서 `type: integer` 없이 숫자 `const`·`enum`을 쓴 곳은 Alert `ocsf.class_uid` 하나였다.** `const`·`enum` 25곳 중 나머지 24곳은 문자열이다. 다시 생성해도 생성 코드는 바뀌지 않았다(`Literal[2004]` 그대로). 앞으로 생길 숫자 `const`·`enum`도 막도록 schema 모양 검사(`test_numeric_const_and_enum_have_integer_type`)를 더했다. 요청에는 없었다.
- **BOM을 거부하는 이유는 "`psql -f`와 결과를 같게"가 아니라 "도구마다 결과가 갈라지지 않게"로 적었다(2026-11-04).** 손으로 확인해 보니 psql 17.6은 클라이언트 인코딩이 UTF8이면 파일 맨 앞의 BOM을 떼고 실행한다(`psql -f`, `psql < 파일` 모두 성공). LATIN1·SQL_ASCII이면 실행기와 같은 `syntax error at or near "\ufeffSELECT"`를 낸다. 거부하는 동작은 정한 대로 두었다. 같은 파일이 도구와 설정에 따라 성공하기도 실패하기도 하고, BOM이 있고 없음에 따라 같은 SQL의 해시가 달라진다. BOM 없는 UTF-8 하나로 맞추면 둘 다 없어진다.
- **두 번째 임시 DB fixture `other_temp_database`를 `tests/conftest.py`에 더했다.** advisory lock이 DB마다 따로인지 보려면 한 테스트에 임시 DB가 두 개 필요하다. 임시 DB를 만들고 지우는 코드는 `created_database()`로 옮겨 두 fixture가 함께 쓴다.
- **이름 끝에 `\n`이 붙은 파일은 고치기 전에도 번호 파일로 인식되지 않았다.** `glob("*.sql")`이 `.sql`로 끝나는 이름만 고르기 때문이다(fnmatch는 `\Z`로 끝을 맞춘다). README.md 같은 SQL이 아닌 파일처럼 넘어가고, 이 테스트는 보호용이다. `$` → `fullmatch`는 정규식만 보고도 맞게 하려는 것이다. 아랍 숫자 `٠٠٠١_x.sql`은 고치기 전에는 1번으로 인식됐고, 지금은 다른 이름 규칙 위반과 같은 `MigrationError`다.
- **`agent_log` `tokens_in = 10.0` 샘플의 rule은 `type`이 아니라 `anyOf`다. 그대로 두기로 정함(2026-11-04).** 처음 정할 때 기대한 rule은 `type`이었다. 하지만 `tokens_in`·`tokens_out`은 `anyOf[integer, null]`이고, 값의 타입이 어느 갈래와도 맞지 않으면 지금 매핑(`_branch_matching_type`)이 `anyOf`를 낸다. 고치기 전에도 `"x"`·`true`는 `anyOf`로 나왔다. 오류 매핑과 schema는 바꾸지 않는다. 나머지 float 샘플(`time`, `severity`, `analysis_round`)은 `type`이다.
- **integer 반영에 보호용 테스트를 더했다.** `number` 필드(`verdict.confidence`의 1과 0.5)와 자유 객체 안의 float(`ticket.details`의 4.0)가 그대로 통과하는지 본다. 요청에는 없었고, integer만 좁혔는지 지키려고 넣었다.
- **실행기의 `_read_sql()`은 경로 대신 `Migration`을 받는다.** 오류 메시지에 번호와 파일 이름을 넣으려는 것이다(내부 함수).
- **미리 읽은 마이그레이션 내용은 `Migration`에 담지 않고 `migrate()` 안의 번호 → (SQL, 해시) dict로 따로 둔다.** `Migration`에 담으면 이름만 검사하는 목록 함수 `find_migrations()`(테스트도 그 목록을 쓴다)가 파일까지 읽어야 해서다.
- **공통 정의 파일 `contracts/common/types.schema.json`을 추가했다.** ID 패턴 9개, 시각, 심각도를 한 곳에 둔다. UUIDv7 정규식을 schema 20여 곳에 복사하지 않기 위해서다. 계약이 아니라서 `validate_contract()`의 이름으로는 쓸 수 없다.
- **생성 옵션을 이렇게 골랐다.**
  - `--use-type-alias`: 목록 안의 ID와 null 가능한 숫자가 RootModel 대신 일반 `str`·`int`로 나온다. 이 옵션이 없으면 `ticket.alert_ids[0]`이 RootModel이라 `.root`를 붙여야 했다.
  - `--enum-field-as-literal=all`: 목록 값이 Enum 클래스 대신 `Literal` 문자열로 나온다.
  - 생성 모듈 이름은 schema 파일 이름에서 나온다(예: `soc.contracts.generated.ticket_schema.Ticket`).
- **위반의 `rule` 이름은 JSON Schema 키워드(`required`, `enum`, `pattern`, `minItems` 등), `json`, `equals_ocsf_class` 중 하나다.** 틀린 샘플 전체로 이 약속을 검사한다(`test_invalid_samples_break_only_promised_rules`).
  - 상태 짝 규칙은 if/then으로 썼으므로, 어기면 `type`으로 나온다. 예: `pending`인데 verdict가 있으면 `triage.verdict: type`.
  - schema 밖 규칙의 이름은 `equals_ocsf_class`다.
  - JSON 사전 검사에 걸리면 `(root): json`이다. 어느 칸인지는 나오지 않는다(경로에 입력 키가 들어갈 수 있어서). 정의된 숫자 필드의 NaN(예: `verdict.confidence`)도 범위 검사가 아니라 여기서 걸린다.
  - 모델 변환 단계는 방어 코드로 남겼다. 여기서 걸리면 rule이 Pydantic 오류 이름이라 약속 밖이다. 알려진 경우(끝에 `\n`이 붙은 ID의 `string_pattern_mismatch`, 숫자 NaN의 `less_than_equal`)는 앞 단계로 옮겼고, 남은 경우는 확인하지 못했다.
- **함수 몇 개를 더 내보낸다.** `soc.contracts`는 `Violation`과 `CONTRACT_NAMES`도 내보낸다. 실행기에는 `find_migrations()`와 `MigrationError`가 있다.
- **테스트를 하나 더 넣었다.** 계약 밖 값을 DB CHECK 제약이 거부하는지 확인하는 `db` 테스트다. 완료 기준에는 없었다.
- **hunt 대상 Agent Log 올바른 샘플(`l3_hunt_tool_call`)을 더했다.** 리뷰가 요청한 것은 틀린 샘플뿐이지만, hunt 갈래가 빈 문자열 말고는 거부하지 않는지 확인하려고 넣었다.

## 다음 사람이 알아야 할 것

- **DB에 쓰기 전에 `validate_contract()`를 거친다.** 생성 모델을 직접 만들면 if/then 규칙(상태 짝, `alert_ids` 개수, 도구 호출 토큰, `subject_id` 접두사), 중복 ID(`uniqueItems`), `ocsf_class` 비교, JSON 사전 검사를 하지 않는다. 모델이 있으면 `validate_contract(name, model.model_dump(mode="json"))`로 다시 확인한다. 반환 타입은 `BaseModel`이다.
- **계약은 모양만 검사한다.** 근거 ID(`evidence_ids`)가 실제로 있는지, Incident `severity` 계산(소속 Alert 최대, 없으면 0), Case가 Incident 값을 그대로 복사했는지는 각 단계 코드가 확인한다.
- **`validate_contract()`를 통과하면 INSERT도 된다.** 값 때문에 INSERT가 실패하지 않는 것이 목표다(외래 키·유일 제약 위반은 별개). JSON으로 나타낼 수 없는 값(bytes·datetime·set·순환 참조·NaN·Infinity), 키와 문자열의 NUL(`\u0000`)과 짝 없는 서로게이트(U+D800~U+DFFF), 문자열이 아닌 dict 키(int·float·bool·None)는 계약 안팎 어느 칸에 있든 `(root): json`으로 거부한다. 시각은 `to_epoch_ms()`로, bytes는 문자열로 바꿔 넣는다. SIEM 응답을 `json.loads`로 읽으면 NaN·NUL·짝 없는 서로게이트(`"\ud800"`)가 섞여 들어올 수 있으므로, 수집·정규화 이슈는 이렇게 거부된 레코드를 어떻게 처리할지(건너뛰고 다음으로 갈지 등) 정한다.
- **JSON 깊이 한도는 100이다(`MAX_JSON_DEPTH`).** 깊이는 dict·list가 겹친 수이고 data 최상위 dict가 1, 그 안의 자유 객체(`original` 등)가 2다. 100을 넘으면 `(root): json`으로 거부한다. `json.dumps`는 Python 3.13.2(재귀 한도 1000)에서 9000단계까지 통과하고 2만 단계에서 `RecursionError`를 냈다(손으로 확인). 이렇게 Python 버전과 설정에 따라 달라지는 지점에 결과를 맡기지 않으려고 한도를 두었다. `RecursionError`도 `(root): json`으로 잡는다. 깊은 SIEM 원문(`original`)이나 LLM 출력(`output`)도 이 한도에 걸리므로, 수집·정규화와 각 단계 이슈가 거부된 레코드 처리를 정할 때 같이 본다.
- **integer 필드는 Python int만 받는다.** 시각·`severity`·`analysis_round`·토큰 같은 integer 필드에 `4.0`이나 `1793678578000.0` 같은 float를 넣으면 `type` 위반이다(null이 될 수 있는 `tokens_in`·`tokens_out`은 `anyOf`). bool은 원래부터 거부된다. Draft 7은 `4.0`도 integer로 보지만 생성 모델은 4로 바꿔 돌려주므로, 그대로 두면 검증한 dict와 모델이 달라진다. 검증한 dict를 그대로 저장해도 되게 하려는 것이다. SIEM 응답의 숫자가 float로 오면 정규화 코드가 int로 바꿔 넣는다. `number` 필드(`confidence`)와 자유 객체 안의 float는 그대로 받는다. schema와 생성 코드는 바꾸지 않았다(검사기의 integer 판정만 바꿨다). 숫자 `const`·`enum`을 쓸 때는 `type: integer`를 같이 둔다. jsonschema는 `const`·`enum`을 수치로 비교해 `2004.0`도 `2004`와 같다고 보기 때문이다(schema 모양 테스트가 검사한다).
- **짝 없는 서로게이트는 문자열을 UTF-8로 바꿔 보아 거부한다.** `json.dumps`는 `\ud800`으로 이스케이프해 통과시키지만, 그대로 두면 text 칸은 `UnicodeEncodeError`, jsonb 칸은 `InvalidTextRepresentation`으로 INSERT가 실패한다(임시 DB에서 손으로 확인). 이모지 같은 BMP 밖 글자는 통과한다. `json.loads`는 `"\ud83d\ude00"` 같은 이스케이프된 쌍을 한 글자로 합친다. 코드에서 서로게이트 두 개를 따로 붙인 문자열(`chr(0xD83D) + chr(0xDE00)`)은 UTF-8로 바꿀 수 없어 거부된다.
- **schema pattern은 `^`로 시작하고 `$`로 끝나게 쓴다.** `validate_contract()`가 끝의 `$`를 `\Z`로 바꿔 검사해 끝에 `\n`이 붙은 값을 거부한다(Python의 `$`는 마지막 `\n` 앞에서도 맞는다). schema에 `\Z`를 직접 쓰지 않는 것은 ECMA 정규식과 Rust regex(Pydantic)가 모르기 때문이다. 테스트가 모든 pattern의 모양을 검사한다. `\d`·`\w`·`\s`는 Python에서 유니코드 글자까지 맞으니 `[0-9]`처럼 범위를 적는다(지금 pattern 9개에는 없다).
- **Hunt 대상 Agent Log의 `subject_id`는 빈 문자열만 거부한다.** Hunt ID 형식이 아직 없어서다. L3 이슈에서 Hunt ID를 정할 때 `agent_log.schema.json`의 `hunt` 갈래(`minLength: 1`)를 그 ID 패턴으로 바꾼다. 공통 계약 변경이라 L1·L2·L3 담당자 전원의 승인이 필요하고, 접두사를 새로 만들면 `soc.ids.new_id()`와 `types.schema.json`에도 더한다.
- **DB CHECK는 행 하나만 봐도 깨진 레코드인지 알 수 있는 것만 막는다.** 목록 값, 숫자 범위, jsonb 칸 모양, ID 목록의 NULL 원소와 개수(`origin`↔`alert_ids` 포함)다. 상태와 다른 칸이 맞는지(Case `resolved`↔`resolved_at`, Ticket `new`→verdict null, Alert `triage.status`↔`triage.verdict`)는 DB가 막지 않고 `validate_contract()`와 단계 코드가 확인한다. 상태 규칙은 단계 담당자가 바꿀 수 있어서다. `0001` 헤더 주석에 같은 기준이 있다.
- **DB는 ID 목록의 NULL 원소와 개수만 확인한다.** 중복과 접두사는 `validate_contract()`만 검사하고, 가리키는 행이 실제로 있는지는 각 단계 코드가 확인한다. 2차원 배열은 `array_position`이 CHECK 위반이 아닌 `feature_not_supported`(0A000) 오류를 내서 들어가지 않는다.
- **L1이 1차 판정 대기 알럿을 찾을 때는 `triage ->> 'status' = 'pending'`으로 쓴다.** 이 식이어야 식 인덱스 `alerts_triage_status_idx`를 탄다. `triage -> 'status' = '"pending"'`처럼 다른 식으로 쓰면 인덱스를 타지 않는다.
- **DB에 접속하는 코드는 세션 시간대를 UTC로 둔다**(예: 연결 옵션 `-c TimeZone=UTC`). psycopg는 timestamptz를 세션 시간대로 바꿔 돌려주므로, UTC가 아니면 시각이 바뀌어 보이고 상한 근처 값은 읽기에서 실패할 수 있다.
- **DB가 JSON null을 거부하므로 SQL NULL을 넣어야 한다.** null이 될 수 있는 `alerts.triage`, `tickets.verdict`, `agent_logs.output`에 None을 쓸 때 psycopg `Jsonb(None)`을 넘기면 JSON null(`'null'::jsonb`)이 되어 CHECK 위반으로 거부된다. 값 None을 그대로 넘겨 SQL NULL로 넣는다. 객체·목록 칸은 모양(객체·목록)까지 확인하므로 JSON null도 거부된다. `agent_logs.input`만 JSON null을 받는다(계약상 JSON 값 전체). 변환 예시는 `tests/test_db_tables.py`의 `to_row()`에 있다.
- **schema를 고치면 생성 코드도 같이 커밋한다.** `uv run python scripts/generate_contracts.py`를 실행한 결과를 함께 올린다. 공통 계약 변경이라 L1·L2·L3 담당자 전원의 승인이 필요하다.
- **마이그레이션 실행기는 같은 DB에서 한 번에 하나만 돈다.** 접속 직후 세션 단위 advisory lock(`LOCK_KEY`)을 잡고, 모든 적용이 끝나 연결을 닫을 때 푼다. 같은 DB에 동시에 돌리면 뒤에 온 쪽이 기다렸다가 남은 것만 적용한다(둘 다 exit 0). 60초(`LOCK_WAIT_SECONDS`)를 넘게 기다리면 `다른 마이그레이션이 실행 중이다(60초 기다렸다). 끝난 뒤 다시 실행한다`를 내고 아무것도 적용하지 않고 exit 1로 끝난다. 기다리는 동안은 아무것도 출력하지 않는다. 잠금은 DB마다 따로라 같은 서버의 다른 DB끼리는 막지 않는다. 1분 넘게 걸리는 마이그레이션이 생기면 그동안 뒤에 온 실행기는 exit 1로 끝나므로(적용은 하지 않는다) 다시 실행하거나, 그 이슈에서 한도를 다시 정한다. 잠금이 풀리지 않으면 `pg_locks`에서 `locktype = 'advisory'`인 세션을 찾는다.
- **번호가 겹치거나 적용한 파일을 바꾸면 실행기가 멈춘다.** 같은 대역에서 두 사람이 같은 번호를 쓰면 실행기는 아무것도 실행하지 않고 실패한다. 머지 전에 번호를 확인한다. 이미 적용한 번호의 파일 이름을 바꾸거나, 그 번호의 파일이 없거나, 내용을 고쳐도 멈춘다. 적용한 파일은 주석 한 글자도 고치지 않고 새 번호를 만든다(줄바꿈 `\r\n`↔`\n`만은 같은 내용으로 본다). 해시를 강제로 고치는 옵션은 없다. 개발 DB 하나를 여러 브랜치에서 같이 쓰면 다른 브랜치에서 적용한 번호의 파일이 없어 멈출 수 있으니, 그때는 새 DB를 쓴다.
- **마이그레이션은 자기 대역의 테이블만 바꾼다.** 번호 대역(0001~0099 공통, 0100~0199 수집·정규화·L1, 0200~0299 L2, 0300~0399 L3)은 병렬로 머지되므로 DB마다 대역 사이 적용 순서가 다를 수 있다. 0200을 적용한 DB에 늦게 머지된 0105가 들어오면, 실행기는 멈추지 않고 0105를 적용하면서 stderr에 `경고: 0105번(0105_….sql)은 이미 적용한 가장 큰 번호 0200번보다 작지만 적용한다(…)` 한 줄을 낸다. 새 DB는 번호 순서대로 적용되고 경고가 없다. 다른 대역의 테이블을 바꾸면 DB마다 스키마가 달라질 수 있다. 멈추게 하지 않은 것은, 하위 대역 PR이 늦게 머지될 때마다 모든 개발 DB를 다시 만들어야 하기 때문이다.
- **SQL 파일은 BOM 없는 UTF-8로 저장한다.** UTF-8이 아니면(예: Windows 한글 편집기의 CP949) `0002번(0002_….sql)을 UTF-8로 읽지 못했다(N번째 바이트)` `MigrationError`를 내고 `python -m soc.db.migrate`는 트레이스백 없이 exit 1로 끝난다. UTF-8 BOM으로 시작해도(메모장 등) `0002번(0002_….sql)이 UTF-8 BOM으로 시작한다. 마이그레이션 파일은 BOM 없는 UTF-8로 저장한다`로 같게 멈춘다. BOM을 떼고 적용하지 않는다. 실행기는 DB에 접속하기 전에 파일을 모두 읽으므로 이때는 아무것도 적용하지 않는다(`schema_migrations`도 만들지 않는다). 해시 비교와 적용은 이때 읽은 내용을 쓰고 파일을 다시 읽지 않는다. SQL 실행 오류는 다르다. 파일마다 따로 적용하므로 앞 번호는 적용된 채로 그 파일만 되돌리고 멈춘다.
- **이 브랜치의 예전 실행기로 마이그레이션한 로컬 DB는 다시 만든다.** `schema_migrations`에 `checksum` 칸이 없어 실행기가 `schema_migrations를 준비하지 못했다: column "checksum" does not exist`로 멈춘다(exit 1). 머지 전이라 새 마이그레이션을 만들지 않고 테이블 정의를 바로 고쳤기 때문이다. `0001` 헤더 주석을 고쳐(2026-11-04) 파일 해시도 바뀌었으므로, 그 전에 이 브랜치로 `0001`을 적용한 DB도 `이미 적용한 파일의 내용이 기록과 다르다`로 멈춘다. 이것도 다시 만든다.
- **마이그레이션 명령은 `.env`를 읽지 않는다.** `uv run --env-file .env python -m soc.db.migrate`처럼 환경변수를 넘긴다.
- **`db` 테스트에는 DB 생성 권한이 필요하다.** `DATABASE_URL` 계정으로 `soc_test_<랜덤>` DB를 만들고, 끝나면 `DROP DATABASE ... WITH (FORCE)`로 지운다. compose 계정과 CI 계정은 이 권한이 있다.
- **`validate_contract()`는 레포 루트 `contracts/`를 읽는다.** 레포 없이 wheel로만 설치하면 schema가 없어 `RuntimeError`가 난다. 배포 형태가 정해지면 바꾼다.
- **`new_id()`의 순서 보장은 한 프로세스 안에서만이다.** 프로세스끼리는 밀리초 단위까지만 맞는다.
- **`types.schema.json`이 생성 코드에 빈 별칭을 남긴다.** 정의만 있는 파일이라 아무도 쓰지 않는 `Types` 별칭이 생긴다. 무시해도 된다.
- **TypeScript 생성 코드는 아직 없다.** 첫 화면 이슈에서 붙인다.
- **Ticket 생성 모드는 키 이름만 있다.** 설정을 읽는 코드, `config/default.toml`, 시나리오 일치 판단, Ticket 생성은 수집·정규화 이슈가 만든다.
- **CI의 새 단계는 아직 돌지 않았다.** 생성 코드 차이 검사와 `db` job은 push 후 처음 돈다. 로컬에서는 같은 조건(`postgres:17.6`, trust 인증)의 임시 컨테이너로 확인했다.
- **OCSF 클래스별 검증은 정규화 이슈에서 반드시 한다.** 이 계약은 `ocsf`를 자유 객체로 두고 Alert의 `class_uid = 2004`와 Event의 `ocsf_class = ocsf.class_uid`만 검사한다. 정규화 결과의 `ocsf`는 해당 class_uid의 OCSF 1.9.0 공식 JSON Schema로 검증해야 하며, 쓰는 클래스마다(최소 Detection Finding 2004, Base Event 0, 매핑하는 이벤트 클래스) 공식 스키마 파일을 생성해 레포에 두고 검증한다(OCSF 정규화, D-007).
- **lock을 바꾸는 명령(`uv add`, `uv lock`, `uv remove`)은 uv 0.8.4~0.12.21로 한다.** `uv.lock`은 revision 3 형식이다. 임시 복사본에서 의존성을 하나 더해 확인했다. 0.8.4 미만(0.6.0·0.6.6·0.7.0·0.8.0·0.8.3)은 revision을 1·2로 내리고, 0.12.22 이상(최신 0.13.7 포함)은 5로 올린다. 예: `uvx --from 'uv==0.12.0' uv lock`. lock을 읽기만 하는 `uv lock --check`는 0.6.0부터 통과하고, revision 5 lock에서도 0.6.6·0.10.0·0.12.0의 `uv lock --check`가 통과한다(`uv sync --locked`는 버전별로 돌려 보지 않았다). revision 5로 옮기려면 팀이 함께 정한다.
- **예전 브랜치(#191 이전)에서 넘어왔으면 소스 없이 `__pycache__`만 남은 폴더를 폴더째 지운다**(예: `src/soc/l1/`). git이 무시하는 폴더라 남아 있기 쉽고, 소스가 없어도 `soc.l1` 같은 이름이 namespace package로 import된다. `__pycache__`만 지우면 빈 폴더가 남아 여전히 import된다(손으로 확인).

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run pytest`: 280개 통과(`db` 76개 제외). 주요 테스트:
  - `tests/test_contracts.py`: 올바른 샘플 35개(상한 경계값 포함)가 통과하고, 모델로 바꿔도 필드가 빠지지 않는다. 틀린 샘플 79개(integer 칸의 float·bool 7개 포함)는 기대한 경로·규칙으로 거부되고, 위반 rule은 약속한 이름뿐이다. JSON 사전 검사 84개(자유 객체 5칸 × 15종, 자유 객체 5칸 × 깊이 101, 2만 단계 1개, `verdict.confidence` NaN, `alert.title` NUL·짝 없는 서로게이트)는 `(root): json`으로 거부되고 메시지에 입력 값이 없다. 이모지가 든 값·키 11개(자유 객체 5칸 × 값·키, `alert.title`), 자유 객체 5칸 × 깊이 정확히 100, `number` 필드·자유 객체의 float 3개는 통과한다. 모든 schema pattern이 `^…$` 모양이고, 끝 `$` 처리 3개(이스케이프 포함)를 확인한다. 숫자 `const`·`enum`은 모두 `type: integer`와 함께 있다.
  - `tests/test_ids.py`, `tests/test_times.py`, `tests/test_migrate.py`
- `DATABASE_URL=<로컬 postgres:17.6 trust 컨테이너> uv run pytest -m db`: 76개 통과(`tests/test_db_tables.py`). 상한 경계값 샘플(int32 최댓값, 상한 시각)도 테이블에 들어가고, 세션 시간대 Pacific/Kiritimati(+14)·Asia/Seoul(+9)에서도 읽힌다. 이 시간대 테스트는 이전 상한(9999-12-31)에서 `timestamp too large (after year 10K)`로 실패하는 것을 확인했다. 끝난 뒤 남은 임시 DB 0개. JSON null 거부 테스트는 CHECK를 넣기 전 SQL에서 실패하는 것을 확인했다
- `DATABASE_URL` 없이 `uv run pytest -m db`: 76개 오류(건너뛰지 않음)
- triage·jsonb 모양 테스트: 새 제약을 넣기 전 SQL에서 실패하는 것을 확인했다. 리뷰 원안 식(`jsonb_typeof(triage) = 'object' AND triage ->> 'status' IN (...)`)으로는 `{}`, status 없음, status null이 여전히 통과해서 `IS TRUE`로 감쌌다
- 두 번째 리뷰 반영(2026-11-04): 항목마다 새 테스트가 고치기 전에 실패하는 것을 확인했다.
  - JSON이 아닌 값 15개: `ContractError`가 나지 않아 실패
  - 순환 참조 5개(리뷰 뒤 사람이 추가로 정함): `json.dumps`의 `ValueError`가 그대로 올라와 실패
  - 번호만 바꾼 마이그레이션(`IF NOT EXISTS`라 다시 실행돼도 오류 없음): `MigrationError`가 나지 않아 실패
  - ID 목록 거부 7개(NULL 원소 3, 빈 목록 4): CHECK 위반이 나지 않아 실패. 같은 값을 계약도 거부하는지 함께 확인한다. 허용 4개(L3 빈 목록, ID 여러 개)는 고치기 전후 모두 통과한다(제약이 너무 좁아지지 않았는지 지킨다)
  - 중복 ID 3개, 도구 호출 토큰 1개, 대상 ID 모양 4개(종류·접두사 불일치 3, hunt 빈 문자열 1): 거부되지 않아 실패
- 손으로 확인(임시 DB): 2차원 배열을 `alert_ids`·`ticket_ids`에 넣으면 `array_position`이 `feature_not_supported` 오류를 내서 들어가지 않는다
- 세 번째 리뷰 반영(2026-11-04): 항목마다 새 테스트가 고치기 전에 실패하는 것을 확인했다.
  - 끝에 `\n`이 붙은 ID 4개: `raw_record.id`·`ticket.alert_ids[0]`·`verdict.evidence_ids[0]`은 모델 단계의 `string_pattern_mismatch`로, `agent_log.subject_id`는 거부되지 않아 실패. pattern 모양 검사는 고치기 전후 모두 통과한다(새 pattern을 지킨다)
  - JSON 사전 검사 47개(자유 객체 5칸 × NaN·inf·-inf·NUL 값·NUL 키·int·None·bool·float 키, `verdict.confidence` NaN, `alert.title` NUL): 거부되지 않거나 다른 위반(`string_type`, `less_than_equal`)으로 실패
  - rule 약속 검사: 지금 코드에서는 통과한다. 1·2번 전 `validate.py`(1bf2ddb)를 임시 worktree에 두고 돌리면, `string_pattern_mismatch` 3건이 약속 밖으로 나오고 `subject_id` 샘플은 거부되지 않아 실패한다
  - `db` 테스트는 더하지 않았다. 올바른 샘플 전체를 `validate_contract()`로 검사한 뒤 INSERT하는 테스트(`test_valid_samples_fit_tables_and_read_back`)가 이미 있다
- 손으로 확인(커밋하지 않은 스크립트, 임시 DB): 첫 개발 때 문자열의 NUL, `details`의 NaN·Infinity가 계약을 통과한 뒤 INSERT에서 실패하는 것을 확인했고, 지금은 `validate_contract()`가 `(root): json`으로 거부한다. 짝 없는 서로게이트도 계약을 통과한 뒤 INSERT에서 실패하는 것을 확인했고, 지금은 같은 `(root): json`으로 거부한다
- 깊이 한도와 `RecursionError`: JSON 사전 검사는 깊이 100까지 받고 101부터 `(root): json`으로 거부한다(자유 객체 5칸 각각 테스트). `json.dumps`가 `RecursionError`를 내는 2만 단계도 같은 `(root): json`이다(테스트). 손으로 확인: Python 3.13.2(재귀 한도 1000)에서 `json.dumps`는 9000단계까지 통과하고 2만 단계에서 `RecursionError`를 낸다
- 네 번째 리뷰 반영(2026-11-04, 마이그레이션 내용 해시): 새 테스트가 고치기 전에 실패하는 것을 확인했다.
  - 해시 기록: `checksum` 칸이 없어(`UndefinedColumn`) 실패
  - 같은 이름으로 내용만 바꾸고 0002를 더함: `MigrationError`가 나지 않고 0002가 적용되어 실패
  - 줄바꿈만 바꾼 파일 2개(LF→CRLF, CRLF→LF)와 두 번 실행 테스트는 고치기 전후 모두 통과한다(검사가 너무 엄격해지지 않았는지 지킨다)
- 손으로 확인(임시 DB): `python -m soc.db.migrate`는 기록된 해시가 다르면 `0001번(0001_common_tables.sql)`을 담은 오류를 내고 exit 1로 끝난다. `checksum` 칸이 없는 예전 `schema_migrations`에서도 exit 1로 멈춘다
- 짝 없는 서로게이트 거부(2026-11-04): 새 테스트가 고치기 전에 실패하는 것을 확인했다.
  - 자유 객체 5칸 × 짝 없는 서로게이트 값(`\ud800`)·키(`\udfff`) 10개와 `alert.title` 1개: 거부되지 않아 실패
  - 이모지 통과 11개와 `db` 테스트(이모지가 든 Alert를 검증한 뒤 INSERT·읽기, `json.loads`로 읽은 이스케이프 쌍 포함)는 고치기 전후 모두 통과한다(지나치게 엄격하지 않은지 지킨다). 올바른 샘플에 BMP 밖 글자가 없어 기존 `db` 테스트로는 덮이지 않아 새로 넣었다
- 다섯 번째 리뷰 반영(2026-11-04): 항목마다 새 테스트가 고치기 전에 실패하는 것을 확인했다.
  - 깊이 한도: 자유 객체 5칸 × 깊이 101은 거부되지 않아 실패, 2만 단계는 `RecursionError`가 그대로 올라와 실패. 깊이 100 통과 5개와 `db` 테스트(깊이 100인 `raw_record.original`을 검증한 dict 그대로 INSERT·읽기)는 고치기 전후 모두 통과한다(한도가 너무 좁지 않은지, 통과한 값이 실제로 들어가는지 지킨다)
  - integer: `alert.time` 1793678578000.0, `alert.severity` 4.0, `incident.analysis_round` 1.0, `agent_log.tokens_in` 10.0 샘플 4개가 거부되지 않아 실패하고, rule 약속 검사도 같은 이유로 실패. `alert.severity` true 샘플은 고치기 전후 모두 통과한다(jsonschema가 원래 bool을 integer로 보지 않는다). `number` 필드·자유 객체의 float 3개도 고치기 전후 모두 통과한다(integer만 좁혔는지 지킨다)
  - 대역 사이 순서: 0001·0200을 적용한 뒤 0105를 더한 테스트는 경고가 없어 실패(0105는 고치기 전에도 적용됐다). 새 DB 번호 순서 테스트는 고치기 전후 모두 통과한다
  - UTF-8이 아닌 SQL(CP949) 2개: `UnicodeDecodeError`가 그대로 올라와 실패(`migrate()`, `main()`). 실행기가 DB에 접속한 뒤 파일을 읽어서 `db` 마커로 넣었다
- 손으로 확인(임시 DB, `src/soc`를 `/tmp`에 복사해 CP949 파일을 더하고 `PYTHONPATH`로 실행, 레포는 건드리지 않음): `python -m soc.db.migrate`가 `마이그레이션 실패: 0002번(0002_cp949.sql)을 UTF-8로 읽지 못했다(…)`만 출력하고 트레이스백 없이 exit 1로 끝난다
- 여섯 번째 리뷰 반영(2026-11-04, 마이그레이션 파일을 DB 접속 전에 읽기): 바꾼 테스트와 옮긴 테스트가 고치기 전에 실패하는 것을 확인했다.
  - `db`: 0001과 CP949 파일 0002를 두고 실행하면 `MigrationError`(번호·파일 이름·4번째 바이트)가 나고 DB에 테이블이 하나도 없다(`schema_migrations`도 없다). 다섯 번째 반영의 "0001만 적용됨"을 확인하던 `test_non_utf8_migration_stops_with_number_and_name`을 이렇게 바꿨다(`test_non_utf8_migration_applies_nothing`). 고치기 전에는 `first_table`과 `schema_migrations`가 있어 실패
  - `main()` 인코딩 오류 테스트를 `db` 마커 없는 `tests/test_migrate.py`로 옮겼다. `main()`은 `DATABASE_URL`이 있는지 먼저 보므로(없으면 exit 2) 환경변수를 빼지 않고 닫힌 포트의 가짜 주소를 넣는다. 접속을 먼저 하면 연결 오류가 나므로 접속 전에 읽는지도 함께 확인된다. 고치기 전에는 연결 오류 메시지만 나와 파일 이름이 없어 실패
  - 보호용(새로 만들지 않음): SQL 실행 오류에서 앞 번호가 적용된 채 멈추는 `test_failed_migration_rolls_back_only_that_file`과 새 DB 번호 순서 적용 `test_new_db_applies_bands_in_number_order_without_warning`은 고치기 전후 모두 통과한다
- 손으로 확인(같은 방식, 빈 임시 DB): `python -m soc.db.migrate`가 `마이그레이션 실패: 0002번(0002_cp949.sql)을 UTF-8로 읽지 못했다(4번째 바이트). …`만 출력하고 트레이스백 없이 exit 1로 끝난다. DB에 `schema_migrations`가 없고 테이블이 0개다
- 일곱 번째 리뷰 반영(2026-11-04, 숫자 `const`, BOM, 실행기 잠금, 파일 이름 정규식, `to_epoch_ms` 타입, CHECK 범위): 새 테스트가 고치기 전에 실패하는 것을 확인했다.
  - 숫자 `const`: Alert `class_uid_float`(`2004.0`)이 거부되지 않아 실패하고, rule 약속 검사도 같은 이유로 실패. schema 모양 검사는 `{"const": 2004}`에 `type`이 없어 실패
  - BOM: `db`(0001과 BOM 파일 0002 → `MigrationError`, 테이블 0개)는 0001이 적용된 뒤 `0002_bom.sql 적용 실패(그 파일은 되돌렸다): syntax error at or near "\ufeffCREATE"`가 나서 실패. `main()`(가짜 `DATABASE_URL`)은 연결 오류만 나와 파일 이름이 없어 실패
  - 잠금: 테스트가 `LOCK_KEY`를 import하므로, 상수 `LOCK_KEY`·`LOCK_WAIT_SECONDS`와 `lock_wait_seconds` 인자만 먼저 넣고(잠금 없음) 돌렸다. 다른 연결이 잠금을 잡은 동안 실행하는 테스트는 `MigrationError`가 나지 않고 적용돼서 실패, 잡았다 놓는 테스트는 "잠금을 기다리지 않고 끝났다"로 실패. 새 DB에 동시 실행 2개는 20번 돌려 20번 모두 실패했다. 리뷰가 예상한 파일 적용보다 앞의 `CREATE TABLE IF NOT EXISTS schema_migrations`가 `duplicate key value violates unique constraint "pg_type_typname_nsp_index"`로 실패했다(`IF NOT EXISTS`도 동시에 만들면 막지 못한다). 고친 뒤 잠금 테스트 4개를 30번 돌려 30번 모두 통과했다
  - 파일 이름: `٠٠٠١_x.sql`이 1번으로 인식돼 `MigrationError`가 나지 않아 실패
  - `to_epoch_ms`: `date`·`str`은 `TypeError`가 아니라 `AttributeError`가 나서 실패
  - 보호용(고치기 전후 모두 통과): Event `ocsf.class_uid = 4002.0` 샘플(schema가 이미 integer), 이름 끝 `\n` 파일(`glob`이 고르지 않음), 다른 DB의 잠금은 막지 않음(고치기 전에는 잠금이 없어서, 고친 뒤에는 advisory lock이 DB마다 따로라서 통과)
  - CHECK 범위: 코드는 바꾸지 않았다. `0001` 헤더 주석에 기준을 더했고 `db` 테스트 76개가 통과한다
- 손으로 확인(`src/soc`를 `/tmp`에 복사하고 `PYTHONPATH`로 실행, 레포는 건드리지 않음, 임시 DB):
  - BOM 파일 `0002_bom.sql`을 더하고 빈 DB에 `python -m soc.db.migrate`: `마이그레이션 실패: 0002번(0002_bom.sql)이 UTF-8 BOM으로 시작한다. …`만 내고 트레이스백 없이 exit 1, 테이블 0개
  - 두 프로세스 동시 실행: 2초 걸리는 `0002_slow.sql`을 더해 돌리는 동안 `pg_locks`에 advisory lock 잡음 1·대기 1이 보였고, 둘 다 exit 0(하나는 2개 적용, 하나는 "적용할 마이그레이션이 없다"), `schema_migrations`에 번호마다 1행. 실제 마이그레이션(`0001`)만으로 새 DB 5개에 동시 실행해도 5번 모두 둘 다 exit 0, 1행
  - 다른 세션이 잠금을 잡은 동안 `python -m soc.db.migrate`: 61초 뒤 `마이그레이션 실패: 다른 마이그레이션이 실행 중이다(60초 기다렸다). 끝난 뒤 다시 실행한다`만 내고 exit 1, 테이블 0개
  - `lock_timeout`은 `pg_advisory_lock`에도 걸린다(0.3초 한도로 0.31초에 `LockNotAvailable` 55P03). 트랜잭션 안에서 `set_config(..., true)`로 둔 값은 트랜잭션이 끝나면 0으로 돌아오고, 그 안에서 잡은 세션 단위 잠금은 남는다. 다른 DB에서는 같은 키를 바로 잡는다
  - psql 17.6의 BOM 처리: 클라이언트 인코딩 UTF8에서는 `psql -f`·`psql < 파일` 모두 BOM을 떼고 실행하고, LATIN1·SQL_ASCII에서는 `syntax error at or near "\ufeffSELECT"`
- `uv run python scripts/generate_contracts.py --check`: 차이 없음. 생성 파일에 한 줄을 더하면 exit 1
- 빈 DB에 `uv run python -m soc.db.migrate`를 두 번 실행: 1개 적용 → "적용할 마이그레이션이 없다"
- 최신 uv로 `uv lock --check`: 통과
