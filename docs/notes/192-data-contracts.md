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
  2. JSON Schema 검사. pattern 끝의 `$`는 `\Z`로 바꿔 검사한다(끝에 `\n`이 붙은 값 거부). `integer`는 Python int만 받는다(bool과 `4.0` 같은 float 거부)
  3. schema로 쓸 수 없는 규칙(Event의 `ocsf_class`)
  4. 생성 모델로 변환

  틀리면 필드 경로와 어긴 규칙만 담은 `ContractError`를 낸다.
- 계약 규칙 중 몇 가지: benign·malicious 판정은 근거 ID가 1개 이상이어야 한다. DB `integer` 컬럼에 대응하는 정수는 int32 상한을, 시각은 9999-12-30T23:59:59.999Z 상한을 둔다. SIEM 프로필·문서 참조·자산 엔티티 값은 빈 문자열을 거부한다. ID 목록(`alert_ids`, `ticket_ids`, `evidence_ids`)은 중복을 거부한다. Agent Log에서 도구 호출은 토큰이 null이고, `subject_id`는 `subject_type`에 맞는 ID여야 한다.
- `soc.ids.new_id(prefix)`는 접두사 + UUIDv7 ID를 만든다. `soc.contracts.to_datetime()`과 `to_epoch_ms()`는 계약의 밀리초와 DB의 `timestamptz`를 서로 바꾼다.
- `uv run python -m soc.db.migrate`는 `src/soc/db/migrations/`의 순번 SQL을 적용한다. 첫 파일 `0001_common_tables.sql`이 공통 테이블 7개를 만든다. DB CHECK는 최상위 목록 값, triage의 모양과 status, jsonb 칸의 모양(객체·목록), ID 목록(`alert_ids`, `ticket_ids`)의 NULL 원소와 개수까지 확인한다. 안쪽 필드는 validate_contract()가 확인한다. jsonb 칸은 JSON null도 거부한다. 실행기는 번호가 겹치거나, 파일 이름이 바뀌었거나, 적용한 파일이 없거나, 적용한 파일 내용이 바뀌면 아무것도 실행하지 않고 멈춘다. 내용은 `schema_migrations.checksum`에 적용할 때 기록한 해시(UTF-8로 읽어 `\r\n`을 `\n`으로 바꾼 뒤의 SHA-256 hex)와 비교한다. `.gitattributes`로 `*.sql`을 LF로 둔다. 기록된 가장 큰 번호보다 작은 미적용 파일(대역 사이 순서)은 멈추지 않고 적용하되 경고 한 줄을 낸다. UTF-8이 아닌 SQL 파일은 번호·파일 이름을 담은 `MigrationError`로 멈춘다.
- Ticket 생성 모드(`auto`/`scenario`)는 동작 없이 필드(`Alert.rule_id`, `Alert.triage`, `Ticket.origin`)와 설정 키 이름(`[ticketing] mode`, `scenario_rule_ids`)만 정했다.
- CI에 생성 코드 차이 검사와 `db` job(PostgreSQL 17.6 서비스 컨테이너)을 추가했다. `docs/architecture.md`를 계획대로 고쳤다.

## 계획과 달라진 점

