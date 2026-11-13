---
issue: 294
date: 2026-11-12
owner: uptime-zero
plan: 294-ingest-quarantine.md
supersedes: ["218-elk-rawrecord.md"]
---

# 저장할 수 없는 문서는 격리하고 수집을 계속한다

## 한 일

- `0107_ingest_quarantine.sql`에 격리 테이블과 `ingest_runs.quarantined`를 추가했다. 기존 실행 행은 기본값 0으로 읽힌다.
- `quarantine.py`는 반복형 JSON 직렬화·깊이/비유한값 검사·격리 키 생성을 제공한다. 격리 키는 모든 행에서 전용이며, sort 토큰은 중첩 객체 키를 정렬하고 공백 없는 canonical JSON 바이트로 만든다. 필드별 Base64url 페이로드가 128자를 넘으면 JSON 바이트의 SHA-256 hex로 축약하고, 원문 전체는 `original_text`에 남긴다. 전체 hit 해시는 `_score`와 sort 뒤쪽 값을 제외한다.
- ELK 응답의 hit 목록 모양만 검사한 뒤 각 hit를 분류한다. 식별자 누락, 비-dict, 계약 위반, 비유한 숫자와 깊이 초과 값을 원문과 함께 격리한다. NUL·짝 없는 서로게이트는 D-049 방식으로 보존한다.
- 페이지별로 정상 원본·격리 행·유효한 다음 체크포인트를 하나의 `save_page` 트랜잭션에 저장한다. 마지막 hit 정렬 값이 재시도 후에도 유효하지 않으면 그 페이지의 원본·격리 행을 저장하고 기존 체크포인트를 유지한 채 `sort_value` 실패로 끝낸다.
- 네트워크/timeout/408/429/5xx 요청 재시도와 sort 문제 페이지 재조회는 독립된 3회 예산이며 대기 함수와 함께 주입할 수 있다. 실행 결과·DB 기록·CLI 출력에 새로 커밋된 격리 수를 포함한다.
- Python 계약, JSON Schema, TypeScript 생성 파일, fixture와 단위/DB 회귀 테스트를 갱신했다. 상세 테스트 구성은 [ingest 테스트 안내](../../tests/ingest/README.md)에 있다.

## 계획과 달라진 점

없음. 긴 토큰 처리 결정은 업데이트된 계획과 D-050에 반영했다.

## 다음 사람이 알아야 할 것

- 계획된 후속 작업: D-008 보관 기간에 따른 격리 원문 삭제, 반복되는 `sort_value`·`checkpoint_cursor`와 응답 전체 `response_shape` 오류의 운영자 알림 및 승인된 복구 절차.
- 설정값인 `siem_profile`은 hit에서 온 필드 토큰의 128자 제한 대상이 아니다. 극단적으로 긴 `siem_profile`도 `(siem_profile, siem_ref)` 유일 인덱스 크기에 영향을 줄 수 있지만, 프로필 이름 길이 검증은 이번 범위 밖이다. `source_key`는 이 유일 인덱스의 키가 아니다.
- 격리 재처리 API/화면과 실행 간 재시도 카운터는 계획 범위 밖이다.

### 후속 이슈 초안: 격리 원문 보관·삭제

**제목:** `feat(ingest): add quarantine retention cleanup`

**본문:** D-008에 맞춰 `ingest_quarantine.original_text`의 보관 기간을 정하고 만료 행을 삭제한다. 보관 설정은 환경변수 이름만 문서화하고, 실행 결과에는 삭제 건수만 남긴다. 만료 기준·시간대·배치 크기와 삭제 동작을 테스트로 고정한다.

### 후속 이슈 초안: 실패 알림·승인 복구

**제목:** `feat(ingest): add quarantine failure alerts and recovery`

**본문:** 반복되는 `sort_value`·`checkpoint_cursor` 및 `response_shape` 실패를 운영자에게 알리고, 사람이 승인한 체크포인트 복구 절차를 제공한다. 원문이나 외부 응답 본문은 알림에 넣지 않으며, 복구 전후 대상·cursor·행 수를 기록한다.

## 확인 방법

- `uv run ruff format --check .` — 340개 파일 포맷 통과.
- `uv run ruff check .` — 통과.
- `uv run python scripts/generate_contracts.py --check` — 생성 Python 계약 일치.
- `npx --yes pnpm --dir frontend contracts` / `npx --yes pnpm --dir frontend contracts:check` — TypeScript 생성 및 35개 파일 일치.
- `uv run pytest` — 1,524 passed, 479 deselected. 종료 시 기존 `FakeSshServer` pending-task 경고가 나왔지만 종료 코드는 0이었다.
- `DATABASE_URL=<임시 PostgreSQL 17 테스트 DB> uv run pytest -m db -q` — 448 passed, 1,555 deselected.
- `uv run pytest tests/ingest/unit/test_quarantine.py -q` — 8 passed.
- `DATABASE_URL=<임시 PostgreSQL 17 테스트 DB> uv run pytest -m db tests/ingest/db/test_quarantine_db.py::test_long_field_tokens_are_hash_bounded_and_fit_the_unique_index -q` — 1 passed. legacy 긴 키의 `ProgramLimitExceeded`, 제한 키 저장, 중복 건너뜀, DB 원문 전체 일치를 확인했다.
