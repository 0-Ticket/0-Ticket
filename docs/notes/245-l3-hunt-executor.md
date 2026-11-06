---
issue: 245
date: 2026-11-05
owner: Pandyo
plan: 245-l3-hunt-executor.md
supersedes: []
---

# L3 헌팅을 실행기에 붙였다: 생성 워커는 하루 1회, 검증은 종료로 끊겨도 실패로 세지 않는다

## 한 일

- **실행기 L3 단계에 워커 두 개를 등록했다**(`[executor.l3] workers`). 기본은 꺼짐(`interval_seconds = 0`)이고 `config/local.toml`에서 켠다.
  - 생성 워커 `soc.l3.hunt.generate:build_worker`(`l3_hunt_hypothesize`)
  - 검증 워커 `soc.l3.hunt.verify:build_worker`(`l3_hunt_verify`)
  - 생성이 먼저라 새 Hunt가 같은 라운드에서 검증된다.
- **생성 워커.** 차례가 되면 수집(`collect_before`) → 가설 생성 run → pending Hunt 저장을 한다.
  - `poll`은 차례면 `["hypothesize"]`, 아니면 빈 목록을 낸다.
  - 차례 기준은 마지막 시도부터 `[l3.hunt] generate_interval_seconds`(기본 86400)가 지났는지다. 마지막 시도는 DB(`cancelled`가 아닌 `l3_hypothesize` Agent Log)와 프로세스 안 기록(`handle` 시작 시각) 중 늦은 것이다.
  - 로그에는 건수와 실패 종류만 남긴다.
- **검증 `cancelled`.** 종료로 끊긴 검증 run은 Hunt에 아무것도 쓰지 않는다. Hunt는 `pending`으로 남고 `attempts`도 그대로다. 다른 실패는 지금처럼 센다.
- **수동 명령 `soc.l3 hunt`는 그대로다.** 수집 → 가설 생성 부분을 생성 워커와 같은 함수(`collect_and_hypothesize`)로 바꿨을 뿐이고, 출력 줄과 종료 코드는 같다.
- **L3 실행 방식(D-030)을 확정으로 옮겼다**(계획 커밋).
- **맥에서 Foundry로 손 확인을 마쳤다**(아래 "실측 결과"). 생성은 간격마다 한 번만 돌았고, 생성 → 검증이 같은 라운드에서 이어졌다. 수집이 실패해도 계속했다. Ctrl+C로 끊긴 검증 run은 `cancelled`로 남고 Hunt는 `failed`가 되지 않았다.

## 계획과 달라진 점

- **함께 쓰는 함수의 위치.** 계획은 "`command.py`의 1~2단계를 함수 하나로 뺀다"였다. 함수(`collect_and_hypothesize`, `format_hypothesize`)는 `generate.py`에 두고, `command.py`가 가져다 쓴다. 생성 워커가 `command.py`(검증 루프·출력)를 가져오지 않게 하기 위해서다.
- **`DATABASE_URL` 읽기를 함수 하나로 두었다**(`verify.database_url_from_env`). 두 `build_worker`가 같이 쓴다. 없으면 `[l3.hunt]` 설정 오류(`ConfigError`)이고 메시지에 주소는 없다. 실행기는 이것을 "워커를 만들지 못했다(ConfigError)"로 보여 주고 종료 코드 2로 끝난다.
- **작업 이름을 상수로 뺐다**(`hypothesize.TASK = "l3_hypothesize"`). 생성 워커가 Agent Log를 찾는 이름과 run의 `task`가 어긋나지 않게 하기 위해서다.
- **조회 함수 이름은 `store.last_attempt_started_at(conn, task)`다.** 작업 이름을 인자로 받는다.
- **생성 워커의 `poll`도 `int | None`을 받는다.** `HuntVerifier`와 모양을 맞췄다. 값은 결과에 영향이 없다.
- **프로세스 안 기록이 간격 안이면 `poll`이 DB를 읽지 않는다.**
- **테스트 파일을 둘로 나눴다.** DB 없이 보는 등록·설정(`tests/test_l3_hunt_worker.py`)과 DB로 보는 동작(`tests/test_l3_hunt_worker_db.py`)이다.
- **main 동기화(`18e0673`) 뒤 `tests/test_l3_hunt_worker.py`의 테스트 3건에서 L1·L2 단계를 끈다**(`l3_only`). main 기본 설정에 L1·L2 워커가 등록돼, 실제 등록 경로로 `Executor`를 만들면 L1·L2 워커(필요한 설정·Qdrant)까지 만들다 실패했다. "`DATABASE_URL`이 없으면 시작하지 않는다" 테스트는 L1 워커가 먼저 실패해 틀린 이유로 통과하고 있어서, 메시지가 `soc.l3.hunt.generate`를 가리키는지도 보게 했다.

