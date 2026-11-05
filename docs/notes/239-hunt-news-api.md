---
issue: 239
date: 2026-11-05
owner: Pandyo
plan: 239-hunt-news-api.md
supersedes: []
---

# Hunt·뉴스 조회 API(FastAPI 앱 뼈대와 GET 세 개)를 만들었다

## 한 일

- `uv run python -m soc.api`가 화면용 API를 uvicorn으로 띄운다. 바인딩은 `[api] host·port`(기본 `127.0.0.1:8000`), DB는 `DATABASE_URL`이다. `DATABASE_URL`이 없거나 설정이 틀리면 종료 코드 2다.
- `GET /api/hunts`는 Hunt 목록을 `id` 내림차순으로 준다. `status`·`hunt_run_id`로 거르고, `cursor`(이전 페이지 마지막 `id`)로 넘긴다.
- `GET /api/hunts/{hunt_id}`는 Hunt 계약 레코드 그대로(`hunt`)와 함께 세 가지를 준다.
  - `techniques`: 기법 이름은 설정 버전에서 찾고, 없으면 null
  - `ticket_id`: L3 Ticket
  - `runs`: Agent Log를 `run_id`로 묶은 요약. 결과는 마지막 model 줄 기준이고 `input`·`output`은 읽지 않는다
- `GET /api/threat-news`는 `COALESCE(published_at, fetched_at)` 내림차순이다. `source`와 기간(`since`·`until`, 양끝 포함)으로 거르고, `cursor` 문자열(`"<시각 ms>_<id>"`)로 넘긴다.
- 오류 본문은 오류 코드와 쿼리 이름만 담는다: 404 `not_found`, 405 `method_not_allowed`, 422 `invalid_query`+`fields`, 503 `db_unavailable`, 500 `internal`. 로그에는 예외 종류 이름만 남긴다.
- 요청마다 `DATABASE_URL`로 연결한다. 세션은 읽기 전용(`default_transaction_read_only=on`)이고 `statement_timeout`·`TimeZone=UTC`를 건다.

## 계획과 달라진 점

- **오류 처리기를 `app.py`가 아니라 `src/soc/api/errors.py`에 두었다.** `app.py`는 앱 조립만 한다. 계획의 "바꿀 곳" 목록에 `errors.py`가 늘었다.
- **500은 예외 처리기가 아니라 미들웨어에서 잡는다.** Starlette는 `Exception` 처리기로 응답을 보낸 뒤에도 예외를 다시 올린다. 그러면 uvicorn이 메시지가 든 traceback을 로그에 남긴다. 미들웨어(`_catch_all`)에서 잡아 다시 올리지 않는다. 테스트는 기본 TestClient(앱 밖으로 나온 예외를 다시 올림)로 500을 받는지 본다.
- **422의 `fields`는 이름순이다.** FastAPI가 검사하는 순서(쿼리 정의 순서)에 기대지 않게 했다.
- **라우트 목록 테스트는 포함한 라우터의 라우트와 OpenAPI 문서로 본다.** FastAPI 0.162는 `include_router`한 라우터를 내부 객체(`_IncludedRouter`)로 감싸 `app.routes`에 둔다. 그래서 `app.routes`에서 `APIRoute`를 바로 셀 수 없다. 앱 바로 아래는 `/openapi.json`(GET·HEAD)뿐인지, 각 라우터(`hunts.router`, `threat_news.router`)의 라우트가 GET만인지, OpenAPI 문서의 경로가 세 개이고 `get`만 있는지 본다.
- **설정 검사 범위.** 계획에 없던 범위를 정했다: `port` 1~65535, `statement_timeout_ms` 1 이상, `connect_timeout_seconds` 1~3600. 모두 정수(`bool` 아님)여야 한다. `source` 쿼리는 1~200자, 뉴스 `cursor`는 40자 이하다.

## 다음 사람이 알아야 할 것

