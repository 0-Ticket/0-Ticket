---
issue: 311
date: 2026-11-13
owner: Pandyo
supersedes: []
---

# 로컬 ATT&CK·CVE·KEV 조회 도구 추가

## 목표

L2·L3 에이전트가 웹 없이 로컬 DB에 저장된 MITRE ATT&CK 기법과 CISA KEV를 `get_attack_technique`, `search_attack_techniques`, `get_cve`로 조회할 수 있게 한다. 기법 ID와 이름, CVE의 KEV 등재 여부를 모델의 기억이 아니라 저장된 사본에서 확인하게 한다. 요청 필드(설명 요약, 탐지 데이터 소스, 벤더·제품, 랜섬웨어 연관, 조치 기한, 데이터 시각)가 지금 저장되어 있지 않으므로 수집 계층(`soc.l3.intel`)을 함께 확장한다.

## 방법

데이터가 흐르는 순서: 수집(`uv run python -m soc.l3.intel`)이 새 필드까지 저장 → 도구가 `soc_agent_reader`로 읽음 → 에이전트.

**1. 저장 확장 (L3 수집)**
- 마이그레이션 `0301_intel_local_lookup.sql`: 이미 적용된 `0300`은 고치지 않는다. 추가만 한다.
  - `attack_techniques`에 nullable 열: `description text`, `detection_sources text[]`, `collected_at timestamptz`. 기존 행은 NULL로 남는다.
  - 새 테이블 `kev_entries(cve_id PK, vulnerability_name, short_description, vendor_project, product, date_added, due_date, known_ransomware_use, required_action, updated_at)`. 값 모양 CHECK는 0300과 같은 기준(행 하나만 봐도 깨진 레코드인지 아는 것). `threat_news`는 바꾸지 않는다.
  - 새 테이블 `intel_source_state(source PK, catalog_version, released_at, collected_at)`: KEV 출처의 마지막 성공 수집 정보. 수집 성공 시 한 행을 갱신한다.
- `parse.py`: `parse_attack`이 `description`(`clean_text`, 상한 글자 수는 설정)과 `detection_sources`(기법 ← `detects` 관계 ← `x-mitre-detection-strategy` → `x_mitre_analytic_refs` → `x-mitre-analytic.x_mitre_log_source_references[].x_mitre_data_component_ref` → data component 이름, 중복 제거·정렬)를 더한다. `parse_kev`는 `NewsItem` 목록과 함께 `KevEntry` 목록, 카탈로그의 `catalogVersion`·`dateReleased`를 돌려준다. 기존 `threat_news` 입력은 그대로다. 20.0 번들에서 관계·분석 객체의 모양이 틀리면 지금처럼 그 출처 전체를 `parse` 실패로 처리한다.
- `store.py`·`collect.py`: ATT&CK 저장은 `ON CONFLICT DO UPDATE`로 바꾸고, `has_attack_version`은 "`collected_at`이 채워진 행이 있는가"로 바꾼다. 이미 저장된 20.0은 다음 수집에서 다시 받아 채운다(별도 명령 없음). KEV는 `threat_news`와 `kev_entries`와 `intel_source_state`를 같은 출처 트랜잭션에서 쓴다.
- 이미 저장된 `threat_news`·`attack_techniques`를 읽는 헌팅(`l3/hunt/store.py`)과 API(`api/routes/hunts.py`, `threat_news.py`)는 열 이름을 지정해 읽으므로 바꾸지 않는다.

**2. 읽기 권한**
- 마이그레이션 `0302_agent_reader_intel.sql`: `soc_agent_reader`에 `attack_techniques`, `kev_entries`, `intel_source_state`의 SELECT만 준다. `threat_news`는 주지 않는다. 0300 헤더의 "권한을 주지 않는다"는 `threat_news`에만 남고, 갱신된 범위는 결정 D-052에 적는다.

