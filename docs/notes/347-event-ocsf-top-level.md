---
issue: 347
date: 2026-11-19
owner: uptime-zero
plan: 347-event-ocsf-top-level.md
supersedes: []
---

# Event를 Alert처럼 OCSF 최상위 구조로 바꾸고, 우리 쪽 값은 details에 모았다

## 한 일

Event(`events` 테이블과 Event 계약)를 Alert(D-065·D-066)와 같은 구조로 맞췄다(D-068).

- **계약.** Event JSON의 최상위는 `events.ocsf` 문서이고 `ocsf` 키는 없다. 필수 키는 `class_uid`(저장한 7개)·`time`·`severity_id`·`details`이고, `details`에 `id`·`raw_id`·`entities`·`assets`가 있다. 조립·헬퍼는 `soc/contracts/event.py`(`assemble_event`, `event_time`, `event_class`, `event_summary`, `event_model_input`)다. 생성 코드(Python·TS)를 다시 만들었다.
- **파생 컬럼.** `time`·`ocsf_class`·`summary` 컬럼은 `mapping.derive_event_columns(ocsf)` 한 곳이 `ocsf`에서 만들고(`time` = `start_time`, 없으면 `time` / `ocsf_class` = `class_uid` / `summary` = `message`) 정규화·재처리·시드 3종이 같은 함수(`event_row`, `with_derived_event_columns`)를 쓴다.
- **요약.** 정규화가 `message`를 항상 채운다. 1순위는 `mapping_tables/events/<클래스 번호>.yaml`의 `summary`(OCSF 경로 목록, 칸 안의 대안 경로는 앞에서부터 처음 값이 있는 것), 2순위 `event.dataset`, 3순위 `event`다. 저장한 7개 클래스를 모두 정의했고 경로는 `ocsf/classes/` 정의로 pytest가 검사한다(`soc/normalize/event_tables.py`). 알럿 매핑표 로더는 이 폴더를 읽지 않는다.
- **activity_id = 99.** Base Event(`event.action`이 있을 때)·4002(목록에 없는 메서드)·6003(접두사에 없는 동작)은 `activity_name`에 출처 고유 값을 담는다. Base Event는 `type_uid`가 0에서 99가 된다.
- **DB.** `0304_event_ocsf_class.sql`이 `events`에 `class_uid` 7개 CHECK(`events_ocsf_class_uid_check`)를 더한다.
- **재처리.** `python -m soc.normalize reprocess --kind event`로 기존 이벤트를 id를 유지한 채 다시 만든다. 기본은 알럿이고 `--source`는 알럿에서만 쓴다.
- **읽는 쪽.** `get_event`(`id_fields=("details.id",)`)와 `raw_detail`의 event `record`가 조립 JSON을 돌려주고, L2 문맥·임베딩·분석 문맥은 `event_model_input`·`event_summary`로 읽는다. 모델 입력의 칸 이름은 그대로다.

## 계획과 달라진 점

- 계약의 `message`는 필수로 두지 않았다(계획의 필수 키는 4개). `event_summary`는 `message`가 없으면 "event"를 돌려준다. 옛 형식 행(`message` 없음)이 재처리 전에도 계약을 통과하게 하려는 것이다.
- 제약 이름을 `events_ocsf_class_uid_check`로 했다. `events.ocsf_class` 컬럼의 CHECK가 이미 `events_ocsf_class_check`라는 이름을 쓴다.
- `validate_event_ocsf`(`validate_alert_ocsf`와 같은 일을 하는 이름)를 `ocsf_schema.py`에 더했다. 읽는 쪽 이름만 맞춘 것이다.
- 이벤트 재처리는 outcome이 없어서 대상이 "정규화에 성공한 모든 이벤트"이고(`--since`·`--limit`만 건다) `normalize_status`를 읽지도 바꾸지도 않는다. 요약 출력의 소스별 줄은 `class_<번호>`로 센다.
- 시드 이벤트 6건(`l1_e2e/dev_seed.json`의 1007 4건·1001 1건·3001 1건)과 `tools/records.json`의 1007 1건은 저장하지 않은 클래스라 CHECK에 걸린다. 알럿 때처럼 OCSF 검증을 통과하게 다시 썼다(Base Event + `activity_name`, 프로세스·파일·계정 내용은 `unmapped`). 3002 시드 8건에는 `service`를 더했다(3002는 `service`나 `dst_endpoint` 중 하나가 필수다). 계획의 "바뀐 점"에 있다.

## 다음 사람이 알아야 할 것

- **시드가 바뀌었다.** L1 e2e 시드의 프로세스·파일·계정 변경 이벤트가 Base Event가 됐다. `get_event`로 읽는 `ocsf`의 모양이 달라진다(프로세스 이름·명령줄은 `unmapped` 아래). L1·L2·L3 담당 확인 대상이다.
- **DB 마이그레이션.** `0304`는 기존 `events`에 `class_uid`가 7개 밖인 행이 있으면 적용에 실패하고 멈춘다(말없이 지우거나 고치지 않는다). 정규화가 만든 이벤트는 0·4002·6003뿐이라 걸리지 않지만, 옛 개발 시드(1007 등)가 들어 있는 DB는 시드를 지우고 다시 넣어야 한다. `ocsf`에 `message`가 없는 옛 행은 CHECK는 통과하고 `reprocess --kind event`로 채운다. 순서는 개발 DB 사본으로 사람이 확인한다.
- **모델 입력.** `event_model_input`의 `ocsf`에 `message`가 더해졌고 `summary`는 같은 값이다. 칸 이름은 그대로다.
- **하지 않은 것.** 클래스를 정규화에 연결(원본에 클래스·수집 키 저장), 이벤트 매핑표(`entries`·`entities`), 엔티티·`observables` 정리, 이벤트 `outcome`, 폴백(읽을 수 없는 이벤트를 class 0으로 저장)은 후속 이슈다. 새 이벤트 종류가 정규화되려면 먼저 클래스 연결이 필요하다.
- **직접 확인하지 못한 것.** Qdrant 테스트(`-m qdrant`)는 돌리지 않았다(임베딩 텍스트는 단위 테스트 `test_embedding_text_keeps_order_drops_empty_values_and_has_no_labels`로 확인). 실제 개발 DB 사본의 건수 확인과 L1·L2·L3·UI 동작 확인은 사람이 한다.
- **L1·L2·L3·UI 담당 확인**은 PR 전에 받아야 한다(공통 계약 변경).

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run python scripts/generate_contracts.py --check`, `uv run pytest`(2,433건 통과)
- DB 테스트: 임시 Postgres 17.6 컨테이너로 `uv run pytest -m "db and not qdrant"` 541건 통과(`class_uid` CHECK, `reprocess --kind event`, 읽는 쪽 포함)
- 프런트: `pnpm run contracts:check`(35개 일치), `pnpm run test`(86건), `pnpm run lint`, `tsc --noEmit` 통과
- `origin/main`과 `tests/fixtures/normalize/raw.json`의 이벤트 샘플 15건을 비교: `time`·`ocsf_class`·`summary`·`entities`·`assets`·`details`는 모두 같고 `ocsf`만 `message`(전부)·`activity_name`(99인 3건)이 더해졌다. Base Event 1건은 `activity_id`·`type_uid`도 0에서 99로 바뀌었다.
- 주요 테스트: `tests/normalize/test_event_assemble.py`, `test_event_tables.py`, `test_reprocess_db.py`(이벤트 6건), `test_normalize_db.py`(CHECK), `tests/test_tools_db.py`(`get_event`), `tests/test_l2_branch.py`
