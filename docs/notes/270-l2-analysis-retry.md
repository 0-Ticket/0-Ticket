---
issue: 270
date: 2026-11-10
owner: Juhyeok0603
plan: 270-l2-analysis-retry.md
supersedes: [261-l2-incident-analysis.md]
---

# L2 분석 실패를 분리하고 멈춘 Incident를 다시 분석한다

## 한 일

L2 분석 라운드 한도를 없애고 연속 실패를 `details.l2_analyze.failure_streak`로 따로 센다.
세 번째 실패는 Incident를 `held`로 옮기고 실패 저장 시각을 `held_at`에 남긴다.
한 시간 뒤에는 새 Ticket 없이도 다시 분석하고, 새 Ticket이 분석 도중 붙으면 현재
Artifact를 저장한 뒤 `analyzing`을 유지해 새 Ticket을 다시 읽는다. 기존 `round_limit`
표시는 마이그레이션에서 제거한다. 계약·분류 후보·API·대시보드·화면 필터도 새 상태를 읽는다.

## 계획과 달라진 점

- 새 마이그레이션 때문에 `tests/test_db_tables.py`의 적용 파일 목록과 개수도 갱신했다.
  계획의 DB 테스트 범위에 포함되는 연동 검사다.

## 다음 사람이 알아야 할 것

- 기존 `failures[]`를 계속 보존하므로 반복 장애가 오래 이어지면 Incident `details`가 커진다.
- 쿨다운에는 Ticket 연결 시 움직이는 `updated_at` 대신 실패를 저장한 시각인
  `held_at`을 쓴다. `held`에 Ticket이 붙어도 상태를 바로 바꾸지 않는다.
- 로컬 설정의 `max_analysis_rounds`는 제거됐다. `max_failures`와
  `failure_retry_cooldown_ms`로 바꿔야 한다.
- 사람은 L1·L2·L3·화면 담당이 공통 Incident 상태 변경을 모두 확인했다고 말했다.
  다만 2026-11-10에 읽은 #270 이슈 댓글은 0건이라 승인 기록 완료 기준은 아직
  충족하지 않았다. GitHub에는 쓰지 않았다.
- Azure 서버의 분리된 시험 폴더에서 실제 LLM을 두 번 호출했다. 합성 Incident의
  첫 분석은 두 번 모두 `evidence_id_error`였고, Incident는 `analyzing`,
  `failure_streak = 1`, Artifact 0건으로 저장됐다. 두 번째 호출은 임시 DB 조회
  도구만 허용해 외부 SIEM을 읽지 않았다. 실제 모델이 Artifact를 완성하는 경로와
  장애 복구 뒤 성공하는 경로는 확인하지 못했다.
- Windows의 기본 전체 pytest는 기존 `test_name_ending_in_newline_is_not_a_migration`이
  줄바꿈 파일명을 만들 수 없어 실패한다. Linux 컨테이너에서는 전체 테스트가 통과했다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run python scripts/generate_contracts.py --check`: 통과
- `frontend/`에서 `pnpm contracts:check`, `pnpm lint`, `pnpm test`, `pnpm build`: 통과
- Linux 컨테이너 `uv run pytest -q`: 1377 passed
- Linux 컨테이너 `uv run pytest -m 'db or qdrant' -q`: 439 passed, Qdrant 버전 조회
  경고 1건. 테스트 DB와 Qdrant는 임시 컨테이너를 썼다.
- `test_six_new_tickets_each_trigger_analysis`: 손으로 만든 RawRecord·Alert·Ticket
  6건을 순서대로 연결해 Artifact 7건(첫 분석 포함)과 `analysis_round = 7`을 확인했다.
- `test_three_failures_hold_until_cooldown_even_if_ticket_updates_incident`:
  모델 실행 후 `held_at`, Ticket 연결 뒤에도 유지되는 복귀 시각, 성공 시 카운터 초기화를 확인했다.
- Azure 서버의 분리된 시험 폴더에서 #270 관련 단위 테스트 24개와 임시 DB 테스트
  40개가 통과했다. 서버의 원래 저장소·`.env`는 수정하지 않았다.
- 마무리 단계에서 백엔드 포맷·린트·계약 생성 검사, Linux 전체 테스트 1377개와
  임시 DB·Qdrant 테스트 439개를 다시 통과했다. 화면 계약 생성·린트·테스트
  23개·빌드도 다시 통과했다. Qdrant 버전 조회 경고 1건과 Vite 번들 크기 경고가 있었다.