## 다음 사람이 알아야 할 것

- **수집은 종료 요청으로 끊기지 않는다.** 수집은 동기 httpx라 실행기의 취소가 닿지 않는다.
  - 최악의 경우 출처 3개 × 30초(`deadline_seconds`)가 걸리고, ATT&CK이 DB에 없으면 다운로드 180초가 더해진다. 종료 대기(30초)를 넘기면 실행기는 종료 코드 1로 끝나고 그 스레드는 버려진다.
  - 수집이 끝난 뒤 시작한 가설 생성 run은 바로 `cancelled`가 된다. 시도로 세지 않으므로 재시작하면 다시 생성한다.
- **재시작하면 한 번 다시 도는 경우.** Agent Log가 남지 않은 시도(ATT&CK 없음으로 건너뜀, 모델을 부르기 전 실패, 수집 중 DB 예외), `cancelled` 생성 run, 종료 대기를 넘겨 기록을 못 쓴 run이다. 일부러 허용했다(계획 "토론으로 정한 것").
- **실패한 생성 run(`rate_limited`·`format_error` 등)도 시도다.** 다음 시도는 하루 뒤다. 급하면 수동 명령 `uv run python -m soc.l3 hunt`를 쓴다(간격을 보지 않는다).
- **종료 대기를 넘긴 검증 run.** 검증은 run이 끝난 뒤 Hunt를 갱신하므로, 강제로 끝나면 `pending`·`attempts`가 그대로 남아 다음 실행에서 다시 한다.
- **`cancelled` 뒤 다시 하는 검증 run은 같은 `attempt` 번호로 Agent Log에 남는다.** Hunt의 `attempts`가 오르지 않았기 때문이다.
- **Agent Log를 못 써 `log_error`가 된 검증 run은 실패로 센다.** 앞 실패가 `cancelled`였어도 그렇다(`detail`에 `prior=cancelled`).
- **실행기와 수동 명령을 동시에 돌리면 가설이 두 번 생성될 수 있다.** 생성 워커는 수동 명령의 시도를 Agent Log로만 안다(같은 `l3_hypothesize`라 끝난 뒤에는 보인다). 검증은 `attempts` 조건으로 안전하다.
- **`agent_logs`의 `task`는 `details` 안에 있고 인덱스가 없다.** 생성 워커는 재시작 직후나 간격이 지난 뒤 라운드마다 표 전체를 한 번 읽는다. 느려지면 인덱스를 마이그레이션으로 더한다(L3 대역 0300~0399).
- **Agent Log의 `started_at`은 실제 시계로 찍힌다.** 생성 워커의 시계(`clock`)와 비교하므로, 테스트는 시각을 정한 줄을 직접 넣는다(`tests/fixtures/l3_hunt/hypothesize_logs.json`).
- **생성 워커는 `handle` 동안 DB 연결 하나를 수집과 모델 run 내내 잡고 있다.** 수동 명령과 같다.
- **`collect_before = false`면 `[l3.intel]` 설정을 읽지 않는다.** 출처 설정이 틀려도 생성 워커는 만들어진다.
- **`generate_interval_seconds`는 `HuntSettings`에 없다.** 생성 워커의 `build_worker`만 읽는다. 수동 명령과 그 테스트는 이 키가 없어도 동작한다.
- **`uv run python -m soc.agent`는 이제 L1·L2도 함께 돈다.** main 기본 설정에 L1·L2 워커가 등록돼 있다(`18e0673`). L3만 볼 때는 `config/local.toml`에서 `[executor.l1]`·`[executor.l2]`의 `interval_seconds = 0`으로 끈다. L3 등록만 보는 테스트도 같은 이유로 L1·L2를 끈다(위 "계획과 달라진 점").
- **#215 기본값 테스트(`test_default_config_executor_values`)의 `workers` 단언을 고쳤다.** l3 기대값만 우리 워커 둘로 바꿨고, main 동기화 때 main이 더한 L1·L2 단언과의 충돌을 같이 풀었다. 띄우는 단계는 `l1`·`l2`뿐이다(L3는 `interval_seconds = 0`).

