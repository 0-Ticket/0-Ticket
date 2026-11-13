---
issue: 294
date: 2026-11-12
owner: uptime-zero
supersedes: ["218-elk-rawrecord.md"]
---

# 저장할 수 없는 문서는 격리하고 수집을 계속한다

## 목표

잘못된 문서 하나 때문에 페이지 전체가 저장되지 않고 체크포인트가 고정되어 반복 실패하는 문제를 없앤다. 격리할 수 있는 문서는 `ingest_quarantine`에 원문과 이유를 보존하고, 정상 문서·격리 행·체크포인트를 페이지 단위로 원자적으로 저장한다.

## 방법

### 입력 분류

- 응답 최상위 모양(`pit_id`, `hits.hits`)이 잘못되거나 응답 전체가 JSON으로 파싱되지 않으면 `response_shape`로 대상을 종료한다. 이때는 문서 단위로 나눌 수 없다. `hits.hits` 안에 dict가 아닌 값이 있으면 해당 값 자체를 원문·해시에 보존하고 `hit_ref`로 격리한다.
- 각 hit를 문서 단위로 분류한다. NaN·양의 Infinity·음의 Infinity, `MAX_JSON_DEPTH=100` 초과, RawRecord 계약 위반, 최종 정렬 값 오류는 격리한다.
- `_index`·`_id`가 없거나 비어 있거나 문자열이 아니어도 합성 `siem_ref`를 만들어 격리하고 수집을 계속한다.
- NUL과 짝 없는 서로게이트는 D-049의 `original_text` 이스케이프 보존을 따른다. 그 자체로 격리하지 않는다.
- 깊이 100 초과 hit는 격리한다. 이미 파싱된 hit의 검사·직렬화는 Python 재귀 한도에 좌우되지 않도록 반복형 순회로 처리한다. 응답 전체 파서가 실패한 경우는 위의 `response_shape` 처리다.
- 한 hit가 여러 조건을 만족할 때 `reason_code`는 우선순위를 고정해 하나만 기록한다. Dict hit에서 페이지 재조회 3회 후에도 남은 정렬 값 오류는 `sort_value`를 기록한다. 그 외에는 비-dict hit 또는 식별자 누락·오류 `hit_ref`, `depth_exceeded`, `non_finite`, `contract_rejected` 순으로 기록한다. `sort_value`는 격리 행 이유이며, 실행 실패는 페이지 마지막 hit의 정렬 값이 계속 잘못된 경우에만 기록한다.

### 격리 테이블과 식별자

- `0107_ingest_quarantine.sql`에 `ingest_quarantine`를 만든다. 마이그레이션 실행 시 번호 사용 여부를 다시 확인한다.
- 필드: `id`(bigint identity), `siem_profile`, `source_kind`, `source_key`, `siem_ref`, `reason_code`, `original_text`, `seen_at`. 필수 필드는 NOT NULL이다. `source_kind`는 `alert` 또는 `event`; `reason_code`는 소문자 코드 형식이다. 외부 원문에는 내용 CHECK를 두지 않는다.
- 모든 격리 hit에 격리 전용 합성 키를 쓴다. `raw_records`의 키와 `siem_ref_key` 동작은 D-049 그대로 둔다. 격리 표에는 기존 키 소비자가 없다.
- 격리 전용 키는 다음 모양이다.

  ```text
  synthetic:v1:<index-token>:<id-token>:<time-token>:<sha256>
  ```

