---
issue: 253
date: 2026-11-05
owner: uptime-zero
plan: 253-l1-ticket-db-l2.md
supersedes: []
---

# L1 판정과 DB 기반 L2 인계

## 한 일

- 기존 실행기에 L1 워커를 등록해 대기 Alert와 Ticket을 P04 상태표에 따라 판정한다.
- 실패 횟수는 `l1_attempts`에 보존한다. 세 번째 실패에서 보류하며 취소는 세지 않는다.
- 대상 행의 상태를 다시 확인하고 Alert 승격과 Ticket 생성, Ticket 상태와 Verdict를 각각 원자적으로 저장한다.
- 입력·도구 근거 장부와 Agent Log 저장은 기존 에이전트 코어를 사용한다.

## 계획과 달라진 점

없음.

## 다음 사람이 알아야 할 것

- 개발 기준에 P04 확정 문서와 W04 PR 브랜치를 로컬로 합쳤다. W04는 아직 `main`에 통합되지 않았다.
- 실행기 여러 프로세스가 같은 대상을 모델에 중복 요청할 수 있다. 이미 적용된 대상에 늦은 결과를 저장하지 않는다.
- DB 장애나 프로세스 종료로 실패 횟수 저장이 커밋되지 않으면 해당 시도는 횟수에 남지 않을 수 있다.
- 실제 조직 ELK와 실제 모델은 이 작업에서 확인하지 않았다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과.
- `uv run pytest`: 1,144개 통과, 332개 제외. 기존 `FakeSshServer`의 pending-task 경고가 출력됐다.
- 격리된 PostgreSQL에서 `uv run pytest -m db -q`: 328개 통과, 1,148개 제외. 새 마이그레이션을 기존 테이블 목록 검사에 반영한 뒤 재검사했다.
