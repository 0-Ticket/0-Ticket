---
issue: 334
date: 2026-11-18
owner: Pandyo
plan: 334-reprocess-alerts.md
supersedes: []
---

# 기존 알럿을 id를 유지한 채 다시 정규화하는 재처리 명령

## 한 일

`python -m soc.normalize reprocess`가 이미 정규화된 알럿을 id를 유지한 채 다시 정규화한다(D-063). `normalize_status.result_id`가 가리키는 알럿 한 건을 행마다 트랜잭션에서 `FOR UPDATE`로 잠그고, 새 결과와 비교해 달라진 컬럼만 UPDATE한다. 기본 대상은 `outcome IS NULL`인 알럿이고, `--source`를 주면 새 결과의 `source`가 같은 모든 알럿이다. 새 결과가 폴백·오류이거나 기존 `outcome`보다 낮으면 건너뛴다. `--dry-run`은 쓰지도 잠그지도 않고 건수와 컬럼 이름, 엔티티 type·role 추가/제거 건수만 낸다. `run`의 INSERT 경로는 그대로다.

## 계획과 달라진 점

- `run._checked_row`에 선택 인자 `previous`(저장된 entities·assets)를 더했다. 엔티티가 같으면 자산을 다시 조회하지 않기 위해서다. 인자를 안 주면 동작은 그대로다.
- `--source` 값은 소스 이름인지 검사하지 않는다. 오타면 `other_source`만 늘고 0건 갱신이다.
- 옵션 파싱은 `argparse`(표준 라이브러리)이고, 틀린 옵션은 종료 코드 2다.

## 다음 사람이 알아야 할 것

- `--source`를 주면 outcome과 관계없이 모든 알럿을 정규화하므로 `--limit` 없이 크게 돌리면 오래 걸린다. 읽는 순서는 `alerts.time`, `id`다.
- `--since`에 시간대가 없으면 UTC다.
- 같은 `raw_id`에 알럿이 둘 이상이면 `result_id` 쪽만 갱신하고 나머지 수는 `duplicate_alerts`로 보고한다. 갱신을 건너뛴 행(폴백·낮아짐)에서는 세지 않는다.
- 폴백 결과로 건너뛴 `outcome IS NULL` 행은 다음 기본 실행에서 다시 읽힌다.
- 재처리는 유사 사례·분기 임베딩(`similar/index.py`, `l2/branch/embed.py`)을 갱신하지 않는다. 임베딩은 옛 값 기준일 수 있다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`: 통과(2095건, 마커 제외).
- `uv run pytest -m db tests/normalize tests/test_pipeline_db.py tests/test_lab_cycle_db.py tests/l1`(DB 이름만 `postgres`로): 80건 통과.
- 새 테스트: `tests/normalize/test_reprocess_db.py`(갱신·id·triage·Ticket 불변, 두 번째 실행 0건, dry-run 무쓰기, 폴백·낮아짐 건너뜀, `--source` 선택, Event 불변, 중복 알럿, 행 단위 DB 오류와 종료 코드 1, `--limit`·`--since`), `tests/normalize/test_normalize_main.py`(환경변수·옵션 오류).
- 개발 DB 사본에서 실제 알럿 재처리: 아직 안 했다. 사람이 `--dry-run`으로 돌려 건수를 알려 주면 PR에 적는다.
