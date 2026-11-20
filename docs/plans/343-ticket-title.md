---
issue: 343
date: 2026-11-19
owner: Pandyo
supersedes: []
---

# Ticket에 제목 추가: 목록·상세에서 ID 대신 사건 제목 보이기

## 목표

Ticket 계약에 필수 `title`(1~200자, 공백뿐인 값 불가)을 더하고, 모든 생성 경로(auto·scenario·l1·l3)가 채운다. 기존 행은 마이그레이션 0109가 채운다. 목록 API(`TicketItem`)와 상세(`Ticket`)가 같은 값을 돌려준다.

## 방법

1. **샘플과 테스트 먼저.** 손으로 만든 `tests/fixtures/tickets/title_cases.json`: 공백·개행·NBSP·U+3000, 목록 밖 공백(U+2003)만 있는 값, U+200B·U+0085·U+2028, 199/200/201자 경계, UTF-16에서 2칸인 글자(이모지), 빈 값·목록 안 공백뿐인 값, alert 정렬 케이스.
2. **계약.** `contracts/ticket.schema.json`에 `title` 필수(string, minLength 1, maxLength 200, pattern `[^\t\n\u000b\f\r \u00a0\u3000]`). 공백 목록(8종)은 `clean_title`과 같다. `scripts/generate_contracts.py`로 Python·TS를 다시 만든다(D-003). TS 생성물에는 pattern이 나오지 않는다.
3. **제목 규칙은 `src/soc/ticketing.py` 한 곳**(L1·L3 공통).
   - `FALLBACK_TITLE = "(제목 없음)"`.
   - 공백 목록 상수 하나(`[\t\n\v\f\r \u00a0\u3000]`)를 정규식으로만 쓴다. `str.split()`·`strip()`은 쓰지 않는다. U+2003·U+0085·U+2028까지 공백으로 봐서 계약 pattern과 어긋나기 때문이다.
   - `clean_title(text)`: 공백 목록의 연속을 한 칸으로 줄이고 앞뒤 한 칸을 뗀다. 목록 밖 글자가 없으면 폴백. 200자(코드포인트)를 넘으면 앞 199자 + `…`.
   - `ticket_title(alerts)`: 심각도 내림차순 → time 오름차순 → id 오름차순으로 첫 alert의 title에 `clean_title`을 적용한다. alert가 없으면 폴백. 현재 생성 경로는 alert 하나만 넘긴다.
   - L3: `clean_title(hunt["hypothesis"])`. LLM 출력이므로 데이터·텍스트로만 다룬다.
4. **생성 코드.** `l1/ticketing.py`의 `_LOCK_ALERT`에 title·severity·time을 더하고, `_make_ticket`이 `ticket_title([alert])`로 채우고, `_TICKET_COLUMNS`에 title을 더한다. L1 승격(`judge.py`)은 같은 `_make_ticket`을 부르고 subject가 `SELECT *` 행이라 값이 이미 있다. L3는 `l3/hunt/store.py`의 `_TICKET_COLUMNS`와 `verify.py:_ticket`.
5. **마이그레이션 `0109_ticket_title.sql`**(0100대, 실행기가 파일마다 트랜잭션). title nullable 추가 → UPDATE → NOT NULL + `CHECK (title ~ E'[^\\t\\n\\u000b\\f\\r \\u00a0\\u3000]')`(계약 pattern과 같은 목록).
   - alert 있는 행: 위 정렬 규칙으로 고른 alert의 제목에 같은 정리·자르기를 SQL로 적용한다(`regexp_replace`로 공백 목록 연속을 한 칸, `'^ | $'` 제거, `char_length` > 200이면 `left(n, 199) || '…'`).
   - L3 행: `hunts.hypothesis`에 같은 정리·자르기.
   - 가리키는 alert가 없는 행과 그 밖의 행: 폴백.
   - 파이썬과 SQL의 결과가 같은지는 같은 입력(`title_cases.json`)으로 비교하는 `db` 테스트가 지킨다.
