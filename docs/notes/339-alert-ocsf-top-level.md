---
issue: 339
date: 2026-11-19
owner: Pandyo
plan: 339-alert-ocsf-top-level.md
supersedes: []
---

# Alert 계약을 OCSF 최상위로: 우리 값은 details에, 모델 입력은 그대로

## 한 일

Alert 계약(`contracts/alert.schema.json`)의 최상위가 OCSF 문서(2004, 폴백 0)이고 `ocsf` 키가 없다. 우리 쪽 값 `id`·`raw_id`·`rule_id`·`entities`·`assets`·`triage`는 `details`에 있다(`rule_id`는 필수이되 null 허용). DB 컬럼은 그대로다. `soc.contracts.alert`에 DB 없는 순수 함수를 모았다.
- `assemble_alert(row)`: alerts 행 → Alert JSON(`ocsf` 컬럼 + `details`, 변환 없음, 읽기 전용)
- `alert_time`·`alert_severity`·`alert_title`·`alert_rule_id`: JSON(또는 `ocsf`)에서 읽는 규칙. 정규화의 `derive_columns`도 이 함수를 쓴다(규칙이 한 곳)
- `alert_model_input(alert)`: 조립 JSON → 전환 전 행 모양(평면 + `ocsf` + `details`). L2 모델 입력이 바뀌지 않게 한다
- `contract_data(name, row)`: DB 행을 계약 검증에 넘기는 모양으로(Alert만 조립)

계약을 읽는 곳은 `l2/branch/read.py`(`BranchRows.alerts`가 조립 JSON), `get_alert`, UI `raw_detail`의 alert `record`다. `ToolSpec.id_fields`는 점 경로(`details.id`)를 받고 `shorten_record`도 그 칸을 줄이지 않는다. 결정은 D-066이다.

## 계획과 달라진 점

- 계획 "바뀐 점"의 한 줄(L2 모델 입력은 `alert_model_input`을 거침) 외에 다음을 골랐다.
- **DB 행을 계약에 넣던 곳도 조립을 거친다.** `normalize/run.py`, 시드 3종(`agent/dev_l1.py`, `l3/hunt/dev_seed.py`, `api/dev_seed.py`)과 테스트의 `validate_contract("alert", row)`는 `contract_data`를 거친다(사람이 정함).
- **`finding_info`는 스키마 `properties`에 두지 않고 `if/then`의 `required`로만 둔다.** `properties`에 넣으면 생성 Pydantic 모델이 폴백 Alert에 `finding_info: null`을 더해 `model_dump`가 입력과 달라진다. 모델 입력이 바뀌는 것을 막으려는 선택이다.
- **`validate_alert_ocsf`(`details`를 뺀 OCSF 검증)** 는 함수와 테스트로 두었다. 정규화 쓰기 경로는 `ocsf` 컬럼을 `validate_ocsf`로 검증하고 있어(같은 문서), 그 줄은 바꾸지 않았다.
- **기대값 픽스처는 손으로 만든 2건**(`tests/fixtures/normalize/alert_json_expected.json`: 2004, 폴백 0)이고, `alert_skeleton.json` 18건은 조립 → 변환 왕복이 이전 행과 같은지로 확인한다(18건 모두). 18건의 새 JSON 전체를 픽스처로 쌓지 않았다.
- `tests/test_db_tables.py`는 Alert 샘플을 DB 행 모양(`alert_model_input`)으로 바꿔 쓴다. 계약 필드와 컬럼이 더는 같지 않아 컬럼 비교는 행 모양 키로 한다.
- 계약 샘플(`tests/fixtures/contracts/valid·invalid/alert.json`)을 새 구조로 다시 썼다. 새 계약은 최상위 추가 키를 허용(`additionalProperties: true`)하므로 "최상위 추가 필드" 거부 샘플은 없어졌다. 대신 `details` 필수 키·`finding_info`(2004만) 누락 샘플을 더했다.
- 시드 픽스처·`tools/records.json`·`ticketing/alerts.json`·`l2/branch.json`의 Alert는 DB 행 모양을 유지하고, 새 계약에 필요한 `ocsf`의 `time`·`severity_id`·`finding_info`만 더했다.

## 다음 사람이 알아야 할 것

- **`get_alert`는 모델에게 OCSF 모양을 준다.** 같은 알럿이 `task.data`에서는 평면 모양이고 `get_alert` 결과에서는 OCSF 모양이다. 근거 ID `alt_…`는 같다(`details.id`). `query_records`·`get_event`는 그대로다.
- **`alert["time"]`과 `alert["severity"]`를 JSON에서 읽지 않는다.** 최상위 `time`은 OCSF 생성 시각이고 `severity`는 없다. `alert_time`·`alert_severity`를 쓴다. SQL은 컬럼이다.
- `l2/analyze/context.py`의 분석 시간 창(`evidence_times`)은 `alert_model_input`을 거친 `time`(`start_time` 기준)을 쓴다. 이 값을 직접 조립 JSON에서 읽으면 의미가 달라진다.
- `l2/analyze`·`l3`의 DB 전체 읽기는 이 개발에서 DB 테스트로만 확인했다. 개발 DB 사본에서 L1 판정·L2 묶음·L3 조회·UI가 전환 전과 같은지는 확인하지 못했고 사람이 확인한다(건수는 PR에 적는다).
- 생성 TS(`contract-alert.ts`, `RawDetail.ts`)가 바뀌었다. 화면(`App.tsx`)은 `data.record`를 `JsonViewer`로 보여 줄 뿐이라 코드 변경은 없다. 보이는 JSON 모양이 OCSF 최상위로 바뀐다.
- 마스킹 범위 재정의와 Event 계약 정렬은 하지 않았다(범위 밖).
- 로컬 `.env`의 `DATABASE_URL`이 가리키는 `zt_dev`가 컨테이너에 없고 `zt`가 있다. DB 테스트는 DB 이름만 `zt`로 바꿔 돌렸다.
- 이 환경에서 원래 실패한다(내 변경 전에도 같다): `tests/test_tools_ssh_host.py`, `tests/test_tools_threat_intel_vt.py`, `tests/test_tools_siem_elk.py`(외부 접속), `tests/test_store_qdrant.py`(Qdrant 환경).

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run python scripts/generate_contracts.py --check`, `pnpm contracts:check`: 일치
- `uv run pytest -m "not qdrant and not llm"`(DB 포함, DB 이름 `zt`): 2831건 통과, 위의 외부 접속 3건 제외
- 새 테스트: `tests/normalize/test_alert_assemble.py`(18건 왕복·헬퍼·충돌·스키마), `tests/test_tools_registry.py`의 근거 ID 장부 3개(`test_id_field_path_registers_nested_id_in_ledger`, `test_unqueried_nested_id_cannot_be_cited`, `test_shortening_keeps_the_nested_id_field`), `tests/test_l2_branch.py::test_classify_model_input_keeps_the_previous_alert_shape`
- 프론트: `pnpm lint`·`pnpm test`(86건)·`pnpm build` 통과
