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

## 후속 이슈 초안 (아직 등록하지 않음)

아래를 GitHub 이슈로 옮겨 등록한다. 등록 전에 사람이 확인한다.

```
제목: fix(normalize): 깨진 원본 한 건이 claim 배치 전체를 멈추지 않게 한다

## 무엇을
- normalize claim에서 original_text를 행마다 파싱한다.
- 파싱에 실패한 행은 invalid_original 실패로 그 행만 기록하고, 같은 배치의 나머지 행은 계속 처리한다.

## 왜
- #277 이후 raw_records 원본은 text로 저장된다. claim의 json.loads는 run()의 try 바깥에 있어서,
  깨진 값 하나가 있으면 예외가 run()까지 올라가 배치 전체가 멈추고 임대가 lease 시간 동안 잡힌다.
- 같은 행이 다시 잡히면 실행마다 반복된다(#294가 없애려는 뺑뺑이와 같은 모양).
- 트리거는 DB를 수동으로 고친 경우뿐이다. 그래서 이번 PR 범위 밖으로 두었다.

## 어떻게
- src/soc/normalize/store.py의 _claim_batch에서 행마다 json.loads를 try로 감싼다.
- 실패한 행은 save_failure(conn, owner, raw_id, "invalid_original")로 기록하고 반환 목록에서 뺀다.
- error_code에 CHECK가 없으므로 마이그레이션은 필요 없다(확인 필요: 실제 제약 재확인).

## 완료 기준
- [ ] original_text가 깨진 행을 DB 테스트에서 직접 넣어 재현하고, 같은 배치의 정상 행이 succeeded가 된다
- [ ] 깨진 행은 failed(invalid_original)가 되고 다음 실행에서 다시 잡히지 않는다
- [ ] uv run ruff format --check ., uv run ruff check ., uv run pytest 통과, uv run pytest -m db 통과
- [ ] docs/notes/277-raw-original-text.md의 한계 1을 해결됨으로 갱신하는 새 기록을 남긴다(지난 기록은 고치지 않는다)

## 함께 반영할 이슈
- #277 (원본 저장 형식)
```

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과.
- `uv run pytest`: 1,476 통과. 기존 `FakeSshServer`의 pending-task 종료 경고가 있었고 종료 코드는 0.
- `uv run pytest -m db`: 격리된 임시 PostgreSQL 17.6에서 428 통과. `0106`이 빈 `raw_records`에서는
  적용되고 기존 행과 진행 중인 insert가 있으면 중단하는지 확인했다.
- Python 계약 생성 `--check`: 통과.
- `pnpm lint`, `pnpm test`(80건), `pnpm build`, `pnpm contracts:check`: 통과. ESLint의 기존
  Fast Refresh 경고와 Vite의 큰 JS 청크 경고가 남았다.
- `git diff --check`: 통과.

## 리뷰 반영

리뷰에서 나온 지적 네 건을 고쳤다. 이전 절은 고치지 않았다. 이전 절의 "확인 방법" 결과는 리뷰 반영 전 기준이다.

- **F1 `siem_ref` 키 불일치**: 수집이 저장하는 `siem_ref`와 `link_by_refs`가 찾는 키가 달랐다. 이제 `soc.ids.siem_ref_key`(JSON 이스케이프, 따옴표 제외) 한 곳에서 만든다. 보통 ID는 값이 같고, 따옴표·백슬래시·제어문자·한글 ID만 바뀐다.
  - 함정: `link_by_refs(conn, profile, pairs)`의 `pairs`는 **원래 형태** `<_index>/<_id>`를 받는다. 저장 키를 넘기면 이중 이스케이프되어 원본을 찾지 못하고 영원히 보류된다. 보류 목록도 받은 원래 형태로 돌아온다.
  - 아직 열린 결정: SIEM 도구(`src/soc/tools/siem.py`)의 결과 `siem_ref`는 원래 형태 그대로다. 저장 키로 바꿀지 사람이 정하기 전에는 건드리지 않았다. 결정이 나면 `docs/decisions.md` D-049 뒤에 기록을 한 줄 더한다.
- **F5 NUL·서로게이트 치환 규칙**: 정규화 `escape_unstorable`의 NUL과 짝 없는 서로게이트를 정규식 하나와 치환 함수 하나로 합쳤다. 수집 쪽 `json.dumps` 이스케이프와 글자 모양이 같다(`json.dumps(ch)[1:-1]`). 한글·백슬래시·따옴표·원래 글자 `\u0000`은 바뀌지 않는다. 동작은 바뀌지 않는다.
- **F6 롤백·재개 테스트**: 옛 NUL 샘플로 하던 거부·롤백 검증이 사라져 있었다. NUL 문서는 이제 정상 저장되므로, 같은 페이지의 원본 INSERT를 트리거로 실패시키는 테스트(`test_db_error_on_page_rolls_back_and_next_run_resumes`)를 더했다. 실패 종류는 `db_error`다. `contract_rejected` 경로는 단위 테스트가 본다. hit 데이터만으로는 계약 위반을 만들 수 없다(`elk._read_page`가 먼저 막는다).
- **F7 시드가 든 개발 DB에서 0106 실패**: 0106은 `raw_records`가 비어 있을 때만 적용된다. RAISE 문구에 이 절차를 가리키도록 했다. 마이그레이션은 데이터를 지우지 않는다.

