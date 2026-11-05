---
issue: 234
date: 2026-11-05
owner: 미정
plan: 234-ocsf-alert-event.md
supersedes: [192-data-contracts.md]
---

# 한 번 실행하는 명령이 raw_records를 OCSF 알럿·이벤트로 바꿔 저장한다

## 한 일

`uv run python -m soc.normalize`가 아직 정규화하지 않은 `raw_records`를 한 묶음(기본 200건) 맡아 `alerts`와 `events`에 저장한다.

- `kind=alert`는 Detection Finding(2004)으로 `alerts`에, `kind=event`는 웹 접근 로그면 HTTP Activity(4002), CloudTrail·Azure·GCP면 API Activity(6003), 그 밖이면 Base Event(0)로 `events`에 저장한다. 원본 한 건당 결과 한 건이다. 원본은 바꾸지 않는다.
- 변환 결과는 OCSF 1.9.0 클래스·객체 정의(`src/soc/normalize/ocsf/`)와 `validate_contract()`를 모두 통과해야 저장된다. 한 건이 실패해도 나머지는 계속 처리하고, 실패는 `normalize_status`에 코드만 남긴다(`validation_failed`, `schema_failed`, `asset_lookup_failed`, `db_error`).
- `normalize_status`는 원본 한 건당 한 행이다. 맡은 작업자는 한 묶음에 대한 임대(기본 600초)를 가진다. 결과 저장과 상태 갱신은 한 트랜잭션이고, 임대를 잃은 작업자의 결과·실패 기록은 거부된다. `result_id`는 유일하다. `alerts`·`events`는 바꾸지 않았다.
- 자산 조회(`src/soc/asset_lookup.py`)는 정규화가 쓰는 같은 연결(`DATABASE_URL`)로 `(Entity type, 정규화한 값)`을 500개씩 한 쿼리로 찾아 `assets`에 붙인다. 자산이 없거나 테이블이 비어 있으면 성공한 불일치다. 연결 실패·시간 초과·테이블 누락은 `asset_lookup_failed`로 그 건을 실패시킨다.
- Asset 계약의 `entity_value`를 `entity: {type, value}`로 바꿨다. L2의 `normalize_value`는 `src/soc/entities.py`의 `normalize_entity_value`로 옮겼다(동작 같음).
- 마이그레이션 `0004_asset_lookup.sql`(자산 테이블)과 `0103_normalize_status.sql`을 더했다.

## 계획과 달라진 점

계획 파일의 "바뀐 점"에 적은 것이 전부다. 요약: OCSF 검증은 공식 클래스별 JSON Schema가 아니라 OCSF 서버의 클래스·객체 정의로 하고 위치는 `src/soc/normalize/ocsf/`다. P06 산출물을 이 이슈에서 만들었다. `cloud` 프로필 속성은 매핑하지 않았다.

## 다음 사람이 알아야 할 것

