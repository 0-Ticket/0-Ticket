---
issue: 277
date: 2026-11-11
owner: uptime-zero
plan: 277-raw-original-text.md
supersedes: []
---

# RawRecord 원본을 JSON 글자로 보관하기

## 한 일

- 수집 원본을 `jsonb` 대신 `original_text text`로 보관하도록 변경한다.
- `json.dumps(ensure_ascii=True)`와 `json.loads`로 NUL·짝 없는 서로게이트를 포함한 입력을 왕복한다.
- 정규화 결과와 원본 상세 API·화면이 확정 계획의 저장 규칙을 따르도록 맞춘다.

## 계획과 달라진 점

없음. 원본 상세의 필드 표는 RawRecord 메타데이터를 유지하고, `원본 JSON` 보기에서
`original_text`를 JSON 문자열로 다시 감싸지 않고 그대로 표시하도록 `JsonViewer`에 선택 인자를
추가했다.

## 다음 사람이 알아야 할 것

- 사용자는 `raw_records`가 비어 있다고 확인했다. 이 실행에서는 해당 DB에 접속하지 않았다.
  `0106` 적용 전에 `SELECT count(*) FROM raw_records;`로 다시 확인한다. 마이그레이션도 행이
  남아 있으면 스스로 중단한다.
- 이슈 #294의 격리·재시도 정책은 이 변경 뒤 별도 계획으로 진행한다.
- 화면 검사는 Vitest와 Vite 빌드로 했으며 브라우저에서 수동 확인하지 않았다. 로컬 Node는
  25.8.1이었고, 레포의 고정 버전(Node 22.22.3)과 다르다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과.
- `uv run pytest`: 1,476 통과. 기존 `FakeSshServer`의 pending-task 종료 경고가 있었고 종료 코드는 0.
- `uv run pytest -m db`: 격리된 임시 PostgreSQL 17.6에서 428 통과. `0106`이 빈 `raw_records`에서는
  적용되고 기존 행과 진행 중인 insert가 있으면 중단하는지 확인했다.
- Python 계약 생성 `--check`: 통과.
- `pnpm lint`, `pnpm test`(80건), `pnpm build`, `pnpm contracts:check`: 통과. ESLint의 기존
  Fast Refresh 경고와 Vite의 큰 JS 청크 경고가 남았다.
- `git diff --check`: 통과.
