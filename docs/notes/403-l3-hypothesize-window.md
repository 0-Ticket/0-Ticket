---
issue: 403
date: 2026-11-27
owner: Pandyo
plan: 403-l3-hypothesize-window.md
supersedes: []
---

# 가설 생성 입력에 조회 구간 window를 넣었다 (실측은 아직)

## 한 일

- 가설 생성 run의 입력 `data`에 검증 run과 같은 `window`(`from`, `to`, UTC epoch 밀리초)가 들어간다. `to`는 생성 시각이고 `from`은 `[l3.hunt] lookback_days`일 앞이다.
- 계산은 `soc.l3.hunt.settings.lookback_window(settings, now)` 하나다. `verify.py`의 `handle`도 이 함수를 쓰며, 검증 입력의 값은 전과 같다.
- `l3_hypothesize.md`가 `window`를 설명하고 조회 도구를 부를 때 `from`→`start_ms`, `to`→`end_ms`로 그대로 쓰게 한다. `l3_verify.md`는 바꾸지 않았다.
- `config/default.toml`의 `lookback_days` 주석이 가설 생성에도 쓴다고 적는다. 새 설정 키와 환경변수는 없다.
- **`format_error`의 원인이 구간이라는 것은 아직 추정이다.** 아래 실측(완료 기준의 마지막 항목)은 사람이 한다.

## 계획과 달라진 점

없음.

## 다음 사람이 알아야 할 것

- **실측 전에는 효과를 모른다.** 단위·DB 테스트는 입력에 `window`가 들어간다는 것만 보인다. 모델이 그것을 쓰는지는 실측으로만 안다.
- **`soc.l3 hunt`는 `pending` Hunt를 전부 검증한다**(`docs/notes/224-l3-real-model.md` "시드와 실측의 함정"). 비용을 줄이려면 실행 전에 아래가 0인지 본다.

  ```sql
  SELECT count(*) FROM hunts WHERE status = 'pending' AND NOT details @> '{"dev_seed": true}';
  ```

- 조회 도구 허용 목록은 이제 단계가 아니라 태스크 이름 키다(`[tools.allowed] l3_hypothesize` 등, `config/default.toml`). `docs/notes/224-l3-real-model.md`의 `local.toml` 예시(`l3 = [...]`)를 그대로 쓰지 않는다. `config/local.toml`에서 `l3_hypothesize`를 덮어쓰지 않으면 기본 목록을 쓴다.
- 이 개발 PC의 `uv run pytest`에서 `test_agent_task_tools.py` 2건, `test_tools_get_raw.py`, `test_tools_siem.py`, `test_tools_ssh.py` 각 1건이 실패한다. `main`에서도 같은 5건이 실패해 이 변경과 무관하다. 원인은 따로 보지 않았다.
- 아래 조회 SQL은 가짜 행으로만 실행해 봤다. 실제 Agent Log 행에서 `input`의 모양이 다르면(예: `window`가 `<data>` 안에 다른 공백으로 직렬화) `window_in_input` 열이 비어 나올 수 있다. 그때는 모델 줄의 `input`을 직접 읽어 `window`를 확인한다.

## 확인 방법

실행한 명령과 테스트(구현 결과):

- `uv run ruff format --check .`, `uv run ruff check .` 통과
- `uv run pytest`: 2,697개 통과, 5개 실패(위의 기존 실패), 835개 제외
- `DATABASE_URL`을 지정해 `uv run pytest -m db tests/test_l3_hunt_db.py tests/test_l3_hunt_worker_db.py tests/test_l3_attempts_db.py`: 57개 통과
- 주요 테스트: `test_lookback_window_counts_back_lookback_days_from_now`(DB 없음), `test_hypothesize_task_reads_recent_news_and_cases`의 `window` 단언, 기존 `test_verify_task_has_hypothesis_techniques_and_window`(검증 입력 불변)

### 실측 절차 (사람이 한다)

준비는 `docs/notes/224-l3-real-model.md` "다시 재는 법"과 같다. `DATABASE_URL`, `AGENT_DATABASE_URL`, `LLM_API_KEY`를 넣고, ATT&CK이 DB에 있어야 가설 생성을 건너뛰지 않는다. 이 브랜치로 실행한다.