**3. 도구** (`src/soc/tools/local_intel.py`, `default_registry()`에 등록, 전부 읽기 전용·DB만 읽음, `tools/db.py`의 `read_rows`·`read_many`)
- `get_attack_technique(technique_id)`: `T1190`, `attack.T1190`, 대소문자 무시를 받아 `T####(.###)`로 정규화한다. 그 밖의 모양은 `invalid_argument`. 결과(aggregate): `status`(`found`/`not_found`/`no_data`), `technique_id`, `name`, `tactics`, `description`(도구 설정의 상한으로 자름), `parent`(하위 기법이면 상위 ID와 이름), `subtechniques`(같은 버전의 하위 기법 ID·이름, 상한), `detection_sources`(상한), 데이터 버전·수집 시각.
- `search_attack_techniques(query, limit)`: 설정 버전의 이름·설명에서 `ILIKE`(`%`·`_`·`\` 이스케이프, 최대 길이 제한). 이름 일치를 앞에 둔다. `limit`은 `[tools] default_limit`·`max_limit` 규칙(`limit_argument`). 결과는 ID·이름·전술·짧은 설명 앞부분. 영어 키워드로 검색한다(프롬프트에 한 줄).
- `get_cve(cve_id)`: `CVE-YYYY-NNNN+` 형식만 받는다. KEV에 있으면 `status: "found"`와 취약점 이름, 벤더·제품, 요약(상한), 랜섬웨어 연관, 추가일, 조치 기한, 필수 조치(상한). 없으면 `not_in_kev`(악용되지 않음이 아니라 KEV 목록에 없다는 뜻). NVD 등 다른 CVE 데이터는 적재하지 않는다.
- 데이터 없음: 설정 버전의 `attack_techniques`가 없거나 `collected_at`이 비었거나, `kev_entries`가 비었거나 `intel_source_state`가 없으면 오류가 아니라 `status: "no_data"`와 이유 이름만 돌려준다. `not_found`/`not_in_kev`와 섞이지 않는다.
- 모든 응답에 `attack_version`, `attack_collected_at`(ATT&CK 도구) 또는 `kev_catalog_version`, `kev_released_at`, `kev_collected_at`(`get_cve`)을 넣는다. 시각은 ISO 8601 UTC 문자열.
- 밖에서 온 문자열(기법 이름·설명, KEV 이름·요약)은 레지스트리가 데이터 구분자로 감싸 전달하며, 길이를 제한한다. 결과는 외부 LLM 입력 필터(D-048)를 그대로 거친다.
- 설정 `[tools.local_intel]`: `attack_version`(`[l3.intel.attack] version`과 같은 값, 올릴 때 함께 바꾼다고 주석에 적는다), `description_max_chars`, `list_max_items`(하위 기법·탐지 소스). `check_config`로 값 모양을 실행 시작 전에 검사한다. 허용 단계는 `[tools.allowed]`의 `l2`·`l3`.
- 프롬프트: `src/soc/agent/prompts/l2.md`, `l3.md`에 `not_in_kev`는 "KEV에 없음"이지 "악용되지 않음"이 아니라는 한 줄과 기법 검색은 영어 키워드로 한다는 한 줄. 도구가 없는 단계(`l1`)는 건드리지 않는다.

**4. 결정 목록 (`docs/decisions.md`)**
- D-040 본문: 저장 필드에 설명·탐지 데이터 소스·수집 시각을 더한다.
- D-052 추가: 로컬 인텔 조회 도구, 읽기 권한 범위, KEV 저장 방식.
- 기록 맨 위에 한 줄. 기존 충돌 표식과 D-049/D-050 중복은 고치지 않는다.

## 바꿀 곳

- `src/soc/db/migrations/0301_intel_local_lookup.sql`, `0302_agent_reader_intel.sql`: 새 파일
- `src/soc/l3/intel/parse.py`, `store.py`, `collect.py`: 위 저장 확장. `__main__.py` 출력은 그대로(건수만)
- `src/soc/tools/local_intel.py`: 새 모듈. `src/soc/tools/__init__.py`: `default_registry()`에 추가, docstring 고침
- `config/default.toml`: `[tools.local_intel]` 추가, `[tools.allowed]`의 `l2`·`l3`에 세 도구 추가
- `src/soc/agent/prompts/l2.md`, `l3.md`: 한 줄씩
- `tests/fixtures/l3_intel/attack.json`, `kev.json`: description·detects·분석·data component·KEV 추가 필드를 손으로 줄여 확장
- 테스트: `tests/test_l3_intel.py`, `tests/test_l3_intel_db.py`(수집 확장), `tests/test_tools_local_intel.py`(순수 검증), `tests/test_tools_local_intel_db.py`(`db` 마커, 읽기 역할 계정), 기본 레지스트리·기본 설정 기대값을 확인하는 기존 테스트(`tests/test_agent_config.py::test_default_tools_config`, `tests/test_tools_registry.py`, `tests/test_db_tables.py`의 `schema_migrations` 행 수)는 지우거나 건너뛰지 않고 기대값만 고친다
- `docs/decisions.md`: D-040 수정, D-052, 기록 줄
- `docs/notes/311-local-intel-tools.md`: 개발 기록(개발·마무리 단계에서)

## 다른 코드와 맞물리는 곳

- 테이블: `attack_techniques`에 nullable 열 3개 추가, 새 테이블 `kev_entries`·`intel_source_state`. 기존 열·테이블 모양은 바꾸지 않아 헌팅·API 읽기 코드는 그대로 동작한다. 이 이슈 담당이 L3 담당이라 수집 변경은 이슈 담당이 직접 확인했다.
- 데이터 형식: `parse_attack`·`parse_kev`의 반환 형식이 바뀐다. 호출하는 곳은 `collect.py`뿐이다(구현 전에 다시 grep으로 확인한다).
- 권한: `soc_agent_reader`에 세 테이블 SELECT가 생긴다. 접속용 LOGIN 역할은 운영자가 이미 `soc_agent_reader` 멤버로 만든 것을 그대로 쓴다.
- 설정 키: `[tools.local_intel]` 신설, `[tools.allowed]` `l2`·`l3` 값에 도구 이름 추가. `config/local.toml`에서 `l2`·`l3`를 따로 정의한 사람은 도구 이름을 직접 더해야 한다(기록에 적는다). `[l3.intel.attack] version`과 `[tools.local_intel] attack_version`은 따로 바꾸므로 어긋나면 `no_data`가 된다.
- 첫 수집 후 `uv run python -m soc.l3.intel`을 한 번 다시 돌려야 기존 ATT&CK 20.0과 KEV 상세가 채워진다.
- 환경변수: 없음.

## 범위 밖

- `l1` 허용, NVD 등 KEV 밖의 CVE 데이터(CVSS 포함)와 임베딩 검색
- analytic 로그 소스의 `channel`(이벤트 코드), 완화책(course-of-action), 침입 집단·소프트웨어 관계
- 보관 기간(지난 ATT&CK 버전·오래된 뉴스 삭제), KEV 항목 삭제 추적(카탈로그에서 빠진 CVE)
- 헌팅·API의 읽기 코드 변경

## 완료 기준

- [ ] 세 도구가 로컬 데이터에서 위 필드를 돌려주고, `tests/fixtures/`의 손으로 줄인 샘플로 확인하는 테스트가 있다
- [ ] `T1190`과 `attack.T1190`(소문자 포함) 입력이 같은 결과를 돌려주는 테스트가 있다
- [ ] 없는 기법 ID는 `not_found`, KEV에 없는 CVE는 `not_in_kev`, 데이터가 없으면 `no_data`로 구분되는 테스트가 있다
- [ ] 모든 응답에 데이터 버전·수집 시각이 들어 있다
- [ ] `limit` 상한과 설명 길이 제한을 넘기지 않는 테스트가 있다
- [ ] 도구가 네트워크 호출을 하지 않는다(테스트에서 소켓을 막아도 통과)
- [ ] 수집 확장: 새 열·테이블이 채워지고, 이미 저장된 ATT&CK 버전이 다시 채워지며, 같은 입력을 두 번 받아도 새로 저장 0건·갱신 0건이다. 헌팅·API 기존 테스트가 통과한다
- [ ] `soc_agent_reader` 계정으로 세 테이블을 읽을 수 있고 `threat_news`는 읽지 못하며 쓰기는 못 한다(`db` 테스트)
- [ ] 허용 목록에서 `l2`, `l3`만 쓸 수 있다(`l1` 거부 테스트)
- [ ] 프롬프트에 `not_in_kev` 해석 한 줄이 들어갔다
- [ ] 실제 ATT&CK 20.0 번들과 KEV로 수집을 한 번 돌려 건수만 기록에 적었다(원본 커밋 없음)
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과
- [ ] `docs/decisions.md`에 D-040 수정과 D-052가 있다
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록

## 토론으로 정한 것

- 수집 코드 불변 → 수집 확장. 요청 필드(설명, 탐지 데이터 소스, 벤더·제품, 랜섬웨어, 기한)와 수집 시각이 저장되어 있지 않아서다. 이슈 담당이 L3 담당이라 직접 확인했다. (추천은 도구만 먼저 내고 수집 확장은 별도 이슈였으나 사람이 정했다.)
- 에이전트 읽기 역할: 이슈 설계의 "권한 없음"(0300)을 뒤집어 새 테이블과 `attack_techniques`에만 SELECT를 준다. `threat_news`는 주지 않는다(추천안 A보다 노출이 작다).
- 허용 단계는 `l2`·`l3`만. `l1`은 기법을 붙이지 않고 도구가 늘수록 모델이 도구를 헷갈려서 제외했다.
- ATT&CK 버전은 `[tools.local_intel] attack_version`에 따로 둔다. 도구가 `soc.l3`에 의존하지 않게 하고 테스트에서 설정을 넣기 쉽게 하려는 것이다. 어긋나면 `no_data`로 드러난다.
- KEV는 `threat_news`에 열을 더하지 않고 새 테이블 `kev_entries`로 둔다. RSS와 공용 테이블을 어색하게 만들지 않고, `get_cve`가 한 테이블만 읽는다.
- 탐지 데이터 소스는 ATT&CK 20.0 구조(기법 ← detects ← 탐지 전략 → analytic → data component)에서 data component 이름을 모은 것이다. 20.0 기법에는 옛 `x_mitre_data_sources`가 없다.
- 데이터가 없을 때는 오류가 아니라 `no_data` 결과 값으로 돌려준다.
- 결정 목록: D-040 수정, D-052 추가. `decisions.md`의 충돌 표식과 D-049/D-050 중복은 건드리지 않고 팀에 알린다.

## 바뀐 점