- **뉴스 정렬·`cursor`는 밀리초로 자른 시각으로 비교한다.** 수집(#221)은 `fetched_at`·`updated_at`에 `datetime.now(UTC)`를 그대로 넣어 마이크로초가 남는다. `cursor`는 epoch_ms라, 자르지 않은 값으로 `(시각, id) < (cursor)`를 비교하면 같은 밀리초 안의 행이 다음 페이지에서 빠진다. 그래서 정렬·기간·`cursor` 비교 모두 `date_trunc('milliseconds', COALESCE(published_at, fetched_at))`를 쓴다. 자르지 않으면 `test_news_pages_do_not_skip_rows_within_the_same_millisecond`가 7건 중 6건만 보고 실패하는 것을 확인했다.
- **새 라우터는 `src/soc/api/routes/`에 파일을 더하고 `app.py`의 `/api` 라우터에 `include_router`한다.** 인증(D-020)도 이 `/api` 라우터에 붙인다.
- **run 요약은 Agent Log의 `details.task`·`details.attempt`·`details.failure`(#209·#210)에 기댄다.** 이 키 이름이 바뀌면 `soc.api.routes.hunts.summarize_runs`를 고친다. 기록 쓰기에 실패한 run(`log_error`)은 줄이 없어 `runs`에 나오지 않는다. 그 실패는 `hunt.details.verify_failures`에 있다.
- **`threat_news`·`attack_techniques`를 L3 밖(화면용 API)에서도 읽는다.** 마이그레이션 0300 머리말의 "L3만 읽는 테이블"은 고치지 않았다(적용한 파일은 고치지 않는다, D-035).
- **응답 모델은 API 전용이다.** 감싸는 모양(목록, `techniques`, `runs`, `next_cursor`)의 TypeScript 타입을 만드는 방법은 첫 화면 이슈가 정한다(데이터 계약, D-003). FastAPI가 `/openapi.json`을 만든다.
- **CORS를 두지 않았다.** 화면 개발 서버가 다른 출처에서 부르면 막힌다. 첫 화면 이슈가 Vite 프록시를 쓸지, CORS를 열지 정한다.
- **실제 모델로 만든 `confirmed` Hunt와 L3 Ticket은 API에서 보지 못했다.** Groq 확인에서 검증 run이 HTTP 400 `tool_use_failed`로 실패해 Hunt가 `pending`으로 남았다(아래 "확인 방법"). `ticket_id`와 `confirmed` 경로는 샘플 테스트로만 확인했다. 실제 모델 확인은 #224
- **`config/local.toml`의 `[llm]`에 값이 있으면 `tests/test_agent_config.py::test_default_llm_and_budget_values`가 실패한다.** 기본값이 비어 있는지 보는 테스트가 local.toml을 덮어쓴 설정을 읽는다. 실제 모델 확인 뒤 테스트를 돌릴 때는 local.toml을 잠시 치운다
- **로컬 PostgreSQL은 UTF-8로 만든다.** `initdb`를 로캘 없이 돌리면 SQL_ASCII가 되어 한글 샘플 INSERT가 `UnicodeEncodeError`로 실패한다(`-E UTF8 --locale=C.UTF-8`). compose와 CI 컨테이너는 UTF-8이다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run pytest`: 903건 통과
- `DATABASE_URL=… uv run pytest -m db`: 227건 통과(로컬 PostgreSQL 16.15, 테스트마다 임시 DB)
- 테스트를 먼저 쓰고, 구현 전에 `soc.api`가 없어 수집 단계에서 실패하는 것을 봤다
- 주요 테스트
  - `tests/test_api.py`(DB 없음)
    - 라우트 목록과 `/docs`·`/redoc` 404
    - 설정 기본값·덮어쓰기·틀린 값
    - `DATABASE_URL` 없음 503, 닫힌 포트 503(주소·비밀번호가 본문·로그에 없음)
    - 422 14가지(입력값이 본문에 없음), 모양이 틀린 Hunt ID 404, 없는 경로 404, POST·PUT·PATCH·DELETE 405
    - 예상하지 못한 예외 500(메시지가 본문·로그에 없고 종류 이름만)
    - 실행 명령 종료 코드 2·0
  - `tests/test_api_db.py`(`db` 마커)
    - Hunt 목록 필드·정렬, 필터 10가지, 페이지, 필터와 `cursor` 함께
    - 상세 5건 계약 검증과 샘플과 같음, `confirmed`만 `ticket_id`, 설정 버전에 없는 기법 이름 null
    - run 요약(실패 run·tool 줄만 실패한 run·토큰 없는 run), Agent Log 원문 없음, 없는 ID 404
    - LLM 출력·뉴스 문자열이 그대로 나옴
    - 뉴스 정렬·필터 8가지·페이지·같은 밀리초 두 행, 읽기 전용 세션
- 손으로 확인(샘플을 넣은 로컬 DB, `uv run python -m soc.api`를 띄워 curl)
  - `/api/hunts` 200·5건, `?status=confirmed` 200·1건
  - 상세 200·runs 3건·`ticket_id` 있음
  - `/api/threat-news` 200·5건, `?limit=2` 200·`next_cursor` 있음
  - `?limit=zz` 422, `hnt_nope` 404, POST 405, `/docs` 404
  - 바인딩 `127.0.0.1:8000`
- Groq로 `soc.l3 hunt`를 돌린 DB로 확인했다. 로컬 PostgreSQL 16(UTF-8)에 마이그레이션 4개, 에이전트 읽기 계정과 `AGENT_DATABASE_URL`은 #211 기록대로 만들었다. `config/local.toml`의 `[llm]`만 Groq `openai/gpt-oss-120b`이고 `strict_mode`는 기본값(`true`)이다
  - `soc.l3 hunt` 종료 0
    - 수집: thehackernews 50건, cisa_kev 1,768건, ATT&CK 706건. boannews는 `network` 실패. 같은 주소를 curl로 부르면 200이라 네트워크 정책 차단은 아니다(프록시 터널이 중간에 끊김)
    - 가설 생성 1건 저장. 검증 1건은 `provider_error`로 `pending`(시도 1)
  - 검증의 `provider_error`는 Groq HTTP 400 `tool_use_failed`였다(429 재시도 뒤). DB 복사본에서 `strict_mode = false`로 다시 돌려도 같은 400이라 strict 때문이 아니다. `strict_mode`는 기본값으로 두었다. 실제 모델 확인은 #224
  - `/api/hunts` 200·1건(`pending`), `?status=pending` 200·1건, `?status=confirmed` 200·0건
  - `/api/hunts/{id}` 200
    - `techniques` 1건, 이름 있음
    - `ticket_id` null
    - `runs` 2건: `l3_hypothesize` `ok`, `l3_verify` `error`·`provider_error`
    - `input`·`output` 없음
  - `/api/threat-news` 200·50건·`next_cursor` 있음
    - `?limit=200`으로 끝까지 넘기면 10페이지 1,818건이다. 중복이 없고 DB 건수와 같다
    - `?source=thehackernews&limit=200` 200·50건, `?source=cisa_kev&limit=200` 200·200건·`next_cursor` 있음, `?source=boannews` 200·0건
  - `hnt_nope` 404, `?limit=zz` 422
