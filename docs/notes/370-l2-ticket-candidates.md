---
issue: 370
date: 2026-11-24
owner: Juhyeok0603
plan: 370-l2-ticket-candidates.md
supersedes: []
---

# L2 Ticket 유사도 후보 분류 개발 기록

## 한 일

- 분류용 임베딩 텍스트를 손제작 같은 사건·다른 사건 샘플로 먼저 고정했다. Ticket/Alert 제목·룰·역할이 표시된 엔티티·Alert/Event 요약·Hunt 가설을 길이 제한해 합치고 모델 판정 이유를 제외한다.
- 색인·후보·분류 워커는 개발 중이다.

## 계획과 달라진 점

없음.

## 다음 사람이 알아야 할 것

- #370 이슈의 확정 댓글과 계획 파일은 같은 방향이다. 이슈 본문의 미결 항목은 계획 파일의 토론으로 정했다.
- `ticket_verdicts`는 L1·L2 유사 사례 검색용이며 이번 분류 색인과 별개다.
- 기존 `branch/embed.py`는 모델 판정 이유를 포함해 그대로 재사용할 수 없다.
- 기존 `embedding.json`의 기대값도 이유 포함 형식이어서 새 입력 규칙에 맞게 갱신했다.

## 확인 방법

- `uv run pytest -q tests/test_l2_vector_text.py tests/test_l2_branch.py`: 7건 통과.
- `uv run ruff check src/soc/l2/branch/embed.py tests/test_l2_vector_text.py tests/test_l2_branch.py`: 통과.
