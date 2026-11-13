---
issue: 311
date: 2026-11-13
owner: Pandyo
plan: 311-local-intel-tools.md
supersedes: []
---

# L2·L3 에이전트가 웹 없이 ATT&CK·KEV를 조회하고, 그 필드를 L3 수집이 저장하게 했다

## 한 일

L2·L3 에이전트가 `get_attack_technique`, `search_attack_techniques`, `get_cve`로 PostgreSQL에 저장된 ATT&CK과 CISA KEV를 읽는다(로컬 ATT&CK·KEV 조회, D-052). 네트워크는 쓰지 않는다.
- 응답은 `status`로 구분한다: `found`/`ok`, `not_found`(그 버전에 그 기법이 없음), `not_in_kev`(KEV 목록에 없음, 악용되지 않는다는 뜻이 아님), `no_data`(저장된 사본이 없음). 모든 응답에 `attack_version`·`attack_collected_at` 또는 `kev_catalog_version`·`kev_released_at`·`kev_collected_at`이 들어간다.
- `T1190`, `attack.T1190`, 소문자를 같은 기법으로 읽는다. 기법의 상위·하위는 저장하지 않고 ID 규칙(`T1059` / `T1059.001`)으로 같은 버전 안에서 도출한다.
- 도구가 필요로 하는 필드가 저장되어 있지 않아 수집(`uv run python -m soc.l3.intel`)을 확장했다. ATT&CK은 설명, 탐지 데이터 소스(기법 ← `detects` ← 탐지 전략 → analytic → data component 이름), 수집 시각을 `attack_techniques`에 더한다. KEV는 새 테이블 `kev_entries`(벤더·제품, 랜섬웨어 연관, 추가일, 조치 기한, 필수 조치)와 `intel_source_state`(카탈로그 버전·릴리스 시각·마지막 성공 수집 시각)에 저장한다. `threat_news`와 헌팅·API 읽기 코드는 바뀌지 않았다.
- 에이전트 읽기 역할 `soc_agent_reader`에 `attack_techniques`, `kev_entries`, `intel_source_state`의 SELECT를 줬다(0302). `threat_news`는 여전히 못 읽는다.
- 허용 단계는 `l2`·`l3`다(`l1` 아님). 프롬프트(`l2.md`, `l3.md`)에 "기법·KEV는 기억하지 말고 도구로 확인, `not_in_kev`/`no_data` 해석" 한 줄을 더했다.

## 계획과 달라진 점

