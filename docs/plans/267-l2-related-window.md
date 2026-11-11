---
issue: 267
date: 2026-11-11
owner: Juhyeok0603
supersedes: [261-l2-incident-analysis.md]
---

# L2 주변 정리 구간을 Incident 전체 기간으로 넓히고 고르게 뽑는다

## 목표

L2 주변 기록 조회가 SIEM 도구의 1회 조회 한도에 잘리지 않고, Incident 문맥에 들어온
Alert·Event의 전체 기간을 살핀다. 시간대와 Alert·Event에 고르게 선택 기회를 주고, 주변
기록의 건수와 모델에 전달하는 필드를 제한한다.

## 방법

### 조회 구간

- 문맥에 직접 들어온 Alert·Event의 `time` 중 가장 이른 값을 기준으로 한다. 둘 다 없으면 읽은
  Ticket 중 가장 이른 `created_at`을 쓴다.
- `window.from` = 기준 시각 − `lookback_ms`, `window.to` = `now_ms`로 계산한다.
  `[l2.analyze] lookback_ms` 기본값은 1일에서 3일로 바꾼다.
- `calculate_window`에서 7일 바닥과 `max_range_days` 인자를 제거한다. 더는 잘리지 않으므로
  `data.window`에서 `truncated`와 `requested_from`을 제거한다.
- 이 계획은 #261 계획(`docs/plans/261-l2-incident-analysis.md:145`)의 7일 자르기와 최신
  `max_related_per_entity`건 선택 규칙을 대체한다. 이전 계획 파일은 고치지 않는다.

### 조회할 엔티티

- Incident의 `ticket_ids`는 Ticket을 연결할 때 뒤에 추가된다. 이 목록을 뒤에서부터 읽어 최근
  연결 Ticket의 엔티티를 먼저 놓는다. `created_at`은 Ticket 생성 시각이므로 연결 순서 판별에
  쓰지 않는다.
- 나머지 Incident 엔티티는 기존 순서를 유지한다. 중복 엔티티는 기존 정규화 기준으로 한 번만
  쓴다.
- `max_seed_entities = 10`은 유지한다. 등급·점수·겹침 순위 체계는 만들지 않는다.

### 주변 기록 선택과 입력 크기

- 전체 구간을 시간상 4개 버킷으로 나눈다. 버킷 수는 코드 상수로 두고 설정 키는 추가하지
  않는다.
- 엔티티마다 Alert와 Event를 각각 한 번 조회한다. 테이블별 쿼리에서 버킷별 최신 후보를 받고,
  같은 시각에서는 ID로 순서를 고정한다.
- 시간 버킷과 기록 종류에 차례로 선택 기회를 준다. 비어 있는 칸의 몫은 후보가 남은 다른 칸에
  양도한다. 엔티티당 `max_related_per_entity = 20`건을 상한으로 유지한다. Alert·Event가 모두
  있으면 각 종류가 선택 기회를 얻고, 한쪽이 없으면 다른 쪽이 빈 몫을 쓴다.
- 여러 엔티티에서 고른 기록은 중복 제거한다. 중복 제거 뒤 전체 최대 80건(코드 상수)을
  적용한다. 전체 상한에서도 엔티티·시간 버킷·기록 종류를 순환하며 빈 몫을 양도한다. 엔티티
  순환 순서는 최근 연결 Ticket을 우선한다. 상한 적용 후 최종 `data.related`는 시간 오름차순으로
  정렬한다.
- `related`의 바깥 구조는 기존의 `{"kind": "alert" | "event", "record": {...}}`를 유지한다.
  기존 계약 검증을 거친 다음 `record`만 줄인다.
  - Alert: `id`, `time`, `severity`, `title`, `entities`
  - Event: `id`, `time`, `summary`, `entities`
- `related`에는 `ocsf`·`assets`·`details` 원문을 넣지 않는다. 상세 내용이 필요하면 모델이 허용된
  `get_alert`·`get_event`를 사용한다. 전체 상한을 적용한 뒤 실제 전달하는 기록의 ID만 근거
  장부에 추가한다.
- 80건 상한은 주변 기록 건수를 제한한다. 제목·요약·엔티티 값의 길이는 계약상 제한되지 않으며,
  소속 기록·자산·이전 Artifact도 입력에 포함된다. 따라서 모든 실데이터 입력의 64,000자 이내를
  보장한다고 주장하지 않는다. 초과하면 기존 `budget_exceeded` 실패 경로를 따른다.

### 모델 도구와 프롬프트

- `[tools] max_range_days = 7`과 시간 범위를 받는 도구의 호출별 검사는 유지한다. 한도 일수를
  조사 입력 `data`에 숫자로 넣는다.