### 후속 후보 (손 확인에서 나옴)

- **일시적인 오류도 2번이면 Hunt가 영구히 `failed`가 된다.** 1차 손 확인에서 `failed` 2건은 모두 `attempts` 2, `verify_failures` 2건이 다 `provider_error`였다. 맥의 네트워크가 불안정해서 난 오류였다. `max_attempts`(2)는 실패 종류를 가리지 않고, `failed`를 다시 `pending`으로 돌리는 코드는 없다. 일시 오류를 따로 셀지, 다시 시도할 길을 둘지 정해야 한다.
- **실행기가 `build_worker`의 `ConfigError` 메시지를 숨긴다.** 새 터미널에서 `DATABASE_URL`이 없어 생성 워커가 `ConfigError`를 냈는데, 실행기는 "워커를 만들지 못했다(ConfigError)"만 보여 줘 이유가 안 보였다. 실행기(#215)는 예외 메시지가 밖에서 온 문자열일 수 있어 종류만 남긴다. 그런데 이 메시지는 코드가 쓴 문장이고 환경변수 이름만 들어가 보여 줘도 안전하다. 고치려면 실행기(`src/soc/agent/executor.py`)를 바꿔야 하므로 #215 담당과 정한다.

### 손으로 확인하는 법 (사람, 맥, Foundry)

`config/local.toml`(커밋 안 함). `[llm]`·`[tools.allowed] l3`는 `docs/notes/224-l3-real-model.md` "다시 재는 법"과 같다.

이번 손 확인에 쓴 값이다. 확인 뒤에 지웠다.

```toml
[executor.l3]
interval_seconds = 30   # 확인용. 운영 권장은 600
poll_limit = 10

[l3.hunt]
generate_interval_seconds = 120   # 확인용. 기본은 86400(하루)
```

main 동기화(`18e0673`) 뒤에는 L1·L2 워커도 기본으로 돈다. L3만 볼 때는 같은 `local.toml`에 아래를 더해 끈다.

```toml
[executor.l1]
interval_seconds = 0

[executor.l2]
interval_seconds = 0
```

환경변수: `DATABASE_URL`, `AGENT_DATABASE_URL`, `LLM_API_KEY`. 새 터미널에서 `DATABASE_URL`을 빠뜨리면 실행기가 "워커를 만들지 못했다(ConfigError)"로 끝난다(이유는 안 보인다. 위 "후속 후보").

```bash
uv run python -m soc.db.migrate
uv run python -m soc.l3.intel          # ATT&CK이 없으면 생성 워커가 건너뛴다
uv run python -m soc.l3 dev-seed       # pending Hunt 2(위협 있음·없음)
uv run python -m soc.agent             # 1라운드: 생성 1 → 검증 3. 다음 검증 run 도중 Ctrl+C
psql "$DATABASE_URL" -f hunts.sql      # #224 기록의 SQL. cancelled 뒤에도 failed가 아닌지 본다
psql "$DATABASE_URL" -f runs.sql       # #224 기록의 SQL. run별 숫자
```

Ctrl+C는 검증 run 도중에 누른다. 생성이 Hunt를 저장한 직후 검증 호출이 흐르는 동안 누르면 된다. `generate_interval_seconds`가 기본값(하루)이면 다시 띄워도 생성은 돌지 않으므로, `dev-seed`를 한 번 더 해 pending Hunt를 만든 뒤 띄운다.

`cancelled` 확인(본문 없이 숫자만):

```sql
SELECT details->>'task' AS task, count(DISTINCT run_id) AS cancelled_runs
FROM agent_logs
WHERE stage = 'l3' AND details->>'failure' = 'cancelled'
  AND started_at >= now() - interval '1 hour'
GROUP BY 1;
```

### 실측 결과

사람이 맥에서 Foundry로 확인했다. 설정은 위 "이번 손 확인에 쓴 값"(`interval_seconds = 30`, `poll_limit = 10`, `generate_interval_seconds = 120`)이다. 가설·이유 원문은 적지 않는다.

- **코드 기준:** 동기화 전 코드(`631d7ea` 위, L1·L2 워커가 아직 없던 때)에서 했다. L3 코드(`src/soc/l3/`)와 실행기(`src/soc/agent/executor.py`, `types.py`)는 main에서 바뀌지 않아(`git diff 631d7ea 18e0673 -- <세 경로>`가 빈 결과) 동기화 뒤에 다시 하지 않았다.

#### 1차: 주기 실행 (11-05 17:36~19:10)

약 95분 돌렸고, 중간에 약 15분 공백이 있었다.

| 항목 | 값 |
|---|---|
| 생성 모델 호출 | 25회(성공 12, `provider_error` 13) |
| 검증 모델 호출 | 62회(성공 56, `provider_error` 6) |
| Hunt(시작 전) | 6개: `confirmed` 1, `inconclusive` 5 |
| Hunt(끝) | 17개: `confirmed` 2, `inconclusive` 11, `rejected` 1, `failed` 2, `pending` 1 |
| 토큰 입력 / 출력 | 243,459 / 20,290 |
| 비용 | 약 $0.049(생성 $0.011, 검증 $0.038). 단가는 이전 L1 실측에서 역산한 입력 $0.15 · 출력 $0.60 / 100만 토큰 |

- **차례 판단:** 생성은 약 2분 12초 간격으로 한 번씩만 돌았다. 120초가 지난 뒤 다음 라운드(30초 간격)에서 차례를 보기 때문으로 보인다. 생성 → 검증이 같은 라운드에서 이어졌다.
- **수집 실패 허용:** 맥의 네트워크가 불안정해 수집이 `network`·`timeout`으로 자주 실패했고, 가설 생성도 `provider_error`로 실패했다. 그래도 프로세스는 멈추지 않았고, 다음 라운드에서 저장된 뉴스로 계속했다.
- **`failed` 2건:** 둘 다 `attempts` 2이고, `verify_failures` 2건이 모두 `provider_error`였다. 일시 오류로 영구 `failed`가 된 사례다(위 "후속 후보").
- **오래 걸린 검증 호출:** 하나가 약 42초 매달린 뒤 `provider_error`로 끝났다.

#### 2차: 종료 시험 (11-06 12:09)

- 생성이 Hunt 1건을 저장한 직후, 검증 호출이 흐르는 중에 Ctrl+C를 눌렀다.
- `agent_logs`: `l3_verify` 모델 호출 줄이 `outcome = error`, `failure = cancelled`로 남았다(12:09:22).
- **끊긴 Hunt:** `pending`, `attempts` 1, `verify_failures` 1건으로 끊기기 전 그대로였다. `cancelled`가 시도로 세지지 않았다.
- `failed`는 2건 그대로였다. 종료 대기 시간 초과 경고는 없었다.
- 이 사이에 만든 새 Hunt는 `pending`, `attempts` 0이다.
- 종료 코드는 확인하지 못했다(출력을 `tee` 파이프로 받아서).

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- 아래 건수는 main 동기화(`18e0673`) 뒤의 숫자다.
- `uv run pytest`: 1256건 통과
- `uv run pytest -m "db or qdrant"`(CI와 같은 명령): 399건 통과, 그중 Qdrant 22건, 건너뜀 0
  - PostgreSQL은 임시 PostgreSQL 16(trust 인증)으로 돌렸다.
  - Qdrant는 Docker로 띄운 `qdrant/qdrant:v1.19.2`(CI와 같은 이미지)로 돌렸다.
  - 경고 1건은 main의 `tests/test_store_qdrant.py`에서 나온 qdrant-client 서버 버전 확인 경고다.
- 동기화 전(`631d7ea` 위)에는 `uv run pytest` 978건, `uv run pytest -m db` 262건이 통과했다. `tests/test_l3_hunt_worker_db.py` 5번 반복: 매번 19건 통과
- 테스트를 먼저 쓰고, `soc.l3.hunt.generate`가 없어 두 새 테스트 파일이 수집 단계에서 실패하고 기본값 테스트 2건(`test_default_config_executor_values`, `test_default_config_has_hunt_settings`)이 실패하는 것을 봤다
- 손으로 확인(사람, 맥, Foundry): 위 "실측 결과"
- 손으로 확인(임시 DB, 세션, LLM 설정 없음, 동기화 전)
  - 기본 설정 `uv run python -m soc.agent`: "등록된 워커가 없다", 종료 코드 0(동기화 뒤에는 L1·L2가 돈다)
  - L3를 켠 설정(`interval_seconds = 2`, `collect_before = false`)으로 7초(약 4라운드)
    - ATT&CK 없음: "건너뜀" 로그 1번
    - ATT&CK 1건을 넣고 재시작: 가설 생성 `provider_error` 1번(모델 호출 전 실패), Agent Log 0, Hunt 0
    - 모두 종료 코드 0
- 주요 테스트
  - `tests/test_l3_hunt_worker.py`(DB 없음)
    - 기본 설정에 두 워커가 순서대로 있고, L3는 꺼져 있어 `DATABASE_URL` 없이도 L3를 띄우지 않는다
    - 켜면 실제 등록 경로로 생성 → 검증 워커가 만들어지고 등록 검사를 통과한다
    - 켰는데 `DATABASE_URL`이 없으면 생성 워커에서 시작하지 않는다
    - 위 세 건은 L1·L2 단계를 끄고 본다(`l3_only`, "계획과 달라진 점")
    - `build_worker`: `DATABASE_URL` 없음, 틀린 헌팅 설정, 틀린 `generate_interval_seconds`(0, -1, 문자열, bool, 없음)
    - 수집을 끄면 `[l3.intel]`을 읽지 않는다
    - 수동 명령 설정은 새 키가 없어도 된다
  - `tests/test_l3_hunt_worker_db.py`
    - 차례: 시도가 없으면 차례, `handle` 두 번에 한 번만 생성, 간격 뒤 다시 차례, 다른 ID는 무시
    - DB의 마지막 시도: 간격 안이면 차례 아님, 간격 밖이면 차례, 실패 run도 시도, `cancelled` run은 시도 아님, 검증 Agent Log는 무관
    - `run_task` + DB 기록기가 쓴 줄을 새 워커(재시작)가 읽음
    - 기록이 남지 않는 경우: ATT&CK 없음, 모델 호출 전 실패, `handle` 중 예외는 반복하지 않고 재시작하면 한 번 다시 한다
    - 수집 실패에도 생성, 로그에 본문 없음, 실패 종류 로그
    - 검증 `cancelled`: Hunt 그대로(3번), 다른 실패는 `cancelled` 사이에도 한도에서 `failed`(`log_error` 포함)
    - 실행기 한 라운드에서 생성 → 새 Hunt 검증
- 기존 테스트에서 바꾼 단언
  - `tests/test_agent_executor.py::test_default_config_executor_values`(#215): l3 `workers`. main 동기화 때 main이 더한 L1·L2 단언과 합쳤다
  - `tests/test_l3_hunt.py::test_default_config_has_hunt_settings`: `generate_interval_seconds`