- **도구 테스트를 구현 뒤에 썼다.** 수집 쪽(파싱, 저장)은 테스트를 먼저 쓰고 실패를 확인했지만, `local_intel.py`는 모듈을 먼저 쓰고 테스트를 이어서 썼다. 테스트는 DB 없이 도는 것(`test_tools_local_intel.py`)과 `db` 마커(`test_tools_local_intel_db.py`) 둘이다.
- **ATT&CK 설명의 저장 상한은 새 설정 없이 `[l3.intel] summary_max_chars`(1000)를 같이 쓴다.** 계획의 "상한 글자 수는 설정"은 이 값으로 충족했다. 도구가 모델에게 보이는 길이는 `[tools.local_intel] description_max_chars`(600)로 따로 자른다.
- **`parse_kev`는 남겼다.** 뉴스 항목만 돌려주는 얇은 함수이고, 수집은 새 `parse_kev_catalog`를 쓴다(기존 테스트가 부르고 있다).
- **KEV 파싱은 새 필드 일부가 없으면 그 출처 전체를 `parse` 실패로 처리한다**(`catalogVersion`, `vendorProject`, `product`, `knownRansomwareCampaignUse`, `requiredAction`). `dueDate`가 날짜 모양이 아니거나 `dateReleased`를 읽지 못하면 `NULL`로 두고 계속한다(CISA 형식이 조금 바뀌어도 수집이 멈추지 않게).
- **`known_ransomware_use`의 값 목록은 DB가 검사하지 않는다**(비어 있지만 않으면 됨). CISA가 새 값을 만들어도 수집이 멈추지 않게 했다.
- **`collected_at`이 `NULL`인 ATT&CK 행은 도구가 읽지 않는다**(0301 이전에 저장된 행). 한 버전 안에 일부만 비어 있으면 그 기법은 `not_found`, 전부 비어 있으면 `no_data`(`attack_detail_not_collected`)다.
- **`search_attack_techniques`의 성공 status는 `ok`**(없으면 `matched: 0`)로 했다. 계획에 이름을 못 박지 않았다. 응답에 `returned`, `description_truncated`, `text_truncated`, `detection_source_count`, `subtechnique_count`를 더했다.
- **결과가 도구 결과 한도(`max_tool_result_chars`)를 넘으면** 하위 기법·탐지 소스·검색 결과 목록을 뒤에서부터 빼고, 그래도 넘으면 설명을 줄인다. 전체 개수 필드는 줄이지 않는다.
- 기존 테스트의 기대값만 고쳤다(지우거나 건너뛰지 않음): `test_agent_config.py::test_default_tools_config`, `test_tools_registry.py::test_default_registry_has_the_five_tools`, `test_db_tables.py`(새 마이그레이션 둘과 새 테이블 둘), `test_tools_db.py::test_reader_role_migration_applies_to_another_database`(읽기 역할 권한 목록).
- `tests/fixtures/l3_intel/attack.json`은 기존 객체 순서를 그대로 두고 설명·탐지 객체를 뒤에 더했다. 다시 저장하면서 줄 모양이 바뀌어 diff가 크다.

## 다음 사람이 알아야 할 것

