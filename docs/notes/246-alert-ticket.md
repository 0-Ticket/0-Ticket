---
issue: 246
date: 2026-11-05
owner: uptime-zero
plan: 246-alert-ticket.md
supersedes: []
---

# Ticket 정책으로 정규화 Alert를 분기한다

## 한 일

W02의 성공 결과 위치를 통해 Alert만 읽고, 현재 정책에 따라 Ticket을 만들거나 `triage=pending`으로 저장하는 단발 실행기를 추가했다.
정책은 TOML 기본·로컬 설정을 읽고, PostgreSQL 활성 정책 행이 있으면 이를 우선한다. 정책 API는 조회와 전체 교체를 제공한다.
`auto`·`scenario`·`l1` Ticket은 Alert 하나만 가리키도록 계약과 DB 제약을 추가했다. L3 Ticket은 기존 동작을 유지한다.

## 계획과 달라진 점

- 사용자는 정책 API를 앱에 연결하되 인증·인가는 후속 구현으로 미루도록 정했다. W04의 정책 경로에는 현재 접근 제어가 없다.
- API 요청 본문 오류는 입력값을 노출하지 않도록 `invalid_body`와 허용된 필드 이름만 반환한다.

## 다음 사람이 알아야 할 것

- D-020 인증·인가가 구현되기 전까지 정책 API에 접근 가능한 클라이언트는 활성 Ticket 정책을 바꿀 수 있다. 기본 API 바인딩은 `127.0.0.1`이지만 `[api].host`로 변경할 수 있다.
- 마이그레이션은 기존 `auto`·`scenario`·`l1` Ticket 중 Alert가 하나가 아니거나 Alert ID가 중복된 행이 있으면 명확한 오류로 중단하며 데이터를 자동 수정하지 않는다.
- 조건부 `maxItems`는 JSON Schema 검사에서 적용된다. 저장 전 `validate_contract("ticket", ...)`를 통과시켜야 한다. 생성 Pydantic 모델만 직접 검사하면 이 조건을 적용하지 않는다.

## 확인 방법

- `uv run python scripts/generate_contracts.py`: 생성 코드 갱신 성공.
- `uv run ruff format --check .`: 227개 파일 포맷 확인 통과.
- `uv run ruff check .`: 통과.
- `git diff --check`: 통과.
- `uv run pytest`: 1,135 passed, 313 deselected.
- `uv run pytest -m db`: 309 passed, 1,139 deselected. PostgreSQL 17.6 임시 컨테이너를 사용했다.
- DB 테스트에는 fixture 기반 정책 API, 단발 실행기, 분기·재시도·동시 실행, 마이그레이션 검증을 포함했다.
- 기본 테스트는 성공했지만 기존 Fake SSH 테스트 종료 시 `Task was destroyed but it is pending!` 경고가 출력됐다.
