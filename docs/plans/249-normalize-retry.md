---
issue: 249
date: 2026-11-05
owner: uptime-zero
supersedes: [234-ocsf-alert-event.md]
---

# W03 — 정규화 실패 전용 재처리 작업 구현

## 목표

W02 정규화 명령은 미처리 자료(`pending`)만 처리하고, 별도 W03 명령은 실패 자료(`failed`)만 다시 처리한다. 두 작업은 기존 `normalize_status`, 정규화 함수, 결과 저장 트랜잭션을 재사용한다.

## 방법

- W02의 대상 선택을 `pending` 상태로 제한한다. 상태 행이 없는 새 RawRecord는 기존처럼 `pending`으로 등록한다. 처리 도중 중단된 `pending` 자료는 임대 만료 뒤 다음 W02 실행에서 다시 선택한다.
- 별도 일회성 진입점 `uv run python -m soc.normalize.retry`를 추가한다. W02와 같은 `[normalize]` 설정(`batch_size`, `lease_seconds`)을 사용하고 새 설정이나 환경변수는 만들지 않는다.
- W03은 `normalize_status.status = 'failed'`인 자료만 선택한다. 새 RawRecord의 상태 행을 만들거나 `pending`·`succeeded` 자료를 처리하지 않는다. 임대가 없거나 만료된 실패 자료를 기존 임대 규칙으로 맡는다.
- W03은 W02의 변환·계약 검사·Asset Lookup·저장 함수를 재사용한다. 성공하면 결과와 `succeeded` 상태를 한 트랜잭션으로 저장하고 임대를 해제한다. 실패하면 안전한 오류 종류 코드와 시도 횟수를 갱신하고 `failed`로 남긴다.
- 작업은 자료별로 실패를 기록하고 다음 자료를 계속 처리한다. 원본·예외 메시지·비밀 값은 출력하거나 상태에 저장하지 않는다. RawRecord를 다시 수집하거나 수정하지 않으며, ELK 체크포인트도 건드리지 않는다.
- W02와 W03은 각각 한 번 실행하고 끝난다. 스케줄러를 만들지 않고, 실행 주기는 외부 cron에서 정한다. 실패 재시도 횟수 제한은 추가하지 않는다. W02 계획의 실패 재시도 책임을 W03으로 옮기며, 이 계획은 W02 계획의 재시도 대상 선택만 대체하고 나머지 내용은 바꾸지 않는다.

## 바꿀 곳

- `src/soc/normalize/store.py`: W02의 pending 전용 선택과 W03의 failed 전용 선택을 분리한다. W03 선택은 새 상태 행을 만들지 않는다.
- `src/soc/normalize/run.py`: pending 처리와 failed 재처리가 동일한 변환·저장 경로를 쓰도록 연결한다.
- `src/soc/normalize/retry.py`: 실패 자료를 처리하는 별도 명령 진입점을 추가한다.
- `tests/fixtures/normalize/`, `tests/test_normalize_db.py`, `tests/test_normalize_main.py`: 두 선택기가 서로의 상태를 가져가지 않는지와 재처리 흐름을 확인한다. 필요하면 retry CLI 검사를 추가한다.
- `docs/notes/249-normalize-retry.md`: 개발 중 확인한 내용과 실행 방법을 기록한다.

## 다른 코드와 맞물리는 곳

- W01의 `raw_records`와 `ingest_checkpoints`는 읽거나 수정하지 않는다.
- W02의 `normalize_status`와 기존 결과 테이블을 그대로 사용한다. 새 마이그레이션이나 데이터 계약 변경은 없다.
- W02 명령의 외부 동작이 바뀐다. W02는 `pending`만 처리하고, 실패 자료 재시도는 W03이 맡는다.

## 범위 밖

- RawRecord 재수집·수정, ELK 접근, 수집 체크포인트 변경
- 새 상태 테이블·정규화 결과 테이블·마이그레이션
- 앱 내부 스케줄러, retry 횟수 상한, 백오프 정책
- OCSF 매핑 규칙이나 Asset Lookup 변경
- W02 계획 파일 수정, GitHub 이슈 댓글 게시

## 완료 기준

- [x] W02 실행은 `pending`만 선택하고 `failed`·`succeeded`는 선택하지 않는다.
- [x] W03 실행은 `failed`만 선택하고, 새 RawRecord 상태 행을 만들거나 `pending`·`succeeded`를 선택하지 않는다.
- [x] 실패 한 건은 다른 자료의 처리를 막지 않는다. 실패 코드는 원문과 예외 메시지 없이 기록되고, 반복 실패 시 시도 횟수가 증가한다.
- [x] 매핑 오류로 실패한 자료가 매핑 수정 후 W03에서 성공하면 결과가 한 건만 저장되고 상태가 `succeeded`가 된다. RawRecord 원본은 바뀌지 않는다.
- [x] 이미 성공한 자료는 W03 재실행으로 다시 처리되지 않는다.
- [x] W03 실행 중 중단된 실패 자료는 임대 만료 후 재선택된다. 임대를 잃은 작업자의 늦은 결과는 저장되지 않고, 결과·성공 상태는 원자적으로 기록된다.
- [x] 합성 fixture와 DB 테스트 및 공통 검사(`uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run pytest -m db`)가 통과한다.

## 토론으로 정한 것

- W02가 미처리와 실패 자료를 함께 처리하던 방식을 나눈다. 일반 처리와 실패 재처리의 책임을 각각 W02의 `pending`, W03의 `failed`로 제한한다.
- W02의 실패 재시도 정책을 이 계획에서 대체한다. W02 계획 파일은 수정하지 않는다.
- W03은 기존 상태·임대·결과 저장 규칙과 설정을 재사용하고 별도 retry 횟수 제한은 두지 않는다.

## 바뀐 점
