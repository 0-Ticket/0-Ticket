---
issue: 226
date: 2026-11-05
owner: Juhyeok0603
plan: 226-l2-branch.md
supersedes: []
---

# Ticket 분류 문맥과 Incident 후보를 읽기 전용으로 만들었다

## 한 일

- `soc.l2.config`가 기본 TOML 위에 로컬 TOML을 덮어쓰고 `[l2]`만 읽으며, `[l2.branch]` 값을 frozen `BranchSettings`로 검증한다.
- `soc.l2.branch.read`가 `escalated` Ticket, `alert_ids`의 Alert, L3 Hunt, Ticket·Hunt의 실제 근거, 시간 창 안의 열린 Incident를 읽는다. Event는 실제 `evt_` 근거로만 읽고 없는 근거는 개수만 남긴다.
- DB와 분리한 순수 함수가 Ticket·Hunt·Incident 엔티티를 type별로 정규화해 강한·보조·공용 등급을 매기고, `(강한 겹침 수, 보조 겹침 수, updated_at)` 내림차순으로 후보를 만든다.
- 공개 진입점 `build_branch()`는 문맥과 상위 후보를 frozen dataclass로 돌려준다. DB에는 쓰지 않고 에이전트도 부르지 않는다.
- 손으로 만든 L2 샘플로 일반 Ticket, `origin = l3` Ticket, 존재·누락 근거, 공용 신호, 종결 상태와 시간 창 밖 Incident를 확인한다.

## 계획과 달라진 점

- 목표·범위·완료 기준은 달라지지 않았다.
- 설정의 강한·보조 목록은 겹침뿐 아니라 두 목록의 합이 Entity type 전체인지도 확인한다. 빠진 type은 세 등급 중 어느 것도 될 수 없으므로 설정 오류로 멈춘다. 삭제하기로 한 `shared_frequency_threshold`를 포함한 예상 밖 키도 받지 않는다.
- PostgreSQL의 `status = ANY(%s)`에는 상태 목록을 Python `list`로 전달한다. `tuple`은 psycopg가 배열이 아니라 레코드로 보내 `malformed array literal`이 났고, DB 테스트를 먼저 실패시킨 뒤 고쳤다.

## 다음 사람이 알아야 할 것

- `user` 값은 AD·Windows 계정이 대소문자를 구분하지 않는 경우가 더 흔해 소문자로 비교한다. Linux에서는 대소문자가 다른 계정을 잘못 합칠 수 있지만, 분류는 확정 판정이 아니라 복구 가능한 묶기라 이 기준을 택했다.
- 공용 설정 값은 Entity type별 정규화 뒤 비교한다. 같은 문자열이라도 URL·process는 대소문자를 보존한다.
- L2-A-2는 `build_branch()`의 `BranchResult.context`와 `BranchResult.candidates`를 에이전트 입력으로 직렬화하면 된다. 이번 코드에는 직렬화나 분류 출력 계약이 없다.
- DB 인증 자체가 실패하면 psycopg의 `OperationalError`가 연결 문자열을 펼쳐 쓸 수 있어 `tests/conftest.py`의 `HiddenUrl`만으로 비밀번호가 가려지지 않는다. 이번 범위에서는 공통 테스트 장치를 바꾸지 않았고, 별도 이슈에서 보완해야 한다. 그 전에는 실패 가능성이 있는 DB 주소를 출력되는 테스트에 넣지 않는다.
- Windows에서는 기존 `test_name_ending_in_newline_is_not_a_migration`이 OS가 줄바꿈 파일명을 만들지 못해 실패하고, 닫힌 포트 연결 테스트가 오래 대기했다. 테스트를 삭제·skip하지 않고 Linux Python 3.13 컨테이너에서 기본 검사 전체를 확인했다.

## 확인 방법

- 테스트를 먼저 쓰고 구현 전에 실행: `soc.l2`가 없어 일반 테스트 2개가 수집 단계에서 실패
- `uv run pytest tests/test_l2_config.py tests/test_l2_branch.py`: 18개 통과
- 일회성 `postgres:17.6`에서 `uv run pytest -m db tests/test_l2_branch_db.py`: 4개 통과
- 같은 DB에서 `uv run pytest -m db`: 118개 통과, 526개 제외
- 읽기 전용으로 마운트한 Linux Python 3.13 컨테이너에서 `uv run pytest`: 526개 통과, 118개 제외
- `uv run ruff format --check .`: 112개 파일 통과
- `uv run ruff check .`: 통과
- 주요 테스트: `test_context_keeps_confirmed_data_and_normalized_signals`, `test_l3_context_uses_hunt_evidence_and_entities_without_duplicates`, `test_candidates_rank_by_strong_weak_then_updated_at`, `test_reads_ticket_evidence_and_only_open_recent_incidents`, `test_open_incident_query_uses_status_index`
