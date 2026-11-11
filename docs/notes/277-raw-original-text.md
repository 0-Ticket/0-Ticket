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

## 알려진 한계 (문서화만, 코드는 바꾸지 않음)

1. **깨진 `original_text`를 claim에서 읽으면 배치가 멈춘다.**
   - 위치: `src/soc/normalize/store.py`의 `_claim_batch`가 `json.loads`를 호출한다. 이 호출은 `_run_batch`의 `try` 바깥에 있어 `run()`이 예외로 끝난다.
   - 임대는 이미 잡혀 있으므로 `lease_seconds` 동안 배치가 `pending`에 남고, 같은 행이 다시 잡히면 반복된다.
   - 트리거: 저장 경로(`json.dumps`)에서는 생기지 않는다. DB를 수동으로 고친 경우에만 생기며, DB 검사는 첫 글자 `{`만 본다.
   - 후속: 행마다 파싱하고 실패하면 `invalid_original`로 그 행만 실패 기록. `error_code`에 CHECK가 없어 마이그레이션은 필요 없다.

2. **정규화 결과의 NUL·서로게이트 치환은 구별되지 않는다.**
   - 위치: `src/soc/normalize/run.py`의 `escape_unstorable`.
   - 결과 값만 보면 원래 `\u0000` 글자와 치환된 NUL이 같다. 원본 `original_text`에서는 백슬래시가 `\\`로 쓰이므로 구별된다.
   - 딕셔너리 키가 NUL 또는 서로게이트 한 글자 차이로만 다르면 치환 뒤 같은 키가 되고, 뒤의 값이 앞의 값을 조용히 덮어쓴다. 원본은 온전하므로 `original_text`에서 복구할 수 있다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과.
- `uv run pytest`: 1,476 통과. 기존 `FakeSshServer`의 pending-task 종료 경고가 있었고 종료 코드는 0.
- `uv run pytest -m db`: 격리된 임시 PostgreSQL 17.6에서 428 통과. `0106`이 빈 `raw_records`에서는
  적용되고 기존 행과 진행 중인 insert가 있으면 중단하는지 확인했다.
- Python 계약 생성 `--check`: 통과.
- `pnpm lint`, `pnpm test`(80건), `pnpm build`, `pnpm contracts:check`: 통과. ESLint의 기존
  Fast Refresh 경고와 Vite의 큰 JS 청크 경고가 남았다.
- `git diff --check`: 통과.