- 결측 토큰은 `n`, 값이 있는 짧은 토큰은 `v<Base64url>`이다. `_index`·`_id`는 비어 있지 않은 문자열일 때만 값 토큰을 만들고, `json.dumps(value, ensure_ascii=True, allow_nan=True)` JSON 문자열 결과의 ASCII 바이트를 인코딩한다. `sort-token`은 `sort`가 비어 있지 않은 배열이면 `sort[0]`의 JSON 타입을 보존해 만든다(예: 정수 `123`과 문자열 `"123"`은 다른 토큰). sort 토큰은 `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=True)`의 ASCII 바이트를 URL-safe Base64로 인코딩하고 패딩 `=`을 뺀다. 패딩을 뺀 Base64url 페이로드가 128자를 넘으면 `h`와 같은 JSON 바이트의 SHA-256 lowercase hex 64자를 쓴다. 이 접두사는 값 존재를 나타내고, 결측 표기 `n`과 구분된다. 이렇게 각 가변 토큰을 제한해 PostgreSQL B-tree 유일 인덱스에 들어가는 키 길이를 제한한다. 체크포인트에 쓸 유효 정렬 값은 별도로 bool이 아닌 0 이상의 정수만 허용한다.
- 해시 입력은 원본을 바꾸지 않은 별도 투영이다. `source_kind`, `source_key`, 그리고 hit 복사본을 포함한다. 최상위 `_score`는 빼고, 비어 있지 않은 `sort` 배열은 첫 값만 남겨 PIT 종속 `_shard_doc` 등 뒤쪽 값을 제외한다. `sort`가 없거나 비어 있거나 배열이 아니면 그 상태를 유지한다. 그 밖의 hit 필드는 유지한다.
- 해시용 직렬화 규칙 v1은 `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=True).encode("ascii")`에 해당하는 결정적 바이트다. NaN·Infinity 표기와 깊은 중첩을 포함해 이 규칙을 재귀 한도와 무관하게 구현한다. SHA-256을 계산하고 골든 fixture로 고정한다.
- 유일 제약은 `(siem_profile, siem_ref)`이며 `ON CONFLICT DO NOTHING`으로 처음 저장한 행을 보존한다. 모든 격리 키에 위치 토큰과 안정적인 hit 해시가 있으므로 같은 위치·해시의 hit만 한 행으로 병합한다. 반복 횟수는 저장하지 않는다. 전체 원본은 `original_text`에 보존한다.

### 페이지 저장과 체크포인트

- 정상 RawRecord, 격리 행, 필요하면 체크포인트를 `store.save_page` 한 트랜잭션에서 저장한다. DB 오류면 페이지 전체를 롤백한다.
- 기존 빈 cursor `{}`는 체크포인트가 없던 경우와 같이 처음부터 조회한다. `time_ms`가 있으면 bool이 아닌 0 이상의 정수여야 하며, 명시적 null을 포함한 위반 값은 PIT를 열기 전에 `checkpoint_cursor`로 해당 대상을 실패시킨다.
- `sort[0]`은 bool이 아닌 0 이상의 정수만 유효하다. 잘못된 정렬 값을 받은 페이지는 같은 논리 검색을 최대 3회 수행한다. 각 시도는 최신 PIT ID와 같은 `search_after` 경계를 사용한다. 재조회 후에도 남은 dict hit의 정렬 값 오류는 `sort_value`로 격리한다. 마지막 hit가 비-dict이거나 정렬 값을 쓸 수 없는 hit면 해당 격리 행과 페이지 내 정상 원본을 저장하고 체크포인트는 유지한 채 실행을 `sort_value`로 종료한다. 다음 실행에서도 반복될 수 있는 의도된 중단이다.
- 페이지 마지막 hit의 정렬 값이 유효하면 해당 시각을 체크포인트로 저장한다. 그 페이지의 비마지막 격리 문서도 저장하고 다음 페이지로 진행한다.

### 재시도

- `network`, `timeout`, HTTP 408·429·5xx는 같은 요청을 최초 호출 포함 총 3회 시도한다. PIT 열기와 검색 요청에 적용한다. PIT 닫기는 재시도하지 않는다. 인증 오류, 그 밖의 4xx·3xx, `too_large`, `response_shape`는 재시도하지 않는다.
- 일시 오류 요청 재시도와 정렬 값 문제로 인한 페이지 재조회는 별도 3회 예산이다. 검색 HTTP 요청은 페이지당 최대 9회다. 일시 오류 요청 재시도 중 3회 모두 실패하면 해당 페이지 재조회 예산이 남아도 실행을 실패시킨다.
- 재시도 사이에는 고정 1초를 둔다(마지막 시도 뒤에는 대기하지 않음). 재시도 횟수는 실행 메모리에서만 관리한다. 대기 함수는 테스트에서 대체할 수 있게 한다.

