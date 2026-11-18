---
issue: 328
date: 2026-11-18
owner: Pandyo
plan: 328-ocsf-schema-mapping-tables.md
supersedes: []
---

# OCSF 1.9.0 스키마를 전체 고정하고 알럿 단순 대응을 YAML 매핑표로 읽게 함

## 한 일

- Base Event(0)·Detection Finding(2004)과 참조 객체 127개를 공식 OCSF 1.9.0 API에서 받아 `ocsf/`에 고정했다(`scripts/fetch_ocsf_schema.py`로 재생성, 출처·방법은 `ocsf/SOURCE.md`). 줄인 `objects.json`(18개)은 이것으로 바뀌었다.
- `ocsf_schema.field_definition(class_uid, path)`가 경로(`finding_info.analytic.uid`, `evidences[].dst_endpoint.ip`)로 타입·요구 수준·enum·배열 여부를 돌려준다. 값 검사는 `float_t`·`json_t`·`bytestring_t`와 `just_one` 제약을 처리한다.
- 소스별 YAML 매핑표(`src/soc/normalize/mapping_tables/*.yaml`)를 `tables.py`가 `yaml.safe_load`로 읽는다. 항목은 `target`·`from`·`transform`·`required`, 선택 `detect`다. 변환은 `transforms.py` 등록부(`time`, `severity`, `round_int`)의 이름만 쓴다.
- `common.yaml`이 `mapping._finding`의 단순 대응 9개(제목, 설명, uid, 룰 ID, 룰 이름, 심각도, risk_score, message, 시각)를 대신한다. 정규화 결과는 이전과 같다(기존 테스트, `alert_skeleton` 15 케이스 포함, 변경 없음).
- `table_check.check_tables`(pytest가 돌린다)가 없는 target, 빠진 필수, 변환 값의 enum 위반을 잡는다. 모르는 변환 이름은 표를 읽을 때 `MappingTableError`다. 정규화 실행기(`run._run_batch`)와 `python -m soc.normalize`가 원본을 맡기 전에 표를 읽는다(CLI는 종료 코드 2).

## 계획과 달라진 점

- 공통 읽기 함수 `_value`를 `paths.read_value`로 옮겼다(`mapping.py`는 그 이름으로 가져다 쓴다). `tables.py`와 `mapping.py`가 서로 import하지 않게 하려는 것이다. `SEVERITY_IDS`·반올림 함수도 `transforms.py`로 옮겼다.
- 변환의 `accepts`(어떤 값을 "있는 값"으로 칠지)를 등록부에 뒀다. 기본(변환 없음)은 비어 있지 않은 문자열이고 `round_int`만 None이 아닌 모든 값이다. 지금 코드의 `_text`·`_value` 동작을 그대로 지키기 위해서다. 계획의 "있는 값" 정의를 구현한 것이다.
- 검증기의 `CODE_FILLED`는 `activity_id`, `category_uid`, `class_uid`, `type_uid`, `metadata`, `finding_info.analytic.type_id`다. 코드가 채우는 2004 경로가 늘면 여기에도 적어야 필수 커버리지 테스트가 통과한다.
- `uv.lock`은 손으로 두 줄만 고쳤다(아래 함정).
- 먼저 쓴 테스트: 스키마 로더 테스트는 고정한 데이터가 있어야 돌아가 구현·데이터 뒤에 처음 실행했다. 매핑표 테스트는 구현 전에 import 오류로 실패하는 것을 확인했다.

## 다음 사람이 알아야 할 것

- **`uv.lock`:** 로컬 uv 0.6.6이 잠금 파일을 `revision = 1`로 통째로 다시 쓴다(2000줄 변경). 그래서 되돌리고 PyYAML 두 줄(`dependencies`, `requires-dist`)만 손으로 넣었다. 새 의존성을 더할 때 같은 일이 생기면 최신 uv로 하거나 손으로 고친다.
- **런타임 검증이 느슨해졌다.** 목록 밖 공식 객체(`related_analytics`, `tactics`, `mitigation` 등)가 검사를 통과한다. 우리 코드가 내보내는 값은 알럿 회귀 테스트만 지킨다.
- `/export/schema`는 1.9.0에서 400이다(프로필 충돌). 단일 컴파일본이 생기면 `SOURCE.md`의 받는 방법을 다시 볼 만하다.
- `common` 표에서 uid·title·time은 코드의 `_FALLBACK_TARGETS`(`mapping.py`)와 짝이다. 표에서 이 항목을 지우거나 이름을 바꾸면 폴백이 항상 일어난다.
- `mapping_tables/`에 소스별 표를 더하면 검증기가 `common`과 합쳐 필수 커버리지를 검사한다. `detect`는 형식·로더·검증기만 있고 쓰이지 않는다(`_detect_source`는 코드). 배열 target(`evidences[].…`)은 검증기가 경로만 확인하고 채우는 코드는 없다.
- `ip`·`port`·`domain_or_ip` 변환은 등록하지 않았다(계획 "범위 밖"). 처음 쓰는 소스별 표 이슈에서 더한다.
- 표 오류는 `python -m soc.normalize`가 시작할 때 종료 코드 2로 알린다. `soc.pipeline`의 정규화 워커는 `run`이 `MappingTableError`를 던지는 것으로 드러나고 시작 시점 검사는 따로 만들지 않았다. 워커가 이 예외를 어떻게 다루는지는 확인하지 못했다.
- 객체 정의가 `objects.json` 한 파일(약 570KB)이다. 읽을 때 한 번 파싱해 캐시한다.
- 개발 DB: 새로 띄운 `docker compose` 컨테이너에는 `.env`의 DB(`zt_dev`)가 없어 `-m db` 테스트가 접속하지 못했다. 이번에는 `DATABASE_URL`의 DB 이름만 `postgres`로 바꿔 돌렸다(테스트는 임시 DB만 만든다).

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`: 통과(db 마커 제외 2065건).
- `uv run pytest -m db tests/normalize tests/test_pipeline_db.py tests/test_lab_cycle_db.py`: 41건 통과(DB 이름은 `postgres`로 바꿔서).
- 새 테스트: `tests/normalize/test_ocsf_full_schema.py`(스키마 고정·로더), `test_fetch_ocsf_schema.py`(스크립트), `test_mapping_tables.py`(표 로더·변환·`$.` 경로·`detect`·검증기·시작 시점). 표 샘플은 `tests/fixtures/normalize/mapping_tables/`.
- `uv run python scripts/fetch_ocsf_schema.py`: `just_one` 처리 전에는 처리하지 않는 제약 종류로 실패했고, 로더 수정 뒤 `classes=[0, 2004] objects=127`로 성공했다.
