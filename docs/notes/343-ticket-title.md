---
issue: 343
date: 2026-11-20
owner: Pandyo
plan: 343-ticket-title.md
supersedes: []
---

# Ticket에 제목을 더하고 모든 생성 경로와 기존 행이 채운다

## 한 일

Ticket 계약에 필수 `title`(1~200자, 공백뿐인 값 불가)을 더했고 `tickets.title`(NOT NULL)을 마이그레이션 `0109`로 만들었다. 제목 규칙은 `src/soc/ticketing.py`의 `clean_title`·`ticket_title` 한 곳이다. auto·scenario·l1 Ticket은 소속 alert의 제목(`_make_ticket`, 승격 경로 `judge.py`도 같은 함수), l3 Ticket은 Hunt의 `hypothesis`(`verify.py:_ticket`)를 쓴다. 공백 연속은 한 칸으로 줄이고, 200자를 넘으면 199자 + `…`이며, 만들 수 없으면 `(제목 없음)`이다. 기존 행은 `0109`가 같은 규칙으로 채운다. 목록 API `TicketItem`에도 `title`이 있다.

## 계획과 달라진 점

- **계약 pattern이 앞뒤를 고정한 모양이다.** 계획과 D-067은 `[^\t\n\u000b\f\r  　]`(고정하지 않음)로 적었다. 그러나 기존 테스트 `test_contracts.py::test_schema_patterns_are_anchored_at_both_ends`가 모든 계약 pattern이 `^`로 시작하고 `$`로 끝나기를 요구한다(`validate_contract`가 끝의 `$`를 `\Z`로 바꾸기 때문). 테스트를 풀지 않으려고 의미가 같은 `^[S]*[^S][\s\S]*$`(S는 공백 8종)로 썼다. "공백 목록 밖 글자가 하나 이상"이라는 뜻은 그대로다. 같은 입력으로 만든 BMP 전체 비교 테스트(`test_contract_pattern_uses_the_same_spaces_as_clean_title`)가 두 정규식(계약, DB CHECK)과 `TITLE_SPACES`가 같은 8종을 공백으로 보는지 지킨다. **D-067 본문에는 고정하지 않은 모양이 적혀 있다. 사람이 D-067의 pattern 표기를 고칠지 정해야 한다.**
- DB CHECK는 고정하지 않은 `title ~ E'[^…]'`다. PostgreSQL `~`는 검색이라 뜻이 같고, 값이 계약 pattern과 일치하는지는 위 테스트와 `test_title_check_and_clean_title_use_the_same_spaces`가 지킨다.
- **L2 테스트 기대값은 고칠 것이 없었다.** L2 테스트는 입력을 Ticket 행에서 만들어서, 픽스처에 `title`만 넣으면 그대로 통과했다. 대신 `test_alert_promotion_then_ticket_decision_reaches_l2`에 `branch.ticket["title"]`(L2가 읽는 Ticket, 곧 모델 입력)이 alert 제목과 같다는 확인을 더했다.
- **화면 코드는 바꾸지 않았다.** 목록 화면은 이미 `itemTitle(item)`(`api/client.ts`)이 `title`이 있으면 그것을 보여 주도록 되어 있어서, API가 `title`을 주자 ID 대신 제목이 보인다. 그래서 `App.test.tsx`의 L3 Ticket 테스트가 `/tkt_/`로 행을 찾던 것을 `ticket.title`로 고쳤다(계획의 "프론트 모의 데이터 보정"에 해당).

## 다음 사람이 알아야 할 것