- `src/soc/l2/prompts/l2_investigate.md:7`의 "조회와 도구 호출은 `data.window.from`부터
  `data.window.to`까지만 사용한다"는 지시는 유지한다. `truncated`·`requested_from`을 설명하는
  다음 줄만 제거한다.
- 주변 기록은 전체 구간에서 고르게 뽑은 단서이며, 시간 범위 조회 도구는 호출마다 7일 이내의
  구간을 지정하도록 안내한다. 전체 구간을 빠짐없이 도구로 재조회하라는 지시는 넣지 않는다.
- `get_alert`·`get_event`는 ID 조회이므로 7일 조건의 대상이라고 표현하지 않는다.

### 시간 인덱스와 적용

- 공통 테이블 대역의 새 마이그레이션 `src/soc/db/migrations/0006_related_time_indexes.sql`에
  다음을 추가한다. 적용된 0001은 고치지 않는다.

```sql
-- 주변 기록 조회가 time 범위로 거르므로 시간 인덱스를 둔다(#267).
-- 일반 CREATE INDEX다. 실행기(src/soc/db/migrate.py)가 파일마다 트랜잭션을 열어
-- CONCURRENTLY를 쓸 수 없고, 빌드 동안 해당 테이블 쓰기가 대기한다.
-- 운영 규모 데이터에서 다시 만들어야 하면 실행기에 파일별 autocommit 표식을 먼저 더한다.
CREATE INDEX alerts_time_idx ON alerts (time);
CREATE INDEX events_time_idx ON events (time);
```

- 개발 기록에는 수집을 멈춘 상태에서 이 마이그레이션을 적용한다고 남긴다.
- 시간 인덱스가 넓은 구간에서 반드시 선택되거나 버킷 정렬을 없앤다고 가정하지 않는다. 임시
  PostgreSQL DB의 실제 테이블에 `generate_series`로 가짜 시간·엔티티를 가진 행을 만들어
  `EXPLAIN ANALYZE`를 수동 실행한다. 데이터와 생성 SQL은 커밋하지 않고, 행 수·실행 계획·소요
  시간만 개발 기록에 남긴다. 인덱스 사용 여부 자체는 완료 조건으로 삼지 않는다.

## 바꿀 곳

- `src/soc/l2/analyze/context.py`: 구간 계산, 엔티티 우선순위, 주변 기록 선택·전체 상한·필드
  축소, 근거 장부.
- `src/soc/l2/analyze/worker.py`: 변경된 문맥 인자와 도구 1회 한도 전달.
- `src/soc/l2/config.py`, `config/default.toml`: `lookback_ms`의 3일 기본값. 주변 기록 20건·엔티티
  10개 설정은 유지.
- `src/soc/l2/prompts/l2_investigate.md`: 구간 지시는 유지하고 잘림 안내만 제거. 주변 기록과
  도구 한도 안내 추가.
- `src/soc/db/migrations/0006_related_time_indexes.sql`: Alert·Event 시간 인덱스.
- `tests/fixtures/l2/`, `tests/test_l2_analyze.py`, `tests/test_l2_config.py`,
  `tests/test_l2_worker.py`, `tests/test_l2_branch_db.py`, `tests/test_lab_cycle_db.py`: 손으로 만든
  샘플과 변경된 호출·설정·DB 동작 검사.
- `tests/test_db_tables.py`: 새 마이그레이션 파일을 고정 목록에 추가하고 두 인덱스 생성 확인.
- `docs/notes/267-l2-related-window.md`: 적용 조건, 성능 확인 결과, 남는 입력 예산 한계 기록.

## 다른 코드와 맞물리는 곳

- L2 조사 입력의 `data.window`에서 두 키가 빠지고 도구 1회 한도가 추가된다. 입력을 읽는
  프롬프트와 테스트를 함께 바꾼다.
- `calculate_window`, `read_context`, `L2AnalyzeWorker`의 호출자와 테스트를 함께 바꾼다.
- `related`의 `kind`·`record` 구조는 유지하지만 `record` 필드가 줄어든다. 이 데이터를 읽는
  프롬프트·fixture·테스트에서 전체 계약 행을 기대하지 않도록 확인한다.
- `alerts`·`events`에는 인덱스만 추가한다. 테이블의 데이터 형식과 계약은 바꾸지 않는다.
- 새 설정 키, 라이브러리, 확정 결정은 추가하지 않는다.

## 범위 밖

