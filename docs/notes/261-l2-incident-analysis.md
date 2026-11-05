---
issue: 261
date: 2026-11-06
owner: Juhyeok0603
plan: 261-l2-incident-analysis.md
supersedes: []
---

# L2 Incident 분석 결과를 근거와 함께 저장한다

## 한 일

L2 실행기에 `l2_analyze` 워커를 추가해 analyzing Incident를 조사 run과 보고 run으로 처리한다.
조사 구간·관련 Alert/Event·자산·이전 Artifact를 문맥으로 넘기고, 중첩 근거까지 장부로 검사한다.
성공 결과는 Incident Artifact와 순서가 있는 Proposal 행으로 원자적으로 저장한다.
실패·취소·일시 오류 재시도·분석 라운드 한도와 ATT&CK 기법 필터를 계획대로 구분한다.
네 계약과 ID 접두사, 마이그레이션, fixture와 DB 회귀 테스트를 함께 추가했다.

## 계획과 달라진 점

- 계획의 `read.py`·`decide.py` 역할은 각각 `context.py`·`tasks.py`에 뒀다. 기존 L2 코드의
  문맥/AgentTask 구분과 이름을 맞춘 것이다.
- 새 DB 테스트 파일을 만들지 않고 기존 `tests/test_l2_branch_db.py`의 L2 공용 fixture와 삽입
  도우미를 재사용했다. 별도 샘플과 중복 준비 코드를 만들지 않기 위해서다.

## 다음 사람이 알아야 할 것

- 실제 모델 확인은 `config/local.toml`에 LLM endpoint와 model 설정이 없어 실행하지 못했다.
- Windows에서는 기존 `test_name_ending_in_newline_is_not_a_migration`이 줄바꿈 파일명을 만들지
  못해 실패한다. 이 테스트를 제외한 기본 테스트와 모든 DB·Qdrant 표식 테스트는 통과했다.
- Qdrant 검사에서 서버 버전을 읽지 못했다는 기존 호환성 경고 1건이 있었지만 테스트는 통과했다.

## 확인 방법

- `uv run python scripts/generate_contracts.py --check` — 통과
- `uv run ruff format --check .` — 통과
- `uv run ruff check .` — 통과
- `uv run pytest -k "not test_name_ending_in_newline_is_not_a_migration"` — 1241개 통과. 제외한
  Windows 기존 테스트 1개는 플랫폼 제한으로 실패
- `uv run pytest -m "db or qdrant"` — 380개 통과
- L2 분석 DB 테스트 — 성공 저장·재시도·실패·취소·한도·재분석·자산 실패·동시 변경·판정 상태
  10개 통과
