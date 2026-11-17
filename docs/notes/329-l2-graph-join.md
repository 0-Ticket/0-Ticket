---
issue: 329
date: 2026-11-18
owner: Juhyeok0603
plan: 329-l2-graph-join.md
supersedes: [319-incident-graph.md]
---

# L2 그래프 연결 기준을 출발 측 엔티티로 제한한다

## 한 일

- L2 그래프의 SQL 후보 조회와 직접 그래프 판정에서 출발·상대 엔티티의 역할이 모두 `src`인지 확인한다. 공개 IP 제외 코드를 없애 출발지 IP로 연결할 수 있게 했다. `public_ip_only`는 새로 기록하지 않지만 과거 화면 표시는 유지했다.
- `[l2.branch] max_incident_tickets = 10`을 추가했다. 후보 조회에서 가득 찬 Incident를 먼저 빼고, 모델이 기존 Incident를 고른 뒤 저장 시 잠근 행에서도 상한을 재확인한다. 그사이 가득 찼으면 새 Incident를 만들고 `incident_full`을 기록한다.
- 수집기 host와 목적지 값은 그래프 경로에서만 제외했다. Alert·Ticket·Incident의 엔티티 저장 및 Incident 상세 API·화면은 바꾸지 않았다.

## 계획과 달라진 점

- 기존 DB 분류 fixture의 Alert에는 `target` host만 있어 새 규칙에서 경로가 없었다. 가짜 출발지 IP(`192.0.2.7`)를 추가하고 원래 host는 남겨 연결과 증거 보존을 함께 검사한다. 계획의 범위·동작 변경은 없다.

## 다음 사람이 알아야 할 것

- 기존 23 Ticket `held` Incident는 이번 변경 뒤에도 1시간 쿨다운마다 `analyzing`으로 복귀해 `budget_exceeded`를 반복할 수 있다. 기존 관계와 저장된 경로는 소급 변경하지 않는다. 현 Incident API·화면은 상태 변경 기능이 없으므로, 순환을 끊어야 하면 DB 운영자가 별도 수동 조치를 검토해야 한다.
- #326부터 새 Alert는 센서 `host.name`을 엔티티로 올리지 않는다. 과거 Alert와 Event에는 값이 남아 있고 Event는 원래 그래프 경로에 쓰지 않는다.
- `max_incident_tickets`는 새 연결에만 적용한다. 10개 이하에서도 입력 길이에 따라 `budget_exceeded`가 날 수 있다. `candidate_window_ms`의 `updated_at` 기준과 `max_candidates = 5`는 그대로다.
- 같은 type·값에 `src`와 `dst`가 함께 있으면 역할 필터를 먼저 적용해야 `dst`가 `src`를 덮지 않는다. 후보 수 한도보다 앞에서 SQL 역할 필터와 Ticket 수 상한을 적용해야 잘못된 `candidate_limit`이 생기지 않는다.

## 확인 방법

- `uv run pytest -q tests/test_l2_graph.py tests/test_l2_config.py tests/test_l2_worker.py`: 33개 통과.
- 임시 PostgreSQL 17 컨테이너에서 `-m db`로 `tests/test_l2_branch_db.py`, `tests/test_api_ui.py`, `tests/test_lab_cycle_db.py`: 40개 통과, 비-DB 6개 제외. 이후 API의 host 보존과 10번째 Ticket 연결 테스트를 각각 추가해 다시 실행했고 각각 통과했다. 기본 포트 5432는 기존 프로세스가 사용 중이어서 별도 Compose 프로젝트의 55432 포트로 실행했다. 테스트는 임시 DB만 만들고 지웠다.
- `uv run ruff format --check .`: 406개 파일 통과. `uv run ruff check .`: 통과.
- `pnpm --dir frontend test`: 86개 통과. 과거 `public_ip_only` 문구를 읽는 화면 테스트도 포함한다.
- Linux Python 3.13 컨테이너에서 `uv run pytest -q`: 2001개 통과, 별도 서비스가 필요한 마커 554개 제외. Windows의 같은 명령은 기존 `test_name_ending_in_newline_is_not_a_migration`에서 파일명 제약으로 실패해 그 지점까지 1350개 통과한 뒤 중단했다. 테스트를 건너뛰도록 바꾸지 않았다.
