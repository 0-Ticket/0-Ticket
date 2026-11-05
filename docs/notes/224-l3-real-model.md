---
issue: 224
date: 2026-11-05
owner: Pandyo
plan: 224-l3-real-model.md
supersedes: []
---

# L3 실제 모델 확인: 개발용 시드, 실측 준비, 기본값 테스트 보완

## 한 일

- `uv run python -m soc.l3 dev-seed`는 개발 DB에 검증 run 실측용 시드를 넣는다. 이전 시드는 지우고 다시 넣는다. `--remove`는 지우기만 한다.
  - 시드는 `pending` Hunt 2개(위협 있음·없음)와 근거 Alert 1·Event 5(원본 6)다. 샘플은 `tests/fixtures/l3_hunt/dev_seed.json`이다.
  - 레코드 시각은 넣는 시점에서 `ago_ms`를 뺀 값이라, 검증 조회 기간(7일) 안에 든다.
  - 출력은 건수와 시드 Hunt ID뿐이다.
- 지우기는 한 트랜잭션에서 시드 Hunt의 L3 Ticket → 시드 Hunt → 시드 원본을 가리키는 Alert·Event → 시드 원본 순서다. Agent Log는 남긴다. 시드 Ticket이 Incident에 붙어 있으면 아무것도 지우지 않는다(종료 코드 1).
- 기본값을 검사하는 테스트(`test_agent_config.py` 3건, `test_l3_config.py` 2건, `test_l3_hunt.py` 1건)가 저장소 `config/` 대신 `default.toml`만 복사한 임시 폴더(`conftest.py`의 `default_config_dir`)를 읽는다. 검사 내용은 같다.
- 실제 모델 확인용 `llm` 마커 테스트 `tests/test_l3_hunt_llm.py` 1건. 임시 DB에 시드를 넣고 위협 있음 Hunt를 운영 경로(`run_agent`)로 검증한다. 계약 통과(`confirmed`·`rejected`·`inconclusive`)와 Agent Log만 단언한다.

## 계획과 달라진 점

- **Alert·Event에는 `details.dev_seed`를 넣지 않았다.** 계획은 Alert·Event·Hunt 모두 `details.dev_seed = true`였다. 그런데 에이전트 도구(`get_alert`·`get_event`)는 `details`를 모델에게 그대로 보여 준다. 그러면 모델이 "개발용 시드" 표시를 보고 판단할 수 있어 실측이 흐려진다. 그래서 Alert·Event는 시드 원본(`siem_profile = "dev-seed"`)을 가리키는 것(`raw_id`)으로 찾아 지운다. Hunt는 계획대로 `details.dev_seed = true`이고, 시나리오 이름을 `details.scenario`(`threat`·`no_threat`)에 더 넣었다. 검증 run 입력에는 Hunt `details`가 들어가지 않는다.
- **`dev-seed` 종료 코드에 2를 더했다.** `DATABASE_URL`이 없거나 샘플이 계약에 맞지 않으면 2다. `soc.l3 hunt`의 설정 오류(2)와 맞췄다.
- **`soc.l3.__main__`에 `build_parser()`를 두었다.** 도움말에 "개발 DB 전용"이 있는지 테스트하기 위해서다.
- **`test_l3_config.py`의 `valid_l3()`를 지웠다.** 쓰던 곳이 하나라 그 테스트가 `default_config_dir`을 받게 했다.
- **boannews는 이 세션에서도 재현했다**(아래). LLM 비용이 들지 않아 진단 스크립트 확인 겸 돌렸다. 맥 재현은 계획대로 사람이 한다.

## 다음 사람이 알아야 할 것

### Foundry (사람이 확인함, 2026-11-05)

| 항목 | 값 |
|---|---|
| 모델 | `gpt-oss-120b`(OpenAI, Sold by Azure), 버전 4 |
| 배포 유형·리전 | Global Standard, West US 3 |
| TPM/RPM | 실제 할당량 미확인(참고치 500만/5천) |
| 단가 | 입력 $0.15 / 출력 $0.60 (1M 토큰당) |
| 무료 크레딧 | 약 26.7만 원, 적용 여부 미확인 |
| 계획 전 사용량 | 27회 호출, 약 9.21만 토큰, 예상 약 25원 |
| `strict` | 빈 응답으로 거부(사람이 확인함). 아래 |

- 이 세션(클라우드 컨테이너, 프록시 경유)에서 Foundry 주소까지 연결된다. 키 없이 보내 401을 받았고 모델 호출은 하지 않았다.

### strict 빈 응답 (코어 담당 안건)

