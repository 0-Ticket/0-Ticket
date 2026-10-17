# 확장 구조

기업마다 쓰는 SIEM, 로그 형식, 자산 관리 도구, LLM이 다르다. 0-Ticket SOC는 코어 코드를 고치지 않고 **설정을 바꾸거나 플러그인을 추가하는 것만으로** 이런 차이를 맞출 수 있게 만든다.

이 문서는 박스를 구현할 때 지켜야 할 확장 원칙과, 확장할 수 있는 지점의 목록이다.

## 원칙

### 1. 인터페이스와 구현체를 나눈다

바뀔 수 있는 부분은 모두 **인터페이스**(Python `Protocol`)로 정의하고, 실제 동작은 **구현체**가 맡는다.

- 인터페이스: `src/soc/<그룹>/<확장 지점>/base.py`
- 기본 구현체: 같은 폴더의 `<이름>.py`
- 예: `src/soc/ingest/siem/base.py`(SIEM 커넥터 인터페이스), `src/soc/ingest/siem/direct.py`(SIEM 없이 수집하는 기본 구현체), `src/soc/ingest/siem/<SIEM 이름>.py`(외부 SIEM 커넥터)

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

- 기본 설정: `config/default.<확장자>` (레포에 커밋, 비밀 값 없음)
- 조직 설정: 환경변수 `ZT_CONFIG`가 가리키는 파일. 기본 설정 위에 덮어쓴다. 레포에 커밋하지 않는다.
- 비밀 값은 설정에 직접 쓰지 않는다. **환경변수 이름**만 적고, 값은 `.env`에 둔다.
- 설정 파일 형식은 결정 대장 D-015에서 정한다. 아래 예시는 TOML로 썼다.

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
| 소스 커넥터 | 1 | `sources` | 파일, 웹 로그, 클라우드 감사 로그 | EDR, 메일 게이트웨이, 사내 앱 로그 추가 |
| 원본 저장소 | 2 | `raw_stores` | 로컬 파일 | 오브젝트 스토리지 |
| SIEM 커넥터 | 3 | `siem` (기존 그룹을 그대로 쓰는 것을 제안) | Wazuh (초기 구현 대상, D-037), `direct`(SIEM 없이 C1을 C2로 넘김). 한 번에 하나를 설정으로 선택 | ELK, Splunk |
| 별칭 표 | 4 | (파일) | 기본 시나리오 별칭 표 | 자사 SIEM 시나리오, 새 로그 형식 |
| 룩업 제공자 | 5 | `lookups` | CSV 자산·계정 표 | CMDB, 디렉터리 서비스, 위협 인텔 평판 서비스 |
| 저장소 백엔드 | 5, 6, 7, 10, 12, 18, 20, 22, 24 | `stores` | PostgreSQL (D-002). Event도 RDB | 다른 RDB, 별도 로그 저장소(이벤트) |
| 벡터 저장소 | 8 | `vector_stores` | Qdrant (D-003). Ticket, Case만 | 다른 벡터 DB |
| 임베딩 제공자 | 8 | `embedders` | D-010 | 상용 임베딩 API |
| LLM 제공자 | 11, 13, 14, 19, 23, 24 | `llm_providers` | D-009 + OpenAI 호환 API | 상용 모델, 사내 모델, 로컬 모델 |
| 전문 에이전트 | 13, 14 | `specialists` | Web (Cloud는 보류) | Cloud, 엔드포인트, 메일, 네트워크 전문 에이전트 추가 |
| 프롬프트 | 11, 13, 14, 19, 23, 24 | (파일) | 기본 프롬프트 | 자사 판정 기준, 언어 |
| MCP 도구 | 15 | `mcp_servers` | 내부 데이터 조회, Web 도메인 | 사내 도구 연결 |
| SIEM MCP 어댑터 | 15 | (제안: siem_mcp_adapters) | Wazuh (초기, D-035). 선택된 SIEM을 따라간다. 읽기 전용 | ELK, Splunk |
| 증거 요청 큐 | 26 | (제안: evidence_queues) | PostgreSQL 테이블 큐 (D-034) | 다른 큐 백엔드 |
| 사람 검토 채널 | 21 | `review_channels` | 웹 화면 (D-013, `docs/frontend.md`) | 메신저, 사내 포털 |
| 티켓·케이스 시스템 | 10, 22 | `case_systems` | 내부 저장과 내부 UI (D-012) | 외부 티켓·케이스 관리 도구와 동기화 |
| 알림 채널 | 사용자 접점 | (제안: notification_channels) | Slack (D-033) | 메신저, 메일 |
| 엔티티 분기 규칙 | 25 | (파일) | 공격 대상 시나리오 목록, 공용 엔티티 기준, Incident 매칭 기준 | 자사 공격 시나리오, 자사 공용 자산 |
| 헌팅 쿼리 | 23 | (파일) | 기본 기준선 쿼리 | 자사 환경 기준선 |
| 룰 변환 대상 | 24 | `rule_targets` | 연결된 SIEM 어댑터를 따름 | 다른 SIEM 쿼리 언어 |

