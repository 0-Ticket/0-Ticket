---
issue: 250
date: 2026-11-05
owner: Juhyeok0603
plan: 250-l2-ticket-incident.md
supersedes: []
---

# Ticket을 Incident로 분류하고 벡터 후보를 색인했다

## 한 일

L2 분류 워커가 escalated Ticket의 레이블 없는 임베딩 텍스트를 만들고, Qdrant의 비슷한 linked
Ticket 또는 최근 열린 Incident를 후보로 에이전트에 전달한다. Qdrant hit의 모양과 PostgreSQL 소속
관계를 확인하고, 후보·판정 fallback 다섯 값을 Ticket에 기록한다. 저장 직전에 Ticket과 선택한
Incident를 잠가 한 트랜잭션으로 연결하며, 커밋 뒤 Ticket point를 적재한다. `python -m soc.l2
reindex [--recreate]`는 PostgreSQL의 일관된 linked Ticket만 다시 색인한다.

## 계획과 달라진 점

- 계획에 적은 검사를 역할별로 나눠 `test_l2_decide.py`, `test_l2_worker.py`,
  `test_l2_command.py`, `test_l2_branch_qdrant.py`를 추가했다. 동작 범위는 바뀌지 않았다.
- L1→L2 교차 단계 DB 테스트가 삭제된 `read_branch_data(..., now, window)` 인자를 계속 넘기고 있어
  새 문맥 조회 계약에 맞췄다.

## 다음 사람이 알아야 할 것

- #226 기록대로 L2 파이프라인 DB 연결은 `DATABASE_URL`을 쓰며 도구용 읽기 계정의 권한을 넓히지
  않는다.
- #257 기록대로 Windows의 실제 Qdrant 테스트는 `QDRANT_URL=http://127.0.0.1:6333`이 빠르다.
- BGE-M3 실측에서 일반 Ticket과 L3 Ticket 샘플의 자기 유사도는 각각 `1.000000`, 교차 유사도는
  `0.534009`였다. 기본값을 조정하는 근거로 쓰지 않았다.
- 실제 외부 LLM은 `config/local.toml`과 `LLM_API_KEY`가 없어 호출하지 않았다. 가짜 모델은 실제
  `run_task()`·`branch_decision` 계약·후보 부분집합 검사를 통과했다.
- Windows에서는 기존 `test_name_ending_in_newline_is_not_a_migration`이 만들 수 없는 파일명 때문에
  실패하고, 닫힌 127.0.0.1:1 접속을 쓰는 기존 migration 테스트 두 개는 로컬 방화벽에서 끝나지
  않았다. 이 세 테스트를 제외한 기본 테스트는 통과했고 이번 변경과 관련된 DB·Qdrant 묶음은
  제외 없이 통과했다.

## 확인 방법

- `uv run python scripts/generate_contracts.py --check`: 통과
- `uv run ruff format --check .`: 257개 파일 통과
- `uv run ruff check .`: 통과
- 기본 pytest에서 위 Windows 기존 테스트 3개 제외: 1,215 passed
- `uv run pytest -m "db or qdrant"`: 370 passed
- `uv run pytest -m embedder tests/test_store_embedder.py::test_real_embedder_makes_unit_vector`:
  1 passed
- `uv run pytest -m qdrant tests/test_l2_branch_qdrant.py`: 1 passed
