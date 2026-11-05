---
issue: 224
date: 2026-11-05
owner: Pandyo
plan: 224-l3-real-model.md
supersedes: []
---

# L3 헌팅을 실제 모델(Foundry gpt-oss-120b)로 재고, 개발용 시드와 기본값 테스트를 보완했다

## 한 일

- **실측.** #223의 L3 헌팅(가설 생성 run → 검증 run)을 Azure Foundry `gpt-oss-120b`로 돌려 쟀다(사람이 맥에서 함, 아래 "실측 결과").
  - 가설 생성은 3/3, 검증은 9/9가 출력 계약을 통과했다.
  - 위협 있음 시나리오는 3/3 `confirmed`이고 L3 Ticket이 만들어졌다. 위협 없음 시나리오는 `rejected` 1, `inconclusive` 2다.
  - 12 run 비용은 약 $0.027이다.
- **`uv run python -m soc.l3 dev-seed`.** 개발 DB에 검증 실측용 시드를 넣는다. 이전 시드는 지우고 다시 넣는다. `--remove`는 지우기만 한다.
  - 시드는 `pending` Hunt 2개(위협 있음·없음)와 근거 Alert 1·Event 5(원본 6)다. 샘플은 `tests/fixtures/l3_hunt/dev_seed.json`이다.
  - 레코드 시각은 넣는 시점 기준이라 검증 조회 기간(7일) 안에 든다.
  - 지우기는 시드 Hunt의 L3 Ticket·시드 Hunt·시드 원본과 그것을 가리키는 Alert·Event만 지운다. Agent Log는 남긴다. 시드 Ticket이 Incident에 붙어 있으면 아무것도 지우지 않는다.
- **기본값 테스트.** 기본값을 검사하는 테스트가 저장소 `config/`(`local.toml` 포함) 대신 `default.toml`만 복사한 임시 폴더(`conftest.py`의 `default_config_dir`)를 읽는다. 검사 내용은 같다. 이제 `config/local.toml`이 있어도 `uv run pytest`가 통과한다. 고친 테스트는 아래와 같다.
  - `test_agent_config.py` 3건
  - `test_l3_config.py` 2건
  - `test_l3_hunt.py` 1건
  - `test_tools_siem.py` 1건, `test_tools_ssh.py` 1건
- **실제 모델 테스트 1건.** `tests/test_l3_hunt_llm.py`(`llm` 마커)는 임시 DB에 시드를 넣고 위협 있음 Hunt를 운영 경로(`run_agent`)로 검증한다.
- **Foundry 확인 결과**와 **strict 빈 응답**(코어 담당 안건), **400 `tool_use_failed`·boannews 재현 결과**를 아래에 적었다. 코어 코드(`src/soc/agent/`, `src/soc/tools/`)와 수집 코드(`soc.l3.intel`)는 고치지 않았다.

## 계획과 달라진 점

- **도구 담당 테스트 2건도 고쳤다(계획 "바뀐 점", 사람이 정함).** 실측 `local.toml`이 `[tools.allowed] l3`를 줄이자 `test_tools_siem.py::test_default_config_has_siem_settings_without_secrets`, `test_tools_ssh.py::test_default_config_has_ssh_settings_and_no_hosts`도 실패했다. 이 두 건도 `default_config_dir`로 읽게 했다.
- **400 `tool_use_failed`는 재현되지 않아 코어를 고치지 않았다(계획 "바뀐 점").**
- **Alert·Event에는 `details.dev_seed`를 넣지 않았다.** 계획은 Alert·Event·Hunt 모두 `details.dev_seed = true`였다. 그런데 에이전트 도구(`get_alert`·`get_event`)는 `details`를 모델에게 그대로 보여 준다. 모델이 "개발용 시드" 표시를 보면 실측이 흐려진다. 그래서 Alert·Event는 시드 원본(`siem_profile = "dev-seed"`)을 가리키는 것(`raw_id`)으로 찾는다. Hunt는 계획대로 `details.dev_seed = true`이고, 시나리오 이름을 `details.scenario`(`threat`·`no_threat`)에 더 넣었다. 검증 run 입력에는 Hunt `details`가 들어가지 않는다.
- **`llm` 테스트에 `db` 마커를 붙이지 않았다.** 계획은 `llm`·`db` 마커였다. 그런데 `db` 마커를 붙이면 CI의 db job(`uv run pytest -m db`)이 이 테스트를 골라 키 없이 실제 모델을 부르려다 실패한다. DB는 `temp_database` fixture가 그대로 요구한다.
- **`dev-seed` 종료 코드에 2를 더했다.** `DATABASE_URL`이 없거나 샘플이 계약에 맞지 않으면 2다. `soc.l3 hunt`의 설정 오류(2)와 맞췄다.
- **`soc.l3.__main__`에 `build_parser()`를 두었다.** 도움말에 "개발 DB 전용"이 있는지 테스트하기 위해서다.
- **`test_l3_config.py`의 `valid_l3()`를 지웠다.** 쓰던 곳이 하나라서 그 테스트가 `default_config_dir`을 받게 했다.
- **boannews는 세션에서도 재현했다.** LLM 비용이 들지 않아 진단 스크립트를 확인하면서 같이 돌렸다. 맥 재현은 계획대로 사람이 했다.