6. **API.** `ui_models.TicketItem.title`, `ui_read.TICKET_COLUMNS`에 `t.title`. 상세(`TicketDetail`)는 계약 `Ticket`이라 자동으로 포함된다. `frontend/src/api/generated/`를 갱신한다. 화면은 따로 고친다.
7. **L2.** 코드는 바꾸지 않는다. `rows.ticket` 전체가 모델 입력에 들어가므로 `title`이 포함된다(`l2/analyze/context.py`, `l2/branch/context.py`). L2 테스트 기대값만 갱신한다.
8. **결정 기록.** D-067(확정), D-068(추후). `_make_ticket` 근처에 시나리오 규칙 주석 한 줄.

## 바꿀 곳

- `contracts/ticket.schema.json`, `src/soc/contracts/generated/ticket_schema.py`, `frontend/src/api/generated/*`
- `src/soc/ticketing.py`, `src/soc/l1/ticketing.py`, `src/soc/l3/hunt/store.py`, `src/soc/l3/hunt/verify.py`
- `src/soc/db/migrations/0109_ticket_title.sql`
- `src/soc/api/ui_models.py`, `src/soc/api/ui_read.py`
- `tests/`: 제목 규칙, 마이그레이션(db), 계약, L1·L3 생성, L2 기대값, API, 직접 INSERT 2곳(`test_ticketing_db.py:131`, `normalize/test_reprocess_db.py:122`)
- 시드·픽스처 JSON: `api/seed.json`, `api/ui_seed.json`, `l3_hunt/seed.json`, `contracts/valid·invalid/ticket.json`, `l2/*.json`, `agent/l2_classify_existing.json`, `similar/cases.json` 등 Ticket 행이 있는 것
- 프론트 테스트의 Ticket 모의 데이터(`App.test.tsx` 등)
- `docs/decisions.md`, `docs/plans/343-ticket-title.md`, `docs/notes/343-ticket-title.md`

## 다른 코드와 맞물리는 곳

공통 계약 변경이다. L1·L2·L3·UI 담당 모두 계획 확정 전에 승인했다.

- **Ticket 계약과 `tickets` 테이블**: 필수 필드와 NOT NULL 컬럼이 늘어 INSERT하는 모든 곳이 영향받는다.
- **`_make_ticket`·`_insert_ticket`**(L1, `judge.py`가 부른다)과 L3 `store.insert_ticket`.
- **L2 모델 입력**(`tickets[].title`)과 L2 테스트 기대값. L2 담당 확인 대상이다.
- **목록 API `TicketItem.title`**과 TS 생성 타입. UI 담당 확인 대상이다.

## 범위 밖

- 화면 수정(목록·상세·Incident 화면이 title을 보여 주는 것).
- 시나리오 모드의 묶음 Ticket 요약 제목(D-068로 남긴다). 생성 경로에서 alert가 2개 이상인 Ticket을 만드는 것.
- Ticket 제목은 생성 시점 값이다. alert 제목이 재처리(D-063)로 바뀌어도 따라가지 않는다.
- 유사 사례 색인 텍스트와 에이전트 읽기 권한(`soc_agent_reader`, 0007)은 바꾸지 않는다.

## 완료 기준

