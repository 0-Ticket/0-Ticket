---
issue: 239
date: 2026-11-05
owner: Pandyo
supersedes: []
---

# Hunt·뉴스 조회 API 만들기

## 목표

화면용 API(FastAPI, D-016) 앱 뼈대를 `src/soc/api/`에 만들고, 읽기 전용 GET 세 개(`/api/hunts`, `/api/hunts/{hunt_id}`, `/api/threat-news`)로 헌팅 결과와 수집한 뉴스를 돌려준다. Agent Log 원문은 열지 않고, 오류 응답에 입력값·DB 오류 메시지를 넣지 않는다.

## 방법

### 1. 의존성과 결정

- `fastapi==0.162.0`, `uvicorn==0.54.0`을 `pyproject.toml` 의존성에 더한다. uvicorn은 mcp를 통해 이미 `uv.lock`에 있는 버전이다. fastapi 0.162.0은 지금 lock의 Starlette 1.10.0과 함께 풀린다.
- 결정 목록에 화면용 API 실행·의존성(D-042)을 더한다.
- 테스트는 Starlette TestClient로 한다. Starlette 1.10.0의 TestClient는 `httpx2`를 쓴다(openai가 이미 끌어오는 패키지, #221 계획 "토론으로 정한 것" 1). HTTP 클라이언트(httpx, D-039)는 쓰지 않는다.

### 2. 설정 (`config/default.toml`의 `[api]`)

| 키 | 기본값 | 뜻 |
|---|---|---|
| `host` | `"127.0.0.1"` | uvicorn 바인딩 주소. 인증(D-020)이 생기기 전까지 로컬만 |
| `port` | `8000` | uvicorn 포트 |
| `statement_timeout_ms` | `5000` | 요청 DB 세션의 문장 시간 상한 |
| `connect_timeout_seconds` | `5` | DB 접속 시간 상한 |

- `soc.api.config.load_config()`가 `config/default.toml` 위에 `config/local.toml`을 덮어쓰고 `[api]`만 돌려준다. L3·L2 로더와 같은 모양이고 새 공통 로더는 만들지 않는다. 값이 틀리면 `ConfigError`.
- 기법 이름에 쓰는 ATT&CK 버전은 `soc.l3.config.load_config()`의 `[l3.intel.attack] version`을 읽는다.

### 3. 앱 뼈대 (`src/soc/api/`)

- `create_app(settings) -> FastAPI`. `docs_url=None`, `redoc_url=None`. `/openapi.json`은 둔다.
- 라우터는 `src/soc/api/routes/` 아래 파일별(`hunts.py`, `threat_news.py`)로 두고 `/api` 접두사 라우터 하나에 묶는다. 인증(D-020) 이슈가 이 라우터에 붙인다. 지금은 인증 자리를 미리 만들지 않는다.
- 엔드포인트는 모두 동기 `def`다(FastAPI 스레드 풀).
- 실행: `uv run python -m soc.api`. `DATABASE_URL`이 없으면 변수 이름만 출력하고 종료 코드 2. 있으면 `[api] host·port`로 uvicorn을 띄운다.

### 4. DB 접속

- 요청마다 `DATABASE_URL`로 새로 연결하고 요청이 끝나면 닫는다(FastAPI 의존성). 연결 풀은 두지 않는다.
- 세션: `TimeZone=UTC`, `statement_timeout`, `default_transaction_read_only=on`, `connect_timeout`. #211 `soc/tools/db.py`와 같은 설정이고 계정만 `DATABASE_URL`이다. `DATABASE_URL`은 쓰기 권한이 있는 계정이라 읽기 전용 세션을 방어선으로 둔다.
- 에이전트 DB 읽기 역할(`AGENT_DATABASE_URL`)은 쓰지 않는다(#211, `alerts`·`events`만 읽음).

### 5. 공통 규칙

- 시각은 모두 epoch_ms 정수(`to_epoch_ms`). 쿼리의 `since`·`until`도 epoch_ms이고 0 이상 `253402214399999` 이하다.
- `limit`: 기본 50, 1~200.
- 목록 응답: `{"items": [...], "next_cursor": <문자열 또는 null>}`. 다음 페이지가 없으면 null. `cursor`는 화면이 해석하지 않는 문자열이다.
- 밖에서 온 문자열과 LLM 출력(`hypothesis`, `reason`, `details` 안의 문자열, 뉴스 `title`·`summary`·`link`)은 JSON 문자열 그대로 돌려주고 가공하지 않는다. 화면은 텍스트로만 보인다(D-019).
- 응답 모델은 API 전용으로 `src/soc/api/models.py`에 둔다. Hunt 부분은 생성 모델 `soc.contracts.generated.hunt_schema.Hunt`를 재사용한다.

### 6. 오류 응답

| 경우 | 상태 | 본문 |
|---|---|---|
| 없는 Hunt ID, 모양이 틀린 Hunt ID, 없는 경로 | 404 | `{"error": "not_found"}` |
| GET이 아닌 메서드 | 405 | `{"error": "method_not_allowed"}` |
| 잘못된 쿼리 값 | 422 | `{"error": "invalid_query", "fields": ["limit"]}` (쿼리 이름만) |
| `DATABASE_URL` 없음, DB 접속·조회 실패(`psycopg.Error`) | 503 | `{"error": "db_unavailable"}` |
| 그 밖의 예외 | 500 | `{"error": "internal"}` |

- FastAPI 기본 422는 입력값(`input`)을 본문에 넣으므로 `RequestValidationError` 처리기를 바꾼다. `fields`에는 정의된 쿼리 이름만 넣는다.
- 서버 로그에는 예외 종류 이름만 남긴다. 예외 메시지(psycopg 메시지에는 호스트가 들어갈 수 있음), 입력값, 주소는 남기지 않는다.

### 7. `GET /api/hunts`

- 쿼리: `status`(`pending`·`confirmed`·`rejected`·`inconclusive`·`failed`), `hunt_run_id`(`hrn_` ID 모양), `limit`, `cursor`(`hnt_` ID 모양)
- 정렬: `id` 내림차순(UUIDv7이라 만든 순서, ID 형식 D-034). 다음 페이지는 `id < cursor`. `next_cursor`는 이번 페이지 마지막 `id`
- 항목: `id`, `hunt_run_id`, `status`, `hypothesis`, `attack_techniques`, `confidence`, `attempts`, `verified_at`, `created_at`, `updated_at`

### 8. `GET /api/hunts/{hunt_id}`

응답:

```json
{
  "hunt": {"...": "Hunt 계약 모양 그대로(details 포함)"},
  "techniques": [{"id": "T1059", "name": "Command and Scripting Interpreter"}],
  "ticket_id": "tkt_... 또는 null",
  "runs": [
    {"run_id": "run_...", "task": "l3_hypothesize", "attempt": 1, "outcome": "ok",
     "failure": null, "tokens_in": 1200, "tokens_out": 300,
     "started_at": 1793678580123, "duration_ms": 4200}
  ]
}
```

- `techniques`: `hunt.attack_techniques` 순서대로. 이름은 설정 버전의 `attack_techniques`에서 찾고 없으면 null
- `ticket_id`: `tickets.hunt_id = <hunt_id>`인 Ticket의 `id`. 없으면 null
- `runs`: `agent_logs`에서 `subject_type = 'hunt'`이고 `subject_id`가 이 Hunt의 `id`(검증 run) 또는 `hunt_run_id`(가설 생성 run)인 줄을 `run_id`로 묶는다. `input`·`output` 컬럼은 SELECT하지 않는다
  - `task` = `details.task`, `attempt` = `details.attempt`
  - `outcome`·`failure` = 마지막 model 줄(`seq`가 가장 큰 `kind = 'model'`)의 `outcome`·`details.failure`(없으면 null). model 줄이 없으면 마지막 줄의 값. tool 줄의 실패는 run 결과로 보지 않는다
  - `tokens_in`·`tokens_out` = 각 합(null 제외). 모두 null이면 null
  - `started_at` = 첫 줄의 `started_at`. `duration_ms` = 줄마다 `started_at + duration_ms` 중 가장 큰 값 − 첫 줄 `started_at`
  - 정렬은 `started_at`, `run_id` 오름차순
  - 기록 쓰기에 실패한 run(`log_error`)은 줄이 없어 나오지 않는다. 그 실패는 `hunt.details.verify_failures`에 있다

### 9. `GET /api/threat-news`

- 쿼리: `source`(빈 값 불가), `since`, `until`, `limit`, `cursor`
- 기간과 정렬 기준은 `COALESCE(published_at, fetched_at)`(#223과 같음). `since` 이상 `until` 이하. `since > until`이면 422(`fields: ["since", "until"]`)
- 정렬: 그 시각 내림차순, 같으면 `id` 내림차순. `cursor`는 `"<그 시각 epoch_ms>_<id>"` 문자열이고, 다음 페이지는 `(시각, id) < (cursor 시각, cursor id)`. 모양이 틀린 `cursor`는 422
- 항목: `id`, `source`, `kind`, `title`, `summary`, `link`, `published_at`, `fetched_at`, `updated_at`

### 10. 테스트

- 샘플(`tests/fixtures/api/`, 손으로 만듦): 상태 5가지 Hunt(두 가설 생성 run), `confirmed` Hunt의 L3 Ticket, 뉴스 4건 이상(`published_at` null 1건, 지시문을 넣은 제목 1건, 출처 2개), ATT&CK 기법(설정 버전에 없는 기법을 쓴 Hunt 1건 포함), Agent Log(가설 생성 run, 실패한 검증 run과 성공한 검증 run, tool 줄 실패 포함). 모두 계약 검증을 통과하는 값이고 IP·도메인은 `docs/security.md` 규칙을 따른다
- DB가 필요한 테스트는 `db` 마커, 기존 임시 DB 장치(`tests/conftest.py`)와 마이그레이션 실행기를 쓴다
- DB 없이 도는 테스트: 라우트 목록, 설정 로더, `DATABASE_URL` 없음 → 503과 실행 명령 종료 코드 2, 422 본문

### 11. 실제 데이터 확인

- Groq `openai/gpt-oss-120b`를 커밋하지 않는 `config/local.toml`의 `[llm]`에 넣고 `uv run python -m soc.l3 hunt`를 돌린 DB로, `uv run python -m soc.api`를 띄워 세 API를 직접 부른다. Groq가 strict를 거부하면 `config/local.toml`에서만 `strict_mode = false`로 둔다
- 커밋되는 코드와 `config/default.toml`의 LLM 설정은 바꾸지 않는다(기본 LLM은 Azure Foundry, D-009). Azure 실제 연결 확인은 #215
- 기록에는 건수와 상태 코드만 적는다. 모델 품질은 판단하지 않는다(실제 모델 확인은 #224)
- 실행할 수 없으면 샘플을 넣은 DB로 확인하고 그렇게 적는다

## 바꿀 곳

- `pyproject.toml`, `uv.lock`: `fastapi==0.162.0`, `uvicorn==0.54.0`
- `docs/decisions.md`: D-042 행과 기록 한 줄
- `config/default.toml`: `[api]`
- `src/soc/api/`: `__init__.py`, `__main__.py`, `app.py`(`create_app`, 오류 처리기), `config.py`, `db.py`, `models.py`, `routes/hunts.py`, `routes/threat_news.py`
- `tests/fixtures/api/`: 샘플
- `tests/test_api.py`(DB 없음), `tests/test_api_db.py`(`db` 마커)
- `docs/notes/239-hunt-news-api.md`: 개발 기록

## 다른 코드와 맞물리는 곳

- **`hunts`·`tickets`·`agent_logs`·`threat_news`·`attack_techniques`를 읽는다.** 테이블은 바꾸지 않는다. `threat_news`·`attack_techniques`는 마이그레이션 머리말에 "L3만 읽는 테이블"로 적혀 있는데, 화면용 API가 읽는 쪽으로 하나 늘어난다. L3 담당(같은 담당)이 안다.
- **Agent Log 줄 모양에 기댄다.** run 요약은 `details.task`·`details.attempt`·`details.failure`(#209·#210)를 읽는다. 이 키를 바꾸면 API도 바꿔야 한다.
- **새 설정 키 `[api]`, 새 명령 `python -m soc.api`, 새 패키지 `soc.api`.** 다른 담당의 화면용 API는 `src/soc/api/routes/`에 파일을 더하고 같은 `/api` 라우터에 붙인다.
- **첫 화면 이슈.** 응답 모델이 API 전용이라 감싸는 모양(목록, `techniques`, `runs`, `next_cursor`)은 `contracts/`에 없다. 이 모양의 TypeScript 타입을 만드는 방법(예: OpenAPI 생성, 쓰려면 그때 확정)은 첫 화면 이슈가 정한다(데이터 계약, D-003).
- **인증(D-020) 이슈.** `/api` 라우터 하나에 인증을 붙이고, 기본 바인딩(127.0.0.1)을 바꿀지 정한다.

## 범위 밖

- 인증, CORS, 화면
- Agent Log 원문(`input`·`output`) 조회
- 헌팅·대응을 실행하는 API, GET이 아닌 메서드
- 연결 풀, 비동기 DB
- Azure 실제 연결 확인(#215), L3 실제 모델 품질 확인(#224)

## 완료 기준

- [ ] `tests/fixtures/`의 손으로 만든 Hunt(상태 5가지)·Ticket·뉴스·Agent Log로 세 API의 응답 테스트가 있다(`db` 마커)
- [ ] `confirmed` Hunt 상세에는 `ticket_id`가, 나머지는 null이다
- [ ] 상세 `runs`에 가설 생성 run(`hrn_`)과 검증 run(`hnt_`)이 모두 나오고, `input`·`output`이 없다. 결과는 마지막 model 줄 기준이다(tool 줄 실패만 있는 run은 `ok`)
- [ ] 설정 버전에 없는 기법은 이름이 null로 나온다
- [ ] 필터(`status`, `hunt_run_id`, `source`, 기간)·정렬·다음 페이지 테스트가 있다. `published_at`이 null인 뉴스는 `fetched_at`으로 기간·정렬에 들어간다
- [ ] 없는 ID와 없는 경로는 404, 잘못된 쿼리 값은 422, DB 접속 실패는 503, 그 밖의 예외는 500이고, 본문에 입력값·DB 오류 메시지·주소가 없다
- [ ] 응답의 Hunt 부분이 Hunt 계약 검증(`validate_contract("hunt", …)`)을 통과한다
- [ ] 라우트 목록 테스트: `/api/` 아래는 GET만 있고, 그 밖에는 `/openapi.json`(GET·HEAD)만 있다. `/docs`·`/redoc`은 없다
- [ ] 지시문을 넣은 뉴스 제목이 바뀌지 않은 JSON 문자열로 나온다
- [ ] Groq로 `soc.l3 hunt`를 돌린 DB로 세 API를 직접 불러 본 결과(건수·상태 코드)를 `docs/notes/`에 적는다
- [ ] 결정 목록에 D-042 행과 기록이 있고, `fastapi`·`uvicorn` 의존성이 추가됐다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과(`db` 마커 테스트도 실행)
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록

## 토론으로 정한 것

1. **테스트 클라이언트는 httpx(D-039)가 아니라 `httpx2`다.** Starlette 1.10.0의 TestClient가 `httpx2`를 먼저 import한다. 이슈의 "(httpx, D-039)"를 바로잡는다.
2. **앱 뼈대를 이 이슈가 만든다.** 열린 이슈 가운데 API 앱을 만드는 다른 이슈가 없다.
3. **인증 없이 127.0.0.1에 바인딩하고, 라우터는 `/api` 하나로 묶는다.** 인증 자리를 미리 만들지 않는다(필요한 만큼만).
4. **응답 모델은 API 전용이다.** Hunt 부분은 생성 모델을 재사용한다. 감싸는 모양의 TypeScript 타입은 첫 화면 이슈가 정한다.
5. **시각은 응답과 쿼리 모두 epoch_ms다.** Hunt 계약과 같다.
6. **`limit` 기본 50·상한 200. Hunt는 `id` 내림차순에 `cursor` = 마지막 `id`, 뉴스는 정렬 시각과 `id`를 담은 문자열 하나.** 뉴스는 정렬 기준이 `id`가 아니라서 페이지가 어긋나지 않게 한다.
7. **뉴스 기간 필터도 `COALESCE(published_at, fetched_at)` 기준이다.** 정렬·#223과 같게 한다.
8. **요청마다 연결하고 읽기 전용 세션을 쓴다.** 연결 풀(`psycopg_pool`)은 확정되지 않은 의존성이다.
9. **run 요약은 `run_id`로 묶고 결과는 마지막 model 줄 기준이다.** 이슈에 없던 `attempt`를 더했다. tool 줄 실패는 정상 흐름에서도 생긴다.
10. **`/docs`·`/redoc`은 끄고 `/openapi.json`은 둔다.** Swagger UI는 외부 CDN 스크립트를 받는다. 라우트 테스트는 `/openapi.json`의 GET·HEAD(FastAPI 기본)를 허용한다.
11. **오류 본문은 오류 코드만 담는다(6절 표).** 이슈에 없던 503·500·405를 더했다. FastAPI 기본 422는 입력값을 본문에 넣고(0.162.0에서 확인), psycopg 메시지에는 호스트가 들어갈 수 있다.
12. **실제 데이터 확인은 Groq로 한다.** Azure 계정은 준비돼 있지만 배포는 개발이 끝난 뒤에 한다. 커밋하는 코드·설정은 Azure 기준 그대로 두고(D-009), 확인 실행만 `config/local.toml`로 Groq를 쓴다.
13. **이슈에 없던 세부(응답의 `hunt`·`items`·`next_cursor` 키, 뉴스 `cursor` 문자열 모양, 기간 양끝 포함, `[api]` 시간 상한 키)는 확정할 때 AI가 관례로 채웠다.** 리뷰에서 바꿀 수 있다.

## 바뀐 점