## 실측 결과

사람이 맥에서 쟀다(2026-11-05).

- 설정: `strict_mode = false`, `[tools.allowed] l3`는 내부 DB 도구 5개, `[agent.l3]` 기본값(max_turns 10, max_input_chars 48,000, reasoning_effort medium)
- 순서: `dev-seed` → `soc.l3 hunt`를 3라운드
- 측정 대상: 03:33 이후 12 run(가설 생성 3, 검증 9)
- 검증 9 = 라운드마다 시드 2 + 그 라운드에 생성된 가설 1
- 가설·이유 원문은 적지 않는다

### 가설 생성 run (3)

| 항목 | 값 |
|---|---|
| 출력 계약 | 3/3 첫 응답에서 통과(재요청 없음) |
| 턴 | 1 |
| 도구 호출 | 0 (strict를 끈 뒤의 4 run 모두 0) |
| 입력 토큰 | 2,932 |
| 출력 토큰 | 313~1,042 |
| 시간 | 3.3~6.3초 |

### 검증 run (9)

| 시나리오 | 결과 |
|---|---|
| 위협 있음(시드) | `confirmed` 3/3, L3 Ticket 3/3 |
| 위협 없음(시드) | `rejected` 1/3, `inconclusive` 2/3 |
| 생성된 가설(라운드마다 1) | 결과별 건수는 받지 않음 |

| 항목 | 값 (9 run 평균) |
|---|---|
| 출력 계약 | 9/9 통과(실패 종류 없음) |
| 턴 | 5.3 |
| 도구 호출 | 4.1 (합계 37회, 오류 4회) |
| 입력 토큰 | 약 12,800 |
| 출력 토큰 | 약 1,400 |

- 도구 오류 4회는 모두 `invalid_argument`이고 2라운드에 몰려 있다.
- 2라운드 위협 없음 run은 10턴(`max_turns` 10)까지 써서 성공했다. 한도에 닿은 사례 1건이다.

### 전체

| 항목 | 값 |
|---|---|
| 비용 추정 | 12 run 약 $0.027, 라운드당 약 $0.009(입력 $0.15·출력 $0.60 / 1M 토큰) |
| 429 | 0회 |
| 모델 호출 한 번의 입력 최대 | 16,267자(`max_input_chars` 48,000 안) |
| `budget_exceeded` | 0회 |
| `llm` 마커 테스트 | 1 passed(13.7초) |

### strict를 켠 이전 실행 (측정 대상 아님)

- 02:19~02:27에 strict를 켠 채 돌린 5 run은 5/5 `format_error`였다. 아래 "strict 빈 응답"과 같은 증상이다.
- strict를 끄고 돌린 첫 run은 형식 오류 재요청 1번 뒤 통과했다.

### 실측에서 판단한 것

