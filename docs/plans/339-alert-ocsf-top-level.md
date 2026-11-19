---
issue: 339
date: 2026-11-19
owner: Pandyo
supersedes: []
---

# Alert 계약을 OCSF 최상위 구조로 전환: 우리 쪽 값은 details에 모음

## 목표

Alert JSON(계약)의 최상위를 OCSF 1.9.0 문서(Detection Finding 2004, 폴백은 Base Event 0) 그대로 두고 `ocsf` 키를 없앤다. 우리 쪽 값은 모두 `details`에 모은다. DB 컬럼과 L1·L2·L3가 모델에 주는 입력(평면 모양)은 바꾸지 않는다. DB 행에서 Alert JSON을 만드는 함수를 한 곳에 두고 계약을 읽는 코드를 새 경로로 바꾼다.

## 방법

1. **샘플과 테스트 먼저.** `tests/fixtures/normalize/alert_skeleton.json`(18건)을 그대로 쓴다. 조립 함수의 기대값(새 Alert JSON)은 이 18건에서 만든 테스트용 픽스처로만 둔다. 시드 JSON(`tests/fixtures/l1_e2e/dev_seed.json`, `l3_hunt/dev_seed.json`, `l3_hunt/seed.json`, `api/ui_seed.json`)은 DB 행 모양을 유지한다. 새 샘플과 실데이터 원본은 만들거나 커밋하지 않는다.
2. **계약(`contracts/alert.schema.json`).** 최상위는 OCSF 문서이고 필수 키만 적는다. 나머지 OCSF 속성은 `additionalProperties: true`다.
   - 필수: `class_uid`(2004 또는 0), `time`, `severity_id`, `details`. `class_uid`가 2004일 때만 `finding_info`를 필수로 둔다(draft-07 `if/then`). 폴백(0)에는 `start_time`·`finding_info`가 없다.
   - `details` 필수 키 6개: `id`, `raw_id`, `rule_id`, `entities`, `assets`, `triage`. `rule_id`는 필수이되 `string | null`이다(폴백은 null). 부가 값(`fallback` 등)은 `details`에 더 올 수 있다.
   - Alert 10개 필드(`id`, `raw_id`, `time`, `severity`, `title`, `rule_id`, `entities`, `assets`, `triage`, `details`)와 OCSF 2004·0 최상위 속성을 대조해 겹치는 것은 `time`(OCSF는 생성 시각)과 `severity`(OCSF는 문자열 라벨) 둘뿐임을 확인했다. 이 둘은 우리 값이 `details`에 들어가지 않고 컬럼 값과 의미가 다르므로 헬퍼로 읽는다(5번).
   - Python(Pydantic)·TypeScript 생성물을 `scripts/generate_contracts.py`로 갱신한다(D-003). 생성 코드는 직접 고치지 않는다.
