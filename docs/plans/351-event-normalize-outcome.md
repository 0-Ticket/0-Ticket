---
issue: 351
date: 2026-11-20
owner: uptime-zero
supersedes: []
---

# 전체 이벤트의 정규화 품질(`outcome`) 기록

## 목표

현재 정규화가 만드는 이벤트에 품질과 매핑 출처를 기록한다. 신규 처리와 재처리에서 같은 판정 기준을 사용하며, 보고서에서 이벤트와 알럿 품질을 각각 조회할 수 있게 한다.

## 방법

1. **샘플과 테스트 먼저.** `tests/fixtures/normalize/`의 손으로 만든 샘플을 사용해 nginx 선택 필드, ModSecurity 시각, 6003과 지원 매핑이 없는 이벤트를 확인한다. 필요한 샘플은 실제 원본 값 없이 추가한다.
2. **이벤트 공통 판정.** 클래스별 OCSF 검증과 계약 검증을 거친 결과에 아래 기준을 적용한다. 매핑표의 `required`는 품질 판정에 필요한 입력을 표시하고, OCSF 필수 조건은 완성된 출력에서 검사한다. 이번에 품질 판정 대상 필드를 추가하지 않는다. 누락 판단은 클래스 표와 소스 표의 최종 적용 결과를 따른다.

   | 결과 | 기준 |
   |---|---|
   | `ok` | 매핑이 정한 품질 기준을 충족한다. 선택 필드는 없거나 읽지 못하면 기존대로 생략한다. |
   | `partial` | 유효한 이벤트를 만들었지만 매핑이 품질 판정에 필요하다고 정한 값을 얻지 못했거나, 매핑이 허용한 대체 시각을 사용했다. |
   | `fallback` | 지원 매핑이 없어 Base Event(0) 경로에서 유효한 이벤트를 만들었다. `error_code`에 `unsupported_event_mapping`을 기록한다. |
   | `status = failed` | 유효한 이벤트를 만들 수 없거나 저장에 실패했다. 기존 실패 경로에서 `status`와 오류 코드를 기록하고 `outcome`은 NULL로 둔다. |

3. **ModSecurity 시각.** #349와 같은 시각 선택 규칙을 사용한다. 유효한 `transaction.time_stamp`는 요청 발생 시각으로 쓴다. 그 필드가 아예 없고 `@timestamp`가 유효하면 `partial`, `missing_fields = [metadata.original_time]`, `error_code = missing_request_time_used_at_timestamp`를 기록한다. 사유 코드가 요청 시각의 부재와 실제 사용한 필드 `@timestamp`를 함께 나타낸다. `transaction.time_stamp`가 있는데 해석할 수 없거나 두 경로 모두에서 시각을 얻지 못하면 기존대로 `validation_failed`다.
4. **저장.** `Result`의 기존 품질 필드를 사용해 `normalize_status`의 `outcome`·`source`·`missing_fields`·`error_code`를 이벤트 결과와 같은 트랜잭션에 저장한다. `missing_fields`에는 OCSF 경로를 넣는다. 이벤트 `source`는 일치한 소스 표 파일 이름의 확장자를 뺀 값, 인덱스 규칙으로 고른 경우 `class_4002`·`class_6003`, 지원 매핑이 없는 경우 `unknown`이다. 입력 문서의 인덱스 문자열이나 `event.module` 값을 그대로 기록하는 경로는 없다. 새 마이그레이션에서 기존 `source` CHECK를 종류별 제약으로 바꾼다. 알럿과 결과 종류가 없는 행은 기존 허용 목록과 NULL을 허용하고, 이벤트는 로더가 확인한 소스 표 이름과 코드가 정한 이름을 사용한다. 검증된 이름만 허용한다는 조건은 로더와 코드에서 지킨다. 기존 품질 미기록 행은 명시적인 재처리 전까지 NULL이다. 대체 시각만을 위한 컬럼은 추가하지 않는다.
5. **재처리.** `reprocess --kind event`에서 신규 처리와 같은 매핑과 판정 함수를 쓴다. 기존 성공 행을 대상으로 하는 조회 범위와 `--since`·`--limit`·`--dry-run` 동작을 유지한다. 이벤트 ID·원본 ID·결과 포인터를 유지하며, 변경분이 있으면 이벤트와 품질 기록을 행 단위 트랜잭션에서 함께 갱신한다. 내용이 같고 품질만 비어 있는 행도 갱신 대상이다.
   - 이미 기록된 품질이 `ok > partial > fallback` 순서에서 하락하면 건너뛰고 `worse`로 집계한다. 검증·자산 조회 등에 실패한 재처리는 기존 결과를 보존하고 기존 실패 사유로 집계한다.
   - 새 결과가 `fallback`일 때 기존 이벤트가 Base Event(0) 이외의 클래스면, 기존 `outcome`이 NULL이어도 이벤트와 품질 기록을 보존하고 `worse`로 집계한다. 기존 결과가 Base Event이고 품질이 비어 있으면 `fallback`을 기록할 수 있다. Base Event에서 유효한 다른 클래스로 개선되는 경우 같은 ID로 갱신한다.