- **L3 예산 기본값은 바꾸지 않았다.** `budget_exceeded`가 없었다. 계획대로 수치만 적는다. `max_turns`에 닿은 run이 1건(성공) 있었다. 실데이터 실측(#218·#234 이후)에서 다시 본다.
- **가설 생성 run은 L3 도구를 쓰지 않았다**(4 run 모두 도구 호출 0, 1턴). 2층 `l3.md`의 검증용 문장("가설 → 집계 → 레코드")이 가설 생성 run에 붙어도 도구 호출이나 턴 낭비로 이어지지 않았다. 변경 안건은 올리지 않는다.
- **위협 없음 판정이 흔들린다(별도 안건).** 같은 시드로 `rejected` 1, `inconclusive` 2였다. `rejected`는 근거가 1개 이상 있어야 하고, 없으면 코드가 `inconclusive`로 낮춘다(#223). 그래서 모델이 근거를 대지 않았거나, 스스로 `inconclusive`를 냈을 수 있다. 어느 쪽인지 이번 수치로는 구분하지 않았다. 이 이슈에서 프롬프트는 고치지 않는다.

## 다음 사람이 알아야 할 것

### Foundry (사람이 확인함, 2026-11-05)

| 항목 | 값 |
|---|---|
| 모델 | `gpt-oss-120b`(OpenAI, Sold by Azure), 버전 4 |
| 배포 유형·리전 | Global Standard, West US 3 |
| TPM/RPM | 실제 할당량 미확인(참고치 500만/5천). 실측 중 429 0회 |
| 단가 | 입력 $0.15 / 출력 $0.60 (1M 토큰당) |
| 무료 크레딧 | 약 26.7만 원, 적용 여부 미확인 |
| 계획 전 사용량 | 27회 호출, 약 9.21만 토큰, 예상 약 25원 |
| `strict` | 빈 응답으로 거부(사람이 확인함). 아래 |

- 클라우드 세션(프록시 경유)에서도 Foundry 주소까지 연결된다. 키 없이 보내 401을 받았다.

### strict 빈 응답 (코어 담당 안건)

- Foundry에서 도구 정의에 strict를 켜면(`[llm] strict_mode = true`) 최종 답(content)이 빈 문자열로 온다. strict를 끄거나 도구가 없으면 정상이다. 추론 강도·출력 상한과는 관계없다.
- 지금 코어에서는 빈 content가 JSON 파싱 실패 → 형식 오류 재요청 → `format_error`로 끝난다. strict를 켠 이전 실행 5/5가 `format_error`였다.
- 코어는 고치지 않았다. 코어 담당(#209·#210·#211)이 정할 것:
  1. 기본값 `strict_mode = true`를 기본 LLM(Foundry)에 맞춰 바꿀지
  2. 빈 content를 다른 형식 오류와 구분해 기록할지
- 그전까지 Foundry를 쓰는 사람은 `config/local.toml`에 `strict_mode = false`를 둔다.

### 400 `tool_use_failed`

- **Foundry에서 재현되지 않았다**(검증 9 run, 도구 호출 37회, 400 0회). Groq에서만 난 것으로 보고 코어는 고치지 않았다. 지금 키가 Azure 키라 Groq에서는 다시 재현하지 않았다.
- 지금 규칙: 400은 `RetryingModel`이 다시 부르지 않는다(429만). `run_task`가 `provider_error`로 끝내고, Hunt는 `attempts`만 오른다. `max_attempts`(2)에 이르면 `failed`다.
- Groq로 되돌려 쓸 때(D-009) 이 실패가 다시 나면 그때 원인을 보고 정한다. `tool_use_failed` 코드만 보고 재시도하면 #210이 피한 제공자별 분기가 생긴다.

### boannews 수집 실패

| 환경 | 결과 |
|---|---|
| 맥(사람) | 0/15 실패 |
| 클라우드 세션(프록시 경유, httpx 0.28.1) | 4/24 실패 |

- 세션에서 난 실패는 모두 연결 단계 `ConnectError`(← `ConnectionResetError`)였다.
- 요청 헤더를 바꾼 세 변형(기본 / 압축 끔 / curl과 같은 User-Agent)을 번갈아 돌렸는데, 헤더와 관계없이 가끔 끊기고 바로 다음 시도는 성공했다.
- 그래서 원인은 환경(프록시 경유 연결)이고, `soc.l3.intel` 코드는 고치지 않았다.
- 응답 크기가 요청마다 다르다(압축 해제 후 311,021~322,905바이트). 같은 주소를 서로 다른 캐시 서버가 답하는 것으로 보인다.
- 수집에는 재시도가 없어서, 한 번 끊기면 그 실행에서는 그 출처가 `network`로 끝난다. 헌팅은 저장된 뉴스로 계속된다(#223).

### 테스트와 `config/local.toml`

- **도구 담당(#212·#213) 테스트 2건을 고쳤다.** 읽는 설정 위치만 바뀌었다.
- **`tests/test_l2_config.py`도 같은 모양이다**(저장소 `config/`를 합쳐 읽는다). 이번 `local.toml`은 `[l2]`를 건드리지 않아 실패하지 않았다. 고칠지는 L2 담당이 정한다. `conftest.py`의 `default_config_dir`을 쓰면 된다.
- 같은 두 파일의 다른 테스트(`test_default_config_passes_the_config_check` 등)도 저장소 `config/`를 읽는다. `local.toml`에 `[tools.siem]`·`[[tools.ssh.hosts]]` 같은 값을 넣으면 실패할 수 있다. 이번에는 실패하지 않아 그대로 두었다.
- `elk`·`ssh` 마커 테스트는 일부러 `local.toml`을 읽으므로 그대로다.
- `llm` 마커 테스트는 임시 LOGIN 역할을 만든다. `DATABASE_URL` 계정에 CREATEROLE이 필요하다(`test_tools_db.py`와 같다).

### 시드와 실측의 함정

- **`soc.l3 hunt`는 `pending` Hunt를 전부 검증한다.** 시드가 아닌 `pending` Hunt가 있으면 그것도 검증 run을 돌려 비용이 는다. 실측 전에 아래 값이 0인지 본다.

  ```sql
  SELECT count(*) FROM hunts WHERE status = 'pending' AND NOT details @> '{"dev_seed": true}';
  ```

- **시드 Hunt 결과는 다음 `dev-seed` 전에 읽는다.** `dev-seed`가 이전 시드를 지운다. Agent Log는 남는다.
- **위협 없음 Hunt를 검증할 때도 위협 있음 시나리오의 레코드가 같은 DB에 있다.** 모델이 그것을 근거로 들 수 있다.
- 다른 Ticket의 `alert_ids`가 시드 Alert를 가리켜도 FK가 없어 막지 않는다. 지금은 그런 Ticket을 만드는 단계가 없다.
- **`run_agent`가 모델을 부르기 전에 실패하면 Agent Log가 남지 않는다**(키 없음, 연결 설정 없음 등). 아래 집계 SQL에는 그 run이 빠지므로 Hunt의 `details.verify_failures`로 센다.

### 다시 재는 법

`config/local.toml`(커밋 안 함):

```toml
[llm]
base_url = "https://<리소스 이름>.openai.azure.com/openai/v1/"
model = "<배포 이름>"
api_key_env = "LLM_API_KEY"
strict_mode = false

[tools.allowed]
l3 = ["get_alert", "get_event", "query_records", "query_http_flow", "summarize_http_flow"]
```

환경변수: `DATABASE_URL`, `AGENT_DATABASE_URL`(읽기 계정, `docs/notes/211-tool-registry.md`), `LLM_API_KEY`.

```bash
uv run python -m soc.db.migrate
uv run python -m soc.l3.intel                       # ATT&CK이 DB에 없으면 가설 생성을 건너뛴다
uv run python -m soc.l3 dev-seed                    # 라운드마다
uv run python -m soc.l3 hunt                        # 라운드마다(최대 4 run)
psql "$DATABASE_URL" -f hunts.sql                   # 라운드마다, 다음 dev-seed 전에
psql "$DATABASE_URL" -f runs.sql                    # 모든 라운드가 끝나면 한 번
uv run pytest -m llm tests/test_l3_hunt_llm.py      # 1 run
```

`hunts.sql`: 이번 라운드 Hunt 결과(본문 없이 상태·건수만)

```sql
SELECT coalesce(details->>'scenario', 'generated') AS scenario,
       status,
       attempts,
       cardinality(evidence_ids) AS evidence,
       confidence,
       details->'downgraded'->>'from' AS downgraded_from,
       (SELECT count(*) FROM tickets t WHERE t.hunt_id = h.id) AS tickets,
       details->'verify_failures'->-1->>'failure' AS last_failure
FROM hunts h
WHERE updated_at >= now() - interval '1 hour'
ORDER BY created_at;
```

`runs.sql`: run별 숫자(입력·출력 본문은 읽지 않고, 입력은 길이만)

```sql
SELECT min(started_at) AS started_at,
       run_id,
       min(details->>'task') AS task,
       min(subject_id) AS subject_id,
       count(*) FILTER (WHERE kind = 'model') AS turns,
       count(*) FILTER (WHERE kind = 'tool') AS tool_calls,
       count(*) FILTER (WHERE kind = 'tool' AND outcome = 'error') AS tool_errors,
       coalesce(sum(tokens_in), 0) AS tokens_in,
       coalesce(sum(tokens_out), 0) AS tokens_out,
       round((coalesce(sum(tokens_in), 0) * 0.15
              + coalesce(sum(tokens_out), 0) * 0.60) / 1e6, 6) AS cost_usd,
       round(max(extract(epoch FROM started_at) * 1000 + duration_ms)
             - min(extract(epoch FROM started_at) * 1000)) AS span_ms,
       max(length(input::text)) FILTER (WHERE kind = 'model') AS max_model_input_len,
       sum((details->>'retries')::int) FILTER (WHERE kind = 'model') AS retries_429,
       string_agg(DISTINCT details->>'failure', ',') AS failures,
       max(details->>'validation') AS validation
FROM agent_logs
WHERE stage = 'l3' AND started_at >= now() - interval '1 day'
GROUP BY run_id
ORDER BY 1;
```

- `max_model_input_len`은 Agent Log에 저장된 입력 JSON의 길이다. 예산 검사(`max_input_chars`: system 지시 + 입력 항목 JSON)와 같은 값이 아니라서 근사로만 본다. 예산을 넘으면 `failures`에 `budget_exceeded`가 남는다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run pytest`: 910건 통과. `config/local.toml`이 없을 때와, 실측과 같은 모양(LLM 설정 + `[tools.allowed] l3` 축소 + `[l3.hunt] collect_before = false`, 주소는 자리표시)일 때 모두 같다. 고치기 전에는 `local.toml`이 있으면 5건이 실패했다
- `uv run pytest -m db`: 237건 통과. Docker가 돌지 않아 임시 PostgreSQL 16(trust 인증)으로 돌렸다. `llm` 테스트가 여기에 섞이지 않는 것을 확인했다(`-m llm`으로는 1건만 모인다)
- `uv run pytest -m llm tests/test_l3_hunt_llm.py`
  - 사람이 맥에서 Foundry로 1 passed(13.7초)
  - 세션에서는 `LLM_API_KEY`를 빼고 돌려, 시드 → 검증 → `provider_error`로 `pending` 유지까지 연결만 확인했다(실제 모델 호출 0회)
- 테스트를 먼저 쓰고, `soc.l3.hunt.dev_seed`가 없어 두 시드 테스트 파일이 수집 단계에서 실패하는 것을 봤다
- 손으로 확인(임시 DB): `soc.db.migrate` → `dev-seed`(넣음 hunts 2, alerts 1, events 5, raw_records 6) → `dev-seed`(같은 건수 지우고 다시 넣음) → `hunts.sql`(pending 2) → 샘플 Agent Log로 `runs.sql` → `dev-seed --remove`(hunts 2 등 지움)
- 주요 테스트
  - `tests/test_l3_dev_seed.py`(DB 없음): 샘플이 문서용 IP·`example.com`만 씀, 두 시나리오와 `ago_ms` 범위, 행이 계약을 통과하고 시각이 지금 기준, 매번 새 ID, 틀린 `ago_ms` 거부, 도움말의 "개발 DB 전용"
  - `tests/test_l3_dev_seed_db.py`
    - 넣기와 다시 넣기
    - 시드 행만 지우고 시드가 아닌 행·Agent Log는 남김, L3 Ticket 함께 지움
    - Incident에 붙으면 넣기·지우기 모두 거부, 빈 DB 지우기
    - 명령: 출력(가설 본문 없음), `--remove`, 거부 시 종료 1, `DATABASE_URL` 없음 2, DB 오류 1(주소 없음)
  - `tests/test_l3_hunt_llm.py`(`llm`): 실제 모델 검증 1건
