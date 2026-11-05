---
issue: 249
date: 2026-11-05
owner: uptime-zero
plan: 249-normalize-retry.md
supersedes: [234-ocsf-alert-event.md]
---

# 실패한 정규화 자료를 W03에서 따로 재처리한다

## 한 일

- W02 정규화 실행은 새 상태 행을 만든 뒤 `pending`만 임대한다. `failed`는 다음 실행에서 자동 재시도하지 않는다.
- `uv run python -m soc.normalize.retry` 진입점을 추가해 `failed` 자료만 처리한다. 기존 상태 행만 조회하므로 새 RawRecord 상태 행을 만들지 않는다.
- W02와 W03은 같은 변환·검증·자산 조회·저장 흐름과 설정을 사용한다. 실패한 자료는 기존 규칙대로 오류 종류와 시도 횟수를 기록하고, 매핑이 수정되어 재처리에 성공하면 결과와 성공 상태를 원자적으로 저장한다.
- DB 테스트는 기존 손 작성 샘플 `tests/fixtures/normalize/raw.json`을 재사용해 선택 경계, 중복 방지, 수정된 매핑의 회복, 임대 만료와 늦은 작업자 거부를 확인한다.

## 계획과 달라진 점

목표와 동작 편차는 없다. 실행 경로가 갈라져도 처리 로직이 복제되지 않도록 `_run_batch`와 공통 CLI 설정·연결 함수를 공유했다.

## 다음 사람이 알아야 할 것

- W03도 한 번 실행하고 끝난다. 실행 주기는 외부 cron에서 정한다.
- 새 설정, 마이그레이션, 상태 테이블은 추가하지 않았다. DB 테스트는 `DATABASE_URL`로 연결해 격리된 임시 DB를 만들고 지운다.

## 확인 방법

- `uv run ruff format --check .` — 통과.
- `uv run ruff check .` — 통과.
- `uv run pytest` — 1,123개 통과, 296개 기본 제외.
- `uv run pytest -m db` — 292개 통과, 1,127개 기본 제외.
- 정규화 DB 테스트 19개 통과. 일회용 PostgreSQL 컨테이너를 사용했고 저장소 `.env`는 만들거나 수정하지 않았다.