6. **보고서.** `uv run python -m soc.normalize report`와 `report --kind alert`는 알럿, `report --kind event`는 이벤트를 선택한다. `result_kind`를 기준으로 성공한 행 중 품질이 기록된 행을 소스·품질·누락 필드별로 센다. 집계에는 원본 값을 넣지 않는다.

## 바꿀 곳

- `src/soc/normalize/mapping.py`, `errors.py`, `store.py`: 이벤트 품질 판정과 사유 코드, 신규 처리 저장 경로.
- `src/soc/normalize/reprocess.py`, `report.py`, `__main__.py`: 재처리 갱신·보존과 품질 보고서의 종류 선택.
- `src/soc/db/migrations/`: `normalize_status.source` 제약 변경 마이그레이션.
- `tests/fixtures/normalize/`, `tests/normalize/`, `tests/test_migrate.py`: 샘플·품질·마이그레이션 회귀 검사.

## 다른 코드와 맞물리는 곳

- `normalize_status`의 기존 품질 컬럼을 이벤트에서도 읽고 쓴다. `result_kind`를 기준으로 알럿과 이벤트를 조회하면 같은 `source` 이름을 각각 집계할 수 있다.
- `events`의 OCSF 문서와 Event 외부 계약은 현재 구조(D-068)를 사용한다. 품질 정보의 저장 위치는 `normalize_status`다.
- `report`에 `--kind`가 추가된다. 기존 옵션 없는 명령의 알럿 집계 형식을 유지한다.

## 범위 밖

- 새 이벤트 매핑, 수집 설정의 `class` 연결, 새 품질 판정 대상 지정, 선택 필드 오류의 별도 집계.
- 알럿 품질 정책 변경, 이벤트 대체 시각 저장 컬럼, 운영 DB 일괄 재처리.

## 완료 기준

- [ ] nginx HTTP 상태 코드가 없는 샘플과 `"abc"`인 샘플 모두 해당 필드를 생략한다. 다른 문제가 없으면 둘 다 `ok`다.
- [ ] ModSecurity 원래 시각 유효, 원래 시각 부재와 유효한 `@timestamp`, 원래 시각 해석 불가, 양쪽 시각 확보 불가를 각각 확인한다. 대체 시각을 쓴 결과에서 `partial`과 사유, 사용한 `@timestamp`를 확인할 수 있다.
- [ ] 유효한 6003 결과, 지원 매핑이 없는 Base Event의 `fallback`, OCSF 검증 실패의 `failed`와 NULL `outcome`을 확인한다.
- [ ] 신규 처리와 재처리에서 같은 원본과 매핑의 품질·사유가 일치한다. 재처리에서 기존 이벤트 ID를 유지하고 품질 미기록 Base Event가 `fallback`으로 기록된다. 기존 4002가 Base Event로 내려가는 경우와 `ok`가 `partial`로 내려가는 경우는 보존한다. `--dry-run`은 쓰지 않는다.
- [ ] 이벤트 소스 이름은 저장할 수 있고 알럿 소스 제약은 유지된다. `report`와 `report --kind event`에서 같은 소스 이름의 알럿과 이벤트가 각각 집계된다. 품질 미기록 행을 집계에 포함하지 않는다.
- [ ] 마이그레이션 적용과 이름·목록·개수 검사를 포함한 필수 포맷·린트·테스트가 통과한다.

## 토론으로 정한 것

- 이슈 본문의 상태 코드 `"abc"` 예시를 바꿨다. 알럿과 같은 품질 기준을 적용해, 선택 항목은 부재와 읽기 실패를 동일하게 품질 판정에서 처리한다. `partial`의 대표 검증 사례는 ModSecurity 대체 시각이다.
- 대체 시각 출처는 기존 `error_code`로 기록한다. 현재 대체 경로는 `@timestamp` 한 가지이며 동일 코드로 사유와 출처를 확인할 수 있다.
- 이벤트 재처리에도 알럿의 품질 하락 방지 원칙(D-063)을 적용한다. 이미 Base Event인 행에는 빈 품질을 채울 수 있도록 허용한다. 이벤트 품질 저장·조회와 재처리 결정은 D-073에 기록한다.

## 바뀐 점
