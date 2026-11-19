---
issue: 347
date: 2026-11-19
owner: uptime-zero
supersedes: []
---

# Event 계약을 Alert처럼 OCSF 최상위 구조로 바꾸고, 우리 쪽 값은 details에 모은다

## 목표

Event(`events` 테이블과 Event 계약)를 Alert(#338 D-065, #339 D-066)와 같은 구조로 맞춘다. `events.ocsf`가 원본이고, 계약 JSON의 최상위는 OCSF 1.9.0 문서(`ocsf` 키 없음)이며, 우리 쪽 값 `id`·`raw_id`·`entities`·`assets`는 `details`에 둔다. `time`·`summary`·`ocsf_class` 컬럼은 `ocsf`에서 파생 함수 한 곳이 만든다. 읽는 쪽은 같은 결과를 낸다.

## 방법

1. **샘플과 테스트 먼저.** `tests/fixtures/`의 기존 이벤트 샘플(4002·6003·Base Event)과 시드 픽스처를 쓴다. 새 샘플과 실데이터 원본은 만들거나 커밋하지 않는다. 조립 함수 기대값은 테스트용 픽스처로만 둔다.
2. **계약(`contracts/event.schema.json`).** 최상위는 OCSF 문서이고 필수 키만 적는다: `class_uid`, `time`, `severity_id`, `details`. 나머지 OCSF 속성은 `additionalProperties: true`다. `details` 필수 키는 `id`, `raw_id`, `entities`, `assets`다. 생성 코드(Python·TS)는 `scripts/generate_contracts.py`로 갱신한다(D-003). `contracts/validate.py`의 "`ocsf_class` == `ocsf.class_uid`" 규칙은 구조상 사라진다.
3. **조립·파생 모듈.** `soc/contracts/alert.py` 옆에 `event.py`를 둔다(`assemble_event`, `event_time`, `event_summary`, `event_model_input`, `contract_data` 확장). DB 없는 순수 함수이고 읽기 전용이다.
4. **파생 함수 한 곳.** `ocsf`에서 컬럼을 만든다. `time` = `start_time`, 없으면 `time`(알럿과 같은 헬퍼) / `ocsf_class` = `class_uid` / `summary` = `message`. 정규화·재처리·시드 3종이 모두 쓴다.
5. **시각.** OCSF 정의대로 `time` = 활동 발생 시각(`@timestamp`), `start_time`은 개별 이벤트에는 비운다.
6. **summary.** 정규화가 `message`를 항상 채운다. 1순위 클래스별 요약(예 `GET /api 200`), 2순위 `event.dataset`, 3순위 `event`. 데이터셋은 OCSF 문서에 없으므로 파생 함수가 아니라 정규화(매핑) 단계에서 처리한다.
7. **요약 정의.** `mapping_tables/events/<클래스 번호>.yaml`의 `summary` 항목에 OCSF 경로 목록으로 쓴다. 값이 있는 부분을 공백으로 이어 1순위를 만든다. 저장한 7개 클래스(0·2003·3002·4001·4002·4003·6003)를 정의하고, 경로가 `ocsf/classes/` 정의에 있는지 pytest로 검사한다. 알럿 매핑표 로더(`mapping_tables/*.yaml`만 읽음)와 `table_check.py`는 이 폴더를 읽지 않는다. 이 폴더를 읽고 검사하는 로더는 따로 둔다.
8. **activity_id = 99.** Base Event, 4002, 6003 공통으로 `activity_id = 99`(Other)이면 `activity_name`에 출처 고유 값(알 수 없는 메서드·동작, Base Event는 `event.action`)을 담는다. Base Event는 요약 1순위가 `activity_name`이고, `event.action`이 없으면 `activity_id = 0`이다. `type_uid`는 클래스×100 + `activity_id`라 Base Event는 0에서 99가 된다(`0.json` enum에 99가 있음을 확인함).
9. **검증.** OCSF 검증(`validate_ocsf`)은 `details`를 뺀 문서에, 계약 검증은 전체에 적용한다. `details`에는 OCSF 속성 이름과 같은 키가 없음을 테스트로 확인한다.
10. **DB.** 마이그레이션 `0304_event_ocsf_class.sql`: `events`에 `(ocsf ->> 'class_uid') IN ('0','2003','3002','4001','4002','4003','6003')` CHECK를 더한다. 옛 형식의 NULL은 통과하고, 어긋나는 기존 행이 있으면 알리고 멈춘다. 생성 컬럼은 쓰지 않는다.
11. **재처리.** `python -m soc.normalize reprocess --kind event`(기본 `--kind alert`는 지금과 같다). `--source`는 `--kind alert`에서만 허용한다. id를 유지한 채 다시 만들고(기존 행 `ocsf`에 `message`가 없어 채워야 한다) 값이 달라진 행만 갱신한다. 정규화·자산 조회가 실패한 행은 건너뛰고 건수를 출력한다. `outcome` 비교는 이번에 하지 않는다. 알럿 동작은 바꾸지 않는다.
12. **읽는 쪽.** `get_event`는 조립 JSON을 돌려주고 `ToolSpec.id_fields`는 `("details.id",)`다. 조회 API `raw_detail`의 event `record`를 조립 JSON으로, L2 문맥·임베딩(`summary`)·L3 근거·UI·프런트 생성 타입(`contract-event.ts`, `RawDetail.ts`)을 새 구조에 맞춘다. 모델 입력 모양은 `event_model_input`으로 유지한다. `l2/branch/read.py`의 `_TIME_FIELDS["event"]`는 알럿처럼 조립 JSON에서 변환이 필요 없고, 모델 입력의 `time`은 `start_time` 우선 헬퍼를 거친다.
13. **자산 조회.** `lookup_assets`는 `entities`를 키로 하는 현재 방식을 유지한다. 조회 순서와 재처리의 재사용 규칙도 바꾸지 않는다.
14. **결정 기록.** `docs/decisions.md`에 D-068을 더한다(D-066의 "`get_event`는 바꾸지 않는다"를 대체).

## 바꿀 곳

- `contracts/event.schema.json`, 생성물 `src/soc/contracts/generated/`·`frontend/src/api/generated/contract-event.ts`·`RawDetail.ts`, `src/soc/contracts/validate.py`
- `src/soc/contracts/event.py`(새 파일), `src/soc/contracts/__init__.py`
- `src/soc/normalize/mapping.py`·`store.py`·`run.py`: 파생 함수, 요약 정의 읽기, `message`와 `activity_name` 채우기
- `src/soc/normalize/mapping_tables/events/*.yaml`(7개)와 이벤트 요약 로더
- `src/soc/normalize/reprocess.py`, `src/soc/normalize/__main__.py`: 이벤트 재처리
- `src/soc/db/migrations/0304_event_ocsf_class.sql`
- 시드 3종(`agent/dev_l1.py`, `l3/hunt/dev_seed.py`, `api/dev_seed.py`)과 시드 픽스처(`ui_seed.json`, `l1_e2e/dev_seed.json`, `l3_hunt/dev_seed.json`, `l3_hunt/seed.json`)
- `src/soc/tools/internal.py`, `src/soc/api/ui_read.py`, `src/soc/l2/branch/*`, `src/soc/l2/analyze/context.py`
- 픽스처·테스트: `tools/records.json`, `l2/branch.json`, `l2/embedding.json`, `contracts/valid·invalid/event.json` 등
- `docs/decisions.md`, `docs/plans/347-event-ocsf-top-level.md`, 개발 중 `docs/notes/347-event-ocsf-top-level.md`

## 다른 코드와 맞물리는 곳

공통 계약 변경이다. L1·L2·L3·UI 담당 확인을 계획 확정 뒤 PR 전에 받는다.

- **Event 계약**(`contracts/event.schema.json`)과 생성 코드: 최상위가 OCSF 문서로 바뀌고 `ocsf` 키가 없어진다. 필수 키와 `additionalProperties`가 바뀐다.
- **`events` 테이블**: `ocsf`가 원본이 되고 `ocsf`에 `message`가 더해지며 CHECK 제약이 생긴다. 컬럼 이름·타입은 바뀌지 않는다.
- **에이전트 도구**: `get_event` 반환 모양이 조립 JSON으로 바뀌고 `id_fields`가 `details.id`가 된다. `query_records`는 바꾸지 않는다.
- **UI**: `raw_detail`의 event `record` 응답 모양과 프런트 생성 타입이 바뀐다.
- **L2·L3**: `BranchRows`의 이벤트 모양과 L3 근거 읽기가 바뀐다.
- **정규화 CLI**: `reprocess`에 `--kind`가 더해진다. 기본 동작은 그대로다.

## 범위 밖

- 클래스를 정규화에 연결(원본에 클래스·수집 키 저장)
- 이벤트 매핑표(`entries`·`entities`)
- 엔티티 정리와 `observables` 파생(이벤트의 entities에서 observables·evidences를 만드는 규칙 적용)
- 이벤트 `outcome` 기록과 `reprocess`의 `outcome` 비교
- 폴백(읽을 수 없는 이벤트를 class 0으로 저장)
- DB 컬럼 변경, `events`를 비우고 재수집하는 방식

## 완료 기준

- [ ] Event 계약의 최상위가 OCSF 문서이고 `details`에 `id`·`raw_id`·`entities`·`assets`가 있다. 생성 코드(Python·TS)가 일치한다.
- [ ] 파생 함수 한 곳이 `time`·`summary`·`ocsf_class`를 만들고 정규화·재처리·시드 3종이 모두 쓴다.
- [ ] `mapping_tables/events/`의 요약 정의가 저장한 7개 클래스를 덮고, 경로가 클래스 정의에 있음을 테스트한다. 알럿 로더가 `events/` 안 파일을 읽지 않음을 테스트한다.
- [ ] 현재 이벤트(4002·6003)의 요약 텍스트가 이전과 같다(OCSF에서 빠진 값 제외). `activity_id = 99`인 이벤트(Base Event, 알 수 없는 4002 메서드·6003 동작)는 `activity_name`이 채워지고, Base Event는 `event.action`이 있으면 요약이 이전과 같다.
- [ ] `details`에 OCSF 속성 이름이 섞이지 않았음을 테스트로 확인한다.
- [ ] 마이그레이션 CHECK가 있고 기존 행이 어긋나면 멈추고 알린다.
- [ ] `reprocess --kind event`로 기존 이벤트를 id 유지한 채 다시 만들 수 있고, 기본(알럿) 동작과 `--source`는 그대로이며 `--kind event`에서 `--source`는 거부한다(개발 DB 사본에서 건수 확인은 사람이 한다).
- [ ] 읽는 쪽(`get_event`, `raw_detail`, L2 문맥, L3 근거, UI)이 같은 모델 입력과 화면 결과를 낸다. `ToolSpec.id_fields`가 `get_event`의 근거 ID를 경로로 읽는다.
- [ ] 자산 조회 결과가 정렬 전후 같다(같은 `entities`면 같은 `assets`).
- [ ] L1·L2·L3·UI 담당 확인(PR 전).
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`가 통과한다.

## 토론으로 정한 것

- **시각:** OCSF 정의를 따른다. 개별 이벤트(0·4002 등)의 `time`은 활동 발생 시각이고 `start_time`은 집계에만 쓰므로 비운다.
- **summary:** 알럿처럼 `message`에서 파생한다(알럿은 `finding_info.title`, 없으면 `message`). 1순위 클래스별 요약, 2순위 `event.dataset`, 3순위 `event`. 클래스별 1순위는 OCSF 정의에 있는 속성 경로로 `mapping_tables/events/<번호>.yaml`에 미리 정의한다(예 4002 `http_request.http_method`, `http_request.url.path`, `http_response.code`).
- **범위:** 구조 정렬만 한다. 클래스 연결과 이벤트 매핑표는 후속 이슈다.
- **DB 제약:** 알럿(0303)처럼 `class_uid` CHECK를 둔다. 허용 클래스는 저장한 7개다.
- **`activity_id = 99` 규칙:** 이슈 본문은 Base Event만 다뤘으나, OCSF 규칙이 클래스 공통이고 현재 4002·6003 코드도 `activity_id = 99`를 `activity_name` 없이 만들고 있어 Base Event·4002·6003에 공통 적용한다.
- **재처리:** 이번에는 `outcome` 비교 없이 달라진 행만 갱신한다. `outcome` 도입은 다음 작업 중 겹치는 곳에서 한다. 선택은 `--kind event`다.
- **entities→observables 파생:** 이번에는 이벤트에 적용하지 않는다(엔티티 정리와 함께 후속).
- **개발 시점:** #340이 머지(PR #346)되어 4001·4003·3002·2003 정의가 `main`에 있으므로 확정 후 바로 개발한다.
- **결정:** D-068. D-066의 "`get_event`는 바꾸지 않는다"를 대체한다.

## 바뀐 점

- 2026-11-19 · 7개 클래스에 없는 시드 이벤트(1007·1001·3001)가 CHECK에 걸려 알럿(#338)처럼 시드를 OCSF 검증을 통과하게 다시 쓰기로 했다(Base Event + `activity_name`, 내용은 `unmapped`). 시드 변경은 L1·L2·L3 담당 확인 대상이다.
- 2026-11-19 · 제약 이름을 `events_ocsf_class_uid_check`로 했다(`events.ocsf_class` 컬럼 CHECK가 이미 `events_ocsf_class_check`를 쓴다). 계약의 `message`는 필수로 두지 않고 `event_summary`가 비면 "event"를 돌려준다.
- 2026-11-19 · 계약에 `message`를 필수(공백뿐인 값 거부)로 두고, `assemble_event`가 `ocsf`에 `message`가 없는 옛 행은 `summary` 컬럼 값으로 채운다. 요약 칸은 유한한 실수도 읽는다. 앞의 "message는 필수로 두지 않고 비면 event를 돌려준다" 줄을 대체한다.
