---
issue: 351
date: 2026-11-20
owner: uptime-zero
plan: 351-event-normalize-outcome.md
supersedes: []
---

# 이벤트 정규화 품질(outcome)을 기록하고 보고서·재처리에 연결했다

## 한 일

정규화가 만드는 모든 이벤트가 `normalize_status`에 `outcome`·`source`·`missing_fields`·`error_code`를 남긴다.
`ok`는 기준 충족, `partial`은 품질 판정에 필요한 값을 못 얻었거나 ModSecurity가 `@timestamp`를 대신 쓴 경우
(`missing_request_time_used_at_timestamp`, `missing_fields = [metadata.original_time]`), `fallback`은 지원 매핑이 없어
Base Event로 만든 경우(`unsupported_event_mapping`)다. 소스는 소스 표 이름(`nginx`, `modsecurity`),
인덱스 규칙이면 `class_4002`·`class_6003`, 미지원이면 `unknown`이다.
`reprocess --kind event`는 신규 처리와 같은 `normalize` 결과로 이벤트와 품질을 한 트랜잭션에서 갱신하고,
품질 하락과 "기존 4002 등이 Base Event로 내려가는 경우"는 `worse`로 건너뛴다.
`report`(= `--kind alert`)와 `report --kind event`는 `result_kind`로 각각 집계한다.

## 계획과 달라진 점

- 이벤트 사유 코드는 알럿 목록(`PARTIAL_REASONS`, `FALLBACK_REASONS`)에 섞지 않고 `EVENT_PARTIAL_REASONS`, `EVENT_FALLBACK_REASONS`로 따로 뒀다. 알럿 목록을 검사하는 기존 테스트를 바꾸지 않으려는 선택이다.
- 시각 대체는 "소스 표에 `time` 항목이 있는데 그 원본 필드가 아예 없을 때"로 일반화했다. 지금은 ModSecurity뿐이다. 누락 경로 이름 `metadata.original_time`은 상수(`REQUEST_TIME_GAP`)다. 다른 소스가 같은 대체를 쓰게 되면 표로 옮겨야 한다.
- 소스 표 이름 검사(`^[a-z][a-z0-9_]{0,63}$`, `unknown`·`class_*` 제외)를 `event_tables.py` 로더에 넣었다. DB CHECK가 이벤트 이름 형식만 확인하므로 "검증된 이름" 조건은 로더가 지킨다.

## 다음 사람이 알아야 할 것

- 마이그레이션 0305의 CHECK는 `result_kind`가 NULL일 때 중간식이 NULL이 되어 통과하는 함정이 있어 `COALESCE(result_kind, '')`로 막았다. 새 CHECK를 쓸 때 같은 점을 본다.
- 현재 이벤트 표에서 `required: true`는 4002의 `time`뿐이고 그 값이 없으면 정규화가 `validation_failed`로 실패한다. 그래서 "필수 값 누락 partial" 경로는 표를 바꿔 끼운 테스트로만 확인했다(`test_a_required_value_that_a_table_cannot_get_makes_the_event_partial`).
- 기존 이벤트 행은 재처리 전까지 품질이 NULL이고 보고서에 잡히지 않는다. 운영 DB 일괄 재처리는 범위 밖이다.
- 재처리 `by_source` 키가 `class_4002` 같은 클래스 이름에서 품질의 `source` 이름(`nginx` 등)으로 바뀌었다. 출력 형식을 읽는 곳이 있으면 확인한다.
- `report`의 알럿 집계가 `result_kind = 'alert'` 조건을 갖는다. 알럿이 아닌 행은 원래 outcome이 NULL이라 알럿 출력은 같다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과.
- `DATABASE_URL`로 `uv run pytest -m db tests` 통과(609건).
- 주요 테스트: `tests/normalize/test_event_quality.py`, `test_alert_skeleton_db.py`(이벤트 기록·보고서·CHECK), `test_reprocess_db.py`(보존·갱신·dry-run), `tests/test_db_tables.py`(0305 목록).
