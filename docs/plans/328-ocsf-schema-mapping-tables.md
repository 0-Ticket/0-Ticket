---
issue: 328
date: 2026-11-18
owner: Pandyo
supersedes: [234-ocsf-alert-event.md]
---

# OCSF 1.9.0 스키마 전체 고정과 선언형 매핑표 기반 만들기

`supersedes`는 234 계획의 "객체 정의를 줄여 담는다"는 방식만 2004·0과 그 참조 객체에 대해 대체한다. OCSF 서버 정의로 검증한다는 결정(D-007)은 그대로다.

## 목표

Detection Finding(2004)·Base Event(0)와 이 둘이 참조하는 객체 전체를 공식 OCSF 1.9.0 정의로 고정하고, 알럿 정규화의 단순 대응(`common` 9개 항목)을 코드가 아닌 YAML 매핑표로 읽는 기반을 만든다. 소스별 표는 만들지 않는다. 정규화 결과는 이전과 같다.

## 방법

1. **테스트 먼저.** `tests/fixtures/normalize/mapping_tables/`에 손으로 쓴 작은 테스트용 표(정상, 없는 `target`, 필수 누락, 잘못된 enum, 미등록 `transform`, `detect` 형식)를 두고, 스키마 로더·표 로더·검증기의 실패하는 테스트를 먼저 쓴다. 정규화 결과는 기존 테스트(`alert_skeleton` 15 케이스 포함)가 변경 없이 통과하는 것으로 확인한다.
2. **스키마 고정.** `scripts/fetch_ocsf_schema.py`(httpx)가 `https://schema.ocsf.io/api/1.9.0/classes|objects/<이름>?profiles=`에서 `base_event`·`detection_finding`을 받고 `object_type`을 따라 참조 객체를 모두 받는다(확인한 수: 객체 127개, 약 490KB). 결과를 `src/soc/normalize/ocsf/classes/0.json`, `2004.json`, `objects.json`(객체 이름을 키로 한 파일 하나, `win/reg_key` 같은 이름 그대로)에 키 정렬해 쓴다. 받은 정의는 직접 고치지 않는다.
   - 객체 `constraints`의 종류를 모두 모아, 스키마 로더가 처리하지 않는 종류가 있으면 스크립트가 실패한다.
   - `ocsf/SOURCE.md`에 출처(공식 API 주소), 받은 날짜, 버전, 재생성 명령, 단일 컴파일본이 없는 이유(`/export/schema`가 프로필 충돌로 400)를 적는다. 프로필 없이(`profiles=`) 받는다.
   - 4002·6003 클래스 파일은 건드리지 않는다. 기존 18개 객체는 새 정의와 `requirement`·`type`·`is_array`·`object_type`·enum 값이 같음을 확인했다.
3. **스키마 로더.** `ocsf_schema.py`에 클래스 uid와 경로(`finding_info.analytic.uid`, `evidences[].dst_endpoint.ip`)로 필드 정의(타입, 요구 수준, enum, 배열 여부)를 돌려주는 함수를 더한다. `validate_ocsf`의 시그니처와 동작은 유지하되 `float_t`(유한 수, bool 제외), `json_t`(JSON 값), `bytestring_t`와 문자열 계열 타입을 올바르게 처리한다.
4. **변환 등록부.** `src/soc/normalize/transforms.py`에 이름을 붙여 등록한다. `common`이 쓰는 `time`(ISO 8601 → UTC epoch ms), `severity`(low 2, medium 3, high 4, critical 5, 그 밖은 값 없음), `round_int`(유한 수 → 반올림 정수). 변환은 내보낼 수 있는 값 집합(`values`, 선택)을 선언하고, 검증기가 그 집합이 target의 enum 안에 드는지 본다. 타입 호환 검사는 하지 않는다.
5. **표 형식과 로더.** `src/soc/normalize/mapping_tables/*.yaml`, 읽을 때는 `yaml.safe_load`만 쓴다.
   - 항목: `target`(OCSF 경로), `from`(원본 경로 목록, 앞에서부터 처음 있는 값), `transform`(선택), `required`(선택, 기본 false). 표 최상위에 선택 `detect`.
   - `from`: `_source` 기준 점 표기이며 `mapping._value`·`_text` 규칙(평면 점 키 먼저, 없으면 중첩)을 따른다. `_source` 밖(hit)은 `$._id`처럼 `$.`로 시작한다. "있는 값"은 지금 코드와 같다. 문자열은 비어 있지 않은 것, 읽지 못하는 값은 다음 필드로 넘어가지 않고 오류다.
   - `detect`: 필드 `equals` 값 또는 키 존재, 위에서부터 첫 일치. 로더·검증기·테스트용 표까지만 만든다. `_detect_source`는 코드에 둔다.
   - 모르는 `transform` 이름은 표 로드 시점에 오류다. 정규화 실행기가 시작할 때 모든 표를 한 번에 읽는다.
