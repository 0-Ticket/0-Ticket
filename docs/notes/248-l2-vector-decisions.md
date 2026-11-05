---
issue: 248
date: 2026-11-05
owner: Juhyeok0603
plan: 248-l2-vector-decisions.md
supersedes: []
---

# L2 벡터 후보 검색 결정을 확정했다

## 한 일

- Incident 분류 방법(D-027)의 후보 경로를 벡터 검색 우선으로 바꾸고, 컬렉션 부재·조회 실패·
  PostgreSQL 확인 후 유효 후보 0건이면 기존 직접 조회로 떨어지게 정했다.
- Qdrant(D-013)를 용도별 파생 색인으로 두고, L2 분류 후보용 컬렉션에는 `linked` Ticket과
  소속 Incident payload만 넣으며 PostgreSQL을 권위 원본으로 유지하게 했다.
- 기본 임베딩 모델(D-031)을 BGE-M3 dense·로컬 ONNX·1024차원·Cosine으로 확정했다.
  모델 ID·revision은 설정 값이고 컬렉션 이름을 용도·모델 ID·revision에서 파생한다.
- 「담당자가 정함」에서 D-031을 빼고 결정 변경 주체를 「기록」에 남겼다.

## 계획과 달라진 점

없음.

## 다음 사람이 알아야 할 것

- 이 결정이 머지돼도 벡터 경로 구현 전에는 #226의 직접 조회만 동작한다. 후보 경로 설정,
  Qdrant 적재·검색, 모델 실행, 재구축 명령은 후속 L2-A가 만든다.
- 벡터 시간 필터는 두지 않는다. 후보 Incident를 PostgreSQL에서 읽을 때 `updated_at` 시간 창을
  한 번 적용해야 한다.
- 유효 후보가 0건이면 직접 조회로 떨어지지만, 유효 후보가 있는 상태의 일부 point 누락은
  감지하지 못한다. 이 경우 PostgreSQL에서 컬렉션을 다시 만들어야 한다.
- 잘못 연결된 Ticket을 떼거나 다른 Incident로 옮기는 기능은 없다. 벡터 검색이 제시한 후보의
  최종 선택은 기존 D-027대로 에이전트가 한다.

## 확인 방법

- `uv run ruff format --check .`: 217개 파일 검사 통과
- `uv run ruff check .`: 통과
- Windows의 `uv run pytest`: 1,121개 통과, 293개 제외, 1개 실패. 기존
  `test_name_ending_in_newline_is_not_a_migration`이 줄바꿈 파일명을 만들 수 없어 실패했다.
- Linux 재검사를 위해 Docker를 확인했지만 Docker Desktop 엔진이 실행 중이 아니어서 돌리지
  못했다.
- 문서만 바뀌어 새 fixture나 동작 테스트는 추가하지 않았다.