- [ ] `ticket.schema.json`에 title(필수, 1~200자, 위 pattern)이 있고 생성 코드가 다시 만들어졌으며 CI 계약 생성 차이 검사 통과
- [ ] title이 없거나 빈 문자열·공백 목록 안의 글자뿐인 값·201자인 Ticket을 계약 검증이 거부하는 테스트
- [ ] 계약 pattern의 공백 목록과 `clean_title`·DB CHECK의 공백 목록이 같은지 비교하는 테스트(한쪽만 바뀌어 어긋나는 것을 막는다)
- [ ] 마이그레이션 0109가 빈 DB와 기존 데이터가 있는 DB 모두에서 적용되고, 기존 Ticket의 title이 alert 제목(auto·scenario·l1) / hypothesis(l3) / 폴백(가리키는 alert가 없는 행)으로 채워지는 테스트(`db` 마커)
- [ ] 같은 입력(`title_cases.json`)으로 파이썬 `clean_title`과 SQL 백필의 결과가 같은 `db` 테스트(NBSP·U+3000·개행, 199/200/201자, 코드포인트 경계 포함). 목록 밖 공백(U+2003)만 있는 제목은 폴백이 아니라 그대로 계약·DB CHECK를 통과함을 확인
- [ ] 자르기·공백 정리·폴백 단위 테스트(`clean_title`)
- [ ] `ticket_title` 단위 테스트: 정렬은 심각도 내림차순 → time 오름차순 → id 오름차순, alert가 없으면 폴백
- [ ] 기본 모드에서 alert 하나로 만든 Ticket의 title이 그 alert 제목과 같은 테스트(L1 승격 origin=l1 포함)
- [ ] alert 제목이 빈 문자열일 때, 그리고 목록 밖 공백(U+2003)만 있을 때 `run()`이 contract_error 없이 Ticket을 만들고 같은 alert를 다시 시도하지 않는 `db` 테스트(빈 제목은 폴백, U+2003 제목은 그대로, D-059, 승격 경로 포함)
- [ ] L3가 만드는 Ticket의 title이 hypothesis를 정리·자른 값이고, hypothesis가 공백 목록뿐이면 폴백인 테스트
- [ ] `_TICKET_COLUMNS` 두 곳과 `_LOCK_ALERT`(title·severity·time)에 반영, 직접 INSERT 테스트 2곳과 시드·픽스처 JSON 수정
- [ ] 목록 API 응답(`TicketItem`)과 상세 응답에 title이 있는 테스트, 프론트 생성 타입 갱신, 프론트 Ticket 모의 데이터 보정, `pnpm lint`·`pnpm test`·`pnpm build` 통과
- [ ] L2 입력에 title이 들어가는 것을 반영한 L2 테스트 기대값 갱신
- [ ] `docs/decisions.md`에 D-067(확정)·D-068(추후)과 기록 줄, `_make_ticket` 근처 주석
- [x] L1·L2·L3·UI 담당 승인(계획 확정 전에 받음)
- [ ] 키·비밀 값이 코드, 테스트, 로그, notes, PR에 없다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run pytest -m "db or qdrant"` 통과
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록(생성 경로에서 alert 2개 이상이 나오지 않는다는 점 포함)

## 토론으로 정한 것

이슈 본문과 달라진 점:

- **다중 alert 규칙**: 이슈의 "여럿이면 심각도가 가장 높은 alert 제목"은 현재 계약·DB(auto·scenario·l1은 alert 1개, `ticket.schema.json`·0104)와 맞지 않았다. 규칙은 순수 함수 `ticket_title(alerts)`로 두고 단위 테스트하며, 생성 경로는 alert 하나로 같은 함수를 부른다. 정렬은 심각도 내림차순 → time 오름차순 → id 오름차순이다. 현재 생성 경로에서는 2개 이상이 나오지 않는다는 점을 기록에 적는다.
- **L3 Ticket 제목**: `hypothesis`를 공백·개행 정리 후 자른 값이다(Hunt에 제목 필드가 없다). LLM 출력이라 데이터·텍스트로만 다룬다.
- **길이와 자르기**: 200자(코드포인트), 넘으면 앞 199자 + `…`, 계약에 `maxLength: 200`. 공백·개행은 한 칸으로 줄인다.
- **제목을 만들 수 없을 때**: 고정 폴백 문구 `(제목 없음)`으로 통일하고 생성 코드와 백필이 같은 문구를 쓴다. 빈 제목이 `contract_error`로 같은 alert를 매번 다시 시도하는 일을 막는다(D-059).
- **공백 기준**: "공백뿐인 값 불가"의 기준은 `\S`가 아니라 명시한 공백 목록 8종이다. `\S`는 유니코드 공백 전체를 공백으로 보는데 `clean_title`은 목록의 8종만 공백으로 봐서, U+2003 같은 글자만 있는 제목이 `clean_title`을 통과하고 계약에서 거부된다. 그러면 `run()`이 같은 alert를 매번 다시 시도해 D-059 문제가 다시 생긴다. 계약 pattern·DB CHECK·`clean_title`이 같은 목록을 쓴다(사람이 정함).
- **백필**: 마이그레이션 0109 하나(nullable 추가 → UPDATE → NOT NULL + CHECK). alert가 있는 행은 규칙대로, L3 행은 `hunts.hypothesis`로, 가리키는 alert가 없는 행과 그 밖의 행은 폴백. 자르기 규칙이 파이썬과 SQL에서 같은지는 같은 입력으로 결과를 비교하는 테스트로 지킨다.
- **시나리오 규칙 기록**: D-067(확정)에는 auto·l1·l3와 "시나리오 1:1이면 alert 제목"만 적는다. "묶음 Ticket의 AI 요약 제목"은 D-068(추후)로 두고, 계약이 묶음을 먼저 허용해야 한다고 덧붙인다.
- **L2 모델 입력**: `title`이 들어가는 것을 받아들이고 L2 테스트 기대값을 갱신한다. L2 담당 승인 범위에 포함한다.
- **목록 API**: `TicketItem`에 title을 더한다(`ui_read.TICKET_COLUMNS`, 생성 TS 타입 갱신). 화면은 따로 고친다. UI 담당 확인 대상이다.
- **프론트 모의 데이터**: `title`이 필수가 되면 타입 검사가 깨지므로 모의 데이터 보정을 이번 범위에 넣는다.
- **담당자 승인**: 계획 확정 전에 받는다(#339 방식). 이슈 댓글로 "확정할 계약 변경안"을 올려 받았다.

## 확인하지 못한 것

- 개발 DB에서 가리키는 alert가 없는 기존 Ticket의 건수. 백필 전에 아래 쿼리로 센다(건수만 기록한다).
- 프론트 코드. 생성 타입과 `client.ts` 외의 Ticket 사용처, `App.test.tsx`의 모의 데이터는 읽지 않았다.
- 정규식은 임시 사본에서 생성된 Python(pydantic)·`jsonschema`·JS RegExp·PostgreSQL에서 같은 결과를 확인했다. `ajv`(설치 안 됨), 실제 `generate_contracts.py --check`, 실제 `tickets` 테이블의 CHECK는 개발 때 확인한다.

백필 전 개발 DB 확인 쿼리(읽기 전용):

```sql
-- 1) origin별 Ticket 수
SELECT origin, count(*) FROM tickets GROUP BY origin;

