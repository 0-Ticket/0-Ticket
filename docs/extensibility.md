# 확장 구조

기업마다 쓰는 SIEM, 로그 형식, 자산 관리 도구, LLM이 다르다. 0-Ticket SOC는 코어 코드를 고치지 않고 **설정을 바꾸거나 플러그인을 추가하는 것만으로** 이런 차이를 맞출 수 있게 만든다.

이 문서는 박스를 구현할 때 지켜야 할 확장 원칙과, 확장할 수 있는 지점의 목록이다.

## 원칙

### 1. 인터페이스와 구현체를 나눈다

바뀔 수 있는 부분은 모두 **인터페이스**(Python `Protocol`)로 정의하고, 실제 동작은 **구현체**가 맡는다.

- 인터페이스: `src/soc/<그룹>/<확장 지점>/base.py`
- 기본 구현체: 같은 폴더의 `<이름>.py`
- 예: `src/soc/ingest/siem/base.py`(SIEM 커넥터 인터페이스), `src/soc/ingest/siem/direct.py`(SIEM 없이 데이터셋을 재생하는 개발·데모용 구현체), `src/soc/ingest/siem/<SIEM 이름>.py`(외부 SIEM 커넥터)

### 2. 코어는 구현체 이름을 모른다

파이프라인 코드는 인터페이스만 쓴다. `if siem == "<특정 SIEM>":` 같은 분기를 코어에 두지 않는다. 어떤 구현체를 쓸지는 설정이 정하고, 레지스트리가 이름으로 찾아 준다.

### 3. 레지스트리로 찾는다

확장 지점마다 레지스트리가 있다. 구현체는 이름으로 등록된다.

- **기본 구현체**: 레포 안에서 등록한다.
- **외부 플러그인**: 기업이 레포를 포크하지 않고 별도 Python 패키지로 만들어 설치한다. 패키지의 `pyproject.toml`에 entry point를 선언하면 자동으로 등록된다.

```toml
# 기업 플러그인 패키지의 pyproject.toml 예시
[project.entry-points."zero_ticket_soc.siem"]
acme_siem = "acme_soc_plugins.siem:AcmeSiemAdapter"
```

entry point 그룹 이름은 `zero_ticket_soc.<확장 지점>`이다. 아래 "확장 지점" 표의 "그룹" 열을 따른다.

### 4. 조직별 값은 설정으로

어떤 구현체를 쓸지, 모델 이름, 임계값, 규칙 파일 경로 같은 조직별 값은 코드가 아니라 설정 파일에 둔다.

- 기본 설정: `config/default.toml` (레포에 커밋, 비밀 값 없음)
- 조직 설정: 환경변수 `ZT_CONFIG`가 가리키는 파일. 기본 설정 위에 덮어쓴다. 레포에 커밋하지 않는다.
- 시연 설정: `config/demo/settings.toml`. 형식은 조직 설정과 같고 `ZT_CONFIG`로 고른다. 내부 주소가 없는 시연 샘플이라 예외로 커밋한다(`docs/security-policy.md` 1항).
- 비밀 값은 설정에 직접 쓰지 않는다. **환경변수 이름**만 적고, 값은 `.env`에 둔다.
- 설정 파일 형식은 TOML이다(D-015). 표준 라이브러리 `tomllib`로 읽는다.

```toml
# 조직 설정 예시
[siem]
adapter = "acme_siem"         # 등록된 어댑터 이름. SIEM이 없으면 "direct"
base_url = "https://siem.example.com"
token_env = "SIEM_TOKEN"      # 값은 .env의 SIEM_TOKEN

[llm]
provider = "openai_compatible"
model = "my-model-name"
base_url = "https://llm.example.com/v1"
api_key_env = "LLM_API_KEY"

[llm.agents.l2]               # 에이전트별로 다른 모델
model = "my-larger-model"
```

### 5. 데이터는 코어 필드 + 확장 필드

`docs/data-contracts.md`의 코어 필드는 모든 조직이 같다. 조직마다 필요한 추가 필드는 객체의 `extensions` 필드에 넣는다.