### 실행 기록과 출력

- `ingest_run` 계약의 필수 필드와 `ingest_runs`에 NOT NULL `quarantined` 정수(0 이상 CHECK)를 추가한다. 기존 행은 기본값 0으로 채운다.
- `inserted`와 `quarantined`는 이번 실행에서 실제 커밋한 신규 행 수다. 중복으로 건너뛴 행과 롤백된 페이지는 세지 않는다. 부분 성공 뒤 실행이 실패해도 앞서 커밋한 누계와 실패 `outcome`을 기록한다.
- 실행 출력에도 신규 격리 수를 표시한다. 일부 문서 격리만으로는 실행을 실패 처리하지 않고, 마지막 hit 정렬 값 문제 등으로 멈춘 경우 실제 실패 코드를 남긴다.

### 기록과 선행 작업

- #277의 `0106`과 D-049를 포함한 최신 `origin/main`에서 작업한다. 마이그레이션 번호는 다음 사용 가능 번호를 확인한다(현재 후보 `0107`).
- 계획 218의 문서 단위 검증 실패 시 페이지 전체를 멈추는 규칙을 이 계획으로 대체한다. 이전 계획 파일은 수정하지 않는다.
- 격리 원문에도 D-008 보관 기간을 적용한다. 보관 설정과 실제 삭제 기능은 별도 후속 이슈다.
- 반복되는 `sort_value`·`checkpoint_cursor` 실패와 격리 불가능 오류의 운영자 알림·사람 승인 복구 절차는 별도 후속 이슈다. 화면, API, 격리 재처리도 범위 밖이다.

## 바꿀 곳

- `src/soc/ingest/elk.py`: 응답 구조 검사와 문서 분류, 재시도·페이지 재조회
- `src/soc/ingest/run.py`: 격리·정상 저장·체크포인트 경계, `SourceResult`, 실행 출력 및 `ingest_runs` 기록
- `src/soc/ingest/store.py`: 격리 행을 페이지 트랜잭션으로 저장하고 신규 격리 건수 반환
- `src/soc/ingest/errors.py`: `sort_value`, `checkpoint_cursor` 및 필요한 실패 종류
- `src/soc/db/migrations/`: `ingest_quarantine`와 `ingest_runs.quarantined` 변경
- `contracts/`, `src/soc/contracts/`: 격리 행·실행 건수 계약과 생성 코드
- `tests/fixtures/ingest/`, `tests/ingest/`, 계약·마이그레이션 테스트
- `docs/decisions.md`, `docs/notes/294-ingest-quarantine.md`

## 다른 코드와 맞물리는 곳

- `ingest_run` 공개 계약과 `ingest_runs` 행에 `quarantined` 필드를 추가한다.
- `store.save_page`와 `elk.iter_pages`의 수집 모듈 내부 반환 형식 및 호출부를 바꾼다.
- RawRecord 저장 키는 기존 D-049 규칙을 유지한다. 격리 표의 `siem_ref`는 모든 격리 hit에 쓰는 전용 합성 키다.
- 페이지 트랜잭션 밖의 기존 `ingest_runs` 실패 허용 동작과 체크포인트 계약은 유지한다.

## 범위 밖

- 격리 원문 보관 기간 설정 및 삭제 기능
- 운영자 알림·복구 명령
- 응답 전체 JSON 파싱 실패에서 문서 단위로 복구하는 기능
- 격리 행 조회 화면/API와 재처리 기능
- 실행을 넘어 누적하는 재시도 카운터

## 완료 기준

