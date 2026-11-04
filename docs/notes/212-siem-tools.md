---
issue: 212
date: 2026-11-05
owner: Interludeal
plan: 212-siem-tools.md
supersedes: []
---

# SIEM 조회 도구 query_siem·count_siem을 만들었다

## 한 일

- 에이전트가 SIEM(ELK)을 직접 조회하는 도구 두 개를 `src/soc/tools/siem.py`에 만들었다. `query_siem`은 문서 목록(l1·l2·l3), `count_siem`은 필드 값별 상위 10개 건수(l2·l3)를 돌려준다. 운영 레지스트리(`default_registry()`)와 `[tools.allowed]`에 넣었다.
- 수집(#218)과 같은 ELK에 같은 환경변수(`ELK_URL`·`ELK_API_KEY`)와 같은 인증(`Authorization: ApiKey`)으로 접속한다. 부르는 API는 `POST /<대상 index>/_search` 하나다. 리다이렉트는 따라가지 않고, 요청 단위 timeout과 별도로 호출 한 번의 전체 마감 시간(`deadline_seconds`, D-039)을 보며, 압축을 푼 응답이 5MB를 넘으면 끊는다.
- 모델은 쿼리를 쓰지 않는다. 대상 이름(`alerts`·`web_access`·`cloudtrail`)과 필드마다 하나인 필터 인자(`source_ip`, `user_name`, `status_code` …)만 고르고, 도구가 `bool.filter`(range + term) dict를 만든다. 대상 이름과 대상별 필터·반환 필드는 코드 상수이고, 설정 `[[tools.siem.targets]]`는 이름에 `index`·`time_field`만 붙인다.
- 결과는 ELK 원본 필드(ECS)이고 `"source": "siem"`, `"schema": "ecs"`를 적는다. 히트마다 `siem_ref`(`<_index>/<_id>`)와 고른 필드만 담는다. 근거 장부에는 그 호출의 `call_id`(agl_)만 들어간다.
- 레지스트리에 두 칸을 더했다. `ToolError(code, reason=…)`와 `report_tool(…, reason)`으로 Agent Log tool 줄에 `details.reason`(`auth`, `http_status`, `response_shape`, `too_large`, `network`, `config`)을 남긴다. `ToolSpec.check_config`는 실행 시작 전에 허용된 도구의 설정을 검사하고, 틀리면 실행이 `provider_error`로 끝난다.

## 계획과 달라진 점

- **`siem_ref`를 인용하면 `evidence_id_error`가 아니라 `format_error`다.** Verdict 계약의 `evidence_ids`는 근거 ID 모양(`alt_`·`evt_`·`agl_`)만 받으므로, `siem_ref`(`<_index>/<_id>`)는 장부 검사 전에 계약 검사에서 막힌다. 재요청에도 같으면 `format_error`로 끝난다. 인용할 수 없다는 점은 같다. 결과 본문 속 `alt_` 모양 문자열은 계획대로 `evidence_id_error`다(`test_citing_siem_ref_is_rejected`, `test_citing_alert_id_in_result_body_is_evidence_id_error`).
- **`count_siem`이 항목을 빼면 뺀 건수를 `other_count`에 더한다.** 계획은 "건수가 적은 항목부터 뺀다"까지만 정했다. 보이는 건수 + `other_count` = 전체가 되도록 했다.
- **정렬에 `unmapped_type: "date"`를 넣었다.** `web_access`처럼 여러 인덱스 패턴을 함께 조회할 때 시각 필드가 매핑되지 않은 인덱스가 있으면 ES가 정렬 오류를 내기 때문이다. 요청 본문의 최상위 키는 계획대로 6개 그대로다.
- **필터 인자에 `alert_severity`(`low`·`medium`·`high`·`critical`)를 넣었다.** 계획의 필터 표에 있다. 이슈 본문의 "등"을 계획 표대로 닫은 목록으로 만들었다.
- **`check_config`는 대상 이름과 표 모양만 본다.** 코드에 없는 이름, 이름 중복, 이름 없는 항목, `targets`가 목록이 아님 → `provider_error`. `index`·`time_field` 형식, timeout·크기 값, 환경변수는 호출할 때 본다(`failed`/`unavailable`, reason `config`). 계획 표 그대로다.
- **도구는 함수 `siem_tools(transport=None, clock=time.monotonic)`가 만든다.** 테스트가 `httpx.MockTransport`와 가짜 시계를 끼우는 자리다. 운영 레지스트리는 `siem_tools()`(실제 네트워크·시계)를 쓴다.
- **#211 테스트에서 고친 곳**(지우거나 건너뛴 것은 없다)
  - `tests/test_tools_registry.py::test_default_registry_has_the_five_tools`: 운영 레지스트리에 `query_siem`·`count_siem`이 늘어 기대 목록에 더했다.
  - `tests/test_agent_config.py::test_default_tools_config`: `[tools.allowed]` 기본값이 바뀌어 기대 목록을 고쳤다. docstring의 "환경변수 이름도 두지 않는다"는 `[tools.siem]`에 이름이 생겨 맞지 않아 고쳤다.
  - reason·`check_config` 때문에 고친 #209·#210·#211 테스트는 없다. reason이 없을 때 `details`가 그대로인지는 새 테스트(`test_no_reason_keeps_details_as_before`)가 확인한다.

## 다음 사람이 알아야 할 것

- **Verdict가 `siem_ref`를 인용하면 장부 검사 전에 계약 검사에서 막힌다.** Verdict 계약의 `evidence_ids`는 근거 ID 모양(`alt_`·`evt_`·`agl_`)만 받아서, `siem_ref`(`<_index>/<_id>`)를 인용하면 형식 오류 재요청이 가고, 그래도 같으면 `evidence_id_error`가 아니라 `format_error`로 끝난다. 테스트는 이 동작대로 `test_citing_siem_ref_is_rejected`(`format_error`)와 `test_citing_alert_id_in_result_body_is_evidence_id_error`로 나눴다.
- **`ToolSpec`에 `check_config` 칸이 생겼다.** `ToolRegistry.session()`이 허용 목록에 있는 도구의 `check_config(tools_config)`를 부른다. `ToolConfigError`나 다른 예외가 나면 실행은 `provider_error`("도구 설정 오류")다. 허용되지 않은 도구의 설정은 보지 않는다. 칸이 없는 도구는 그대로다.
- **`ToolError`·`report_tool`에 `reason`이 생겼다(#213·#214가 쓴다).** `raise ToolError("failed", reason="auth")`처럼 쓰면 tool 줄 `details.reason`에 남는다. `details.failure`는 계속 코드 5개 중 하나다. 모델에게 가는 `TOOL_ERROR` 문구는 reason과 상관없이 같다. reason에는 비밀 값·응답 본문·주소를 넣지 않는다. `ToolRecorder`를 직접 구현한 테스트 도우미가 있으면 `reason=None` 인자를 받게 해야 한다.
- **`aggregate`의 뜻은 "핸들러가 모양과 한도를 정하고, 인용은 `call_id`만"이다.** `query_siem`은 집계가 아니지만 이 뜻에 맞아 `aggregate`를 쓴다. 이름이 어색할 뿐 동작은 맞다. 레지스트리의 `result_kind` 값은 바꾸지 않았다.
- **`kibana.alert.*` 필드는 #208 매핑 확정 때 다시 확인해야 한다.** `alerts`의 룰 이름·심각도는 `kibana.alert.rule.name`·`kibana.alert.severity`(Elastic Security 필드, ECS 아님)로 두었다. 실제 알럿 인덱스에 없거나 이름이 다르면 `soc.tools.siem`의 `FILTERS`·`TARGET_FIELDS`를 고친다. 다른 대상의 필드(`url.path`, `cloud.account.id` 등)도 #208에서 실제 매핑을 확인한다.
- **동기 httpx가 이벤트 루프를 최대 `deadline_seconds`(15초)까지 막는다.** 핸들러는 동기 함수라 SDK의 이벤트 루프 안에서 그대로 돈다. DB 도구도 같다. 한 실행에 도구 호출이 몰리거나 여러 실행을 한 루프에서 돌리면 비동기 클라이언트나 스레드로 옮겨야 한다.
- **#218과 파일이 겹친다.** `config/default.toml`(#218은 `[ingest]`, 이 이슈는 `[tools.allowed]`·`[tools.siem]`), `pyproject.toml`(#218은 `pythonpath`, 이 이슈는 `elk` 마커), `.env.example`(둘 다 `ELK_URL`·`ELK_API_KEY`). 내용은 겹치지 않지만 줄 단위로 충돌할 수 있다. 나중에 머지되는 쪽이 rebase하고, `.env.example`의 두 이름은 한 번만 남긴다.
- **D-021 프로필이 생기면 바꿀 것.** 지금은 `[tools.siem]`의 `url_env`·`api_key_env`로 접속한다. 프로필이 생기면 프로필로 접속하게 바꾼다. `docs/security.md`는 프로필에서 고르는 환경변수 이름을 `SIEM_` 접두사로 제한하는데, `ELK_` 이름은 설정 파일 값이라 지금은 대상이 아니다. D-021 때 이름을 맞춰야 할 수 있다.
- **API 키 권한.** 대상 인덱스(`[[tools.siem.targets]]`의 `index`)에 `read`만 있으면 된다. PIT·scroll·클러스터 권한은 필요 없다.
- **`ELK_URL`은 http도 받는다.** 로컬 ELK 때문이다(#218과 같다). 자체 서명 인증서용 CA 설정은 없다.
- **대상이 없을 때.** 와일드카드 패턴에 맞는 인덱스가 없으면 0건(오류 아님). alias처럼 고정 이름이 없으면 ES가 404를 내고 `failed`(`http_status`)다. 알럿이 아직 없는 클러스터에서 `alerts`를 조회하면 이렇게 될 수 있다.
- **`tests/test_migrate.py::test_name_ending_in_newline_is_not_a_migration`은 Windows에서 실패한다.** 줄바꿈이 든 파일 이름을 만들 수 없어서다. `main`에서도 같고 이 이슈와 관계없다. Linux CI에서는 통과한다.
- **테스트 도우미.** `tests/fake_siem.py`의 `FakeElk`는 `POST /<index>/_search` 밖의 요청(다른 경로·메서드, 쿼리 문자열, 허용 목록 밖 본문 키)을 받으면 `violations`에 남기고 599로 답한다. 도구가 그 응답을 `failed`로 바꾸므로, 테스트 끝에 `violations`가 비었는지 따로 확인한다(`tests/test_tools_siem.py`의 `elk` 픽스처).

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run pytest`: 651건 통과, 1건 실패(`test_name_ending_in_newline_is_not_a_migration`, Windows에서만 실패하고 `main`에서도 같다), 154건 제외(`db`·`llm`·`qdrant`·`elk` 마커). Windows에서 실행했다
- `uv run pytest -m db`: 돌리지 않았다. 이 PC에 0-Ticket용 PostgreSQL과 `DATABASE_URL`이 없었고, 사람이 건너뛰기로 정했다. 이 이슈가 고친 DB 관련 코드는 `LogRecorder.report_tool`의 `details.reason` 한 칸이다(DB 쓰기 코드는 바꾸지 않았다). CI의 `pytest -m db` 단계에서 확인한다
- 새 테스트
  - `tests/test_tools_siem.py`(네트워크 없음, `httpx.MockTransport` + `tests/fixtures/siem/`): 대상 3개의 요청 경로·본문·헤더와 결과 모양, range·term만 쓰는 쿼리, 필터 순서·정렬, 0건, 뒤 히트부터 빼기·한 건도 못 맞추면 0건, `</tool_result>` 탈출 방지, `count_siem` 상위 10개·120자·건수 적은 것부터 빼기·`other_count`, 인자 검사 25가지(요청이 나가지 않음), 설정에서 뺀 대상, 필터 5개·CIDR·IPv6 허용, 도구 설명, 설정 오류 → `provider_error`, 오류 표 12가지(문구·`details.failure`·`details.reason`·리다이렉트 안 따름·비밀/주소/본문/쿼리 없음), 크기 초과, 가짜 시계로 마감 시간, 환경변수 없음·틀림, 설정 값 틀림, 연속 2회 차단, 가짜 모델로 `call_id` 인용 Verdict 통과, `siem_ref` 인용 거부, 본문 속 `alt_` 인용 `evidence_id_error`, 전체 실행에서 401 숨김, Agent Log에서 키·주소 가림, 기본 설정·`.env.example`·`elk` 마커
  - `tests/test_tools_registry.py`: reason이 `details.reason`에만 가고 모델 문구는 같음, reason이 없으면 `details` 그대로, `check_config`는 허용된 도구만·틀리면 `provider_error`
  - `tests/test_agent_redact.py`: `[tools.siem]`의 `url_env`·`api_key_env` 값 가림(`redact.py`를 고치지 않고 통과)
  - `tests/test_tools_siem_elk.py`(`elk` 마커): 실제 ELK
- 실제 ELK로는 확인하지 않았다. 아래 방법으로 사람이 PC의 로컬 ELK에서 돌린다.

### 실제 ELK 테스트(`elk` 마커) 실행 방법

1. 필요한 환경변수: `ELK_URL`(예: `http://localhost:9200`, 계정 정보 없이), `ELK_API_KEY`(대상 인덱스 `read`만 있는 API 키의 encoded 값). 값은 `.env`에만 두고 커밋하지 않는다.
2. 대상 인덱스가 기본값과 다르면 `config/local.toml`(커밋 안 함)에 적는다. `[[tools.siem.targets]]`는 표의 배열이라 local.toml에 적으면 기본값 목록 전체를 대신한다.

   ```toml
   [[tools.siem.targets]]
   name = "alerts"
   index = ".alerts-security.alerts-default"
   time_field = "@timestamp"

   [[tools.siem.targets]]
   name = "web_access"
   index = "logs-nginx.access-*"
   time_field = "@timestamp"

   [[tools.siem.targets]]
   name = "cloudtrail"
   index = "logs-aws.cloudtrail-*"
   time_field = "@timestamp"
   ```

3. 환경변수를 불러와 실행한다. 테스트는 대상마다 최근 7일을 `query_siem`(limit 5)과 `count_siem`으로 한 번씩 부르고, 건수만 출력한다.

   Git Bash:

   ```bash
   set -a; source .env; set +a; uv run pytest -m elk -s tests/test_tools_siem_elk.py
   ```

   PowerShell:

   ```powershell
   Get-Content .env | Where-Object { $_ -match '^[A-Z_]+=' } | ForEach-Object { $k, $v = $_ -split '=', 2; Set-Item "env:$k" $v }
   uv run pytest -m elk -s tests/test_tools_siem_elk.py
   ```

4. 환경변수가 없으면 테스트는 건너뛰지 않고 실패한다. 결과를 계획·기록·PR에 적을 때는 건수만 적는다(`docs/security.md` "데이터").