- Foundry에서 도구 정의에 strict를 켜면(`[llm] strict_mode = true`) 최종 답(content)이 빈 문자열로 온다. strict를 끄거나 도구가 없으면 정상이다. 추론 강도·출력 상한과는 관계없다. 확인 호출은 하지 않았다.
- 지금 코어에서는 빈 content가 JSON 파싱 실패 → `format_error` 재요청 → 또 비면 `format_error`로 끝날 것이다(코드로 본 추정이고 실제로 돌려 보지 않았다).
- 코어는 고치지 않았다. 코어 담당(#209·#210·#211)이 정할 것:
  1. 기본값 `strict_mode = true`를 기본 LLM(Foundry)에 맞춰 바꿀지
  2. 빈 content를 다른 실패와 구분해 기록할지
- 실측은 `strict_mode = false`로 한다.

### 400 `tool_use_failed`

(맥 실측 뒤 채움: Foundry 재현 여부, 오류 종류·상태·코드만)

지금 규칙: 400은 `RetryingModel`이 다시 부르지 않는다(429만). `run_task`가 `provider_error`로 끝내고, Hunt는 `attempts`만 오른다. `max_attempts`(2)에 이르면 `failed`다.

### boannews 수집 실패

- **세션 환경(프록시 경유, httpx 0.28.1)에서 재현됨.** 수집 코드와 같은 클라이언트로 24번 받아 4번 실패했다. 실패는 모두 연결 단계 `ConnectError`(← `ConnectionResetError`)였다. 요청 헤더를 바꾼 세 변형(기본 / 압축 끔 / curl과 같은 User-Agent)을 번갈아 돌렸는데, 기본 3번·curl UA 1번이 실패했고 바로 다음 시도는 성공했다. 헤더와 관계없이 연결이 가끔 끊기는 것이다.
- 응답 크기가 요청마다 다르다(압축 해제 후 311,021~322,905바이트). 같은 주소를 서로 다른 캐시 서버가 답하는 것으로 보인다.
- 이 환경에서는 L3 코드 원인이 아니다. 맥 결과는 아래에 채운다. 수집에는 재시도가 없어 한 번 끊기면 그 실행에서는 그 출처가 `network`로 끝난다. 재시도를 넣을지는 이 이슈 범위 밖이다(필요하면 안건).

(맥 재현 결과: 사람이 진단 스크립트 결과를 붙이면 채움)

### 테스트와 `config/local.toml`

- `tests/test_l2_config.py`도 같은 모양이다(저장소 `config/`를 합쳐 읽는다). 이번 실측 `local.toml`은 `[l2]`를 건드리지 않아 실패하지 않는다. 고칠지는 L2 담당이 정한다. `conftest.py`의 `default_config_dir`을 쓰면 된다.
- `elk`·`ssh` 마커 테스트는 일부러 `local.toml`을 읽으므로 그대로다.

### 시드와 실측의 함정

- **`soc.l3 hunt`는 `pending` Hunt를 전부 검증한다.** 시드가 아닌 `pending` Hunt(예: 지난 실측에서 남은 것)가 있으면 그것도 검증 run을 돌려 비용이 늘어난다. 실측 전에 `SELECT count(*) FROM hunts WHERE status = 'pending' AND NOT details @> '{"dev_seed": true}'`가 0인지 본다.
- **시드 Hunt 결과는 다음 `dev-seed` 전에 읽는다.** `dev-seed`가 이전 시드를 지운다. Agent Log는 남는다.
- **위협 없음 Hunt를 검증할 때도 위협 있음 시나리오의 레코드가 같은 DB에 있다.** 모델이 그것을 근거로 들 수 있다.
- 다른 Ticket의 `alert_ids`가 시드 Alert를 가리켜도 FK가 없어 막지 않는다(지금은 그런 Ticket을 만드는 단계가 없다).
- **`run_agent`가 모델을 부르기 전에 실패하면 Agent Log가 남지 않는다**(키 없음·연결 설정 없음 등). 집계 SQL에는 그 run이 빠지므로 Hunt `details.verify_failures`로 센다.
- `llm` 마커 테스트는 임시 LOGIN 역할을 만든다. `DATABASE_URL` 계정에 CREATEROLE이 필요하다(`test_tools_db.py`와 같다).

### 맥에서 실측하는 법

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
psql "$DATABASE_URL" -f runs.sql                    # 3라운드가 끝나면 한 번
DATABASE_URL=… uv run pytest -m llm tests/test_l3_hunt_llm.py   # 1 run
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

- `max_model_input_len`은 Agent Log에 저장된 입력 JSON의 길이다. 예산 검사(`max_input_chars`, system 지시 + 입력 항목 JSON)와 같은 값은 아니므로 근사로만 본다. 예산을 넘으면 `failures`에 `budget_exceeded`가 남는다.
- 비용은 위 단가로 계산한 추정이다.

## 실측 결과

(사람이 맥에서 실측한 수치를 받아 채움. 가설·이유 원문은 적지 않는다)

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run pytest`: 910건 통과(`local.toml` 없음). 임시 PostgreSQL 16(trust 인증)으로 `uv run pytest -m db`: 237건 통과
- 실측과 같은 모양의 임시 `config/local.toml`(LLM 설정 + `[tools.allowed] l3` 축소 + `[l3.hunt] collect_before = false`)로 `uv run pytest`: 고치기 전 5건 실패 → 고친 뒤 계획 대상 3개 파일은 통과. 남은 2건(`test_tools_siem.py`, `test_tools_ssh.py`의 기본값 검사)은 도구 담당 테스트라 손대지 않았다(사람 확인 대기)
- 테스트를 먼저 쓰고, `soc.l3.hunt.dev_seed`가 없어 두 시드 테스트 파일이 수집 단계에서 실패하는 것을 봤다
- `LLM_API_KEY`를 뺀 채 `uv run pytest -m llm tests/test_l3_hunt_llm.py`: 시드 → 검증 → `provider_error`로 `pending` 유지까지 연결을 확인했다(실제 모델 호출 0회)
- 주요 테스트
  - `tests/test_l3_dev_seed.py`(DB 없음): 샘플이 문서용 IP·`example.com`만 씀, 두 시나리오와 `ago_ms` 범위, 행이 계약을 통과하고 시각이 지금 기준, 매번 새 ID, 틀린 `ago_ms` 거부, 도움말의 "개발 DB 전용"
  - `tests/test_l3_dev_seed_db.py`: 넣기, 다시 넣기, 시드 행만 지우고 시드가 아닌 행·Agent Log는 남김, L3 Ticket 함께 지움, Incident에 붙으면 거부(넣기·지우기 모두), 빈 DB 지우기, 명령 출력(가설 본문 없음), `--remove`, 거부 종료 1, `DATABASE_URL` 없음 2, DB 오류 1(주소 없음)
