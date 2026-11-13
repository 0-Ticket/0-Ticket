# 결정 목록

팀이 정한 도구와 방식이다. "확정"인 것만 코드에 들어간다. 이 목록은 2026-11-03, PR #191부터 쓴다. 번호가 #191보다 작은 이슈·PR에 적힌 결정 번호는 이 목록과 관계없다.

## 상태

| 상태 | 뜻 |
|---|---|
| 확정 | 팀이 정했다. 코드에 쓴다 |
| 후보 | 유력하지만 팀이 아직 의논하지 않았다. 쓰려면 계획 이슈에서 확정한다 |
| 담당자가 정함 | 그 부분을 구현하는 담당자가 계획 이슈에서 정한다. 예시는 참고용이다 |
| 추후 | 지금은 만들지 않는다 |
| 폐기 | 쓰지 않기로 했다 |

## 쓰는 법

- 정할 것이 생기면 계획 이슈의 "어떻게"에 적는다. `/soc-plan`이 확정되지 않은 도구나 방식을 발견하면 안건으로 올린다.
- 사람이 정하면 이 문서의 해당 행을 "확정"으로 옮기고 맨 아래 "기록"에 한 줄을 남긴다. 상태는 사람만 정하고, 사람이 정한 것을 AI가 받아 적는 것은 괜찮다.
- 결정을 바꾸면 같은 ID의 내용을 고치고 기록에 남긴다. 번호는 다시 쓰지 않는다.
- 다른 문서에서 결정을 가리킬 때는 `PostgreSQL(D-012)`처럼 설명을 먼저 쓰고 괄호에 ID를 쓴다. ID만 쓰지 않는다.

## 확정

### 기반