- 사람이 정한 변경(JSON null 거부, OCSF 클래스별 검증 위치, 근거 필수, 정수·시각 상한과 시각 상한 조정, 빈 문자열 거부, `raw_id` 인덱스, 실행기의 파일 이름 비교, triage·jsonb 모양 제약, JSON이 아닌 값 거부, 실행기의 빠진 파일 확인, ID 목록 제약, 중복 ID 거부, 도구 호출 토큰, 대상 ID 모양, pattern 끝 `$` 처리, JSON 사전 검사 확장, 마이그레이션 내용 해시, 짝 없는 서로게이트 거부, JSON 깊이 한도, integer는 int만, 대역 사이 적용 순서 경고, UTF-8이 아닌 SQL 오류)은 계획 파일 "바뀐 점"에 있다.
- **`agent_log` `tokens_in = 10.0` 샘플의 rule은 `type`이 아니라 `anyOf`다.** 사람이 정할 때 기대한 rule은 `type`이었다. 하지만 `tokens_in`·`tokens_out`은 `anyOf[integer, null]`이고, 값의 타입이 어느 갈래와도 맞지 않으면 지금 매핑(`_branch_matching_type`)이 `anyOf`를 낸다. 고치기 전에도 `"x"`·`true`는 `anyOf`로 나왔다. 매핑은 바꾸지 않았다. 나머지 float 샘플(`time`, `severity`, `analysis_round`)은 `type`이다.
- **integer 반영에 보호용 테스트를 더했다.** `number` 필드(`verdict.confidence`의 1과 0.5)와 자유 객체 안의 float(`ticket.details`의 4.0)가 그대로 통과하는지 본다. 요청에는 없었고, integer만 좁혔는지 지키려고 넣었다.
- **실행기의 `_read_sql()`은 경로 대신 `Migration`을 받는다.** 오류 메시지에 번호와 파일 이름을 넣으려는 것이다(내부 함수).
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
- **integer 필드는 Python int만 받는다.** 시각·`severity`·`analysis_round`·토큰 같은 integer 필드에 `4.0`이나 `1793678578000.0` 같은 float를 넣으면 `type` 위반이다(null이 될 수 있는 `tokens_in`·`tokens_out`은 `anyOf`). bool은 원래부터 거부된다. Draft 7은 `4.0`도 integer로 보지만 생성 모델은 4로 바꿔 돌려주므로, 그대로 두면 검증한 dict와 모델이 달라진다. 검증한 dict를 그대로 저장해도 되게 하려는 것이다. SIEM 응답의 숫자가 float로 오면 정규화 코드가 int로 바꿔 넣는다. `number` 필드(`confidence`)와 자유 객체 안의 float는 그대로 받는다. schema와 생성 코드는 바꾸지 않았다(검사기의 integer 판정만 바꿨다).
- **짝 없는 서로게이트는 문자열을 UTF-8로 바꿔 보아 거부한다.** `json.dumps`는 `\ud800`으로 이스케이프해 통과시키지만, 그대로 두면 text 칸은 `UnicodeEncodeError`, jsonb 칸은 `InvalidTextRepresentation`으로 INSERT가 실패한다(임시 DB에서 손으로 확인). 이모지 같은 BMP 밖 글자는 통과한다. `json.loads`는 `"\ud83d\ude00"` 같은 이스케이프된 쌍을 한 글자로 합친다. 코드에서 서로게이트 두 개를 따로 붙인 문자열(`chr(0xD83D) + chr(0xDE00)`)은 UTF-8로 바꿀 수 없어 거부된다.
- **schema pattern은 `^`로 시작하고 `$`로 끝나게 쓴다.** `validate_contract()`가 끝의 `$`를 `\Z`로 바꿔 검사해 끝에 `\n`이 붙은 값을 거부한다(Python의 `$`는 마지막 `\n` 앞에서도 맞는다). schema에 `\Z`를 직접 쓰지 않는 것은 ECMA 정규식과 Rust regex(Pydantic)가 모르기 때문이다. 테스트가 모든 pattern의 모양을 검사한다. `\d`·`\w`·`\s`는 Python에서 유니코드 글자까지 맞으니 `[0-9]`처럼 범위를 적는다(지금 pattern 9개에는 없다).
- **Hunt 대상 Agent Log의 `subject_id`는 빈 문자열만 거부한다.** Hunt ID 형식이 아직 없어서다. L3 이슈에서 Hunt ID를 정할 때 `agent_log.schema.json`의 `hunt` 갈래(`minLength: 1`)를 그 ID 패턴으로 바꾼다. 공통 계약 변경이라 L1·L2·L3 담당자 전원의 승인이 필요하고, 접두사를 새로 만들면 `soc.ids.new_id()`와 `types.schema.json`에도 더한다.
- **DB는 ID 목록의 NULL 원소와 개수만 확인한다.** 중복과 접두사는 `validate_contract()`만 검사하고, 가리키는 행이 실제로 있는지는 각 단계 코드가 확인한다. 2차원 배열은 `array_position`이 CHECK 위반이 아닌 `feature_not_supported`(0A000) 오류를 내서 들어가지 않는다.
- **L1이 1차 판정 대기 알럿을 찾을 때는 `triage ->> 'status' = 'pending'`으로 쓴다.** 이 식이어야 식 인덱스 `alerts_triage_status_idx`를 탄다. `triage -> 'status' = '"pending"'`처럼 다른 식으로 쓰면 인덱스를 타지 않는다.
- **DB에 접속하는 코드는 세션 시간대를 UTC로 둔다**(예: 연결 옵션 `-c TimeZone=UTC`). psycopg는 timestamptz를 세션 시간대로 바꿔 돌려주므로, UTC가 아니면 시각이 바뀌어 보이고 상한 근처 값은 읽기에서 실패할 수 있다.
- **DB가 JSON null을 거부하므로 SQL NULL을 넣어야 한다.** null이 될 수 있는 `alerts.triage`, `tickets.verdict`, `agent_logs.output`에 None을 쓸 때 psycopg `Jsonb(None)`을 넘기면 JSON null(`'null'::jsonb`)이 되어 CHECK 위반으로 거부된다. 값 None을 그대로 넘겨 SQL NULL로 넣는다. 객체·목록 칸은 모양(객체·목록)까지 확인하므로 JSON null도 거부된다. `agent_logs.input`만 JSON null을 받는다(계약상 JSON 값 전체). 변환 예시는 `tests/test_db_tables.py`의 `to_row()`에 있다.
- **schema를 고치면 생성 코드도 같이 커밋한다.** `uv run python scripts/generate_contracts.py`를 실행한 결과를 함께 올린다. 공통 계약 변경이라 L1·L2·L3 담당자 전원의 승인이 필요하다.
- **마이그레이션 실행기에는 잠금이 없다.** 같은 대역에서 두 사람이 같은 번호를 쓰면 실행기는 아무것도 실행하지 않고 실패한다. 머지 전에 번호를 확인한다. 이미 적용한 번호의 파일 이름을 바꾸거나, 그 번호의 파일이 없거나, 내용을 고쳐도 멈춘다. 적용한 파일은 주석 한 글자도 고치지 않고 새 번호를 만든다(줄바꿈 `\r\n`↔`\n`만은 같은 내용으로 본다). 해시를 강제로 고치는 옵션은 없다. 개발 DB 하나를 여러 브랜치에서 같이 쓰면 다른 브랜치에서 적용한 번호의 파일이 없어 멈출 수 있으니, 그때는 새 DB를 쓴다. 실행기 두 개를 동시에 돌리면 막지 못한다.
- **마이그레이션은 자기 대역의 테이블만 바꾼다.** 번호 대역(0001~0099 공통, 0100~0199 수집·정규화·L1, 0200~0299 L2, 0300~0399 L3)은 병렬로 머지되므로 DB마다 대역 사이 적용 순서가 다를 수 있다. 0200을 적용한 DB에 늦게 머지된 0105가 들어오면, 실행기는 멈추지 않고 0105를 적용하면서 stderr에 `경고: 0105번(0105_….sql)은 이미 적용한 가장 큰 번호 0200번보다 작지만 적용한다(…)` 한 줄을 낸다. 새 DB는 번호 순서대로 적용되고 경고가 없다. 다른 대역의 테이블을 바꾸면 DB마다 스키마가 달라질 수 있다. 멈추게 하지 않은 것은, 하위 대역 PR이 늦게 머지될 때마다 모든 개발 DB를 다시 만들어야 하기 때문이다.
- **SQL 파일은 UTF-8로 저장한다.** UTF-8이 아니면(예: Windows 한글 편집기의 CP949) `0002번(0002_….sql)을 UTF-8로 읽지 못했다(N번째 바이트)` `MigrationError`를 내고 `python -m soc.db.migrate`는 트레이스백 없이 exit 1로 끝난다. 파일은 DB에 접속한 뒤 해시를 비교하거나 적용할 때 읽으므로, 그 앞 번호의 미적용 파일은 이미 적용됐을 수 있다. 그래서 이 테스트는 `db` 마커다.
- **이 브랜치의 예전 실행기로 마이그레이션한 로컬 DB는 다시 만든다.** `schema_migrations`에 `checksum` 칸이 없어 실행기가 `schema_migrations를 준비하지 못했다: column "checksum" does not exist`로 멈춘다(exit 1). 머지 전이라 새 마이그레이션을 만들지 않고 테이블 정의를 바로 고쳤기 때문이다.
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
- `uv run pytest`: 271개 통과(`db` 72개 제외). 주요 테스트:
  - `tests/test_contracts.py`: 올바른 샘플 35개(상한 경계값 포함)가 통과하고, 모델로 바꿔도 필드가 빠지지 않는다. 틀린 샘플 77개(integer 칸의 float·bool 5개 포함)는 기대한 경로·규칙으로 거부되고, 위반 rule은 약속한 이름뿐이다. JSON 사전 검사 84개(자유 객체 5칸 × 15종, 자유 객체 5칸 × 깊이 101, 2만 단계 1개, `verdict.confidence` NaN, `alert.title` NUL·짝 없는 서로게이트)는 `(root): json`으로 거부되고 메시지에 입력 값이 없다. 이모지가 든 값·키 11개(자유 객체 5칸 × 값·키, `alert.title`), 자유 객체 5칸 × 깊이 정확히 100, `number` 필드·자유 객체의 float 3개는 통과한다. 모든 schema pattern이 `^…$` 모양이고, 끝 `$` 처리 3개(이스케이프 포함)를 확인한다.
  - `tests/test_ids.py`, `tests/test_times.py`, `tests/test_migrate.py`
- `DATABASE_URL=<로컬 postgres:17.6 trust 컨테이너> uv run pytest -m db`: 72개 통과(`tests/test_db_tables.py`). 상한 경계값 샘플(int32 최댓값, 상한 시각)도 테이블에 들어가고, 세션 시간대 Pacific/Kiritimati(+14)·Asia/Seoul(+9)에서도 읽힌다. 이 시간대 테스트는 이전 상한(9999-12-31)에서 `timestamp too large (after year 10K)`로 실패하는 것을 확인했다. 끝난 뒤 남은 임시 DB 0개. JSON null 거부 테스트는 CHECK를 넣기 전 SQL에서 실패하는 것을 확인했다
- `DATABASE_URL` 없이 `uv run pytest -m db`: 72개 오류(건너뛰지 않음)
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
- `uv run python scripts/generate_contracts.py --check`: 차이 없음. 생성 파일에 한 줄을 더하면 exit 1
- 빈 DB에 `uv run python -m soc.db.migrate`를 두 번 실행: 1개 적용 → "적용할 마이그레이션이 없다"
- 최신 uv로 `uv lock --check`: 통과