- **마이그레이션 뒤 수집을 한 번 더 돌려야 한다.** 이미 저장된 ATT&CK 20.0과 KEV는 새 열·표가 비어 있어, 그 전까지 도구는 `no_data`를 돌려준다(오류가 아님). 수집은 같은 버전이라도 `collected_at`이 비어 있으면 다시 받는다.
- **버전은 두 곳에서 바꾼다.** `[l3.intel.attack] version`(수집)과 `[tools.local_intel] attack_version`(도구)이 다르면 도구가 `no_data`(`attack_version_missing`)를 돌려준다. `config/local.toml`에서 `[tools.allowed]`의 `l2`·`l3`를 따로 정의했으면 세 도구 이름을 직접 더해야 한다.
- **ATT&CK 20.0에는 옛 `x_mitre_data_sources`가 없다.** 탐지 데이터 소스는 `detects` 관계로 이어진 탐지 전략·analytic의 data component 이름이다. 기법 706개 중 654개가 하나 이상 갖는다(나머지 52개는 파서가 놓친 것이 아니라 번들에 정보가 없다: 49개는 탐지 전략과 analytic은 있지만 analytic에 로그 소스 참조가 없고("조직 밖에서 일어나는 활동이라 탐지가 어렵다"는 취지의 설명, 예: 인프라 확보 하위 기법), 3개(`T1685.007`, `T1698`, `T1699`)는 `detects` 관계 자체가 없다. 가리키는 data component 객체가 없는 경우는 0건이다). analytic의 `channel`(이벤트 코드)은 저장하지 않는다.
- **KEV에서 빠진 CVE는 `kev_entries`에서 지우지 않는다.** 카탈로그에서 내려간 항목도 계속 `found`로 나온다(범위 밖으로 둠).
- **`kev_entries`는 `threat_news`와 이름·요약이 중복된다.** 헌팅·API가 `threat_news`를 읽고 도구가 `kev_entries`를 읽게 나눈 대가다.
- **한국어 질의로는 검색되지 않는다.** 이름·설명이 영어이고 `ILIKE`라서다. 프롬프트와 도구 설명이 영어 키워드를 쓰라고 안내한다. 706행 전체를 읽는 검색이라 색인은 두지 않았다.
- **첫 ATT&CK 수집이 메모리를 더 쓴다.** 실제 20.0 번들(약 55MB)을 받아 파싱하는 첫 실행의 최대 상주 메모리가 약 370MB였다. 같은 버전을 건너뛰는 실행은 약 70MB다. 상한 `max_bytes`(100MB) 안이다.
- 네트워크 호출 없음 테스트는 파이썬 소켓 연결(`socket.connect`)·`httpx`만 막는다. DB 접속은 libpq가 해서 막히지 않고, psycopg가 DB 호스트 이름을 풀 때 `socket.getaddrinfo`를 부르므로 DB 테스트에서는 그것을 막지 않는다. 도구 모듈이 `httpx`를 가져오지 않는 것도 테스트한다. 이 한계는 2026-11-13에 따로 확인했다(임시 DB, 테스트 코드 아님): 파이썬 감사 훅으로 도구 호출 세 번의 소켓·`urllib`·`http.client`·`ssl` 이벤트를 모으면 `socket.connect` 0건, HTTP·TLS 0건이고 `getaddrinfo`가 DB 호스트 이름으로 3건, 이벤트 루프 내부 소켓 생성이 6건이었다. 같은 호출 중 `lsof`로 본 이 프로세스의 인터넷 연결은 DB 서버 포트로 가는 연결 3개(호출마다 1개)뿐이었다.
- `docs/decisions.md`의 기존 충돌 표식과 D-049/D-050 중복은 건드리지 않았다. 팀이 따로 정리해야 한다.
- 0300 헤더의 "에이전트 읽기 역할에 권한을 주지 않는다"는 `threat_news`에만 남는다. 적용된 마이그레이션은 고치지 않아 주석은 그대로이고, 갱신된 내용은 D-052에 있다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run pytest`: 1799건 통과
- `DATABASE_URL=… uv run pytest -m db`: 471건 통과 (읽기 역할 권한 기대값을 고치기 전 첫 실행에서 1건이 실패했고, 고친 뒤 전체를 다시 돌려 통과)
- 주요 테스트
  - `tests/test_l3_intel.py`: KEV 상세·카탈로그 정보, 길이 상한, 필수 필드 누락 실패, ATT&CK 설명·탐지 데이터 소스(폐기된 관계·없는 참조 건너뜀, 모양이 틀리면 `parse` 실패)
  - `tests/test_l3_intel_db.py`: 새 열·표 저장, 같은 입력 두 번이면 바뀌지 않고 수집 시각만 움직임, 바뀐 항목만 갱신, KEV 실패 시 상세·상태가 그대로, `collected_at`이 빈 버전 다시 받기, CHECK
  - `tests/test_tools_local_intel.py`: ID 정규화, 잘못된 인자는 DB에 닿지 않음, `T1190`/`attack.T1190`/`attack.t1190` 같은 결과, `not_found`/`not_in_kev`/`no_data` 구분, 상한(설명·목록·`limit`·결과 한도), 설정 오류, 네트워크 호출 없음
  - `tests/test_tools_local_intel_db.py`(`db`): 읽기 역할로 읽기, `threat_news`와 쓰기 거부, 수집 전 `no_data`, 다른 버전 `no_data`, 비어 있는 행 미제공
- 실제 출처로 실행(임시 DB, 2026-11-13, 끝나고 지움)
  - 첫 실행: 종료 코드 0. 보안뉴스 50건, The Hacker News 50건, CISA KEV 1779건, ATT&CK 20.0 706건을 모두 새로 저장했다. `kev_entries` 1779건(랜섬웨어 `Known` 361건, 조치 기한 없음 0건), `intel_source_state` 1행.
  - 저장된 ATT&CK: 706건 모두 설명 있음(최대 1000자), 탐지 데이터 소스 있음 654건, `collected_at`이 빈 행 0건. T1190은 탐지 데이터 소스 6개.
  - 두 번째 실행: 종료 코드 0. 새로 저장 0건, 갱신 0건, ATT&CK은 같은 버전이라 건너뜀.