- 키는 `<조직 또는 플러그인 이름>.<필드>` 형식. 예: `acme.cost_center`
- 코어 코드는 `extensions`를 읽지 않고 그대로 전달하고 저장한다.
- 원본에 있었지만 매핑되지 않은 값은 `unmapped`, 조직이 일부러 붙인 값은 `extensions`다.
- 열거형 중 조직이 늘릴 수 있는 것(소스 종류, 처리 유형, 전문 에이전트, 공격 유형, IOC 종류, 근거 종류, 벡터 컬렉션 등)은 **등록형 값**으로 둔다. 기본값이 있고, 플러그인이 새 값을 등록할 수 있다. 계약 Schema에서는 `enum`이 아니라 문자열로 두고, 값 검증은 레지스트리가 한다(`docs/data-contracts.md` "계약 Schema").

### 6. 규칙과 프롬프트는 파일로

별칭 표, 엔티티 분기 규칙, 헌팅 쿼리, 프롬프트는 코드가 아니라 파일로 둔다. 조직은 설정에서 자기 파일 폴더를 지정해 기본 파일 위에 덮어쓸 수 있다. 같은 이름의 파일이 있으면 조직 파일이 이긴다.

프롬프트 파일에는 역할, 규칙, 출력 형식, 참고 정보만 들어간다. 로그 원문을 구분자로 감싸 붙이는 일은 LLM 호출 함수가 코드로 하므로, 조직 프롬프트로 바꾸거나 뺄 수 없다(`docs/llm-policy.md` 2항).

## 확장 지점

