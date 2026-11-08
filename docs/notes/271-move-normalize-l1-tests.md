---
issue: 271
date: 2026-11-08
owner: uptime-zero
plan: 271-move-normalize-l1-tests.md
supersedes: []
---

# normalize·l1 테스트를 모듈 디렉터리로 이동

## 한 일

`tests/` 루트에 있던 normalize 테스트 4개와 l1 테스트 3개를 각각 `tests/normalize/`,
`tests/l1/`으로 이동했다. `tests/l1/`의 빈 하위 디렉터리 3개(evidence, mcp, specialists)도
삭제했다.

서브디렉터리로 이동하면 pytest가 sys.path에 `tests/`를 추가하지 않아 루트 테스트 헬퍼
(`conftest`, `fake_model`, `test_agent_core`, `test_ticketing_db`)를 직접 import하는
파일들이 깨진다. `pyproject.toml`의 `pythonpath`에 `"tests"`를 추가해 해결했다.

## 계획과 달라진 점

- 계획에서 fixture 경로 수정 대상을 `test_normalize_mapping.py`, `test_l1_judge.py`,
  `test_l1_e2e_llm.py` 3개로 적었으나, `test_normalize_db.py`도 같은 패턴
  (`Path(__file__).parent / "fixtures"`)을 쓰고 있어 함께 수정했다.
- `pyproject.toml`의 `pythonpath`에 `"tests"` 추가가 필요했다. 계획에 없던 항목이지만
  서브디렉터리 import 해결을 위한 필수 조치다.

## 다음 사람이 알아야 할 것

- `tests/ingest/db/`, `tests/ingest/unit/`의 테스트들은 `Path(__file__).resolve().parents[N]`
  방식으로 fixture 경로를 잡는다(N=2: `db/`→`ingest/`→`tests/`). 이번에 이동한 파일들은
  `Path(__file__).parent.parent / "fixtures"`로 통일했다.
- `test_l1_judge_db.py`는 `test_ticketing_db.py`(루트)에서 `insert_ticket`, `seed_cases`,
  `NOW_MS`를 import한다. `test_ticketing_db.py`를 나중에 `tests/l1/`으로 옮긴다면
  import 경로를 다시 확인해야 한다.

## 확인 방법

`uv run pytest` (db·llm·qdrant·embedder·elk·ssh 마커 제외) 통과 확인.