- [ ] NaN, ±Infinity, 깊이 초과, RawRecord 계약 위반, 정렬 값 문제 hit를 격리하고 해당 원문을 보존한다.
- [ ] `_index`·`_id` 누락·빈 값·잘못된 형식의 hit가 합성 키로 격리되고 수집이 이어진다.
- [ ] D-049 RawRecord 키와 격리 전용 키가 혼용되지 않고, 결측/실제 값, 정수·문자열·비정상 sort 토큰, 제어 문자, Unicode, 짝 없는 서로게이트를 안전하게 처리한다.
- [ ] 128자보다 긴 Base64url 페이로드는 고정 길이 SHA-256 토큰으로 축약되어 유일 키 길이를 제한하고, 전체 값은 `original_text`에 남는다.
- [ ] 해시 골든 fixture가 키 순서·공백 차이, NaN·±Infinity, Unicode, 깊은 중첩, `_score` 및 `_shard_doc` 변화에 대한 정책을 고정한다.
- [ ] 같은 합성 키를 재수집하면 한 행만 남고 `quarantined`에는 새로 커밋된 격리 행만 반영된다.
- [ ] 정상 원본·격리 행·체크포인트가 페이지 단위로 원자적이며, DB 오류 시 전부 롤백된다.
- [ ] 중간 hit의 정렬 값 문제는 3회 재조회 후 `sort_value`로 격리하고, 뒤의 정상 hit 기준으로 체크포인트를 넘긴다.
- [ ] 마지막 hit가 비-dict이거나 정렬 값 문제가 지속되면 페이지 원본·격리 행을 커밋하고 체크포인트를 유지한 채 `sort_value`로 실패한다. 비-dict hit의 격리 행은 `hit_ref` reason을 갖는다.
- [ ] 일시 오류는 요청마다 3회 시도하고, 정렬 값 재조회 예산과 분리되며, 요청 종류별 재시도 여부가 테스트된다.
- [ ] 잘못된 `time_ms` 체크포인트가 `checkpoint_cursor`로 실패한다.
- [ ] `ingest_run` 계약, DB 행, 출력이 `quarantined`를 기록하며 과거 실행은 0으로 처리된다.
- [ ] 합성 fixture 우선 테스트, `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run pytest -m db`가 통과한다.
- [ ] `docs/notes/294-ingest-quarantine.md`에 결과와 후속 이슈 초안을 기록한다.

## 토론으로 정한 것

- 원 이슈의 식별자 누락 시 격리 불가라는 중단 방향을 합성 키 사용·수집 지속으로 바꾼다. RawRecord에는 D-049를 유지하고 격리 hit는 모두 위치·해시 합성 키를 쓴다. 같은 위치·안정 해시의 hit는 한 행으로 합치고, 문서별 반복 수는 세지 않는다.
- 합성 토큰은 존재 여부 접두사와 Base64url로 구분자·결측 sentinel 충돌을 막는다. 패딩을 뺀 Base64url 페이로드가 128자를 넘는 토큰은 `h<sha256>`로 줄이고 전체 값은 `original_text`에 보존한다. 해시 입력은 `_score`와 PIT 종속 sort 후행 값을 제외한 전체 hit 투영으로 정하고, D-049 원문 보존은 그대로 유지한다.
- NaN·±Infinity와 깊이 100 초과 문서는 원문을 보존하면서 격리한다. NUL·짝 없는 서로게이트는 D-049가 보존하므로 격리하지 않는다.
- 일시 오류와 정렬 값 재조회는 각각 총 3회 예산으로 계산하고 고정 1초 대기를 둔다. 한 페이지 검색 요청의 최댓값은 9회다.
- 실행별 신규 격리 수를 `ingest_run`과 출력에 추가한다. 중복 건너뜀과 롤백은 세지 않는다.
- 마지막 정렬 값 문제의 커밋 후 정지는 의도한 동작으로 명시한다. 반복 알림·복구 및 D-008 실제 삭제 기능은 별도 이슈로 관리한다.
- 이 계획은 #277의 D-049 원문 저장·키 이스케이프 변경 이후에 구현하며, 계획 218 파일은 수정하지 않는다.

## 바뀐 점

- 2026-11-12 · 사람이 #294 정책과 합성 키·해시·실행별 격리 건수를 확정했다.
- 2026-11-12 · 리뷰에서 PostgreSQL 유일 인덱스의 키 길이 한계를 확인해 사람과 논의했다. Base64url 토큰이 128자를 넘으면 해당 JSON 바이트의 SHA-256 토큰으로 축약하고 원문은 `original_text`에 보존하기로 확정했다.
