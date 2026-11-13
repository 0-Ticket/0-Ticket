---
issue: 277
date: 2026-11-11
owner: uptime-zero
supersedes: [218-elk-rawrecord.md]   # `original`을 jsonb로 저장하던 부분만 바꾼다
---

# RawRecord 원본을 JSON 글자(text)로 보관하기

## 목표

NUL(`\u0000`)이나 짝 없는 서로게이트가 든 ELK 문서가 와도 수집 페이지가 실패하지 않고, 원본은 SIEM이 준 JSON 그대로 되살릴 수 있게 보관된다. 정규화 결과에는 NUL·서로게이트가 남지 않고, 원본 상세 API는 저장한 글자를 그대로 돌려준다.

## 방법

PostgreSQL `jsonb`는 `\u0000`을 받지 않아, NUL이 든 문서 하나가 페이지 저장 전체를 실패시킨다. 원본을 `jsonb` 대신 이스케이프된 JSON 글자(`text`)로 보관하고, 읽는 쪽에서 `json.loads`로 되살린다.

1. **마이그레이션 `0106`** (수집·정규화 대역 0100~0199에서 0105 다음 빈 번호)
   - 먼저 `SELECT count(*) FROM raw_records`가 0인지 확인하고, 0이 아니면 예외로 멈춘다.
   - `raw_records.original`(jsonb, `CHECK jsonb_typeof(original) = 'object'`)을 지우고 `original_text text NOT NULL`과 `CHECK (left(original_text, 1) = '{')`를 더한다.
   - `0003_agent_reader.sql`은 바꾸지 않는다(`raw_records`에 권한을 주지 않는다).
2. **계약**: `contracts/raw_record.schema.json`의 `original`(object)을 `original_text`(string)로 바꾸고, `scripts/generate_contracts.py`로 `src/soc/contracts/generated/raw_record_schema.py`를 다시 만든다(생성 코드는 손으로 고치지 않는다, D-003).
3. **수집**
   - `original_text`는 `json.dumps(hit, ensure_ascii=True)`로 만든다. ASCII만 남아 NUL·서로게이트가 `\u0000`·`\udXXX` 이스케이프 글자로 들어간다.
   - `siem_ref`는 `<_index>/<_id>`를 JSON 문자열 이스케이프한 형태에서 양쪽 따옴표를 뺀 값(`json.dumps(f"{_index}/{_id}")[1:-1]`)이다. 유일 제약은 이 값에 건다. NUL 등이 없는 보통 문서는 지금과 같은 값이다.
4. **정규화**
   - `claim_pending_batch`·`claim_failed_batch`가 `original_text`를 읽어 `json.loads`로 `RawRow.original`(dict)에 넣는다. 매핑 코드는 지금처럼 dict를 받는다.
   - `_normalize_and_save`에서 `validate_ocsf`·`validate_contract` 전에 `mapped.row`의 모든 문자열 값과 dict 키를 재귀로 치환한다: NUL → `\u0000`(6글자), 짝 없는 서로게이트 → `\udXXX`(6글자). `mapping.py`는 바꾸지 않는다.
5. **API·화면**: `raw_detail`과 응답 모델은 `original_text`를 저장된 글자 그대로 돌려준다(파싱하지 않는다). 화면은 텍스트로만 표시한다(`textContent`, HTML 렌더링 금지).
6. **개발 시드**: `original`을 쓰던 시드를 `original_text`로 맞춘다.

테스트 먼저: `tests/fixtures/ingest/`에 손으로 만든 샘플(NUL 문서, 짝 없는 서로게이트 문서, 백슬래시 문서, 보통 문서)을 두고 테스트를 먼저 쓴다.

## 확정된 결정

| 항목 | 정한 것 |
|---|---|
| 원본 저장 형식 | `raw_records.original_text text NOT NULL`, `CHECK (left(original_text, 1) = '{')`. `original`(jsonb) 삭제 |
| 이스케이프 | `json.dumps(hit, ensure_ascii=True)` |
| 마이그레이션 번호 | `0106` |
| 마이그레이션 전제 | `raw_records`가 비어 있어야 한다. 아니면 멈춘다 |
| 계약 필드 | `original`(object) → `original_text`(string) |
| `siem_ref` | `json.dumps(f"{_index}/{_id}")[1:-1]`, 유일 제약은 이 값에 |
| 정규화 치환 | `_normalize_and_save`에서 문자열 값과 dict 키 모두, NUL → `\u0000`, 짝 없는 서로게이트 → `\udXXX`(각 6글자) |
| `mapping.py` | 바꾸지 않는다 |
| 원본 상세 API | 저장된 글자 그대로, 파싱 없음. 화면은 텍스트로만 |
| `0003_agent_reader.sql` | 바꾸지 않는다 |

결정 목록에 원본 보관 형식(D-049)으로 올렸다.

## 바꿀 곳

- `src/soc/db/migrations/0106_raw_original_text.sql`: 빈 테이블 확인, `original` 삭제, `original_text`와 CHECK 추가
- `contracts/raw_record.schema.json`: `original` → `original_text`(string)
- `src/soc/contracts/generated/raw_record_schema.py`: `scripts/generate_contracts.py`로 다시 생성
- `src/soc/ingest/store.py`: `save_page`가 `original_text`를 저장
- `src/soc/ingest/run.py`: `_raw_record`가 `original_text`와 이스케이프한 `siem_ref`를 만든다
- `src/soc/normalize/store.py`: `claim_pending_batch`·`claim_failed_batch`가 `original_text`를 읽어 `json.loads`
- `src/soc/normalize/run.py`: `_normalize_and_save`에서 검증 전에 NUL·서로게이트 재귀 치환(값과 키)
- `src/soc/api/ui_read.py`: `raw_detail`과 응답 모델이 `original_text`를 그대로 돌려준다
- 화면의 원본 상세 표시: `original_text`를 텍스트로만 표시(생성된 API 타입이 바뀌면 함께 맞춘다)
- `src/soc/agent/dev_l1.py`, `src/soc/l3/hunt/dev_seed.py`, `src/soc/api/dev_seed.py`: `original_text`로 맞춘다
- `tests/fixtures/ingest/`: NUL·서로게이트·백슬래시·보통 문서 샘플
- `tests/`: 왕복, 정규화 치환, 페이지 저장, 원본 상세 테스트