"(제안: …)"으로 적은 그룹 이름은 `src/soc/plugins.py`의 기존 규칙(소문자 snake_case 복수형, 예: `review_channels`, `vector_stores`)을 따른 제안이다. 확정되면 코드와 이 표를 함께 고친다. SIEM 커넥터와 SIEM MCP 어댑터는 같은 SIEM 이름으로 함께 선택된다(D-037).

기본 구현체 중 "로컬 파일", "CSV", `direct`는 외부 도구 없이 표준 라이브러리만으로 만드는 기본값이라 결정 대장에 따로 두지 않는다. 외부 도구를 쓰는 기본 구현체는 결정 대장의 ID를 따른다.

웹 화면도 확장 구조를 따른다. 등록형 값과 `extensions`는 화면 코드에 고정하지 않고 받은 그대로 보여 준다. 플러그인이 새 값이나 필드를 더해도 화면을 고치지 않아도 된다(`docs/frontend.md` "공통").

## 자주 하는 확장

### SIEM 없이 받기

설정의 `[siem] adapter`를 `direct`로 둔다. 소스 커넥터가 낸 C1이 `direct` 어댑터를 거쳐 C2가 되고, 이후 흐름은 SIEM이 있을 때와 같다. 어느 소스를 알럿으로, 어느 소스를 이벤트로 볼지와 시나리오 이름은 설정에서 정한다.

### 새 SIEM 붙이기

1. `src/soc/ingest/siem/base.py`의 커넥터 인터페이스를 구현한다. 그 SIEM에서 알럿·이벤트를 가져와 C2 SiemAlert를 내보내면 된다. 같은 SIEM용 SIEM MCP 어댑터(읽기 전용)도 함께 만든다.
2. 레포에 기여하면 같은 폴더에 두고, 사내 전용이면 별도 패키지로 만들어 `zero_ticket_soc.siem` entry point로 등록한다.
3. 설정의 `[siem] adapter`를 새 이름으로 바꾼다. 한 번에 하나의 SIEM만 연결한다.
4. 그 SIEM의 시나리오용 별칭 표를 추가한다(박스 4).

### 다른 LLM 쓰기

- OpenAI 호환 API를 제공하는 모델: 설정의 `provider`, `model`, `base_url`, `api_key_env`만 바꾼다. 코드는 바꾸지 않는다.
- 호환되지 않는 API: `src/soc/llm/base.py`의 인터페이스를 구현한 제공자를 추가하고 `zero_ticket_soc.llm_providers`로 등록한다.

### 새 로그 소스 붙이기

1. 소스 커넥터를 구현해 C1 RawRecord를 내보낸다. `source_type`에 새 이름을 등록한다.
2. 그 로그의 별칭 표를 추가한다.
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