-- 2) 가리키는 alert가 없는 auto·scenario·l1 행 (폴백이 될 행)
SELECT count(*) FROM tickets t
WHERE t.origin <> 'l3'
  AND NOT EXISTS (SELECT 1 FROM alerts a WHERE a.id = ANY(t.alert_ids));

-- 3) alert 제목에 공백 목록 밖 글자가 없는 행 (폴백이 될 행)
SELECT count(*) FROM tickets t JOIN alerts a ON a.id = t.alert_ids[1]
WHERE t.origin <> 'l3' AND a.title !~ E'[^\\t\\n\\u000b\\f\\r \\u00a0\\u3000]';

-- 4) hypothesis에 공백 목록 밖 글자가 없는 L3 행 (폴백이 될 행)
SELECT count(*) FROM tickets t JOIN hunts h ON h.id = t.hunt_id
WHERE t.origin = 'l3' AND h.hypothesis !~ E'[^\\t\\n\\u000b\\f\\r \\u00a0\\u3000]';
```

## 바뀐 점

- 2026-11-20 · 계약 pattern을 `[^S]`에서 같은 뜻의 `^[S]*[^S][\s\S]*$`(S는 공백 8종)로 바꿨다. 기존 테스트 `test_schema_patterns_are_anchored_at_both_ends`가 모든 계약 pattern의 앞뒤 고정을 요구하기 때문이다. 이 계획의 pattern 표기와 D-067도 같은 모양으로 맞췄다(사람이 정함).
