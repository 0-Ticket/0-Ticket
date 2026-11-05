---
issue: 215
date: 2026-11-05
owner: Pandyo
plan: 215-executor-l1-e2e.md
supersedes: []
---

# 실행기와 워커 틀을 만들고, 워커 없이 L1 판정을 실제 모델로 잴 준비를 했다

## 한 일

- **실행기(`uv run python -m soc.agent`).** `[executor.<stage>] workers`에 적은 워커를 단계별 스레드로 돌린다.
  - 단계 안에서는 한 번에 1건, 등록 순서대로 돈다. 단계끼리는 동시에 돈다.
  - `poll`·`handle`의 예외는 로그(워커 이름·subject ID·예외 종류)만 남기고 다음 건으로 간다.
  - 워커가 없거나 `interval_seconds = 0`인 단계는 띄우지 않는다.
  - SIGINT·SIGTERM을 받으면 진행 중인 `run_agent`를 `cancelled`로 끝내고 기다린다. Agent Log도 남는다.
- **워커 틀.** `soc.agent.AgentWorker` Protocol과 등록 함수 `build_worker(config) -> AgentWorker`를 정했다. L1·L2 워커는 각 담당이 만든다(아래 "워커 틀", 알림 초안).
- **`[llm] strict_mode` 기본값 `false`.** Foundry는 strict를 켜면 최종 답이 빈 문자열이다(#224). 기본 LLM(D-009)·에이전트 구조(D-024) 메모를 고쳤다.
- **L1 측정 명령(`uv run python -m soc.agent.dev_l1 seed|run|remove`).** 개발 DB에 L1 시드(Alert 6, Event 17)를 넣고, L1 워커 없이 Alert마다 `run_agent`를 한 번 부른다. 실제 모델 호출은 사람이 맥에서 한다(아래 "다시 재는 법").
- **`llm` 테스트 1건(`tests/test_l1_e2e_llm.py`).** 임시 DB에서 위협 Alert 1건을 실제 모델로 판정해 Verdict 계약·근거 장부·Agent Log를 본다.
- **실측 결과는 아직 없다.** 사람이 맥에서 잰 뒤 이 파일의 "실측 결과"를 채운다.

## 계획과 달라진 점

- **`dev_l1.py`는 테스트보다 먼저 썼다.** 절차(샘플 → 테스트 → 코드)와 순서가 다르다. 실행기는 테스트를 먼저 쓰고 실패를 확인했다. `dev_l1`은 모듈을 쓴 뒤 테스트를 붙였고, 테스트가 샘플 오류 1건(아래)을 잡았다.
- **샘플 1건의 시각을 고쳤다.** `benign_scheduled_task`의 "지난주 같은 작업" Event가 7.04일 전이라 도구가 한 번에 보는 범위(`max_range_days` 7일)를 넘었다. 6일 전으로 옮겼다.
- **측정용 작업 프롬프트는 샘플 파일(`tests/fixtures/l1_e2e/dev_seed.json`의 `task_prompt`)에 뒀다.** L1 코드가 아니라 측정용이라 `src/`의 프롬프트 폴더에 두지 않았다.
- **설정 로더에 `load_full_config`를 더했다.** 실행기가 `[executor]`를 읽고 설정 전체를 `build_worker`에 넘기기 위해서다. `load_config`(세 절만)는 그대로다.
- **맥 실측 뒤 측정 입력에 조회 구간을 더했다(사람이 정함).** 처음 입력에는 Alert 시각만 있고 프롬프트가 "앞뒤 하루를 본다"고 해서, 모델이 epoch 밀리초 산수를 했다. 빈 응답이 많아(아래 "실측 결과") 코드가 계산한 `window_start_ms`·`window_end_ms`를 넣고, 프롬프트는 그 값을 도구에 그대로 쓰라고 바꿨다.
- **집계 SQL이 시작 시각(`since`)부터만 센다.** 처음에는 "최근 1일"이라 고치기 전 18 run이 섞인다. 빈 응답 수도 센다.
- **세부 동작**
  - `[executor]`에 모르는 키가 있으면 시작하지 않는다.
  - 단계 절이 빠지면 그 단계는 돌지 않는 것으로 본다.
  - 돌지 않는 단계(`interval_seconds = 0` 또는 워커 없음)는 워커를 만들지 않는다. 그 단계의 등록 오류는 켤 때까지 드러나지 않는다.
  - `handle`에서 새어 나온 `asyncio.CancelledError`도 잡는다. 스레드가 죽지 않게 하기 위해서다.

## 다음 사람이 알아야 할 것

### 워커 틀 (L1·L2·L3 공통)

```python
class AgentWorker(Protocol):  # soc.agent.AgentWorker
    stage: Literal["l1", "l2", "l3"]  # 등록한 [executor.<stage>]와 같아야 함
    name: str  # 단계 안에서 유일

    def poll(self, limit: int) -> Sequence[str]: ...
    def handle(self, subject_id: str) -> None: ...


def build_worker(config: dict[str, Any]) -> AgentWorker: ...  # 각 담당 모듈
```

| 항목 | 약속 |
|---|---|
| 등록 | `[executor.<stage>] workers = ["soc.<모듈>:build_worker"]`. `soc.` 아래 모듈만 받는다. 가져오지 못하거나, 함수가 예외를 내거나, `stage`가 다르거나, `name`이 겹치면 실행기가 시작하지 않는다(종료 코드 2) |
| `config` | 기본 설정 위에 `local.toml`을 덮어쓴 설정 전체. 자기 절만 읽는다. 비밀 값·DB 주소는 워커가 환경변수에서 직접 읽는다 |
| `poll` | 실행기는 항상 정수 `poll_limit`을 넘긴다. 결과가 기록된 건은 다시 내지 않는다. HuntVerifier의 `poll(limit: int \| None)`도 이 모양을 만족한다 |
| `handle` | 멱등이다. `run_agent`(동기)를 부르고 결과를 자기 테이블에 쓴다 |
| 예외 | 실행기가 잡아 로그만 남긴다. 같은 건이 계속 실패하면 매 라운드 다시 나오므로 시도 횟수는 워커가 센다 |
| 종료 | `run_agent`가 `failure = "cancelled"`로 돌아온다. 실패 횟수에 넣지 않고 다음 실행에서 다시 하기를 권한다 |
| 스레드 | `handle`은 단계 스레드에서 돈다. `asyncio.run`처럼 이벤트 루프를 만들거나 바꾸는 코드를 쓰지 않는다(종료 때 취소가 닿지 않는다). DB 연결은 `handle`마다 연다 |

### 취소가 동작하는 방식과 한계

- 단계 스레드는 시작할 때 이벤트 루프를 만들어 그 스레드의 기본 루프로 등록한다. `Runner.run_sync`(openai-agents 0.24.0)는 스레드의 기본 루프를 그대로 쓴다. 그래서 실행기가 `call_soon_threadsafe`로 그 루프의 작업을 모두 취소하면, `run_task`가 `asyncio.CancelledError`를 `cancelled`로 바꾼다. 코어 코드는 고치지 않았다.
- **SDK 내부 동작에 기대는 부분이다.** openai-agents를 올렸을 때 `run_sync`가 새 루프를 만들게 바뀌면 취소가 닿지 않는다. `test_stop_cancels_running_run_agent`가 실패해서 알 수 있다.
- 취소는 `handle`이 끝날 때까지 0.2초마다 다시 보낸다. 형식 오류 재요청처럼 `handle` 안에서 run이 이어지면, 뒤 run도 취소된다.
- 동기 DB 도구가 도는 중이면 취소는 그 문장이 끝날 때까지(`statement_timeout_ms`, 기본 5초) 늦다. 모델 호출은 바로 끊긴다.
- 종료 요청이 run이 끝나는 순간과 겹치면, 거의 끝난 run도 `cancelled`로 보고될 수 있다.
- `shutdown_timeout_seconds`(기본 30초) 안에 끝나지 않은 단계는 로그에 남기고 종료 코드 1로 끝낸다. 그 run의 Agent Log는 남지 않는다(`run_agent`가 끝날 때 쓰기 때문이다).
- **HuntVerifier는 `cancelled`도 시도 횟수에 넣는다(`verify.py`).** 종료가 `max_attempts`(2)번 겹치면 Hunt가 `failed`가 된다. L3 3-c에서 고친다.

### 확장 지점 (L3 3-c 훅)

훅은 만들지 않았다. 더할 때 손댈 곳은 아래뿐이다. 지금 구조가 훅을 막지 않는다.

| 시점 | 위치 |
|---|---|
| 라운드 전후(예: L3 가설 생성 run을 검증 poll 앞에) | `_StageThread._run`의 `self._round()` 앞뒤 |
| 워커 하나의 poll 전후, 건 하나의 handle 전후 | `_StageThread._round` |
| 등록·시작 | `Executor.__init__`(워커를 만든 직후), `Executor.start` |
| 종료 | `Executor.stop` |

- L3 가설 생성은 훅 대신 워커 하나로 만들 수도 있다. `poll`이 "생성할 차례면 표시 ID 하나"를 내는 식이다. 어느 쪽인지는 L3 3-c가 정한다.
- `soc.l3 hunt` 명령은 실행기와 따로 `poll(None)`을 쓴다. 이 이슈의 영향은 없다.

### L1 측정 시드와 실측의 함정

- **측정용 작업 프롬프트와 입력 모양은 L1 코드가 아니다.**
  - 입력은 `data = {"alert": {id, time, severity, title, rule_id, entities}, "window_start_ms", "window_end_ms"}`이다. 근거 장부는 그 Alert ID로 시작한다.
  - 조회 구간은 코드가 Alert 시각으로 계산한다: 6일 전부터 1일 뒤까지(합 7일 = `[tools] max_range_days` 기본값). 시나리오의 Alert·Event는 모두 이 구간 안에 있다(테스트로 확인).
  - L1 담당이 정할 프롬프트·입력과 다를 수 있다. 그때는 수치를 다시 잰다.
  - **시각 산수를 모델에게 시키지 않는다.**
    - 고치기 전 입력(Alert 시각만, "앞뒤 하루를 본다")에서는 모델 호출의 38~48%가 빈 응답이었다. message도 function_call도 없이 추론만 있었다.
    - 같은 설정의 L3 검증은 4%(51호출 중 2)였다.
    - 빈 응답의 추론 끝은 모두 "query_records를 부르자"는 계획이었다. 그 앞에 epoch 밀리초 ±1일 산수가 반복됐다.
    - L3 검증은 코드가 계산한 `window`(`from`·`to`)를 받아 이 산수가 없다.
    - L1 워커도 조회 구간을 코드가 계산해 `data`로 넘기고, 프롬프트는 "그 값을 도구의 start_ms·end_ms에 그대로 넣는다"고 쓰는 것이 좋다.
    - 고친 뒤 수치는 아래 "고친 뒤"에 채운다. 가설이 맞는지는 그 수치로 본다.
  - Alert에 판정 결과(`triage`)는 쓰지 않는다.
- **시드 표시는 RawRecord `siem_profile = "dev-seed-l1"`이다.**
  - L3 시드(`dev-seed`)와 서로 지우지 않는다.
  - 엔티티 값도 L3 시드와 겹치지 않는다(테스트로 확인).
  - 같은 개발 DB의 다른 Alert·Event(수집 데이터 등)는 모델이 도구로 볼 수 있다. 실측은 시드 말고는 비어 있는 개발 DB에서 하는 것이 좋다.
- **`[tools.allowed] l1`에서 `query_siem`을 빼고 잰다.** ELK가 없으면 도구 오류가 되고, 그 오류도 도구 오류 수에 섞인다.
- **집계 SQL은 `since`부터 센다.** 고치기 전 run이 같은 DB에 남아 있으므로 이번 라운드의 `seed` 직전 시각을 `-v since=…`로 넘긴다.
- **집계 SQL은 `remove` 전에 돌린다.** 시나리오 이름을 Alert → RawRecord로 찾기 때문이다. Agent Log는 지워도 남지만 시나리오 칸이 비게 된다.
- **`run_agent`가 모델을 부르기 전에 실패하면 Agent Log가 남지 않는다**(키 없음, 연결 설정 없음 등). 그런 run은 `run` 출력 줄(`failure=`)에서만 보인다.
- `decision`은 Agent Log에서 읽지 않는다(본문을 읽게 되므로). `run` 출력 줄로 센다.

### 다시 재는 법 (사람이 맥에서)

`config/local.toml`(커밋 안 함). `strict_mode`는 이제 기본이 `false`라 적지 않아도 된다.

```toml
[llm]
base_url = "https://<리소스 이름>.openai.azure.com/openai/v1/"
model = "<배포 이름>"
api_key_env = "LLM_API_KEY"

[tools.allowed]
l1 = ["get_alert", "get_event", "query_records", "query_http_flow", "summarize_http_flow"]
```

환경변수: `DATABASE_URL`, `AGENT_DATABASE_URL`(읽기 계정, `docs/notes/211-tool-registry.md`), `LLM_API_KEY`.

고친 뒤 1라운드(6 run):

```bash
uv run python -m soc.db.migrate
SINCE="$(date -u '+%Y-%m-%d %H:%M:%S+00')"         # 이번 라운드 시작 시각(이전 run을 빼기 위해)
uv run python -m soc.agent.dev_l1 seed            # 이전 시드를 지우고 다시 넣음
uv run python -m soc.agent.dev_l1 run | tee l1_round.txt   # 6 run. 출력 줄로 decision을 센다
psql "$DATABASE_URL" -v since="$SINCE" -f runs_l1.sql      # run별 숫자
psql "$DATABASE_URL" -v since="$SINCE" -f summary_l1.sql   # 합계·평균·빈 응답
uv run python -m soc.agent.dev_l1 remove
uv run pytest -m llm tests/test_l1_e2e_llm.py     # 1 run(임시 DB)
```

여러 라운드를 잴 때는 `SINCE`를 첫 라운드 전에 한 번만 정하고, `seed` → `run`을 라운드마다 되풀이한 뒤 SQL을 돌린다.

`run` 출력 한 줄의 모양(이유 본문 없음):

```text
malicious_powershell expected=malicious ok=True failure=- decision=malicious confidence=0.9 evidence=3 turns=3 tool_calls=2 tool_errors=0 tokens_in=9000 tokens_out=700 ms=5400 run_id=run_…
```

`runs_l1.sql`: run별 숫자(입력·출력 본문은 읽지 않고, 입력은 길이만)

```sql
SELECT min(l.started_at) AS started_at,
       l.run_id,
       min(split_part(r.siem_ref, '/', 1)) AS scenario,
       count(*) FILTER (WHERE l.kind = 'model') AS turns,
       count(*) FILTER (WHERE l.kind = 'tool') AS tool_calls,
       count(*) FILTER (WHERE l.kind = 'tool' AND l.outcome = 'error') AS tool_errors,
       string_agg(DISTINCT l.details->>'failure', ',') FILTER (WHERE l.kind = 'tool') AS tool_error_codes,
       coalesce(sum(l.tokens_in), 0) AS tokens_in,
       coalesce(sum(l.tokens_out), 0) AS tokens_out,
       round((coalesce(sum(l.tokens_in), 0) * 0.15
              + coalesce(sum(l.tokens_out), 0) * 0.60) / 1e6, 6) AS cost_usd,
       round(max(extract(epoch FROM l.started_at) * 1000 + l.duration_ms)
             - min(extract(epoch FROM l.started_at) * 1000)) AS span_ms,
       count(*) FILTER (WHERE l.kind = 'model' AND l.outcome = 'ok' AND NOT EXISTS (
           SELECT 1 FROM jsonb_array_elements(
               CASE WHEN jsonb_typeof(l.output) = 'array' THEN l.output ELSE '[]'::jsonb END) e
           WHERE e->>'type' IN ('message', 'function_call'))) AS empty_responses,
       max(length(l.input::text)) FILTER (WHERE l.kind = 'model') AS max_model_input_len,
       sum((l.details->>'retries')::int) FILTER (WHERE l.kind = 'model') AS retries_429,
       string_agg(DISTINCT l.details->>'failure', ',') FILTER (WHERE l.kind = 'model') AS run_failure,
       max(l.details->>'validation') AS validation
FROM agent_logs l
LEFT JOIN alerts a ON a.id = l.subject_id
LEFT JOIN raw_records r ON r.id = a.raw_id
WHERE l.stage = 'l1' AND l.details->>'task' = 'l1_e2e_probe'
  AND l.started_at >= :'since'::timestamptz
GROUP BY l.run_id
ORDER BY 1;
```

`summary_l1.sql`: 합계·평균. `hit_max_turns_6`은 `[agent.l1] max_turns`(기본 6)에 닿은 run 수다. 값을 바꾸면 숫자도 바꾼다.

```sql
WITH runs AS (
  SELECT run_id,
         count(*) FILTER (WHERE kind = 'model') AS turns,
         count(*) FILTER (WHERE kind = 'tool') AS tool_calls,
         count(*) FILTER (WHERE kind = 'tool' AND outcome = 'error') AS tool_errors,
         count(*) FILTER (WHERE kind = 'model' AND outcome = 'ok' AND NOT EXISTS (
             SELECT 1 FROM jsonb_array_elements(
                 CASE WHEN jsonb_typeof(output) = 'array' THEN output ELSE '[]'::jsonb END) e
             WHERE e->>'type' IN ('message', 'function_call'))) AS empty_responses,
         coalesce(sum(tokens_in), 0) AS tokens_in,
         coalesce(sum(tokens_out), 0) AS tokens_out,
         max(details->>'validation') AS validation,
         bool_or(details->>'failure' = 'budget_exceeded') AS budget_exceeded
  FROM agent_logs
  WHERE stage = 'l1' AND details->>'task' = 'l1_e2e_probe'
    AND started_at >= :'since'::timestamptz
  GROUP BY run_id
)
SELECT count(*) AS runs,
       count(*) FILTER (WHERE validation = 'ok') AS validation_ok,
       count(*) FILTER (WHERE budget_exceeded) AS budget_exceeded,
       count(*) FILTER (WHERE turns >= 6) AS hit_max_turns_6,
       sum(turns) AS model_calls,
       sum(empty_responses) AS empty_responses,
       round(100.0 * sum(empty_responses) / nullif(sum(turns), 0), 1) AS empty_pct,
       round(avg(turns), 1) AS avg_turns,
       max(turns) AS max_turns,
       round(avg(tool_calls), 1) AS avg_tool_calls,
       sum(tool_calls) AS tool_calls,
       sum(tool_errors) AS tool_errors,
       round(avg(tokens_in)) AS avg_tokens_in,
       round(avg(tokens_out)) AS avg_tokens_out,
       round(avg(tokens_in + tokens_out)) AS avg_tokens,
       round(avg(tokens_in * 0.15 + tokens_out * 0.60) / 1e6, 6) AS avg_cost_usd,
       round(sum(tokens_in * 0.15 + tokens_out * 0.60) / 1e6, 6) AS total_cost_usd
FROM runs;
```

- `empty_responses`는 성공한 모델 호출 중 출력 항목에 `message`도 `function_call`도 없는 것(추론만 있는 응답)이다. 항목의 `type`만 보고 본문은 읽지 않는다.
- `max_model_input_len`은 Agent Log에 저장된 입력 JSON의 길이다. 예산 검사(`max_input_chars`)와 같은 값이 아니라 근사로만 본다.
- 비교 기준(설계 추정): 평균 L1 작업 약 1.1만~1.8만 토큰, 약 $0.0035.

### 실측 결과

#### 고치기 전 (low 12 run, medium 6 run)

사람이 맥에서 쟀다(2026-11-05).

- 입력: Alert 시각만 있고, 프롬프트는 "alert.time 앞뒤 하루 안을 먼저 본다"
- 설정: `reasoning_effort` low로 12 run(2라운드), medium으로 6 run(1라운드), 모두 18 run. 나머지는 `[agent.l1]` 기본값

| 항목 | 값 |
|---|---|
| 빈 응답(모델 호출 중 message·function_call 없이 추론만) | 38~48% |
| 같은 설정의 L3 검증 빈 응답(비교) | 4%(51호출 중 2) |
| 빈 응답의 추론 끝 | 모두 "query_records를 부르자"는 계획. 그 앞에 epoch 밀리초 ±1일 산수가 반복됨 |

- 그 밖의 숫자(통과 수, 턴, 토큰, 비용, decision)는 이 기록에 받지 않았다. 필요하면 사람이 채운다.

#### 고친 뒤 (1라운드, 6 run)

- 입력: `window_start_ms`·`window_end_ms`(코드가 계산, Alert 시각 6일 전 ~ 1일 뒤)를 더하고, 프롬프트는 그 값을 도구에 그대로 넣으라고 함
- 설정: `reasoning_effort` (사람이 적음), 나머지는 `[agent.l1]` 기본값

| 항목 | 값 |
|---|---|
| run 수 / 계약·근거 통과(`validation = ok`) | |
| 모델 호출 / 빈 응답 / 빈 응답 비율 | |
| `budget_exceeded` / `max_turns` 6에 닿은 run | |
| 평균 턴 / 최대 턴 | |
| 평균 도구 호출 / 도구 오류(코드별) | |
| 평균 토큰(입력·출력) / 평균 비용 / 합계 비용 | |
| 시나리오별 decision(정상 2·위협 2·애매 2) | |
| `llm` 테스트 | |

### 예산 판단

- 기준(계획): `budget_exceeded` 0건이고 `max_turns` 6에 닿은 run이 없으면 `[agent.l1]` 기본값을 그대로 둔다. 하나라도 있으면 사람이 수치를 보고 정한다.
- 바꾸면 `config/default.toml`, `tests/test_agent_config.py`, 이 기록을 함께 고치고 아래 알림 목록에 더한다.

### 연구 레포 설계 문서 수정 알림 목록

연구 레포 `0-Ticket/soc-incident-response-research`, 기준 커밋 `84a6139`.

- **기준 커밋이 main에 없다.** `84a6139`은 `Interludeal` 브랜치에만 있다. 이슈가 가리키는 기준을 main에 둘지 정해야 한다.
- `설계/01-SDK와 모델.md` "`strict` 처리": "기본값은 `true`, 거부되면 끈다" → Foundry는 400이 아니라 빈 답으로 거부해서 기본값을 `false`로 바꿨다(#224, #215).
- `설계/02-인터페이스.md` "AgentWorker", `파이프 전달 사항.md` 2·3절: 등록 방법(`[executor.<stage>] workers = ["soc.<모듈>:build_worker"]`, `build_worker(config)`), 설정 키(`interval_seconds`, `poll_limit`, `shutdown_timeout_seconds`), "`handle` 안에서 이벤트 루프를 만들지 않는다"를 더한다.
- `설계/08-실행기.md`: 바꿀 것 없음(이미 "스레드마다 이벤트 루프"). 실행 명령 `uv run python -m soc.agent`와 기본값(L1·L2 10초·10건, L3 0, 종료 대기 30초)은 더하면 좋다.
- `설계/03-에이전트 내부.md` "예산", `설계/01-SDK와 모델.md` "비용": 실측 뒤 값을 바꾸면 더한다.

### 담당 알림 초안 (사람이 올림)

L1 담당:

```text
#215 실행기가 정한 워커 틀입니다. L1 워커는 L1 담당이 만듭니다.
- AgentWorker(soc.agent.AgentWorker): stage="l1", name, poll(limit:int)->Sequence[str], handle(subject_id)->None
- 등록: config/default.toml [executor.l1] workers = ["soc.l1.<모듈>:build_worker"]
  build_worker(config)->AgentWorker. config는 설정 전체, DB 주소·키는 워커가 환경변수에서 읽습니다
- 실행: uv run python -m soc.agent (기본 10초 간격, 한 번에 10건, 단계 안 1건씩)
- 지킬 것: handle 멱등, 판정이 기록된 건은 poll에서 빼기, 시도 횟수는 워커가 셈,
  cancelled는 실패로 세지 않고 다시(설계 02-인터페이스 L1 처리 표)
- handle 안에서 asyncio.run 등 이벤트 루프를 만들지 않기, DB 연결은 handle마다
- [llm] strict_mode 기본값이 false가 됐습니다(Foundry, #224)
- 측정용 L1 실측 수치와 방법: docs/notes/215-executor-l1-e2e.md (측정용 프롬프트·입력 기준이라 L1 프롬프트가 정해지면 다시 잽니다)
- 조회 구간은 코드가 계산해 data로 넘기고, 프롬프트는 "그 값을 도구의 start_ms·end_ms에 그대로 넣으라"고 써 주세요. 모델에게 epoch 밀리초 산수를 시켰더니 빈 응답이 38~48%였습니다(L3는 코드가 window를 넘겨 4%)
- 판정 결과 조건(D-025)은 L1 담당이 정합니다
```

L2 담당(#228):

```text
#228 관련: #215 실행기가 정한 워커 틀입니다.
- AgentWorker(soc.agent.AgentWorker): stage="l2", name, poll(limit:int)->Sequence[str], handle(subject_id)->None
- 등록: config/default.toml [executor.l2] workers = ["soc.l2.branch.worker:build_worker"]
  build_worker(config)->AgentWorker. config는 설정 전체(config["l2"]를 읽으면 됩니다), DATABASE_URL은 워커가 읽습니다
- 키: [executor.l2] interval_seconds(기본 10, 0이면 안 돎), poll_limit(기본 10). 실행: uv run python -m soc.agent
- 실행기는 poll에 항상 정수를 넘깁니다. 결과가 기록된 건은 다시 내지 않기, handle 멱등
- handle 예외는 실행기가 잡아 로그만 남깁니다. 같은 건이 계속 실패하면 매 라운드 다시 나오므로 시도 횟수는 워커가 셉니다
- 종료하면 run_agent가 failure=cancelled로 돌아옵니다. 실패 횟수에 넣지 않기를 권합니다
- handle 안에서 asyncio.run 등 이벤트 루프를 만들지 않기, DB 연결은 handle마다
- llm 마커: 기본 실행·CI 제외, uv run pytest -m llm <파일>, 키는 LLM_API_KEY만(tests/test_l1_e2e_llm.py, tests/test_l3_hunt_llm.py 참고)
- [llm] strict_mode 기본값이 false가 됐습니다(Foundry, #224)
- #227 워커가 이 틀을 따르면 #228의 등록은 설정 한 줄입니다
```

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run pytest`: 963건 통과(`config/local.toml` 없음). 조회 구간을 더하기 전에는 962건
- `uv run pytest -m db`: 243건 통과. Docker가 없어 임시 PostgreSQL 16(trust 인증)으로 돌렸다
- `uv run pytest -m llm tests/test_l1_e2e_llm.py`(세션, 모델 설정 없음): `provider_error`(LLM 연결 설정이 없다)로 실패. 시드·읽기 계정·`run_agent`까지 연결만 확인했다(실제 모델 호출 0회)
- 실행기 테스트(`tests/test_agent_executor.py`) 10번 반복: 매번 34건 통과
- 테스트를 먼저 쓰고, `AgentWorker`가 없어 실행기 테스트 파일이 수집 단계에서 실패하는 것을 봤다(`dev_l1`은 위 "계획과 달라진 점")
- 손으로 확인
  - 가짜 모델 + 임시 DB + 실제 도구(읽기 계정): `seed`(Alert 6, Event 17, RawRecord 23) → 위협 Alert 1건 `run_task`. `query_records`가 그 호스트의 Event 4건을 돌려줬고, Verdict가 계약·근거 장부를 통과했다(`ok`). Agent Log 3줄(model·tool·model)
  - 같은 DB에서 `runs_l1.sql`(2 run)·`summary_l1.sql`이 돈다
  - `since`·빈 응답을 더한 SQL: 가짜 Agent Log(추론만 있는 호출 1, 정상 호출 3, `since` 전 run 1)로 `empty_responses` 1/4, `since` 전 run 제외를 확인했다
  - 실제 프로세스에 SIGTERM: "종료 중" 출력 후 종료 코드 0
  - `uv run python -m soc.agent`(기본 설정): "등록된 워커가 없다" 후 종료 코드 0
- 주요 테스트
  - `tests/test_agent_executor.py`
    - 단계 간 병렬(두 단계의 handle이 서로를 기다림)
    - 단계 안 순차·등록 순서·`poll_limit`
    - 예외 격리(handle·poll, 로그에 메시지 없음)
    - `interval_seconds = 0`이면 poll 없음
    - 종료 시 `cancelled` + Agent Log 줄, 종료 요청 뒤에 시작한 run도 취소, 종료 대기 시간 초과
    - 등록 오류(`soc.` 밖, 모양, 없는 모듈·함수, stage 불일치, name 중복, 생성 실패), 설정 값 오류, 기본값, `main`
  - `tests/test_agent_dev_l1.py`(DB 없음)
    - 문서용 IP·example 도메인, 시나리오 2·2·2, L3 시드와 엔티티 겹치지 않음, 7일 범위
    - 행 계약, 새 ID, 틀린 `ago_ms`, 프롬프트 금지 문구·버전, 작업 모양, 출력 줄에 이유 없음, 주소 숨김
  - `tests/test_agent_dev_l1_db.py`
    - 넣기, 다시 넣기, 지우기(L3 시드·Agent Log 남김)
    - 모델에게 보일 칸, run이 Alert마다 1번이고 `triage`를 쓰지 않음, 명령 종료 코드
  - `tests/test_l1_e2e_llm.py`(`llm`): 실제 모델 1건