- **선행 이슈 상태:** 2026-11-05 현재 P01(#208), P05(#219), W01(#218), P06(#241)은 모두 열려 있다. 사용자는 이슈가 열린 상태여도 현재 방향을 W02에서 확정 가정으로 적용하라고 지시했다. 병합 전에 선행 이슈의 최종 결정과 다시 대조한다.
- **미확인 항목 U-01~U-09**(계획 참고)는 조직 ELK에서 확인되지 않았다. 공개 기준 데이터셋에서 확인한 U-01의 `kibana.alert.ancestors` 형태와 U-08의 개발 별칭은 근거로 기록했지만, 조직 ELK의 일치 여부는 미확인이다. W02 코드는 연결 키(U-01)를 읽지 않는다. 이 브랜치 코드에는 `UNVERIFIED(U-NN)` 주석 태그가 없으며, 식별자와 임시 처리는 계획 표에 있다.
- **Asset 계약 변경:** `entity_value`를 `entity: {type, value}`로 바꿨다. 계약 fixture(`valid/alert.json`, `valid/asset.json`, `invalid/asset.json`)도 새 모양이다. L1·L2·L3 담당자의 계약 변경 승인 기록은 확인하지 못했으므로 사람이 확인해야 한다.
- 자산 조회는 읽기 전용 계정이 아니라 정규화와 같은 연결을 쓴다. 읽기 역할(`soc_agent_reader`)에는 자산 테이블 권한을 주지 않았고 `docs/security.md`도 바꾸지 않았다. 문장 시간 상한은 조회 트랜잭션에만 적용한다(`set_config`).
- **자산 행을 채우는 코드는 없다.** 테이블이 비어 있으면 모든 조회가 불일치다. 실행 결과에 자산 0건을 따로 보여 주지 않는다.
- OCSF 정의의 `cloud` 같은 프로필 속성과 정의에 없는 속성은 검사에서 실패한다. 새 속성을 내보내려면 `ocsf/objects.json`에 객체 정의를 더한다(`ocsf/SOURCE.md`).
- 한 번 실행은 배치 한 번만 처리한다. 실패 건은 시도한 지 오래된 순서로 다음 실행에서 다시 잡히며, 새 원본이 먼저다. 실패가 계속되면 횟수 제한 없이 이어진다.
- `normalize_status`에 `lease_lost`는 저장하지 않고 실행 출력에만 센다.
- 임대는 묶음에 걸려 있어서 `lease_seconds`가 묶음을 처리하는 시간(건수 × 건당 최대 조회 시간)보다 짧으면 뒤쪽 원본이 `lease_lost`가 될 수 있다. 설정 로더는 이 관계를 검사하지 않는다.
- 원본에서 정수로 읽는 값(HTTP 상태 코드)은 ASCII 숫자 9자리 이하 문자열만 받는다. 유니코드 숫자나 아주 긴 숫자 문자열로 `int()`가 예외를 내 실행이 멈추는 문제를 막았다(검토에서 발견, 샘플 3건으로 고정).
- `0103`은 W01(#218)의 `0100`~`0102`가 머지되기 전에도 적용된다. 번호 순서 경고만 나올 수 있다.
- Azure·GCP 이벤트는 CloudTrail 필드 이름으로 읽으므로 `source.ip` 등이 없으면 `schema_failed`가 된다(U-07).

## 확인 방법

- `uv run ruff format .`, `uv run ruff format --check .`(197 files), `uv run ruff check .`, `uv run pytest`, `uv run pytest -m db`, `uv run python scripts/generate_contracts.py --check` 통과. 최신 `origin/main` 기준 전체 테스트는 1,017 passed, DB 테스트는 로컬 PostgreSQL에서 259 passed.
- `uv run pytest`: 963 통과, `uv run pytest -m db`: 253 통과(로컬 PostgreSQL).
- 주요 테스트: `tests/test_normalize_mapping.py`(샘플 18건 변환·실패 코드, OCSF 검사), `tests/test_normalize_db.py`(반복 실행, 임대 상실, 실패 덮어쓰기 거부, 원본 해시 불변, 자산 붙이기), `tests/test_asset_lookup.py`, `tests/test_normalize_config.py`, `tests/test_normalize_main.py`.
- 임시 DB에서 CLI 실행: 샘플 18건 중 성공 11건(알럿 2, 이벤트 9), 실패 7건(`schema_failed` 3, `validation_failed` 4). 두 번째 실행은 실패 7건만 다시 잡았고 결과가 늘지 않았다.
- 실제 ELK에서는 확인하지 않았다. 합성 샘플로만 검증했다.

## 추가 합의 (2026-11-05)

- `kind=event` RawRecord는 OCSF Event 하나, `kind=alert` RawRecord는 Detection Finding(class_uid 2004) 하나로 정규화한다. 프로젝트는 Event에서 Alert를 만들지 않는다. ELK가 생성해 Alert 저장소에 쓴 `kind=alert` 원본만 정규화한다.
- 같은 RawRecord의 재수집·재처리는 원본 식별자 기준으로 중복을 막는다. 동일 활동을 가리키는 Event와 Alert는 각각 보존하고 관계로 연결한다. 한 Alert가 여러 Event를 대표할 수 있으므로 1:1로 가정하지 않는다.
- 연결 필드 후보 `kibana.alert.ancestors`는 공개 데이터셋에서만 확인했다. ELK 환경이 아직 구성되지 않아 실제 조직 ELK의 필드와 참조 대상 인덱스는 검증하지 못했다. 따라서 W02는 연결을 만들지 않으며, 실제 확인 후 추출·`link_by_refs` 호출과 미해결 쌍 재처리를 W01 후속 이슈에서 다룬다.
- 이 기록을 갱신할 때 확인한 GitHub 상태는 #208(P01)·#219(P05) 닫힘, #218(W01)·#241(P06) 열림이다. P01이 닫혀도 ELK의 실제 참조 필드는 검증되지 않았으므로 U-01은 미확인이다.
- Asset 승인 상태 갱신(2026-11-05): 사용자가 공통 Asset 계약 변경 승인을 받았다고 확인했다. 위의 승인 기록 미확인 문구는 당시 확인 상태를 남긴 것이며, 현재 W02에서는 승인 대기 항목으로 취급하지 않는다.