| 확장 지점 | 박스 | 그룹 (entry point) | 기본 구현체 | 조직이 바꾸는 예 |
|---|---|---|---|---|
| 소스 커넥터 | 1 (외부) | `sources` | 파일 (`direct` 어댑터의 데이터셋 재생 입력, 개발·테스트·데모용) | 다른 데이터셋 형식. 운영 로그 소스는 외부 SIEM에 붙인다 |
| 원본 저장소 | 2 (외부) | `raw_stores` | 로컬 파일 (`direct` 재생용) | 운영 원본 로그 보관은 외부 SIEM 소관 |
| SIEM 커넥터 | 3 | `siem` (기존 그룹을 그대로 쓰는 것을 제안) | Wazuh (초기 구현 대상, D-037), `elastic`(ELK: Elasticsearch + Kibana Security. `_search`로 `[siem.elastic] alert_index`·`event_index`를 읽는다. 시나리오 `elastic_security_alert`·`elastic_access_event`, #99), `direct`(SIEM 없이 데이터셋을 재생해 C1을 C2로 넘김. 개발·테스트·데모용, 운영 대상 아님). 운영에서는 외부 SIEM 하나를 설정으로 선택 | Splunk |
| 별칭 표 | 4 | (파일) | 기본 시나리오 별칭 표 `src/soc/normalize/aliases/<scenario>.toml`. 조직 폴더는 `[normalize] alias_dir`이고, 같은 이름 파일이 기본 표를 통째로 바꾼다. 텍스트 한 줄 원본은 `parse`(이름 붙은 그룹 정규식)로 나눈다. parse 정규식은 공격자가 만든 문자열에 적용되므로 역추적이 폭발하지 않게 쓴다(중첩 반복 금지). 대상 값이 `normalize.max_parse_length`보다 길면 적용하지 않는다 | 자사 SIEM 시나리오, 새 로그 형식 |
| 룩업 제공자 | 5 | `lookups` | `csv`: CSV로 적재한 자산·계정 표(RDB, `postgresql.lookups`)를 읽는다(#60). `none`(항상 찾지 못함)도 설정으로 고를 수 있다. 인터페이스 `src/soc/normalize/lookup/base.py`의 `find_asset(value, at)`, `find_user(user, at)`. `[lookup] provider`로 고르고 코어는 `soc.normalize.lookup.open_lookup`으로 연다. 정규화 결합(`LookupEnricher`)과 증거 요청 큐의 lookup 처리자가 같은 제공자를 쓴다 | CMDB, 디렉터리 서비스, 위협 인텔 평판 서비스 |
| 저장소 백엔드 | 5, 6, 7, 10, 12, 18, 20, 22, 24 | `stores` | PostgreSQL (D-002). Event도 RDB. 구현체 이름은 `<백엔드>.<저장소 종류>`(예: `postgresql.records`, `postgresql.tickets`)이고, `[store] backend` 하나로 고르며 코어는 `soc.store.open_store(<종류>, ...)`에 종류만 넘긴다 | 다른 RDB, 별도 로그 저장소(이벤트) |
| 벡터 저장소 | 8 | `vector_stores` | Qdrant (D-003). Ticket, Case만 | 다른 벡터 DB |
| 임베딩 제공자 | 8 | `embedders` | bge-m3, 로컬 실행 (D-010) | 상용 임베딩 API |
| 검색 결과 융합 | 8 | `FUSION_FUNCTIONS` 함수 맵 | RRF (`[vector_search] fusion_method`) | `keyword_first`, `weighted_rrf`, `dbsf`, `weighted_score` 중 선택하거나 함수를 추가 |
| LLM 제공자 | 11, 13, 14, 19, 23, 24 | `llm_providers` | OpenAI 호환 제공자. 데모 기본값: 서빙 도구 Ollama, 모델 `granite4:micro` (로컬 서빙, D-009) | 상용 모델, 사내 모델, 로컬 모델 |
| 전문 에이전트 | 13, 14 | `specialists` | `web`: Web 전문가 Agent(#63). 인터페이스 `src/soc/l1/specialists/base.py`의 `SpecialistContext`를 받아 C22 요청 하나를 C14로 답하는 함수. C22 `domain` 값이 구현체 이름이고(도메인이 없으면 `web`), 코어는 `soc.l1.specialists.open_specialist(domain, context)`로 연다. Cloud(13)는 등록 한 줄 (D-005 확정 후) | Cloud, 엔드포인트, 메일, 네트워크 전문 에이전트 추가 |
| 프롬프트 | 11, 13, 14, 19, 23, 24 | (파일) | 기본 프롬프트 | 자사 판정 기준, 언어 |
| MCP 도구 | 15 | `mcp_servers` | 내부 데이터 조회, Web 도메인. 공식 Python MCP SDK로 구현 (D-041) | 사내 도구 연결 |
| SIEM MCP 어댑터 | 15 | `siem_mcp_adapters` | Wazuh (초기, D-035). 선택된 SIEM을 따라간다. 읽기 전용. `direct`(개발·테스트·시연용, 운영 대상 아님): `siem.direct.files`를 수집과 같은 방식으로 읽고 기본 별칭 표로 엔티티·시간을 찾는다. `elastic`(ELK, #99): 커넥터와 같은 인덱스를 `_search`로 읽는다. ip는 `source.address`(IP 값이면 `destination.ip`도), host는 `host.name`, user는 `user.name`에 term으로 건다. 시간은 이벤트는 `@timestamp`, 알럿은 `kibana.alert.original_time`(없으면 `@timestamp`)이다. 질의 실패는 SIEM에 닿지 못하면 `SiemUnavailableError`, 답을 쓸 수 없으면 `SiemAdapterError`로 알린다(`src/soc/l1/mcp/siem/base.py`, #111). 답을 쓸 수 없음에는 어댑터가 돌려준 레코드의 C2 변환 실패도 포함된다. `query_siem` 도구는 두 오류를 같은 타입·고정 메시지로 다시 만들고, 다른 예외는 고정 메시지의 `SiemAdapterError`로 바꾼다. elastic은 아직 연결 불가를 구분하지 못해 모든 실패가 `SiemAdapterError`다(박스 3 별도 이슈) | Splunk |
| 증거 요청 큐 | 26, 27 | `evidence_queues` | PostgreSQL 테이블 큐 (D-034). 구현체 이름 `postgresql`, `[evidence_queue] backend`로 고르고 코어는 `soc.l1.evidence.open_evidence_queue`로 연다. 백엔드는 이름 두 개를 등록한다: `<백엔드>`(큐 작업자가 쓰는 연결)와 `<백엔드>.readonly`(같은 행을 읽기 전용으로 읽는 연결). 화면용 API(27)는 `open_evidence_queue(..., readonly=True)`로 뒤쪽만 연다 | 다른 큐 백엔드 |
| 사람 검토 채널 | 21 | `review_channels` | 웹 화면 (D-013, `docs/frontend.md`) | 메신저, 사내 포털 |
| 티켓·케이스 시스템 | 10, 22 | `case_systems` | 내부 저장과 내부 UI (D-012) | 외부 티켓·케이스 관리 도구와 동기화 |
| 알림 채널 | 사용자 접점 | (제안: notification_channels) | Slack (D-033) | 메신저, 메일 |
| 엔티티 분기 규칙 | 25 | (파일) | 공격 대상 시나리오 목록, 공용 엔티티 기준, Incident 매칭 기준 | 자사 공격 시나리오, 자사 공용 자산 |
| 헌팅 쿼리 | 23 | (파일) | 기본 기준선 쿼리 | 자사 환경 기준선 |
| 룰 변환 대상 | 24 | `rule_targets` | 연결된 SIEM 어댑터를 따름 | 다른 SIEM 쿼리 언어 |

`stores` 그룹의 이름은 `<백엔드>.<저장소 종류>` 형식이다. Ticket 저장소는 `postgresql.tickets`로 등록하며,
공통 `open_store("tickets", ...)`가 `[store] backend` 설정에 따라 선택한다.

읽기만 하는 쪽(에이전트 도구 15, 화면용 API 27)이 쓰는 저장소 종류는 **같은 테이블을 읽기 전용 계정으로
읽는 별도 종류** `readonly_<종류>`로 한 번 더 등록한다. 지금 쓰는 이름은 `readonly_records`,
`readonly_branches`, `readonly_l1_decisions`, `readonly_tickets`, `readonly_agent_log`이다.
읽기 전용 팩토리는 `[database] readonly_url_env`가 가리키는 계정으로
`soc.db.connect_readonly`로 연결하고(연결에 읽기 전용 트랜잭션도 걸린다), 쓰기 메서드는 지우지 않고
그대로 두어 실수로 호출하면 실패하게 한다(`docs/security-policy.md` 4항). 새 백엔드를 붙이면 코어가 쓰는
종류와 그 `readonly_` 짝을 함께 등록해야 한다.

**빌린 연결 받기 (화면용 API, 박스 27).** 화면용 API는 요청마다 연결 하나를 풀에서 빌려
그 요청의 저장소 전부에 넘긴다(#104). 그래서 팩토리는 선택 인자 `connection`을 하나 더 받는다.

- 코어는 빌린 연결이 있을 때만 `connection=`을 넘긴다. 없으면 기존처럼 `factory(settings, environ)`으로
  부르므로, 이 인자를 받지 않는 팩토리도 그대로 동작한다. 다만 **화면용 API가 고르는 백엔드라면 이 인자를
  받아야 한다**
- `connection`을 받은 저장소는 그 연결을 그대로 쓰고 **닫지 않는다**(`close()`는 자기가 연 연결만 닫는다).
  연결을 풀에 돌려주는 것은 빌린 쪽의 일이다
- 어떤 연결을 빌리는지는 백엔드의 사정이므로 계약에서는 타입을 두지 않는다(`object | None`)
- 풀 자체의 설정은 `[database] pool_max_size`, `[database] pool_timeout_seconds`다. PostgreSQL 백엔드는
  `soc.db.open_readonly_pool`로 풀을 열고, 읽기 전용 트랜잭션 옵션과 autocommit을 풀이 여는 연결에도 건다

"(제안: …)"으로 적은 그룹 이름은 `src/soc/plugins.py`의 기존 규칙(소문자 snake_case 복수형, 예: `review_channels`, `vector_stores`)을 따른 제안이다. 확정되면 코드와 이 표를 함께 고친다.

SIEM 커넥터와 SIEM MCP 어댑터는 설정의 `[siem] adapter` 값 하나로 함께 선택된다(D-037). 두 확장 지점의 그룹은 따로지만 이름은 같은 것을 쓴다. 에이전트가 어떤 MCP 도구를 부를 수 있는지는 설정의 `[mcp.allowed_tools]`에 에이전트 이름별로 적고, 기본값은 비어 있어 모든 호출이 거부된다(박스 15).

`mcp_servers` 그룹의 구현체는 **도구 묶음 함수 하나**다. `ToolContext`(설정, 환경변수, 읽기 전용 Alert·Event 저장소를 처음 쓸 때 여는 함수)를 받아 `ToolSpec` 목록을 돌려주고, 코어가 등록된 모든 묶음을 한 서버에 올린다. 레포 기본 묶음은 `internal_data`(`query_records`, `get_alert`)와 `web`(`query_http_flow`)이고, SIEM 도구(`query_siem`)는 선택된 어댑터에서 온다. 이미 등록된 도구 이름을 다시 쓰는 묶음은 시작할 때 거부된다(허용 목록이 가리키는 도구가 바뀌지 않게). 내부 데이터 조회는 `[database] readonly_url_env`가 가리키는 읽기 전용 계정으로만 하고, 연결에 읽기 전용 트랜잭션도 함께 건다(`docs/security-policy.md` 4항).

전문 에이전트는 자기 이름으로만 도구를 부른다. Web 전문가의 이름은 `web_specialist` 하나이고, `[mcp.allowed_tools]`의 키, `[llm.agents]`의 키, C8 `agent` 값에 같은 이름을 쓴다. 요청을 넣은 에이전트(예: `l1`)의 허용 목록은 전문가에게 넘어가지 않는다. 알럿 앞뒤로 볼 흐름의 범위는 `[specialist]` 설정이다.

허용 목록 예시(조직 설정):

```toml
[mcp.allowed_tools]
l1 = ["query_siem", "query_records", "get_alert"]
web_specialist = ["query_records", "get_alert", "query_http_flow"]
```

기본 구현체 중 "로컬 파일", "CSV", `direct`는 외부 도구 없이 표준 라이브러리만으로 만드는 기본값이라 결정 대장에 따로 두지 않는다. 외부 도구를 쓰는 기본 구현체는 결정 대장의 ID를 따른다.

웹 화면도 확장 구조를 따른다. 등록형 값과 `extensions`는 화면 코드에 고정하지 않고 받은 그대로 보여 준다. 플러그인이 새 값이나 필드를 더해도 화면을 고치지 않아도 된다(`docs/frontend.md` "공통").

## 자주 하는 확장

### SIEM 없이 받기 (개발·테스트·데모용)

운영에서는 항상 외부 SIEM 하나에 연결한다. SIEM이 없는 개발·테스트·데모(데이터셋 재생)에서만 설정의 `[siem] adapter`를 `direct`로 둔다. 소스 커넥터가 낸 C1이 `direct` 어댑터를 거쳐 C2가 되고, 이후 흐름은 SIEM이 있을 때와 같다. 어느 소스를 알럿으로, 어느 소스를 이벤트로 볼지와 시나리오 이름은 설정에서 정한다.

### 새 SIEM 붙이기

1. `src/soc/ingest/siem/base.py`의 커넥터 인터페이스를 구현한다. 그 SIEM에서 알럿·이벤트를 가져와 C2 SiemAlert 내용(`kind`, `scenario`, `raw_ids`, `fields`)을 내보내면 된다. 어댑터는 `source_record_id` 없이 C2 내용을 돌려주고, 코어가 ID를 붙인다(넣어 보내면 거부된다). `tests/ingest/adapter_contract.py`의 공통 계약 테스트를 통과해야 한다. 같은 SIEM용 SIEM MCP 어댑터(읽기 전용)도 함께 만든다.
2. 레포에 기여하면 같은 폴더에 두고, 사내 전용이면 별도 패키지로 만들어 `zero_ticket_soc.siem` entry point로 등록한다.
3. 설정의 `[siem] adapter`를 새 이름으로 바꾼다. 한 번에 하나의 SIEM만 연결한다.
4. 그 SIEM의 시나리오용 별칭 표를 추가한다(박스 4).

사례: ELK(`elastic`, #99)는 커넥터 `src/soc/ingest/siem/elastic.py`, SIEM MCP 어댑터 `src/soc/l1/mcp/siem/elastic.py`, 설정 `[siem.elastic]`의 인덱스 두 개, 별칭 표 `elastic_security_alert`·`elastic_access_event`만 더했다. 코어 코드는 바꾸지 않았다. 시연 설정은 `config/demo-elk/`.

### 다른 LLM 쓰기

- OpenAI 호환 API를 제공하는 모델: 설정의 `provider`, `model`, `base_url`, `api_key_env`만 바꾼다. 코드는 바꾸지 않는다.
- 호환되지 않는 API: `src/soc/llm/base.py`의 인터페이스를 구현한 제공자를 추가하고 `zero_ticket_soc.llm_providers`로 등록한다.
- 제공자는 `ProviderRequest.timeout_seconds`(설정 `llm.timeout_seconds`) 안에 끝내고, 시간 초과는 `provider_timeout`, 429는 `provider_rate_limited`(`retry_after_seconds` 포함)로 알린다. HTTP 401·403은 `provider_auth_failed`, 404는 `provider_model_not_found`, 413은 `provider_request_too_large`다. 429 재시도는 공통 호출 함수가 한다(`docs/llm-policy.md` "모델과 설정").

### 새 로그 소스 붙이기

1. 운영 로그 소스는 외부 SIEM에 붙인다(박스 1·2는 SIEM 소관). 이 프로젝트에서는 그 SIEM 시나리오의 별칭 표를 추가한다.
2. 데이터셋을 `direct` 어댑터로 재생할 때만 소스 커넥터를 구현해 C1 RawRecord를 내보내고 `source_type`에 새 이름을 등록한다.
3. 기존 C3·C13 필드로 표현되지 않는 값은 `extensions`에 넣는다. 여러 조직에 공통으로 필요해 보이면 계약 변경을 제안한다.

## 확장하지 않는 것

아래는 조직이 바꿀 수 없는 코어다. 바꿔야 한다면 플러그인이 아니라 이 레포에 변경을 제안한다.

- 박스 순서와 박스 사이 흐름 (`docs/architecture.md`)
- 데이터 계약의 코어 필드 (`docs/data-contracts.md`)
- 보안 규칙: 로그 원문은 데이터로만 다루고, 되돌릴 수 없는 대응은 사람 승인을 거친다 (`docs/security-policy.md`)
- LLM 출력 검증 규칙 (`docs/llm-policy.md` 4항)
- 로그 원문을 구분자로 감싸는 일. LLM 호출 함수가 코드로 하며, 프롬프트 파일이나 플러그인이 바꿀 수 없다
- 모든 LLM 호출이 `src/soc/llm/`를 거치는 것. 플러그인(전문 에이전트 등)도 모델 SDK를 직접 부르지 않는다
- 대응 동작의 사람 승인. MCP 도구 플러그인은 대응 동작을 직접 실행하지 못하고 코어의 승인 단계를 거친다. 검토 채널 플러그인은 사람의 입력을 전달만 하고, 판정 기록(C15, v1의 C9)과 검증은 코어가 한다

## 구현할 때 지킬 것

- 확장 지점을 처음 만드는 박스는 인터페이스, 레지스트리, 기본 구현체 하나, **가짜 구현체로 교체하는 테스트**를 함께 만든다.
- 인터페이스를 바꾸면 기존 플러그인이 깨진다. 인터페이스 변경은 계약 변경과 같은 절차(`docs/data-contracts.md` "바꾸는 절차")를 따른다.
- 설정 값을 새로 추가하면 기본 설정 파일에 기본값과 한 줄 설명을 함께 넣는다.