6. **`common` 표와 mapping.py.** 아래 9개만 `common.yaml`로 옮기고 `mapping._finding`이 표로 읽게 한다. 나머지는 코드에 둔다.
   - 제목(`finding_info.title`), 설명(`finding_info.desc`), uid(`finding_info.uid` ← `kibana.alert.uuid`, `$._id`), 룰 ID(`finding_info.analytic.uid`, `required`), 룰 이름(`finding_info.analytic.name`), 심각도(`severity_id`, `severity`, `required`), `risk_score`(`round_int`), `message`(설명, 없으면 제목), 시각(`time`, `finding_info.created_time` ← `kibana.alert.start`, `@timestamp`).
   - 폴백 조건은 코드가 갖는다. `finding_info.uid`→`missing_uid`, `finding_info.title`→`missing_title`, `time`→`bad_time` 대응 상수를 두고, 이 target의 값이 없거나 읽을 수 없으면 지금처럼 class 0 폴백이다.
   - 표 `required` 누락(`finding_info.analytic.uid`, `severity_id`)은 `partial` + `missing_fields`다. 순서는 uid → severity → (코드의 `start_time`) → 잘못된 IP로 지금과 같다. `severity_id`는 값이 없으면 지금처럼 코드가 0을 채운다.
   - 상수(class·activity·type uid, `is_alert`, `status_id`), `start_time`·`end_time` 대체, `attacks`, `observables`, 엔티티, `evidences`, `metadata`, `unmapped`는 코드에 둔다.
7. **매핑표 검증기.** `src/soc/normalize/table_check.py`. 표의 `target`이 클래스 스키마에 있는지(`[]` 표기는 경로 검증에서 허용만 한다), 클래스의 필수 필드가 `common`과 소스별 표의 합집합 + "코드가 채우는 경로 목록"(상수)으로 덮이는지, 변환이 선언한 값이 target enum 안인지, `transform`이 등록돼 있는지 본다. 필수 커버리지는 표의 target 부모 객체가 있을 때만 그 객체의 필수 자식을 요구하고, 클래스 최상위 필수는 코드 채움 목록을 뺀 나머지를 요구한다.
   - pytest로 저장소의 모든 표와 테스트용 표를 검사한다. `ci.yml`은 바꾸지 않는다. `common` 표 하나만으로 실제 2004 스키마의 필수 커버리지를 검사하는 테스트도 둔다.
8. **의존성.** `pyproject.toml`에 PyYAML을 직접 의존으로 추가하고(`uv.lock`의 현재 버전으로 고정), `uv sync`로 잠금을 갱신한다. 코드에서 `yaml.safe_load` 외 호출은 없다.

## 바꿀 곳

- `src/soc/normalize/ocsf/classes/0.json`, `2004.json`, `ocsf/objects.json`, `ocsf/SOURCE.md`: 공식 정의로 대체
- `scripts/fetch_ocsf_schema.py`: 새로 만든다(스키마 재생성)
- `src/soc/normalize/ocsf_schema.py`: 필드 정의 조회, 타입 처리
- `src/soc/normalize/transforms.py`, `tables.py`, `table_check.py`: 새로 만든다
- `src/soc/normalize/mapping_tables/common.yaml`: 새로 만든다
- `src/soc/normalize/mapping.py`: `_finding`의 단순 대응 9개를 표로 읽게 한다
- `src/soc/normalize/__main__.py`(필요하면 `run.py`): 시작할 때 표를 읽는다
- `pyproject.toml`, `uv.lock`: PyYAML
- `tests/`, `tests/fixtures/normalize/mapping_tables/`: 테스트와 테스트용 표
- `docs/decisions.md`: D-060, D-061

## 다른 코드와 맞물리는 곳

- `ocsf/objects.json`: 객체 18개 → 127개, 정의에 설명이 더해진다. 읽는 곳은 `ocsf_schema.py`뿐인지 개발 중 확인한다. Event(4002·6003) 검증 결과는 같아야 한다.
- `validate_ocsf`: 시그니처 유지. 검증이 더 느슨해진다(아래 토론).
- 정규화 실행기: 시작할 때 표를 읽으므로, 표가 잘못되면 처리 전에 시작하지 못한다. `soc.pipeline`이 정규화를 부르는 지점도 같은 시작 경로를 타는지 개발 중 확인한다.
- 새 의존성 PyYAML: `uv sync`가 필요하다.
- `mapping.normalize`의 출력, Alert 계약, `normalize_status`: 바꾸지 않는다.

## 범위 밖

- ModSecurity·Suricata·GuardDuty의 실제 소스별 표, `_detect_source`를 표로 옮기는 일
- 시각 분리(`start_time`·`end_time`), 엔티티 role, outcome 판정, `attacks`, `observables`, `evidences`, `metadata`(코드에 남긴다)
- 배열 항목을 채우는 매핑(검증기는 `[]` 경로 표기를 허용만 한다)
- 옵션 프로파일, 2004·0 외 class(4002·6003 포함), Event 정규화, Alert 계약 변경
- `ip`·`port`·`domain_or_ip` 변환 등록(이 변환을 처음 쓰는 소스별 표 이슈에서 더한다)

## 완료 기준

