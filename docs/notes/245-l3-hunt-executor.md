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

## 계획과 달라진 점

- **함께 쓰는 함수의 위치.** 계획은 "`command.py`의 1~2단계를 함수 하나로 뺀다"였다. 함수(`collect_and_hypothesize`, `format_hypothesize`)는 `generate.py`에 두고, `command.py`가 가져다 쓴다. 생성 워커가 `command.py`(검증 루프·출력)를 가져오지 않게 하기 위해서다.
- **`DATABASE_URL` 읽기를 함수 하나로 두었다**(`verify.database_url_from_env`). 두 `build_worker`가 같이 쓴다. 없으면 `[l3.hunt]` 설정 오류(`ConfigError`)이고 메시지에 주소는 없다. 실행기는 이것을 "워커를 만들지 못했다(ConfigError)"로 보여 주고 종료 코드 2로 끝난다.
- **작업 이름을 상수로 뺐다**(`hypothesize.TASK = "l3_hypothesize"`). 생성 워커가 Agent Log를 찾는 이름과 run의 `task`가 어긋나지 않게 하기 위해서다.
- **조회 함수 이름은 `store.last_attempt_started_at(conn, task)`다.** 작업 이름을 인자로 받는다.
- **생성 워커의 `poll`도 `int | None`을 받는다.** `HuntVerifier`와 모양을 맞췄다. 값은 결과에 영향이 없다.
- **프로세스 안 기록이 간격 안이면 `poll`이 DB를 읽지 않는다.**
- **테스트 파일을 둘로 나눴다.** DB 없이 보는 등록·설정(`tests/test_l3_hunt_worker.py`)과 DB로 보는 동작(`tests/test_l3_hunt_worker_db.py`)이다.

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

### 손으로 확인하는 법 (사람, 맥, Foundry)

`config/local.toml`(커밋 안 함). `[llm]`·`[tools.allowed] l3`는 `docs/notes/224-l3-real-model.md` "다시 재는 법"과 같다.

```toml
[executor.l3]
interval_seconds = 60   # 확인용. 운영 권장은 600
```

환경변수: `DATABASE_URL`, `AGENT_DATABASE_URL`, `LLM_API_KEY`.

```bash
uv run python -m soc.db.migrate
uv run python -m soc.l3.intel          # ATT&CK이 없으면 생성 워커가 건너뛴다
uv run python -m soc.l3 dev-seed       # pending Hunt 2(위협 있음·없음)
uv run python -m soc.agent             # 1라운드: 생성 1 → 검증 3. 다음 검증 run 도중 Ctrl+C
psql "$DATABASE_URL" -f hunts.sql      # #224 기록의 SQL. cancelled 뒤에도 failed가 아닌지 본다
psql "$DATABASE_URL" -f runs.sql       # #224 기록의 SQL. run별 숫자
```

Ctrl+C를 검증 run 도중에 누르려면 `dev-seed`를 한 번 더 해 pending Hunt를 만든 뒤 다시 띄우고, "실행 중" 출력 뒤 몇 초 안에 누른다. 생성은 하루 1회라 두 번째 실행에서는 돌지 않는다.

`cancelled` 확인(본문 없이 숫자만):

```sql
SELECT details->>'task' AS task, count(DISTINCT run_id) AS cancelled_runs
FROM agent_logs
WHERE stage = 'l3' AND details->>'failure' = 'cancelled'
  AND started_at >= now() - interval '1 hour'
GROUP BY 1;
```

### 실측 결과

(사람이 붙임: 라운드 수, 생성·검증 run 수, 비용, 소요 시간, `cancelled` run 수와 그 Hunt의 상태·`attempts`)

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run pytest`: 978건 통과(전 964건)
- `uv run pytest -m db`: 262건 통과(전 243건). Docker가 없어 임시 PostgreSQL 16(trust 인증)으로 돌렸다. `tests/test_l3_hunt_worker_db.py` 5번 반복: 매번 19건 통과
- 테스트를 먼저 쓰고, `soc.l3.hunt.generate`가 없어 두 새 테스트 파일이 수집 단계에서 실패하고 기본값 테스트 2건(`test_default_config_executor_values`, `test_default_config_has_hunt_settings`)이 실패하는 것을 봤다
- 손으로 확인(임시 DB, 세션, LLM 설정 없음)
  - 기본 설정 `uv run python -m soc.agent`: "등록된 워커가 없다", 종료 코드 0
  - L3를 켠 설정(`interval_seconds = 2`, `collect_before = false`)으로 7초(약 4라운드)
    - ATT&CK 없음: "건너뜀" 로그 1번
    - ATT&CK 1건을 넣고 재시작: 가설 생성 `provider_error` 1번(모델 호출 전 실패), Agent Log 0, Hunt 0
    - 모두 종료 코드 0
- 주요 테스트
  - `tests/test_l3_hunt_worker.py`(DB 없음)
    - 기본 설정에 두 워커가 순서대로 있고, L3는 꺼져 있어 `DATABASE_URL` 없이도 L3를 띄우지 않는다
    - 켜면 실제 등록 경로로 생성 → 검증 워커가 만들어지고 등록 검사를 통과한다
    - 켰는데 `DATABASE_URL`이 없으면 시작하지 않는다
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
- 기존 테스트에서 바꾼 단언: `tests/test_agent_executor.py::test_default_config_executor_values`(l3 `workers`), `tests/test_l3_hunt.py::test_default_config_has_hunt_settings`(`generate_interval_seconds`)
