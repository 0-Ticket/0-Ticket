---
issue: 271
date: 2026-11-08
owner: uptime-zero
supersedes: []
---

# chore(normalize,l1): 흩어진 테스트를 모듈 디렉터리로 이동

## 목표

`tests/` 루트에 플랫하게 있는 normalize·l1 테스트 파일 7개를 각 모듈 디렉터리로 이동한다.
이동 후 `tests/ingest/`와 동일한 패턴으로 normalize·l1 테스트가 모듈 디렉터리 안에 위치한다.

## 방법

파일을 이동하고, 이동된 파일 내부의 fixture 경로 참조(`Path(__file__).parent / "fixtures"`)를
한 단계 위(`Path(__file__).parent.parent / "fixtures"`)로 수정한다.
`tests/l1/`의 빈 하위 디렉터리(구 하네스 흔적)도 함께 삭제한다.

## 바꿀 곳

**normalize 테스트 이동**

- `tests/test_normalize_config.py` → `tests/normalize/test_normalize_config.py`
- `tests/test_normalize_db.py` → `tests/normalize/test_normalize_db.py`
- `tests/test_normalize_main.py` → `tests/normalize/test_normalize_main.py`
- `tests/test_normalize_mapping.py` → `tests/normalize/test_normalize_mapping.py`

**l1 테스트 이동**

- `tests/test_l1_judge.py` → `tests/l1/test_l1_judge.py`
- `tests/test_l1_judge_db.py` → `tests/l1/test_l1_judge_db.py`
- `tests/test_l1_e2e_llm.py` → `tests/l1/test_l1_e2e_llm.py`

**fixture 경로 수정 대상** (이동된 파일 중 `Path(__file__).parent / "fixtures"`를 쓰는 것)

- `tests/normalize/test_normalize_mapping.py`
- `tests/l1/test_l1_judge.py`
- `tests/l1/test_l1_e2e_llm.py`

**빈 디렉터리 삭제**

- `tests/l1/evidence/`
- `tests/l1/mcp/`
- `tests/l1/specialists/`

## 다른 코드와 맞물리는 곳

없음. 테스트 파일 위치 변경만이고 `src/`의 구현 코드는 건드리지 않는다.

## 범위 밖

- `src/soc/` 하위 빈 고스트 디렉터리 삭제 (전 모듈 한꺼번에 별도 이슈로 처리)
- `tests/ingest/unit/`, `tests/ingest/db/` 구조 변경
- normalize·l1 외 다른 모듈 테스트 위치 변경

## 완료 기준

- [ ] normalize 테스트 4개 `tests/normalize/`로 이동, fixture 경로 참조 수정
- [ ] l1 테스트 3개 `tests/l1/`로 이동, fixture 경로 참조 수정
- [ ] `tests/l1/`의 빈 하위 디렉터리 3개 삭제
- [ ] `uv run pytest` 통과
- [ ] `uv run ruff check .` 통과

## 토론으로 정한 것

- src/ 빈 고스트 디렉터리는 이번 범위에서 제외. 전 모듈에 걸쳐 있어 한꺼번에 처리하는 것이 맞다고 사람이 결정함
- `asset_lookup.py`, `entities.py`, `ids.py`, `ticketing.py`는 단계 경계에서 여러 모듈이 공유하는 파일로, `soc/` 루트 위치가 맞음

## 바뀐 점