| ID | 결정 | 메모 |
|---|---|---|
| D-001 | 백엔드는 Python 3.13 + uv. 린트·포맷 ruff, 테스트 pytest | CI와 같은 명령 |
| D-002 | 설정 파일은 TOML. 기본 설정 위에 조직 설정 파일을 덮어쓴다 | 비밀 값은 넣지 않고 환경변수 이름만 적는다. 조직 설정 파일은 `config/local.toml`처럼 `config/local.*` 이름을 쓰고 커밋하지 않는다 |
| D-003 | 데이터 계약의 원본은 JSON Schema. Python(Pydantic)·TypeScript 코드는 생성하고, 생성 코드는 직접 고치지 않는다 | 계약 원본은 `contracts/`(JSON Schema draft-07). Python은 datamodel-code-generator로 `src/soc/contracts/generated/`에 생성한다. TypeScript는 json-schema-to-typescript로 contracts/에서 생성한다. API 전용 포장 타입은 응답 모델이 내보내는 JSON Schema에서 같은 도구로 생성한다(#266). 생성은 `scripts/generate_contracts.py`, CI는 `--check`로 차이를 검사한다 |
| D-004 | 라이선스는 Apache-2.0 | |
| D-039 | HTTP 클라이언트는 httpx(`httpx==0.28.1`). 리다이렉트는 따라가지 않는다 | 응답 크기 상한은 스트리밍하면서 압축을 푼 바이트로 세고, 요청 단위 timeout과 별도로 출처별 전체 마감 시간을 둔다. openai 3.x가 끌어오는 `httpx2`와 따로 설치된다. httpx는 2024-12 이후 릴리스가 없어, 보안 수정이 필요한데 나오지 않으면 다시 논의한다(#221) |
| D-041 | SSH 라이브러리는 asyncssh(`asyncssh==2.24.1`) | 라이선스는 EPL-2.0 OR GPL-2.0-or-later이고, 수정 없이 import만 한다. 버전은 고정하고 함께 들어오는 패키지는 `uv.lock`으로 고정한다(#213) |

### 수집 · 정규화

| ID | 결정 | 메모 |
|---|---|---|
| D-005 | 외부 SIEM 하나에 설정으로 연결만 한다. 여러 SIEM을 동시에 연결하지 않고, 연결 정보를 프로필로 두어 쉽게 바꿀 수 있게 한다 | SIEM 구축·운영은 범위 밖 |
| D-006 | 처음 연결할 SIEM은 ELK | 다른 SIEM은 필요해질 때 |
| D-007 | 알럿·이벤트 정규화 형식은 OCSF 1.9.0, 라이브러리 없이 직접 구현 | SIEM이 바뀌어도 같은 형태로 다룬다. 정규화 결과의 OCSF 객체는 OCSF 서버의 1.9.0 클래스·객체 정의로 검증한다. 클래스별 공식 JSON Schema 파일을 두도록 한 기존 검증 방식은 #234에서 바꿨다 |
| D-008 | SIEM에서 가져온 원본 Alert·Event는 바꾸지 않고 보관하며, 정규화 결과는 별도 테이블에 둔다 | 보관 기간은 설정 값 |
| D-049 | `raw_records` 원본은 `text`(JSON 글자, `original_text`)로 보관한다. 이스케이프는 `json.dumps(..., ensure_ascii=True)`다. 정규화 결과의 NUL·짝 없는 서로게이트는 `\u0000`·`\udXXX` 6글자로 치환한다(문자열 값과 dict 키 모두, `_normalize_and_save`에서) | jsonb는 `\u0000`을 받지 않아 NUL 문서 하나가 페이지 저장을 실패시켰다(#277). 원본은 `json.loads`로 SIEM이 준 JSON 그대로 되살린다(D-008). `CHECK (left(original_text, 1) = '{')`. `siem_ref`는 `<_index>/<_id>`를 JSON 문자열 이스케이프한 값(따옴표 제외)이다. 마이그레이션 `0106`은 빈 `raw_records`에서만 적용된다 |
| D-050 | 저장할 수 없는 hit는 `ingest_quarantine`에 원문과 이유를 격리한다. 페이지 단위 트랜잭션에서 RawRecord·격리 행·체크포인트를 저장한다. 격리 키는 모든 격리 hit에 위치 토큰과 안정 hit 해시를 넣으며, Base64url 페이로드가 128자를 넘으면 `h`와 해당 JSON 바이트의 SHA-256 hex로 축약한다. 완전히 같은 키는 한 행으로 병합한다. 일시 오류 요청마다 최대 3회, 정렬 값 문제 페이지 재조회마다 최대 3회로 별도 계산한다. 재시도 사이에는 1초 대기한다. `ingest_run`은 신규 격리 수를 기록한다 | NaN·±Infinity와 깊이 100 초과도 격리한다. NUL·짝 없는 서로게이트는 D-049에 따라 보존한다. 전체 원문은 `original_text`에 남긴다. 마지막 hit의 정렬 값 문제가 지속되면 페이지 행은 커밋하고 체크포인트는 유지한 채 실패한다. D-008 보관 설정·삭제와 운영자 알림·복구는 후속 이슈다(#294) |

### 에이전트

| ID | 결정 | 메모 |
|---|---|---|
| D-009 | 기본 LLM은 Azure AI Foundry `gpt-oss-120b`(OpenAI 호환 v1 API, Chat Completions). 주소·모델(배포) 이름·키 환경변수 이름은 설정 값이라 코드를 고치지 않고 Groq·Ollama 같은 다른 OpenAI 호환 제공자로 바꿀 수 있다 | 실제 연결·구독·리전은 #224에서 확인했다(`docs/notes/224-l3-real-model.md`). Foundry는 도구 정의에 strict를 켜면 최종 답이 빈 문자열로 와서 `[llm] strict_mode` 기본값은 `false`다(#215) |
| D-010 | SIEM 조회 도구는 읽기 전용이다 | |
| D-011 | SSH 도구는 읽기 전용이다. 접속 대상·계정·허용 명령은 설정 값이고 기본은 비어 있어 전부 거부한다. 키는 환경변수로만 읽는다. 허용 단위는 인자까지 포함한 명령 템플릿이다. SSH는 원격 서버의 셸이 명령 문자열을 다시 해석하므로, 인자 자리에 들어가는 값은 허용 형식만 받고 셸 특수문자가 들어 있으면 거부한다. 인자 값이 `-`로 시작하면 거부한다. 옵션으로 해석돼 명령이 쓰기·삭제로 바뀌는 것을 막기 위해서다. 원격 접속 계정은 읽기 권한만 가진 계정을 쓴다. 문자열 검사가 뚫려도 쓰기가 되지 않게 하는 마지막 방어선이다 | 원격 셸 해석을 막는 구체 방법(#213): 모델은 설정에 이름을 붙인 호스트와 코드에 정해진 점검 이름만 고르고, 명령 본문과 인자 모양은 코드 상수다(설정은 호스트별로 켤 점검만 정한다). 인자는 허용 문자만 받는다. 정수는 범위만 보고, 경로는 `/`로 시작하고 `[A-Za-z0-9._/-]`만 쓰며 256자 이하이고 `..` 구간·연속 `/`·끝의 `/`는 받지 않는다. `-`로 시작하는 값은 모두 거부한다. 통과한 값도 정수까지 문자열로 바꿔 `shlex.quote`로 감싸 명령에 넣는다. 원격 `authorized_keys`의 `command=` 제한은 운영자가 더할 수 있는 두 번째 방어선이다(코드로 만들지 않는다) |
| D-022 | 에이전트 프레임워크는 OpenAI Agents SDK(`openai-agents==0.24.0`, `openai==3.42.1`). Chat Completions 경로(`OpenAIChatCompletionsModel`)로 붙이고, 에이전트를 실행하는 코드 진입점에서 `set_tracing_disabled(True)`로 트레이싱을 끈다 | 트레이싱은 기본으로 켜져 있고 모델 입력·출력을 OpenAI 서버로 보낸다(`docs/security.md`). 환경변수에 맡기지 않는다. 구조화 출력(`output_type`)과 병렬 도구 호출은 쓰지 않는다. 함께 들어오는 패키지는 `uv.lock`으로 고정한다 |
| D-023 | 에이전트 도구는 파이썬 함수 도구 레지스트리(`soc.tools`의 `ToolRegistry`·`ToolSpec`)로 만들고 Agents SDK 함수 도구(`FunctionTool`)로 감싼다. MCP 서버는 쓰지 않는다 | 도구는 단계별 허용 목록(`[tools.allowed]`)에 있는 것만 SDK에 등록한다. MCP 노출은 필요해지면 레지스트리 위에 얹는다(#211) |
| D-024 | 에이전트 구조는 에이전트 하나 + L1·L2·L3 프롬프트 오버라이딩 + 단계별 스레드다. 파이프는 `run_agent(AgentTask) -> AgentResult`(동기) 하나로 부른다 | 단계별 스레드는 "스레드마다 실행 루프"다. `run_agent`가 안에서 `Runner.run_sync`를 쓴다(#209 계획). 실행기(`soc.agent.executor`)는 단계 스레드마다 asyncio 이벤트 루프를 하나 만들어 그 스레드의 기본 루프로 등록하고, `run_sync`가 그 루프를 쓰게 한다. 루프에서 직접 비동기 코드를 돌리지는 않고, 종료할 때 진행 중인 run을 취소(`cancelled`)하는 데만 쓴다(#215) |
| D-025 | L1 판정 결과 조건. 확신도 임계값은 `[agent.l1]`의 `confidence_threshold = 0.8`이다. `pending` Alert는 `benign`이면 확신도와 관계없이 `held`(Ticket 없음), `malicious`이고 임계값 이상이면 `promoted`와 `origin=l1` Ticket 생성, 그 밖에는 `held`다. `new` Ticket은 `benign`이고 임계값 이상이면 `closed`, `malicious`이고 임계값 이상이면 `escalated`, 그 밖에는 `held`다. 실패한 작업은 최초 실행을 포함해 총 3회까지 시도하고, 마지막에도 실패하면 `held`로 둔다. `cancelled`는 실패 횟수에 넣지 않는다 | `undetermined`, 임계값 미만, 형식·근거·최종 실행 오류는 보류한다. Alert 승격과 Ticket 생성은 한 트랜잭션으로 처리하며, 현재 상태가 `pending`/`new`일 때만 결과를 적용해 재실행으로 중복 생성하지 않는다. 실패 횟수는 워커 재시작 뒤에도 유지한다. 정확한 저장 위치는 구현 이슈에서 정한다(#251) |
| D-048 | 외부 LLM으로 보내는 모델 입력(입력 데이터·도구 결과·형식 오류 재요청)은 보내기 직전에 SDK 입력 필터 한 곳에서 비밀 값을 `[REDACTED]`로 가린다. 규칙은 Agent Log 쓰기 직전 가림과 같고 같은 가림 함수를 쓴다. 가림 중 예외가 나거나 JSON 값이 아닌 타입을 만나면 원문을 보내지 않고 run을 `provider_error`로 끝낸다. 근거 ID 모양 값(접두사 + UUIDv7)은 환경변수 값 치환에서만 건너뛴다. 도구 쪽에서 비밀이 나올 자리를 미리 빼지는 않는다 | 규칙: 설정 `*_env`가 가리키는 환경변수 값(8자 이상), DB 비밀번호, `password`·`passwd`·`pwd`(값이 `/`로 시작하는 두 단계 이상 경로면 제외)·`api_key`·`token`·`secret` 계열의 `=`·`:` 값, `Bearer`, `Authorization: Basic\|ApiKey`, 비밀 키 이름의 객체 값(숫자·배열·객체 값 포함. 페이지 이동 표지 `next_token` 등은 제외). 입력 데이터와 도구 결과(`<태그>`로 감싼 JSON)는 JSON으로 풀어 객체 키 규칙을 적용하고 바뀐 것이 없으면 원문 그대로 둔다. 환경변수 값은 JSON 이스케이프 모양도 가린다. 모양을 모르는 비밀, 8자 미만 비밀, 명령줄(`--password 값`)·이름·값 쌍 헤더는 못 가린다. 한계는 `docs/security.md`. SSH `processes`의 명령줄 위험은 #213 그대로다. 필터는 같은 입력 이력이면 항상 같은 결과를 낸다(D-036 `input_from` 접두 비교). Agent Log의 model 줄 `input`과 `records` 도구 줄 `output`은 모델이 받은 입력과 같아진다(`text`·`aggregate` 도구 줄은 자르기 전 원본이다). 표시(`details.redacted`)는 만들지 않는다(#279) |
| D-049 | 도구의 동기 핸들러(DB·SIEM)는 호출마다 전용 데몬 스레드에서 돌리고 레지스트리가 `asyncio.wrap_future`로 기다린다. `async def` 핸들러(SSH)는 이벤트 루프에서 그대로 await한다. 취소하면 기다림만 끊고 진행 중인 DB 문장·HTTP 요청은 끝까지 두며 결과는 버린다. 취소로 버려진 스레드가 생기면 `soc.agent.executor` 로그에 도구 이름과 경과 시간만 WARNING으로 남긴다. `asyncio.to_thread`와 async 클라이언트(psycopg async, `httpx.AsyncClient`)는 쓰지 않는다 | `to_thread`의 기본 실행기 스레드는 프로세스 종료 때 합류돼 종료가 도구 시간만큼 붙잡히고(#278), psycopg async는 Windows 기본 이벤트 루프(`ProactorEventLoop`)에서 동작하지 않는다. 핸들러는 별도 스레드에서 돌므로 `ctx`와 자기 인자 밖의 스레드 로컬·`contextvars`에 기대지 않는다. 한계: 버려진 스레드는 DB는 접속·문장 시간 제한 안에, SIEM은 `deadline_seconds` 안에 끝나지만 DB 서버가 얼면 제한이 없다. 서버 쪽 문장 취소와 DB 정지 동작은 실제 PostgreSQL로 확인하지 못했다(#280) |
| D-050 | 실행기 단계 스레드의 예외 처리와 종료 코드. `poll`·`handle`의 `Exception`·`CancelledError`·`SystemExit`은 예외 종류만 로그에 남기고 다음 건으로 간다. 그 밖의 `BaseException`과 단계 스레드 자체의 오류는 그 단계를 죽은 것으로 표시하고, 메인 루프가 감지해 다른 단계를 정리한 뒤 종료 코드 3으로 끝난다. 죽은 스레드를 재시작하지 않는다. 종료 코드는 0 정상, 1 종료 대기 시간 초과, 2 설정 오류, 3 단계 스레드가 죽음이다 | 예외 메시지는 밖에서 온 문자열일 수 있어 남기지 않고, 스레드 밖으로 다시 올리지 않는다(`threading.excepthook`이 메시지가 든 트레이스백을 찍는다). `SystemExit`을 치명으로 두면 한 건이 프로세스를 죽이고 재시작 뒤에도 같은 건이 다시 나온다. 재시작은 `BaseException` 뒤 상태를 믿을 수 없어 하지 않고, 프로세스 재시작은 프로세스 관리자의 몫이다. 실행기는 라운드마다 워커별 받은 건수·처리 건수·처리 시간을 `soc.agent.executor`에 INFO로 남긴다. 대기 시간·DB·화면 지표는 새 이슈(#295)에서 각 담당과 정한다(#280) |
| D-051 | 위협 인텔 조회 도구 `lookup_indicator`는 VirusTotal API v3 무료 키를 httpx(D-039)로 부른다. 지표 값(IP·도메인·해시)만 보내고, 공개 주소가 아니거나 비공개 이름이거나 설정 제외 목록에 있는 값은 보내지 않는다. 캐시와 호출 한도는 프로세스 메모리에 두며 재시작하거나 프로세스가 여럿이면 따로 센다. 키는 `VT_API_KEY` 환경변수로만 읽고, 키가 없으면 도구를 등록하지 않는다 | 무료 키 약관은 상업 이용을 제한한다(PR "이유"에 적는다). 회사의 공개 도메인은 설정 제외 목록에 적지 않으면 나간다. l3는 허용하지 않는다(#309) |
| D-052 | 로컬 ATT&CK·KEV 조회 도구 `get_attack_technique`·`search_attack_techniques`·`get_cve`는 네트워크 없이 PostgreSQL의 저장본만 읽고, 허용 단계는 `l2`·`l3`다. 에이전트 읽기 역할 `soc_agent_reader`에는 `attack_techniques`·`kev_entries`·`intel_source_state`의 SELECT만 주고 `threat_news`는 주지 않는다. KEV 상세는 새 테이블 `kev_entries`에 저장하고(`threat_news`는 그대로), 응답에는 데이터 버전·수집 시각을 넣는다. KEV에 없는 CVE는 `not_in_kev`(KEV 목록에 없다는 뜻이지 악용되지 않는다는 뜻이 아님), 데이터가 없으면 `no_data`다. 도구가 읽는 ATT&CK 버전은 `[tools.local_intel] attack_version`이고 `[l3.intel.attack] version`과 함께 바꾼다 | 0300의 "에이전트 읽기 역할에 이 테이블 권한을 주지 않는다"를 이 세 테이블에 한해 바꾼 것이다. NVD 등 KEV 밖의 CVE 데이터는 적재하지 않는다. 기법·CVE 문자열은 밖에서 온 데이터로 다룬다(D-048 입력 필터를 그대로 거친다). 지난 계획·기록(221)은 고치지 않는다(#311) |
| D-053 | 유사 사례 검색 도구 `search_similar_cases`는 판정이 끝난 Ticket을 담은 Qdrant 컬렉션(용도 `ticket_verdicts`)을 임베딩 유사도로 읽고, 허용 단계는 `l1`·`l2`다. L1 판정이 적용된 직후 `verdict`가 있는 Ticket을 같은 프로세스에서 색인하며 point ID는 Ticket ID이고 payload는 비운다. 색인 텍스트는 Alert 제목·Event 요약·Hunt 문장이고 판정 이유는 넣지 않는다. 상태·판정·시각·엔티티는 PostgreSQL에서 읽으므로 `soc_agent_reader`에 `tickets`(id, status, verdict, entities, alert_ids, created_at)·`incidents`(id, ticket_ids, status)·`cases`(id, incident_id)의 열 단위 SELECT를 준다. `decided_by`는 그 Ticket의 Incident에 Case가 있으면 `human`, 그 밖에는 `agent`다. `ticket_id` 검색은 자기 자신과 같은 Incident의 Ticket을 뺀다. 실행기가 임베더를 한 번 만들어 도구 세션에 주입하며, Qdrant 환경변수나 임베더가 없으면 도구를 등록하지 않는다 | Qdrant 쓰기는 PostgreSQL 트랜잭션에 묶지 않아 누락될 수 있고 재색인 명령으로 복구한다(D-013). 판정 이유를 임베딩하지 않는 것은 질의 쪽에 이유가 없어 같은 종류의 텍스트끼리 비교하고, LLM이 쓴 문장이 검색 순위를 좌우하지 않게 하려는 것이다. `decided_by=agent` 사례 경고는 프롬프트 수준이며 D-025의 자동 종결을 구조적으로 막지 못한다. 0003의 "tickets·incidents·cases에 권한을 주지 않는다"를 이 세 표의 위 열에 한해 바꾼 것이다. `python -m soc.agent` 프로세스에 약 2.27GB 모델이 올라간다. L1 담당과 L2 담당이 확인했다(#313) |

### L2

| ID | 결정 | 메모 |
|---|---|---|
| D-027 | Incident 분류 방법. 규칙으로 후보 Incident를 추리고 최종 선택만 에이전트가 한다. 후보 조회 경로는 설정으로 고르며 기본은 `vector`다. vector는 비슷한 Ticket이 속한 Incident를 최고 유사도 순으로, `recent`는 시간 창 안의 열린 Incident를 `updated_at` 순으로 고른다. 엔티티 겹침으로 후보를 추리거나 줄 세우지 않는다. 임베딩 텍스트가 비었거나 컬렉션이 없거나 조회가 실패하거나 PostgreSQL 확인 뒤 유효 후보가 없으면 recent로 떨어진다. 분류 전용 에이전트는 두지 않고 같은 에이전트에 분류용 프롬프트를 덮어쓴다(에이전트 구조, D-024). 에이전트가 실패하거나 후보에 없는 Incident를 고르면 새 Incident를 만든다. 보류하지 않는다. 저장 직전에 Ticket과 고른 Incident를 잠그고 상태를 다시 본 뒤 한 트랜잭션으로 저장한다 | 엔티티 겹침을 빼는 이유는 겹침으로 줄 세우면 엔티티가 겹치지 않는 같은 공격을 뒤로 밀어 벡터 검색의 목적을 없애기 때문이다. 그 대신 해시나 계정이 같은데 Alert 서술이 달라 유사도가 낮은 Ticket은 묶지 못할 수 있다. 에이전트가 실패했을 때 기존 Incident에 붙이지 않는 것은 유사도만으로 떨어뜨리면 근거가 약한 Incident에 붙을 수 있고 틀리게 묶인 것을 되돌릴 수단이 없기 때문이다. 보류하지 않는 이유는 Ticket이 어디에도 붙지 못하는 쪽이 더 나쁘고, 분류는 판정이 아니라 묶기라 새 Incident라는 결정적인 대안이 있기 때문이다. 확신도는 분류 출력에 담아 Agent Log에 남기되 판정에는 쓰지 않는다. 저장 직전 Ticket을 잠가 여러 실행기 프로세스의 중복 저장을 막고, 모델 호출 중에는 트랜잭션을 열어 두지 않는다. `origin = l3` Ticket은 Alert가 없을 수 있어 `hunt_id`로 Hunt를 읽는다(Hunt 계약, #217). 분류 출력은 `contracts/`에 계약으로 둔다. 시간 창·후보 수·벡터 조회 상한은 설정 값이고, 시간 창은 PostgreSQL에서 Incident에 한 번 적용하며 벡터 쪽 Ticket 시각으로는 거르지 않는다. 벡터 검색은 참 후보를 놓치거나 무관한 후보를 낼 수 있고 최종 선택은 에이전트가 한다. 잘못 연결된 Ticket을 자동으로 떼거나 재배정하는 기능은 없어 같은 공격의 상관관계가 나뉜 채 남을 수 있다. 실행 중 같은 차원의 다른 거리 방식으로 컬렉션이 바뀌면 다음 워커 재시작 전까지 감지하지 못한다 |
| D-028 | L2 재분석은 새 Ticket이 자동 분석 가능한 Incident에 붙었을 때와 사람이 반려했을 때 한다. `human_handling`에 새 Ticket이 붙어도 자동 재분석하지 않는다. L2 조사 중 찾은 근거·엔티티는 해당 라운드 판정에 쓰되 재분석 신호로 삼지 않는다. `analysis_round`는 성공·실패마다 증가하는 기록용 순번이며 상한을 두지 않는다. 연속 실패는 별도 카운터로 최초 실행 포함 3회까지만 시도하고, 소진하면 `held`로 옮긴다. `held_at`부터 설정한 쿨다운이 지나면 자동으로 `analyzing`으로 되돌려 실패 카운터를 초기화한다. `cancelled`는 어느 카운터에도 넣지 않는다. 분석 중 새 Ticket이 붙으면 현재 Artifact는 저장하되 `analyzing`을 유지해 새 Ticket을 다시 분석한다. `review_round`가 한도(기본 2)에 이르면 `human_handling`으로 넘긴다 | 조사 중 얻은 정보가 스스로 재분석을 트리거하지 않게 하면서 외부 입력으로 인한 재분석 횟수는 제한하지 않는다. 실패 한도와 쿨다운은 `[l2.analyze]` 설정 값이다. 쿨다운은 Ticket 연결 시 바뀌는 `updated_at`이 아니라 `details.l2_analyze.held_at`을 기준으로 한다. `held`에도 Ticket은 계속 붙을 수 있다 |
| D-045 | L2 분석 결과는 `incident_artifacts`에 성공한 분석 라운드마다 한 행으로 쌓고, 탐지 룰·대응 방안 제안은 `incident_proposals`에 한 건씩 나눠 둔다. `incidents`에는 `summary`·`assessed_severity`만 최신 값으로 갱신한다 | 덮어쓰지 않아 반려 뒤 재분석이 이전 라운드를 문맥으로 읽을 수 있다. 제안은 나중에 하나씩 채택·기각할 수 있게 행으로 나누지만 이번에는 채택 기능과 `status`를 만들지 않는다. 실패한 라운드는 Artifact가 없어 번호에 빈칸이 생길 수 있다. Artifact는 구조화된 행이고 화면에서는 문자열을 텍스트로만 표시한다 |

### L3

| ID | 결정 | 메모 |
|---|---|---|
| D-029 | L3 위협 시나리오 입력은 보안 뉴스(보안뉴스·The Hacker News RSS, CISA KEV)와 MITRE ATT&CK을 코드(`soc.l3.intel`)로 수집한다. 에이전트에는 웹 접근을 주지 않는다 | 수집한 제목·요약은 밖에서 온 문자열이다(`docs/security.md`). 에이전트에는 L3 헌팅 코드가 `AgentTask.data`로만 넘긴다(#221) |
| D-030 | L3 실행 방식. 실행기(`uv run python -m soc.agent`)의 L3 단계에서 생성 워커(수집 → 가설 생성, `soc.l3.hunt.generate`)와 검증 워커(`soc.l3.hunt.verify`)로 주기 실행한다. 수동 명령(`uv run python -m soc.l3 hunt`)은 그대로 둔다. 기본은 꺼짐(`[executor.l3] interval_seconds = 0`)이고 `config/local.toml`에서 켠다 | 가설 생성은 마지막 시도부터 `[l3.hunt] generate_interval_seconds`(기본 하루)마다 한다. 마지막 시도는 `cancelled`가 아닌 `l3_hypothesize` Agent Log와 프로세스 안 기록 중 늦은 것이다. 종료로 `cancelled`가 된 검증 run은 시도 횟수에 넣지 않는다(#245) |
| D-040 | 데이터셋 MITRE ATT&CK Enterprise(공식 STIX JSON, `mitre-attack/attack-stix-data`). 원본은 커밋하지 않고 실행할 때 받아, 폐기·대체되지 않은 기법의 ID·이름·전술·버전과 설명(길이를 자른 평문)·탐지 데이터 소스·수집 시각만 저장한다 | 버전마다 쌓고 쓰는 쪽이 설정 버전으로 고른다. 이용 약관에 따라 README "제3자 데이터" 절에 MITRE 고지문을 싣는다(#221). 설명·탐지 데이터 소스·수집 시각은 로컬 조회 도구를 위해 더했다(#311). 탐지 데이터 소스는 20.0 번들의 detects 관계로 이어진 탐지 전략·analytic의 data component 이름이다 |

### 저장

| ID | 결정 | 메모 |
|---|---|---|
| D-012 | RDB는 PostgreSQL | |
| D-013 | 벡터 DB는 Qdrant. 판정이 끝난 Ticket·Case를 넣고 용도마다 컬렉션을 따로 둔다. L2 분류 후보용 컬렉션에는 Incident에 붙은 `linked` Ticket을 넣고 payload에 소속 Incident를 달아, 새 Ticket과 비슷한 Ticket이 속한 Incident를 후보로 삼는다 | Incident는 Ticket이 붙을수록 텍스트가 길어져 닮은 부분이 묻히거나 입력 길이에서 잘릴 수 있으므로 통째로 임베딩하지 않는다. 분류 후보용 컬렉션은 PostgreSQL을 베낀 파생 색인이고 payload의 관계는 복사본이며 권위 원본은 PostgreSQL이다. 일부 point 누락은 자동으로 감지하지 않고 PostgreSQL에서 컬렉션을 다시 만드는 명령으로 복구한다. Qdrant 쓰기는 PostgreSQL 트랜잭션이나 outbox에 묶지 않는다. 유사 사례 검색용 컬렉션(`ticket_verdicts`, D-053)에는 판정이 있는 Ticket을 넣고, Case는 별도 point로 넣지 않고 Ticket의 Incident에 Case가 있다는 사실로 읽는다(#313) |
| D-014 | Ticket·Case는 외부 도구 없이 자체 테이블과 내부 화면으로 관리한다 | |
| D-031 | 기본 임베딩 모델은 BAAI bge-m3의 dense 표현이며 로컬 ONNX로 실행한다. 기본 벡터는 1024차원이고 거리 방식은 Cosine이다. 모델 ID와 revision은 설정 값이며 컬렉션 이름은 용도·모델 ID·revision에서 파생한다 | sparse·multi-vector는 쓰지 않고 torch를 설치하지 않는다. 실행 라이브러리는 D-044를 따른다. revision은 설정 값이지만 고정한다. 임베더가 출력 차원을 알려 주고 컬렉션은 그 값을 사용해 작은 차원의 가짜 임베더로도 테스트할 수 있게 한다 |
| D-044 | 벡터 DB 클라이언트와 임베딩 실행은 `qdrant-client==1.20.0`, `onnxruntime==1.31.1`, `huggingface-hub==2.4.0`, `tokenizers==0.23.3`, `numpy==2.5.4`. FastEmbed는 bge-m3를 공식 지원하지 않아 쓰지 않고, torch를 끌어오는 경로도 쓰지 않는다 | 2GB가 넘는 torch를 `uv sync`와 CI에 올리지 않기 위해서다. bge-m3 ONNX는 외부 데이터 방식이라 `model.onnx`와 함께 약 2.27GB의 `model.onnx_data`를 요구하고, tokenizer 파일도 같은 revision에서 받는다. 모델 ID와 revision은 설정 값이다(D-031). 파일은 Hugging Face 기본 캐시(심링크)가 아니라 `<HF_HOME>/soc-onnx/<모델 ID>/<revision>`에 실제 파일로 받는다. onnxruntime이 심링크 캐시의 외부 데이터 경로를 거부해 macOS·Linux에서 모델이 열리지 않았기 때문이다(#313) |

### 데이터 계약 · DB

| ID | 결정 | 메모 |
|---|---|---|
| D-026 | Ticket 출처(`origin`)는 `auto`(기본 모드), `scenario`(시나리오 일치), `l1`(L1 1차 판정으로 승격), `l3`(L3 헌팅 발견) 네 가지다 | 값을 더하는 것은 공통 계약 변경이라 L1·L2·L3 담당자 전원의 승인이 필요하다 |
| D-033 | Ticket 생성 모드. 기본 `auto`는 모든 알럿을 Ticket으로 만든다. 설정으로 `scenario`를 켜면 룰 ID 목록과 일치하는 알럿은 바로 Ticket으로 만들고, 나머지는 L1 1차 판정 후 승격하거나 보류한다. 시나리오 일치 Ticket도 L1 Ticket 판정을 거친다 | 2026-11-03 교수님 답변: 금융당국이 요구하는 감사·증적용 알럿은 강제로 Ticket을 만들고, 룰 ID 기반으로 정적 설정한다. 그런 구조가 없는 기업도 쓸 수 있게 시나리오 모드는 선택이다. 설정 키는 `[ticketing] mode`(`auto` \| `scenario`), `[ticketing] scenario_rule_ids`(룰 ID 목록). 정규화는 W02(#234), 정책 분기와 직접 Ticket 생성은 W04(#246)에서 한다 |
| D-034 | ID는 접두사 + UUIDv7 문자열이다. UUIDv7은 라이브러리 없이 직접 구현하고, 같은 밀리초 안에서도 만든 순서가 지켜지게 카운터를 둔다 | Python 3.13 표준 라이브러리에 UUIDv7이 없다. 순서 보장은 한 프로세스 안에서만이고, 프로세스끼리는 밀리초 단위까지 맞는다. 접두사 목록은 `soc.ids`가 기준 |
| D-035 | DB 마이그레이션은 `src/soc/db/migrations/`의 순번 SQL 파일과 실행기(`uv run python -m soc.db.migrate`)로 한다. 번호 대역: 0001~0099 공통, 0100~0199 수집·정규화·L1, 0200~0299 L2, 0300~0399 L3 | 적용한 파일은 고치지 않고 새 번호를 만든다. 파일은 자기보다 작은 번호의 파일이 만든 테이블만 참조한다(빈 DB에서는 번호 순서로 실행되므로) |
| D-036 | Agent Log는 모델·도구 호출의 입출력을 PostgreSQL에 저장한다. 호출이 끝날 때마다 그 줄을 바로 쓴다. model 줄의 입력은 줄마다 새로 더해진 항목만 저장하고, `records` 도구 줄의 출력은 모델에게 보인 결과만 저장한다 | 성능 문제가 생기면 NoSQL을 다시 논의한다. 입출력에는 공격자가 쓴 문자열이 들어가므로 화면에서는 텍스트로만 표시한다(로그 원문·LLM 출력 텍스트 표시, D-019). 복원: 같은 `run_id`의 model 줄을 `seq` 순으로 이어 붙이면(system 지시는 첫 줄, 이후 줄은 `input_from`) 그 호출의 전체 입력이 된다. 그 입력은 모델에게 보낸 값이라 비밀 가림이 적용된 뒤의 값이다(D-048). model 출력 줄·`details`·도구 인자 줄은 쓰기 직전에만 가려, 모델이 낸 원문과 다를 수 있다(#279). 앞 입력의 접두가 아니면 전체를 저장하고 `details.input_reset`을 단다. `records` 도구 줄은 모델에게 보인 결과와 뺀 건수(`omitted`)를 담는다. 도구 결과를 자르기 전 전체로 저장하던 방식(#211)을 바꾼 것이다. 읽는 규칙: 끝난 run에는 `details.validation` 또는 `details.failure`가 있는 model 줄이 있고, `details.sent=false` 줄은 모델에 보내지 않은 호출이다. 줄을 호출마다 쓰므로 강제 종료된 run은 끝난 호출까지만 남고 그 줄이 없다(#278) |
| D-037 | 계약 검증·DB 라이브러리: psycopg 3(`psycopg[binary]`), jsonschema, pydantic v2. 개발용: datamodel-code-generator | psycopg는 LGPL-3.0이고 수정 없이 import해서 쓴다. 생성 도구 버전은 `uv.lock`으로 고정한다 |
| D-038 | 생성 코드 폴더(`src/soc/contracts/generated/`)에서만 ruff E501(줄 길이)을 끈다. 포맷 검사와 나머지 린트 규칙은 그대로 적용한다 | 생성 코드는 손으로 고칠 수 없고, schema의 설명 문장이 한 줄로 생성돼 100자를 넘는다. 2026-11-03 #192 계획에서 사람이 승인한 예외 |

### 화면

| ID | 결정 | 메모 |
|---|---|---|
| D-015 | 화면은 React + Vite + TypeScript | |
| D-016 | 화면용 API는 FastAPI | |
| D-042 | 화면용 API 실행·의존성: `fastapi==0.162.0`, `uvicorn==0.54.0`. 테스트는 Starlette TestClient(`httpx2`)로 한다 | 기본 바인딩은 127.0.0.1이다. 인증(D-020)이 생겼어도 기본값은 그대로 두고 설정(`[api] host`)으로 바꾼다(#284). TestClient는 HTTP 클라이언트(httpx, D-039)가 아니라 openai가 끌어오는 `httpx2`를 쓴다(#239) |
| D-017 | 화면 세부 도구: Tailwind CSS + shadcn/ui, TanStack Query, React Router, MSW(mock API), Vitest + Testing Library, Node LTS + pnpm, ESLint + Prettier | frontend/에서 pnpm lint(ESLint + Prettier 검사), pnpm test(Vitest run), pnpm build(TypeScript 검사 + Vite 빌드). CI도 같은 명령(#266) |
| D-018 | 차트는 Recharts | |
| D-019 | 로그 원문과 LLM 출력은 화면과 알림에서 텍스트로만 표시한다 | `docs/security.md` "화면" |
| D-046 | 화면 폰트는 @fontsource 패키지(`@fontsource/inter`·`roboto-mono`·`michroma`·`jura` 5.3.0, OFL-1.1)로 번들하고 외부 폰트 CDN을 부르지 않는다 | 한글은 시스템 폰트로 대체한다(#274) |

### 계정

| ID | 결정 | 메모 |
|---|---|---|
| D-020 | 사용자 계정을 만든다. 처음 실행할 때 랜덤 문자열로 최초 관리자를 만들고, 비밀번호를 바꾼 뒤 쓴다. 그 밖의 사용자는 회원가입 후 관리자 승인으로 쓴다 | 서버 세션 + HttpOnly 쿠키이고 DB에는 토큰 해시만 둔다. 역할은 admin·analyst다. 최초 관리자의 임시 비밀번호는 서버 시작 때 표준 출력에 1회만 내고 `logging`·DB·파일에 평문으로 두지 않는다. `/api`는 기본 거부이고 공개 라우트만 명시한다. 권한은 `<자원>.<동작>` 이름으로 admin이 사용자별로 부여·회수하고 admin은 항상 전체 권한이다. analyst는 가입 승인 때 조회 권한을 기본으로 받는다(#284) |
| D-047 | 비밀번호 해시는 argon2-cffi(`argon2-cffi==25.1.0`, Argon2id) | 라이브러리 기본 파라미터를 쓴다. 함께 들어오는 `argon2-cffi-bindings`는 `uv.lock`으로 고정한다. PyPI 메타데이터에 라이선스가 비어 있어, 개발 때 설치한 패키지의 LICENSE 파일로 Apache-2.0 호환 여부를 확인하고 notes에 적는다(#284) |

### 설정 (개발 필요)

| ID | 결정 | 메모 |
|---|---|---|
| D-021 | SIEM 연결 설정 화면을 만든다. 화면에서 저장한 설정(프로필)은 PostgreSQL에 두고 설정 파일과 환경변수보다 우선하며, 바꾸면 바로 반영한다. 조회를 포함해 관리자만 접근한다 | 아직 개발되지 않았다. 비밀 값 저장 방식은 이 이슈에서 정하고, 그전까지는 환경변수 이름만 저장한다(`docs/security.md`). 고를 수 있는 환경변수는 `SIEM_` 접두사로 제한한다(`docs/security.md`) |
| D-043 | 런타임 Ticket 정책은 TOML 기본값 위에 PostgreSQL의 단일 활성 정책 행을 적용하고, 관리자 인증 API로 전체 값을 바꾼다. Alert마다 분기 직전에 정책을 읽으며 이미 저장한 분기 결과는 바꾸지 않는다 | 활성 행이 없으면 TOML을 쓴다. 정책 이력은 저장하지 않는다. 조회는 `policy.read`, 변경은 `policy.update` 권한이다(#246, #284) |

## 후보 (의논 필요)

| ID | 안건 | 후보 | 메모 |
|---|---|---|---|

## 담당자가 정함

그 단계를 구현하는 담당자가 계획 이슈에서 정한다. 예시는 이전 논의에서 나온 안이며 그대로 따를 필요는 없다.

| ID | 정할 것 | 예시 | 담당 단계 |
|---|---|---|---|

## 추후

| ID | 항목 | 메모 |
|---|---|---|
| D-032 | 알림 | 추후 개발 예정. 이전 안: Slack, L2 분석이 끝나 사람 승인이 필요할 때만 |

## 폐기

| ID | 항목 | 이유 |
|---|---|---|

## 기록

새 기록을 맨 위에 쓴다.

- #313 · 임베더가 모델 파일을 Hugging Face 캐시 대신 `<HF_HOME>/soc-onnx/…`에 받도록 고쳤다(D-044 메모). 사용자가 이 이슈에서 고치기로 정함.
- #313 · 유사 사례 검색 도구(D-053)를 추가했다. 판정이 끝난 Ticket 전용 컬렉션과 색인 코드를 이 이슈에 포함하고, 에이전트 읽기 역할에 `tickets`·`incidents`·`cases`의 지정 열 SELECT를 준다. 이슈의 `kind` 인자는 두지 않고 결과에 `case_id`·`decided_by`를 넣는다. 사용자가 계획을 확정함.
- #311 · 로컬 ATT&CK·KEV 조회 도구(D-052)를 추가했다. 요청 필드가 저장되어 있지 않아 수집을 확장하고 ATT&CK 데이터셋 저장 필드(D-040)에 설명·탐지 데이터 소스·수집 시각을 더했다. 에이전트 읽기 역할에 새 테이블 세 개의 SELECT를 준다(`threat_news` 제외). L3 담당(이슈 담당)이 확인했고 사용자가 계획을 확정함.
- #309 · 위협 인텔 조회 도구(D-051)를 추가했다. VirusTotal 무료 키, 지표 값만 전송, 캐시·한도는 프로세스 메모리, 키가 없으면 도구 미등록. 사용자가 계획을 확정함.
- #280 · 동기 도구 핸들러를 호출마다 전용 데몬 스레드에서 돌리는 방식(D-049)과 실행기 단계 스레드의 예외 처리·종료 코드 3(D-050)을 추가했다. 팀 합의(#280). 사용자가 계획을 확정함.
- #294 · PostgreSQL 유일 인덱스의 키 길이 한계를 막도록 Base64url 페이로드가 128자를 넘으면 `h` + JSON 바이트 SHA-256 hex로 축약하기로 정했다. 원문은 계속 `original_text`에 보존한다.
- #294 · 수집 불가 hit 격리·재시도 정책(D-050)을 확정했다. 격리 전용 키·페이지 원자 저장·별도 재시도 예산·실행별 격리 건수를 정했다. 계획 218의 문서 단위 정지 원칙을 대체하며 기존 계획 파일은 수정하지 않는다.
- #277 · D-049 결정 반영(사람이 정함). 에이전트에게 보이는 `siem_ref`는 저장 키(`siem_ref_key`, 이스케이프된 값)다. `link_by_refs`는 저장 키 쌍(`SiemRefKey`)을 받고 안에서 이스케이프하지 않는다. 한 dict 안에서 키가 이스케이프 뒤 겹치면 값을 덮어쓰지 않고 `escape_collision` 실패로 기록한다(마이그레이션 없음, `error_code`에 CHECK가 없다).
- #277 · 원본 보관 형식(D-049)을 추가했다. `raw_records` 원본을 jsonb 대신 JSON 글자(`original_text`, `ensure_ascii=True`)로 보관하고, 정규화 결과의 NUL·짝 없는 서로게이트를 값과 키 모두 6글자 이스케이프로 치환한다. 계약 필드 `original` → `original_text`. 사용자가 계획을 확정함.
- #277 · 알려진 한계 두 가지(깨진 원본이 claim에서 배치를 멈춤, 치환 결과의 구별 불가와 키 충돌)는 `docs/notes/277-raw-original-text.md`에 문서화했다. 코드는 바꾸지 않았다.

- #279 · 모델 입력 비밀 값 가림(D-048)을 추가했다. 외부 LLM으로 보내는 입력을 SDK 입력 필터 한 곳에서 가리고, 가림 실패는 `provider_error`로 끝낸다. 환경변수 값 가림 최소 길이를 4에서 8로 올리고 `token`·`secret`·`Authorization: Basic|ApiKey` 모양을 더했다. D-036 메모의 복원 설명을 "모델에게 보낸 가림 적용 후 입력"으로 맞췄다. 팀 공유가 필요하다. 사용자가 계획을 확정함.

- #278 · Agent Log 저장 방식(D-036)을 고쳤다. 호출이 끝날 때마다 줄을 바로 쓰고, model 줄 입력은 새로 더해진 항목만, `records` 도구 줄 출력은 모델에게 보인 결과만 저장한다. 복원 방법과 "끝난 run" 읽는 규칙을 메모에 적었다. #211 기록의 "자르기 전 전체 결과 저장"을 바꾼다. 팀 공유가 필요하다. 사용자가 계획을 확정함.
- #270 · L2 재분석 횟수 한도(D-028)를 없애고 실패 재시도 3회·`held`·1시간 쿨다운 복귀를 확정했다. 분석 중 Ticket이 붙으면 현재 Artifact를 저장하고 새 Ticket을 재분석한다.

- #284 · 사용자 계정(D-020)을 개발 필요에서 확정으로 옮기고 세션·최초 관리자·기본 거부 방식을 메모에 적었다. 비밀번호 해시 argon2-cffi(D-047)를 추가했다. D-042의 "인증이 생기면 다시 정한다"는 기본 바인딩 127.0.0.1 유지로 닫았다. #246 기록의 "접근 제어 없이 노출"은 정책 조회·변경 권한 적용으로 닫았고 D-043 메모를 맞췄다. admin이 사용자별로 권한을 부여·회수하는 권한 층을 D-020에 더했고, 위임 범위는 구현된 API 전부다. 사용자가 계획을 확정함.
- #274 · 화면 폰트 번들 방식(D-046)을 확정했다. 사용자가 UI 개선 계획을 확정함.

- #266 · 화면 검사 명령(D-017)과 API 응답 TypeScript 생성 방식(D-003)을 확정했다. 사용자가 UI 연결 계획과 추가 시드 안전 조건을 확정함.

- #245 · L3 실행 방식(D-030)을 담당자가 정함에서 확정으로 옮김. 실행기 L3 단계에서 생성·검증 워커로 주기 실행, 수동 명령 유지, 기본 꺼짐. L3 담당이 정함(#245)
- #261 · L2 분석 결과 저장(D-045)을 Artifact·제안 테이블로 확정하고, D-028의 새 Ticket 재분석은 자동 분석 가능한 Incident에만 적용한다고 명확히 함. L2 담당이 정함
- #250 · Incident 분류 방법(D-027)에서 엔티티 등급·겹침을 제거하고 후보 경로를 최고 유사도 순 vector와 최근 활동순 recent로 확정했다. 에이전트나 코드 검사가 실패하면 기존 후보에 붙이지 않고 새 Incident를 만들며, 저장 직전 Ticket과 Incident 상태를 다시 확인한다. L2 담당이 정함(#250)
- #257 · 벡터 DB 클라이언트와 임베딩 실행 라이브러리(D-044)를 버전과 함께 확정하고, 임베딩 모델(D-031)이 D-044를 가리키게 함. L2 담당이 정함(#257)
- #248 · Incident 분류 방법(D-027)의 후보 경로를 벡터 검색 우선·직접 조회 선택과 fallback으로 바꾸고, Qdrant(D-013)에 용도별 컬렉션과 분류 후보용 `linked` Ticket 적재를 명시함. 팀 합의(#248). 기본 임베딩 모델(D-031)을 bge-m3 dense·로컬 ONNX·1024차원·Cosine으로 확정하고 모델 ID·revision별로 컬렉션을 가름. L2 담당이 정함
- #251 · L1 판정 결과 조건(D-025)을 확정했다. `[agent.l1].confidence_threshold`는 0.8이고, 확정 판정만 상태에 적용한다. Alert 1차 판정의 benign은 `held`, 임계값 이상 malicious는 Ticket으로 승격한다. Ticket은 임계값 이상 benign이면 `closed`, malicious이면 `escalated`; `undetermined`·낮은 확신도·최종 실패는 `held`다. 실패는 최초 실행 포함 3회까지 시도하고 `cancelled`는 세지 않는다. 상태를 다시 확인한 뒤 Alert 갱신과 Ticket 생성을 한 트랜잭션으로 한다. 실패 횟수의 저장 위치는 구현 이슈에서 정한다.
- #234 · D-007 검증 방식을 클래스별 공식 JSON Schema 파일에서 OCSF 서버의 1.9.0 클래스·객체 정의로 바꾼다. OCSF가 클래스별 JSON Schema를 배포하지 않는다는 근거로 사람이 B안을 승인했다. 계획과 구현 위치는 `docs/plans/234-ocsf-alert-event.md`의 "바뀐 점"과 `src/soc/normalize/ocsf/SOURCE.md`에 기록했다.
- #246 · D-033 구현 메모를 갱신해 정규화(W02)와 정책 분기·직접 Ticket 생성(W04)의 경계를 나눈다. D-043 추가: 관리자 API가 갱신한 단일 PostgreSQL 정책 행은 TOML보다 우선하고, Alert별 스냅샷을 적용한다. 기존 분기 결과는 유지하며 이력은 저장하지 않는다.
- #246 · 사용자가 W04 정책 API를 앱에 연결하되 인증·인가는 후속 작업으로 미루도록 정했다. W04 API는 인증 연결 전까지 접근 제어 없이 노출된다.
- #215 · 기본 LLM(D-009) 메모: Foundry는 strict를 켜면 빈 응답이라 `strict_mode` 기본값을 `false`로 함. 에이전트 구조(D-024) 메모: 실행기가 단계 스레드마다 이벤트 루프를 만들어 종료 시 취소에 씀. 담당(#215)이 정함
- #239 · 화면용 API 실행·의존성(D-042) 추가: fastapi·uvicorn 버전 고정, TestClient는 `httpx2`, 기본 바인딩 127.0.0.1. L3 담당이 정함(#239)

- #213 · SSH 라이브러리 asyncssh(D-041) 추가, SSH 도구(D-011) 메모에 원격 셸 해석을 막는 구체 방법(코드 상수 점검, 허용 문자 인자 검사, `-` 거부, `shlex.quote`)을 채움. 팀 합의(#213)
- #211 · 도구 구현 방식(D-023)을 후보에서 확정으로 옮김. MCP 서버 대신 파이썬 함수 도구 레지스트리를 Agents SDK 함수 도구로 감싸고, MCP 노출은 필요해지면 레지스트리 위에 얹는다. 팀 합의(#211)
- 2026-11-04 · Incident 분류 방법(D-027)과 L2 재분석 기준(D-028)을 담당자가 정함에서 확정으로 옮기고 L2 절을 만듦. 확신도 임계로 거르지 않고 기록만 하며, 저장 경쟁은 고른 Incident 한 줄 잠금으로 막는다(분류는 단계별 스레드라 Ticket끼리 경쟁이 없다). L2 담당이 정함
- #210 · 기본 LLM(D-009)을 Groq에서 Azure Foundry gpt-oss-120b로 바꿈. 설정만으로 Groq·Ollama로 되돌리는 구조 포함. 팀 합의(#210)
- #221 · L3 위협 시나리오 입력(D-029)을 담당자가 정함에서 확정으로 옮김, HTTP 클라이언트 httpx(D-039)와 데이터셋 MITRE ATT&CK Enterprise(D-040) 추가
- 2026-11-04 · Hunt 계약(#217): Hunt 계약과 `hunts` 테이블(마이그레이션 0002)을 추가하고, Ticket에 `hunt_id`(`origin = l3`이면 값, 그 밖에는 null, Hunt 하나에 Ticket 하나)를 더함. ID 접두사 `hnt`·`hrn` 추가, Agent Log hunt 대상 `subject_id`를 `hnt_`·`hrn_` ID로 좁힘. 공통 계약 변경이라 L1·L2·L3 담당자 전원의 승인이 필요하다
- #209 · 에이전트 프레임워크(D-022)와 에이전트 구조(D-024)를 후보에서 확정으로 옮김. 팀 합의(#209, L1·L2·L3 담당). 기본 LLM(D-009)·도구 구현 방식(D-023)·SSH 라이브러리·SSH 도구(D-011) 메모는 처음 쓰는 이슈에서 정한다
- 2026-11-03 · OCSF 정규화(D-007) 메모에 클래스별 공식 JSON Schema 검증을 정규화 이슈에서 반드시 한다고 덧붙임(#192)
- 2026-11-03 · 공통 데이터 계약(#192): Ticket 출처(D-026)를 확정으로 옮김, Ticket 생성 모드·ID·마이그레이션·Agent Log 저장·계약 라이브러리·생성 코드 린트 예외(D-033~D-038) 추가, 데이터 계약(D-003) 메모에 위치와 생성 도구 추가
- 2026-11-03 · 기점을 번호 기준(#191)으로 바꿈, SSH 도구(D-011)에 `-`로 시작하는 값 거부와 읽기 전용 원격 계정 추가
- 2026-11-03 · 하네스 적용 기점(2026-11-03, PR #191) 추가, SSH 도구(D-011)의 원격 셸 해석 내용 바로잡음
- 2026-11-03 · SIEM 설정 화면(D-021)에 `SIEM_` 접두사 제한과 화면 설정 우선을 추가, 결정 ID 표기 규칙 추가
- 2026-11-03 · D-011 결정, D-002·D-020·D-021 메모 보강, 폐기 절 추가, '결정 목록'으로 이름 바꿈
- 2026-11-03 · 결정 목록을 다시 정리함. D-001~D-021 확정, D-022~D-024 후보, D-025~D-031 담당자가 정함, D-032 추후