3. **조립 함수.** DB 없는 순수 읽기 함수 한 곳에 둔다. 행 dict를 받아 Alert JSON을 돌려준다. Alert JSON은 `ocsf` 컬럼의 OCSF 문서에 `details`를 합친 것이다.
   - `details` = DB `details` 컬럼의 부가 값 + `id`·`raw_id`·`rule_id`·`entities`·`assets`·`triage`(컬럼 값). 이름이 겹치면 실패하는 테스트를 둔다.
   - 시각 변환은 하지 않는다. `ocsf`를 그대로 쓴다. `title`·`time`·`severity` 컬럼은 읽지 않는다(`ocsf`와 같음은 #338 일치 검사가 지킨다).
   - 읽기 전용이다. Alert JSON에서 행으로 되돌리는 경로는 만들지 않는다.
   - `SELECT *` 후 `validate_contract`하던 곳(`l2/branch/read.py`)과 #338의 `with_derived_columns` 중 읽기용 용도를 이 함수로 정리한다. `with_derived_columns`가 시드·테스트에서 컬럼을 채우는 쓰기용이면 그대로 둔다.
4. **검증.** OCSF 검증(`validate_ocsf`)은 `details`를 뺀 문서에 적용한다(`validate_ocsf`는 정의에 없는 최상위 키를 거부한다). 계약 검증은 전체에 적용한다. 두 검증이 같은 래퍼를 쓴다. `details`에 OCSF 속성 이름과 같은 키가 없음을 테스트로 확인한다(D-065 유지).
5. **읽는 코드 전환.**
   - 조립 JSON용 헬퍼를 조립 함수와 같은 모듈에 둔다: `alert_time`(`start_time`, 없으면 `time`), `alert_severity`(`severity_id`, 99는 0). 변환 없이 `ocsf` 값을 읽는다. SQL 컬럼을 읽는 경로(`l1/judge.py:_alert_data` 등)는 지금처럼 컬럼과 `to_epoch_ms`를 쓴다.
   - `BranchRows.alerts`(`l2/branch/read.py`)는 조립 JSON이다. `l2/branch/{embed,worker,store}.py`는 `details.id`·`details.entities`·`finding_info.title`(없으면 `message`, D-065)·헬퍼로 읽는다.
   - 에이전트에게 주는 입력(`task.data`: L1 `_alert_data`, L2 `worker.py`의 `{kind, id, entities}` 등)은 지금의 평면 모양을 유지한다. 값만 새 경로에서 꺼낸다.
   - `tools/internal.py`의 `get_alert`는 조립 JSON을 돌려준다. `query_records`와 `get_event`는 그대로다.
   - `api/ui_read.py`의 `raw_detail`은 alert일 때 `record`를 조립 JSON으로 준다(event는 행 그대로). 프론트 생성 타입(`contract-alert.ts`, `RawDetail.ts`)을 갱신하고 화면과 `JsonViewer`를 확인한다.
   - 나머지 대상(`l1/ticketing.py`, `l2/branch/graph.py`, `l3/hunt/store.py`, `similar/index.py`, `tools/similar_cases.py`, `api/routes/{workflow,dashboard}.py`)은 실제로 계약 JSON을 쓰는지 grep으로 확정하고, SQL 컬럼만 쓰면 바꾸지 않는다.
6. **근거 ID 장부.** `ToolSpec.id_fields`가 점 경로(`details.id`)를 받게 확장한다(`tools/registry.py`의 장부 등록과 `shorten_record`의 `id` 보호). 기존 최상위 키 값(`id`)은 그대로 동작한다. `get_alert`는 `id_fields=("details.id",)`다.
7. **결정 기록.** `docs/decisions.md`에 D-066을 더한다(D-059의 Alert 계약 서술과 D-065의 "계약·읽는 쪽 코드는 바꾸지 않는다"를 대체).

## 바꿀 곳

- `contracts/alert.schema.json`, 생성물 `src/soc/contracts/generated/`·`frontend/src/api/generated/contract-alert.ts`·`RawDetail.ts`: 새 구조
- `src/soc/normalize/mapping.py` 또는 새 모듈: 조립 함수와 헬퍼 `alert_time`·`alert_severity`
- `src/soc/normalize/ocsf_schema.py`(또는 호출 지점): `details`를 뺀 검증 래퍼
- `src/soc/l2/branch/{read,embed,worker,store}.py`: 조립 JSON 읽기
- `src/soc/tools/registry.py`, `src/soc/tools/internal.py`: `id_fields` 경로 확장, `get_alert`가 조립 JSON 반환
- `src/soc/api/ui_read.py`: alert `record`를 조립 JSON으로
- `tests/`: 조립 함수(18건 기대값), 스키마, `details` 충돌·OCSF 이름 테스트, 근거 ID 장부 3개, L1·L2·tools·api 테스트 정리
- `docs/decisions.md`, `docs/plans/339-alert-ocsf-top-level.md`, 개발 중 `docs/notes/339-alert-ocsf-top-level.md`

## 다른 코드와 맞물리는 곳

공통 계약 변경이다. L1·L2·L3·UI 담당 모두 계획 확정 전에 공유받고 승인했다.

- **Alert 계약**(`contracts/alert.schema.json`)과 생성 코드: 최상위가 OCSF 문서로 바뀌고 `ocsf` 키가 없어진다. 컬럼 이름·타입은 바뀌지 않는다.
- **에이전트 도구**: `get_alert` 반환 모양이 조립 JSON으로 바뀐다. 같은 알럿이 `task.data`에서는 평면, `get_alert`에서는 OCSF 모양이다(근거 ID `alt_…`는 같다). `ToolSpec.id_fields` 경로 확장은 `soc.tools` 공통 코드 변경이다.
- **UI**: `raw_detail`의 alert `record` 응답 모양이 바뀌고 프론트 생성 타입이 바뀐다. UI 담당 확인 대상이다.
- **L2**: `BranchRows.alerts`의 모양이 바뀐다. L2 담당 확인 대상이다.
- **L1·L3**: 모델 입력과 SQL은 바뀌지 않는다. L1·L3 담당은 공통 계약 변경으로 승인했다.

## 범위 밖

- Event 계약 정렬(후속 이슈로 분리한다)
- 마스킹 범위 재정의(`get_alert`·`details` 키 이름과 D-048 규칙의 관계는 별도 보안 이슈)
- DB 컬럼 변경, `alerts`를 비우고 재수집하는 방식
- 모델 입력(L1·L2·L3 `task.data`)의 모양 변경
- 임베딩·Incident·그래프 묶음의 재생성

## 완료 기준

- [ ] 결정 기록: D-066(Alert 계약 구조 변경, D-059·D-065 해당 부분 대체), 계약 JSON Schema와 생성물(Python·TS) 갱신
- [ ] 스키마: 필수 키 `class_uid`·`time`·`severity_id`·`details`, `class_uid` 2004일 때만 `finding_info` 필수, `details` 필수 키 6개(`rule_id`는 필수이되 `string | null`). 2004와 폴백(0) 샘플이 모두 통과하는 테스트
- [ ] `validate_ocsf`는 `details`를 뺀 문서에, 계약 검증은 전체에 적용하는 방식이 코드와 테스트로 고정됨
- [ ] DB 없는 순수 조립 함수 한 곳(`ocsf` + `details`, 변환 없음, 읽기 전용). `alert_skeleton.json` 18건 기대값 픽스처 테스트와 `details` 키 충돌·OCSF 속성 이름 충돌 테스트
- [ ] `alert_time`(`start_time`, 없으면 `time`)·`alert_severity`(`severity_id`, 99는 0) 단위 테스트(2004와 폴백)
- [ ] 근거 ID 장부 테스트 3개: `details.id` 장부 등록, 미조회 id 판정 거부, `shorten_record`의 `details.id` 보호
- [ ] 읽는 코드 전환 완료(`BranchRows.alerts`·`embed`·`worker`·`store`, `get_alert`, `raw_detail`). 나머지 대상은 grep으로 확인한 결과를 기록에 적음
- [ ] 모델 입력이 바뀌지 않음: `alert_skeleton.json` 18건으로 같은 입력에서 L1·L2의 `task.data`와 SQL 결과가 전환 전과 같음을 테스트
- [ ] 시드 JSON 4개는 DB 행 모양 그대로이고 시드·테스트가 통과
- [ ] 프론트 화면과 `JsonViewer` 동작 확인, 프론트 생성 타입 갱신
- [ ] 개발 DB 사본에서 L1 판정·L2 묶음·L3 조회·UI가 전환 전과 같은지 사람이 확인하고 결과를 건수로 PR 초안에 적음
- [x] L1·L2·L3·UI 담당 승인(계획 확정 전에 받음)
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, 화면 검사(`pnpm lint`·`pnpm test`·`pnpm build`) 통과

## 토론으로 정한 것

이슈 본문과 달라진 점:

- **결정 번호**: 이슈의 "D-059 대체"를 "D-059·D-065 대체"로 정정했다. 계약 구조는 D-059(`class_uid` 2004 또는 0)와 D-065(계약·읽는 쪽 코드는 바꾸지 않는다는 #338 범위)에 걸쳐 있다. 새 결정은 D-066이다.
- **모델 입력은 평면 유지**: L1·L2·L3가 모델에 주는 입력은 지금의 평면 모양을 유지하고 DB 컬럼에서 읽는다. 바꾸면 프롬프트와 판정 결과가 함께 바뀌어 "전환 전과 같은 결과" 확인이 어려워진다. 이슈의 "읽는 코드 전환"은 계약 JSON을 쓰는 곳(L2 `BranchRows`, `get_alert`, UI)으로 좁혀졌다.
- **`get_alert` 근거 ID**: `get_alert`가 조립 JSON을 돌려주면 `id`가 `details.id`로 가서 근거 ID 장부에 안 잡히므로 `ToolSpec.id_fields`가 점 경로를 받게 확장한다. 완료 기준에 장부 테스트 3개를 넣었다.
- **`time`·`severity` 충돌**: 읽는 쪽이 JSON과 SQL로 나뉜다. JSON은 헬퍼 `alert_time`·`alert_severity`(폴백 대체 규칙을 한 곳에 둠), SQL은 컬럼을 쓴다. Alert 10개 필드와 OCSF 2004·0 최상위 속성을 대조해 겹치는 것은 이 둘뿐임을 확인했다.
- **스키마 범위**: OCSF 속성을 모두 옮기지 않고 필수 키만 적는다. OCSF 정의의 검증은 `ocsf/` 고정본(D-061)이 맡는다. 폴백(0)에는 `finding_info`가 없어 2004일 때만 필수다.
- **`rule_id`**: `details`의 필수 키이되 폴백(0)에서는 null이므로 `string | null`이다(사람이 정함).
- **`details` 정의**: "OCSF 속성 이름과 같은 키 없음" 테스트를 유지하고, 계약에는 필수 키 6개를 고정한다. 계약 설명의 "다른 단계는 읽지 않는다"는 고친다.
- **조립 함수**: DB 없는 순수 읽기 함수이고 시각 변환이 없다(`ocsf`는 이미 epoch 밀리초). `title`·`time`·`severity` 컬럼은 읽지 않는다. Alert JSON은 `ocsf` 컬럼 + `details`다. 시드 JSON은 DB 행 모양을 유지하고 새 Alert JSON은 조립 함수 테스트용 기대값 픽스처로만 둔다.
- **UI**: `raw_detail`의 alert `record`를 조립 JSON으로 준다. 생성 타입(`RawDetail.ts`)이 계약에서 나오므로 응답과 타입이 맞는다. UI 담당 확인 대상으로 명시한다.
- **범위 제외**: Event 계약 정렬은 후속 이슈로, 마스킹 범위 재정의는 별도 보안 이슈로 분리한다.
- **담당자 승인**: L1·L2·L3·UI 담당 모두 계획 확정 전에 공유받고 승인했다(담당 단계만 기록).
- **확인 방법**: 개발 DB 사본 확인(사람)과 `alert_skeleton.json` 18건 테스트(같은 입력에서 `task.data`·SQL 결과가 전환 전과 같음)를 둘 다 한다.

## 바뀐 점

- 2026-11-19 · L2 모델 입력(`l2/branch/decide.py`, `l2/analyze/context.py`)은 조립 JSON을 그대로 쓰지 않고 변환 함수 `alert_model_input`(조립 함수와 같은 모듈)을 거쳐 지금의 입력 모양을 유지한다. 분석 시간 창(`evidence_times`)의 시각도 이 함수가 만든 이전 의미(`start_time` 기준)를 쓴다. 조립 함수와 변환 함수의 왕복(이전 모양과 같은 값)을 18건 테스트로 지킨다. DB 행을 계약에 직접 넣던 곳(`normalize/run.py`, 시드 3종)은 조립 함수를 거치게 바꾼다(사람이 정함).