- SIEM 도구 코드와 `[tools] max_range_days` 기본값 변경.
- `[agent.l2]`의 `max_turns`·`max_input_chars`·`max_tool_result_chars` 조정.
- 모든 실데이터 Incident의 입력 글자 수 보장. 주변 기록 80건에도 긴 제목·요약·엔티티 값이 있을
  수 있고, 소속 기록·자산·이전 Artifact만으로도 초과할 수 있다.
- 엔티티 수 상향, `entities`용 GIN 인덱스, 부분 일치 조회.
- L3 Ticket의 Hunt `alt_` 근거를 문맥 행으로 읽는 변경과 `raw_links` 활용.
- `[l2.branch] candidate_window_ms`와 공용 마이그레이션 실행기 변경.

## 완료 기준

- [ ] Alert·Event 문맥이 있으면 가장 이른 증거 시각부터, 둘 다 없으면 Ticket 생성 시각부터 3일
      앞서 주변 조회를 시작하고 현재까지 덮는다.
- [ ] 긴 구간에서 7일 바닥에 잘리지 않는다.
- [ ] 4개 시간 버킷과 Alert·Event 사이에서 빈 몫을 양도하며 엔티티당 최대 20건을 선택한다. 손으로
      만든 샘플에서 과거 기록과 Event가 최근 Alert에 밀려 전부 사라지지 않는다.
- [ ] 중복 제거 뒤 전체 최대 80건을 지킨다. 전체 상한을 채울 때도 최근 연결 Ticket을 우선하면서
      시간대·기록 종류의 선택 기회와 빈 몫 양도를 유지한다.
- [ ] 가장 최근 연결 Ticket의 엔티티가 먼저 조회되고 조회 엔티티 상한은 10개다.
- [ ] `related`의 `kind`·`record` 구조를 유지한다. Alert `record`에 `severity`가 있고, 어떤
      `record`에도 `ocsf` 원문이 없다. 실제 전달한 ID만 근거 장부에 추가된다.
- [ ] 샘플 Incident의 첫 모델 호출 입력이 `[agent.l2] max_input_chars` 안에 있다.
- [ ] `data.window`에 `truncated`·`requested_from`이 없고, 프롬프트의 window 범위 지시는 유지된다.
- [ ] 모델 입력에 도구 1회 한도가 숫자로 들어간다. 시간 범위를 받는 도구의 각 호출은
      `max_range_days` 한도를 지킨다.
- [ ] 기본 `lookback_ms`는 3일이고 기존 양의 정수 검사·예상 밖 키 거부가 유지된다.
- [ ] 새 마이그레이션이 두 시간 인덱스를 만든다. 적용 중 쓰기 대기와 수집 중지 조건이 기록된다.
- [ ] 임시 DB의 `generate_series` 합성 행으로 새 조회의 `EXPLAIN ANALYZE`를 수동 확인하고 행
      수·계획·소요 시간을 개발 기록에 남긴다. 생성 행은 커밋하지 않는다.
- [ ] 손으로 만든 작은 fixture로 긴·짧은 구간, 빈 Alert·Event 문맥, 빈 버킷, Alert 편중, 최근 연결
      Ticket, 전체 80건 상한을 검사한다.
- [ ] 10일 전 Ticket이 붙은 Incident에서 주변 기록이 7일에 잘리지 않는지 손으로 확인한다.
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`가 통과한다.

## 토론으로 정한 것

- 버킷은 설정 대신 코드 상수 4개로 둔다.
- 시간 버킷과 Alert·Event 종류 모두 빈 몫을 다른 쪽에 양도한다.
- 주변 기록 상한 엔티티당 20건, 조회 엔티티 상한 10개를 유지하고, 중복 제거 뒤 전체 80건 상한을
  더한다. 둘 다 코드 상수이거나 기존 설정 키이고 새 설정 키는 만들지 않는다.
- 최근 연결 Ticket의 엔티티를 우선한다. 연결 순서는 `created_at` 대신 Incident `ticket_ids`의 추가
  순서로 판단한다.
- `related`의 `kind`·`record` 구조를 유지하고 Alert에 `severity`를 포함한다.
- 입력 예산 완료 기준은 샘플 Incident의 첫 호출로 한정한다. 실데이터의 예산 초과는 기존 실패
  경로를 따른다.
- 새 시간 인덱스 둘을 범위에 포함한다. 기존 파일별 트랜잭션 방식의 일반 `CREATE INDEX`를 쓰고
  수집을 멈춘 상태에서 적용한다.
- 성능 확인용 다수의 합성 행은 임시 DB에서 `generate_series`로 만들며 레포에 넣지 않는다.
- #261의 구간 자르기와 최신 기록 선택 규칙을 이 계획으로 대체한다.

## 바뀐 점