## 다른 코드와 맞물리는 곳

- **테이블**: `raw_records.original`(jsonb)이 사라지고 `original_text`(text)가 생긴다. 이 열을 읽는 코드(정규화, 원본 상세 API, 개발 시드)는 이번에 모두 맞춘다.
- **데이터 계약**: RawRecord 계약의 `original` → `original_text`. 생성 코드와 API 응답 타입이 바뀐다.
- **API 응답**: 원본 상세 응답이 객체 대신 JSON 글자를 돌려준다. 화면이 이를 텍스트로 표시한다.
- **`siem_ref`**: NUL 등 이스케이프가 필요한 글자가 든 `_index`·`_id`만 값이 달라진다. 보통 문서는 같다.
- `RawRow.original`(dict)과 `mapping.py`의 입력 모양은 바뀌지 않는다.

## 범위 밖

- 이미 쌓인 `raw_records`를 옮기는 데이터 이전. 테이블이 비어 있지 않으면 마이그레이션이 멈춘다.
- `mapping.py` 수정.
- 정규화 결과 외의 곳(Agent Log 등)의 NUL 처리.

## 완료 기준

- [ ] NUL, 짝 없는 서로게이트, 백슬래시가 든 문서가 `original_text`로 저장된 뒤 `json.loads`로 원래 hit와 같게 되살아난다(왕복 테스트)
- [ ] 정규화 결과에 NUL·짝 없는 서로게이트가 값과 키 어디에도 남지 않는다
- [ ] NUL 문서가 든 페이지가 실패 없이 저장된다
- [ ] NUL 때문에 정규화가 `failed`가 되는 줄이 없다
- [ ] 원본 상세 API가 저장된 글자를 바꾸지 않고 돌려주고, 화면은 HTML로 렌더링하지 않는다
- [ ] 마이그레이션 전제(빈 `raw_records`)와 확인 방법을 `docs/notes/277-raw-original-text.md`에 적는다
- [ ] 샘플은 `tests/fixtures/ingest/`에 손으로 만든 것이다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`가 통과하고, DB 테스트는 `-m db`로 통과한다

## 토론으로 정한 것

이슈 본문은 토론 중에 고쳐졌다. 처음 본문과 달라진 점:

- 정규화 치환 대상을 문자열 값만에서 **dict 키까지**로 넓혔다. 키에 NUL이 든 문서도 검증·저장에서 실패하지 않게 하기 위해서다.
- 계약 필드 이름을 `original_text`로 정했다(글자로 보관한다는 것이 이름에 보이게).
- 첫 글자 검사를 `jsonb_typeof` CHECK 대신 `CHECK (left(original_text, 1) = '{')`로 바꿨다. text 열에는 `jsonb_typeof`를 쓸 수 없고, `ensure_ascii` 직렬화의 객체는 항상 `{`로 시작한다.

`docs/plans/218-elk-rawrecord.md`는 고치지 않는다(기록은 쌓는다). 그 계획의 "변경하지 않은 `original`"은 이 계획의 `original_text`로 바뀐다.

### 정하지 못함

없음. 키에 NUL이 든 매핑 키는 재귀 치환으로 처리되므로 실험 환경(랩) 확인 없이 테스트 샘플로 확인한다.

## 바뀐 점

리뷰 지적 4건 반영(F1·F5·F6·F7). 결정은 사용자가 정한 것만 적는다.

- **F1 키 형태**: `soc.ids.siem_ref_key(ref)`가 `<_index>/<_id>`를 JSON 문자열 이스케이프(ensure_ascii)하고 양쪽 따옴표를 뺀다. 수집 저장(`run._raw_record`)과 `store.link_by_refs`가 이 함수만 쓴다. `link_by_refs`의 입력 `pairs`는 **원래 형태** ref이고, 보류 목록도 받은 그대로 돌려준다. 계약 `raw_record.siem_ref`의 설명을 저장 키 기준으로 고쳤다.
- **F1 도구 출력(결정 1 대기)**: `tools/siem.py`의 `siem_ref`(원래 형태)는 아직 바꾸지 않았다. 사용자가 저장 키 또는 원래 형태를 정하기 전까지 도구 출력은 그대로다.
- **F6 거부 방식(결정 2)**: 계약 위반은 hit 데이터만으로 만들 수 없어 롤백 테스트는 `raw_records` INSERT 트리거로 DB 오류(`db_error`)를 낸다. `contract_rejected` 경로는 단위 테스트가 계속 맡는다.
- **F5**: `escape_unstorable`의 NUL과 서로게이트를 정규식 하나와 치환 함수 하나로 합쳤다. 동작은 바뀌지 않는다. 정규화 값은 수집 키와 같은 규칙을 쓰지 않는다(백슬래시·한글은 그대로).
- **F7**: 0106의 RAISE 문구에 개발 DB 해결 절차(`docs/notes/277-raw-original-text.md` "개발 DB에 0106 적용")를 가리키도록 했다. 마이그레이션은 데이터를 지우지 않는다.