### 개발 DB에 0106 적용

개발 DB에 시드(`soc.agent.dev_l1`, `soc.l3 dev-seed`, `soc.api.dev_seed`)가 들어 있으면 0106이 "raw_records에 행이 있어" 멈춘다. 두 방법 중 하나를 고른다.

1. **권장: 개발 DB를 새로 만든다.** 개발 PostgreSQL의 모든 데이터가 지워진다. Qdrant 볼륨은 그대로 둔다.
   ```bash
   docker compose stop postgres
   docker compose rm -f postgres
   docker volume ls                                  # 이름을 확인한다(이 레포의 프로젝트 이름은 zero-ticket-soc)
   docker volume rm zero-ticket-soc_postgres-data    # 위에서 확인한 PostgreSQL 데이터 볼륨 이름
   docker compose up -d
   uv run python -m soc.db.migrate
   # 필요한 시드를 다시 넣는다
   ```
2. **남길 데이터가 있을 때만: 수동 SQL.** 개발 DB에서만, 한 트랜잭션으로 실행한다. 외래 키 순서는 `raw_links`와 `normalize_status`가 `raw_records`를, `alerts`와 `events`가 `raw_records`를 가리키므로 아래 순서다(0001·0102·0103 기준). `alerts`·`events`를 가리키는 티켓 같은 테이블은 외래 키가 없어 끊긴 참조로 남는다. 정리는 개발자가 한다.
   ```sql
   DELETE FROM raw_links;
   DELETE FROM normalize_status;
   DELETE FROM alerts;
   DELETE FROM events;
   DELETE FROM raw_records;
   ```
   `uv run python -m soc.db.migrate`를 다시 실행한다. `soc.agent.dev_l1 remove`와 `soc.l3 dev-seed --remove`는 `raw_links`·`normalize_status`를 지우지 않아 외래 키에 걸릴 수 있으므로 이 절차 대신 쓰지 않는다.
3. 확인: `SELECT count(*) FROM raw_records;`가 0이어야 한다.

주의: 이 브랜치의 0106 파일 내용을 바꿨으므로(RAISE 문구), 이전 문구의 0106을 이미 적용한 DB는 `이미 적용한 파일의 내용이 기록과 다르다`로 멈춘다(`src/soc/db/migrate.py`는 체크섬을 비교한다). 이런 DB는 1번으로 새로 만든다.

## 결정 반영 (2차)

사람이 아래 네 가지를 정했다. 계획 파일(`docs/plans/277-raw-original-text.md`)은 바꾸지 않았고, 앞 절의 기록도 고쳐 쓰지 않았다.

- **D1 에이전트에게 보이는 siem_ref는 저장 키다.** `query_siem`의 `siem_ref`를 `siem_ref_key("<_index>/<_id>")`로 만든다. 그래서 에이전트가 받은 값은 `raw_records.siem_ref`와 글자가 같다. 따옴표·백슬래시·제어문자·한글 `_id`로 왕복하는 테스트를 더했다. 이스케이프할 글자가 없는 값은 예전과 같다. 커밋 `aca7a6d`.
- **D2 두 형태를 타입으로 구분한다.** `soc.ids.SiemRefKey`(NewType)를 더했고 `siem_ref_key`가 이 타입을 돌려준다. `link_by_refs`는 저장 키 쌍만 받고 안에서 이스케이프하지 않는다. 보류 쌍도 받은 저장 키 그대로 돌려준다. 원래 형태를 넘기면 찾지 못한다는 DB 테스트와, DB 없이 조회 키 글자만 보는 단위 테스트(`tests/ingest/unit/test_link_keys.py`)를 더했다. 이 저장소의 `link_by_refs` 호출부는 테스트뿐이라 테스트만 고쳤다. 커밋 `50c0e7c`.
- **D3 키 충돌은 실패로 기록한다.** `escape_unstorable`이 한 dict 안에서 이스케이프 뒤 같은 키를 만들면 `EscapeCollisionError`를 낸다. `NormalizeError`의 하위 클래스이고 코드는 `escape_collision`이다. `FAILURES`에 `escape_collision`을 더했다. `_run_batch`의 except 튜플은 이미 `NormalizeError`를 받으므로 바꾸지 않았다. `_failure_code`는 `error.code`를 그대로 쓴다. 마이그레이션은 없다. `normalize_status.error_code`에는 CHECK가 없다(`0103_normalize_status.sql` 확인). 커밋 `9c5c4fc`.
- **D4 그대로.** `_index`/`_id` 나누기와 `_raw_record`의 직렬화는 바꾸지 않았다. `siem_ref_key` 독스트링에 "키를 `/`로 나누어 되돌리지 않는다"는 문장만 더했다. 커밋 `aca7a6d`.

계약 설명(`contracts/raw_record.schema.json`)은 저장 키 형태라고 고쳤고, 생성 파일(Python, 프론트 `frontend/src/api/generated/`)은 생성기로 다시 만들었다. 커밋 `52506a5`.

### 알려진 한계

- `link_by_refs`에 원래 형태 ref가 NUL 문자를 담고 넘어오면, DB 조회 전에 psycopg가 `DataError`를 낸다(텍스트 파라미터에 NUL을 넣을 수 없다). 저장 키를 넘기면 생기지 않는다. 호출하는 쪽이 저장 키를 넘기는 것으로 막는다. 이 절에서는 고치지 않았다.