- **공백 목록 8종**(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)이 네 곳에 있다: `soc.ticketing.TITLE_SPACES`, 계약 pattern, `0109`의 SQL 두 곳(정리·CHECK). 한쪽만 고치면 안 된다. 어긋나면 `clean_title`을 통과한 제목을 계약이 거부해서 `run()`이 같은 alert를 매번 다시 시도한다(D-059). 어긋남은 BMP 전체 비교 테스트 둘이 잡는다. `str.split()`·`strip()`은 U+2003·U+0085·U+2028까지 공백으로 보므로 쓰지 않는다.
- **U+2003처럼 목록 밖 공백만 있는 제목은 폴백이 아니라 그대로 쓰인다.** 계약·DB CHECK도 통과한다. 화면에는 빈 칸처럼 보일 수 있다.
- **다중 alert 규칙은 생성 경로에서 쓰이지 않는다.** auto·scenario·l1 Ticket은 alert가 정확히 1개(계약, `0104`)이고 l3는 `alert_ids=[]`다. `ticket_title`은 여러 alert를 정렬하는 함수로 단위 테스트만 있다. `0109`의 SQL 정렬(`ORDER BY severity DESC, time, id`)도 alert가 둘 이상인 행이 실제로 없어서 테스트하지 못했다.
- **Ticket 제목은 생성 시점 값이다.** 재처리(D-063)가 `alerts.title`을 바꿔도 따라가지 않는다. 시나리오 묶음 Ticket의 요약 제목은 D-068(추후)이고, 시나리오 규칙 주석은 `l1/ticketing.py:_make_ticket`에 있다.
- **`0109`는 `tickets` 테이블을 트랜잭션 끝까지 잠근다**(`ALTER TABLE ... ADD COLUMN`). 파이프(D-054)·실행기가 도는 DB에서는 멈춘 뒤 적용하는 것이 안전하다. 가리키는 alert가 없거나 제목이 빈 기존 행은 `(제목 없음)`이 된다.
- 에이전트 읽기 역할(`soc_agent_reader`)에는 `tickets.title`을 주지 않았다(0007은 열 단위 SELECT). 유사 사례 도구는 `alerts.title`을 읽는다.
- L2 모델 입력(`tickets[].title`)에 외부 문자열(alert 제목, 가설 문장)이 하나 늘었다. 같은 문자열이 이미 alert와 Hunt로 들어가며 같은 데이터 포장 안에 있다.
- **확인하지 못한 것**: (1) 개발 DB의 기존 Ticket 중 가리키는 alert가 없는 행 수 등을 세는 쿼리는 이 환경에서 돌리지 않았다(`.env`의 개발 DB 이름이 컨테이너에 없었다). 적용 전에 계획 파일의 쿼리 4개를 개발 DB에서 돌려 건수를 PR 초안에 적는다. (2) `ajv`는 설치돼 있지 않아 JS 쪽 pattern은 `RegExp`로만 확인했다. TS 생성물에는 pattern이 나오지 않고 프론트는 검사하지 않는다.
- 로컬에서 DB 테스트를 돌릴 때 `.env`의 `DATABASE_URL`이 가리키는 DB(`zt_dev`)가 컨테이너에 없어서, 같은 서버의 `postgres` DB로 바꿔 실행했다(임시 DB를 만드는 관리자 연결용). 코드와 설정은 바꾸지 않았다.
- ruff E501은 한글을 두 칸으로 센다. 한글 주석·docstring이 100칸을 넘기 쉽다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과.
- `uv run pytest`: 2364 통과. `uv run pytest -m "db or qdrant"`(`DATABASE_URL`은 `postgres` DB, `QDRANT_URL`은 로컬 컨테이너): 569 통과.
- `uv run python scripts/generate_contracts.py --check`, `pnpm contracts:check`: 일치. `pnpm lint`(기존 경고 1건 `flow-chart.tsx`, 이번 변경과 무관), `pnpm test` 86, `pnpm build`: 통과.
- 새 테스트: `tests/test_ticket_title.py`(규칙·계약 pattern·L3 제목, 샘플은 `tests/fixtures/tickets/title_cases.json`), `tests/test_ticket_title_db.py`(`db`: 백필이 같은 입력의 `clean_title`과 같음, CHECK, 빈 제목과 U+2003 제목에서 `run()`이 오류·재시도 없이 Ticket을 만듦), `tests/test_contracts.py`의 새 valid·invalid Ticket 케이스, `test_api_ui.py`(목록·상세 title), `test_l1_judge_db.py`(승격 Ticket title), `test_l3_hunt_db.py`(L3 Ticket title).
- 테스트 먼저: 제목 규칙 단위 테스트는 구현 전에 ImportError로 실패하는 것을 확인했다. `db` 테스트는 마이그레이션을 쓴 뒤에 처음 돌렸다(그 전에 실패를 확인하지 않았다).