```bash
uv run python -m soc.db.migrate
uv run python -m soc.l3.intel          # ATT&CK이 없으면 가설 생성을 건너뛴다
uv run python -m soc.l3 hunt           # 이것을 3번 돌린다(실행마다 가설 생성 run 1개)
psql "$DATABASE_URL" -f runs403.sql    # 3번이 끝난 뒤 한 번
psql "$DATABASE_URL" -f args403.sql
```

`soc.l3 hunt`는 실행마다 가설 생성을 하므로(`generate_interval_seconds`를 보지 않는다) 3번이면 가설 생성 run이 3개다. 두 SQL은 최근 1일의 가설 생성 run(`details.task = 'l3_hypothesize'`)만 본다. 아래 SQL을 각각 `runs403.sql`, `args403.sql`로 저장한다. 본문은 읽지 않고 숫자와 `window` 값만 낸다.

`runs403.sql`: 가설 생성 run별 결과(`reasoning_only`는 message도 function_call도 없이 추론만 있는 모델 응답 수)

```sql
SELECT min(started_at) AS started_at,
       run_id,
       count(*) FILTER (WHERE kind = 'model') AS model_turns,
       count(*) FILTER (WHERE kind = 'model'
                        AND jsonb_typeof(output) = 'array'
                        AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(output) e
                                        WHERE e->>'type' IN ('message', 'function_call'))
       ) AS reasoning_only,
       count(*) FILTER (WHERE kind = 'tool') AS tool_calls,
       string_agg(DISTINCT details->>'failure', ',') AS failures,
       max(details->>'validation') AS validation
FROM agent_logs
WHERE run_id IN (SELECT run_id FROM agent_logs WHERE details->>'task' = 'l3_hypothesize'
                 AND started_at >= now() - interval '1 day')
GROUP BY run_id
ORDER BY 1;
```

`args403.sql`: 가설 생성 run의 조회 호출 인자와 입력에 들어간 `window`

```sql
WITH hyp AS (
  SELECT DISTINCT run_id FROM agent_logs
  WHERE details->>'task' = 'l3_hypothesize' AND started_at >= now() - interval '1 day'
), win AS (
  SELECT run_id,
         min(substring(replace(input::text, '\"', '"') FROM '"window": *\{[^}]*\}')) AS window_in_input
  FROM agent_logs WHERE kind = 'model' AND run_id IN (SELECT run_id FROM hyp) GROUP BY run_id
)
SELECT t.run_id, t.seq, t.name,
       t.input->>'start_ms' AS start_ms,
       t.input->>'end_ms' AS end_ms,
       (t.input->>'end_ms')::bigint - (t.input->>'start_ms')::bigint AS span_ms,
       w.window_in_input
FROM agent_logs t JOIN win w USING (run_id)
WHERE t.kind = 'tool' AND t.name IN ('query_siem', 'count_siem', 'query_records')
ORDER BY t.run_id, t.seq;
```

PR에 적을 표(실행마다 한 줄):

| 실행 | 가설 생성 성공(`failures`에 `format_error` 없음) | 조회 호출 수 | `start_ms`·`end_ms`가 `window`와 같은가 | 추론만 있는 응답 수(`reasoning_only`) |
|---|---|---|---|---|
| 1 | | | 같음 / 다름 / 확인 못 함(조회 0회) | |
| 2 | | | | |
| 3 | | | | |

판정:

- 통과: 3번 모두 가설 생성에 `format_error`가 없고, 조회를 호출했다면 `start_ms`·`end_ms`가 `window` 값과 같다.
- 조회를 한 번도 부르지 않은 실행은 "확인 못 함"으로 적는다.
- `window`를 정확히 썼는데도 추론만 있는 응답으로 실패하면 구간만의 문제가 아니라고 여기에 기록하고 별도 이슈 초안을 만든다.
- `window`를 쓰지 않았으면 `l3_hypothesize.md`를 고친다.