- [ ] 공식 1.9.0 API에서 Detection Finding(2004), Base Event(0)와 참조 객체 127개를 고정했고, `SOURCE.md`에 출처·날짜·재생성 방법이 있으며 `scripts/fetch_ocsf_schema.py`로 다시 만들 수 있다. 처리하지 않는 `constraints` 종류가 있으면 스크립트가 실패한다.
- [ ] 줄인 `ocsf/objects.json`이 고정한 스키마로 대체됐고, 기존 코드(Event 4002·6003 검증 포함)가 새 스키마를 읽는다.
- [ ] 경로로 필드 정의(타입, 필수 여부, enum, 배열 여부)를 조회하는 로더가 있고 `float_t`·`json_t`·`bytestring_t` 처리와 함께 단위 테스트가 있다.
- [ ] 매핑표 형식(YAML)과 로더가 있고(`detect` 형식 포함), `common` 표가 `mapping.py`의 단순 대응 9개를 대신한다.
- [ ] PyYAML이 직접 의존에 있고 코드는 `safe_load`만 쓴다.
- [ ] 변환 등록부가 있고, 표에서 모르는 변환 이름을 쓰면 표 로드 시점에 오류가 나며 정규화 실행기가 시작할 때 모든 표를 읽는다.
- [ ] 검증기가 pytest로 돌고, 존재하지 않는 `target`, 빠진 필수 필드, 잘못된 enum 값, 미등록 `transform`을 각각 실패로 잡는 테스트가 있다. 저장소의 표와 `common` 단독 2004 필수 커버리지는 통과한다.
- [ ] 기존 normalize 테스트 전부(`alert_skeleton` 15 케이스 포함)가 변경 없이 통과한다.
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`가 통과한다.
- [ ] `docs/decisions.md`에 D-060, D-061이 있다.

## 토론으로 정한 것

이슈 본문과 달라진 점과 이유만 적는다. 답은 2026-11-18에 사람이 정했다.

- **공식 "컴파일본" 대신 API 순회.** 단일 컴파일본 파일이 없다(`/export/schema`가 프로필 충돌로 400). 공식 API를 `object_type`을 따라 순회해 클래스 2개와 객체 127개를 받고, `scripts/`의 httpx 스크립트로 재생성한다. 객체는 `objects.json` 한 파일에 키로 둔다.
- **"정제 샘플 6개"를 기존 normalize 테스트 전부로 바꿈.** `alert_skeleton.json`이 15 케이스라 6개를 따로 고를 근거가 없다. 기준은 "기존 normalize 테스트(15 케이스 포함)가 변경 없이 통과"다.
- **런타임 검증이 느슨해지는 것을 받아들임.** 줄인 정의는 목록 밖 객체(`related_analytics`, `tactics`, `mitigation` 등)를 내보내면 실패했지만, 127개 객체는 모두 공식 객체라 통과한다. 우리 코드가 목록 밖 객체를 내보내는지는 알럿 회귀 테스트가 잡는다.
- **PyYAML 직접 의존(D-060).** 이미 간접 의존으로 설치돼 있어 비용이 작다. `safe_load`만 쓴다.
- **`required`의 뜻.** 폴백 조건(uid·title·생성 시각)은 코드에 둔다. 표 `required` 누락은 `partial` + `missing_fields`다. D-059의 두 단계 누락을 그대로 지킨다(D-061).
- **`detect`는 제한된 형식으로, 판별은 코드에 둠.** 필드 `equals` 값 또는 키 존재, 위에서부터 첫 일치. 소스별 표가 없는 이 이슈에서는 형식·로더·검증기·테스트용 표까지만 만든다.
- **`common`으로 옮길 범위는 9개.** 상수, `start_time` 대체, `attacks`, `observables`, 엔티티, `evidences`, `metadata`는 코드에 둔다. 검증기가 코드가 채우는 경로 목록을 상수로 갖는다.
- **Event 클래스(4002·6003)는 건드리지 않음.** 객체 정의가 같고 로더가 같은 키만 읽는다.
- **표는 `src/soc/normalize/` 아래에 둠.** 표는 환경마다 바뀌는 값이 아니라 코드와 함께 배포한다.
- **로더 보완.** `float_t`·`json_t`·`bytestring_t` 등 타입 처리를 고친다. 20개 객체의 `constraints` 종류를 모두 확인하고, 처리하지 않는 종류가 있으면 스키마 고정 스크립트가 실패한다.
- **표 읽는 시점.** 표 로드 시점에 모르는 `transform` 오류가 나고, 정규화 실행기가 시작할 때 모든 표를 한 번에 읽어 처리 중간에 터지지 않게 한다.
- **CI.** pytest로 저장소의 표를 검사하고 `ci.yml`은 바꾸지 않는다.
- **`from` 경로.** `_source` 기준 점 표기(평면 점 키·중첩 모두), `_source` 밖은 `$.` 접두. `target`의 `[]` 표기는 검증기가 허용만 한다.
- **변환별 값 집합 선언.** 표에 리터럴 값이 없어 enum 검사는 변환이 선언한 `values`로 한다. 타입 호환 검사는 하지 않는다.
- **결정 목록:** D-060(YAML·PyYAML `safe_load`), D-061(선언형 매핑표 규칙).

## 바뀐 점

