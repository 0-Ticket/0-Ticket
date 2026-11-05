---
issue: 245
date: 2026-11-05
owner: Pandyo
supersedes: []
---

# L3 헌팅 실행기 등록·주기 실행

## 목표

L3 헌팅을 실행기(`uv run python -m soc.agent`)의 L3 단계에서 주기적으로 돌린다. 생성 워커(수집 → 가설 생성)와 검증 워커(`HuntVerifier`)를 등록하고, 종료로 `cancelled`가 된 검증 run이 Hunt 시도 횟수에 들어가지 않게 고친다. 기본 설정에서 L3는 돌지 않는다(`interval_seconds = 0`). L3 실행 방식(D-030)을 확정한다.

## 방법

### 1. 검증 워커 (`soc.l3.hunt.verify`)

- `build_worker(config)`를 더한다. `DATABASE_URL`을 환경변수에서 읽고(없으면 예외 → 실행기가 시작하지 않는다) `read_hunt_settings(config["l3"])`로 `HuntVerifier`를 만든다.
- `handle`에서 검증 run이 `failure = "cancelled"`로 끝나면 Hunt에 아무것도 쓰지 않고 돌아간다. `attempts`·`details.verify_failures`·`updated_at`이 그대로이고 `pending`으로 남아 다음 라운드에 다시 한다. 그 run은 Agent Log에만 남는다.
- Agent Log를 쓰지 못해 `log_error`가 된 run(앞 실패가 `cancelled`여도)은 다른 실패처럼 센다.
- 다른 실패는 지금처럼 `attempts`를 올리고 `max_attempts`에 이르면 `failed`다.
- 수동 명령 `soc.l3 hunt`의 `poll(None)`(전부)은 그대로다.

### 2. 생성 워커 (`soc.l3.hunt.generate`)

- `build_worker(config)` → `HuntGenerator`. `stage = "l3"`, `name = "l3_hunt_hypothesize"`.
- `build_worker`는 `DATABASE_URL`(환경변수), `read_hunt_settings(config["l3"])`, `collect_before`가 켜져 있으면 `soc.l3.intel.read_settings(config["l3"])`, 그리고 `[l3.hunt] generate_interval_seconds`를 읽는다. `generate_interval_seconds`는 생성 워커가 따로 읽고 `HuntSettings`에는 넣지 않는다(수동 명령은 이 값을 쓰지 않는다). 0보다 큰 수가 아니면 예외.
- 표시 ID는 고정 문자열 `"hypothesize"`다.
- `poll(limit)`: 차례면 `["hypothesize"]`, 아니면 `[]`.
- `handle(subject_id)`: `subject_id`가 `"hypothesize"`가 아니거나 차례가 아니면 아무것도 하지 않는다(멱등). 차례면 먼저 프로세스 안 마지막 시도 시각을 지금으로 기록하고, 수집(`collect_before`) → 가설 생성 run → Hunt 저장을 한다.
  - 수집 → 가설 생성은 `command.py`의 1~2단계를 함수 하나로 빼서 수동 명령과 함께 쓴다. 수동 명령의 출력 줄과 종료 코드는 바뀌지 않는다.
  - 수집 출처가 실패해도 저장된 뉴스로 계속한다(#223 동작).
  - 가설 생성 run이 실패하면 Hunt를 만들지 않고 워커 이름과 실패 종류만 로그로 남긴다. 건너뜀(ATT&CK 없음)도 이유만 로그로 남긴다. 본문은 로그에 쓰지 않는다.
- **차례:** 마지막 시도 시각이 없거나, 지금 − 마지막 시도 ≥ `generate_interval_seconds`. 마지막 시도는 아래 둘 중 늦은 것이다.
  - DB: `agent_logs`에서 `stage = 'l3'`이고 `details->>'task' = 'l3_hypothesize'`인 줄의 가장 늦은 `started_at`. 같은 `run_id`에 `details->>'failure' = 'cancelled'`인 줄이 있는 run은 뺀다(끊긴 생성은 재시작 뒤 다시 한다).
  - 프로세스 안: `handle`이 시작할 때 기록한 시각. Agent Log가 남지 않는 경우(ATT&CK 없음으로 건너뜀, 모델을 부르기 전 `run_agent` 실패, 수집 중 DB 예외 등)도 재시작 전까지 매 라운드 반복하지 않는다. 재시작하면 한 번 다시 돈다(ATT&CK 다운로드를 다시 시도하는 기회).
- 가설 생성 run이 실패해도(`rate_limited`·`format_error` 등) 한 번의 시도로 센다. 다음 시도는 `generate_interval_seconds` 뒤다.
- 시계는 주입한다(기본 UTC 지금). Agent Log의 `started_at`은 실제 시계로 찍히므로, DB 쪽 판단은 테스트에서 시각을 정한 `agent_logs` 줄을 직접 넣어 확인한다.
- `agent_logs`에 인덱스는 더하지 않는다(L3 간격에서 라운드마다 한 번 읽는다).

### 3. 등록과 설정 (`config/default.toml`)

```toml
[executor.l3]
# L3는 기본으로 돌지 않는다(L3 실행 방식, D-030). 켤 때 권장: interval_seconds = 600, poll_limit = 10
interval_seconds = 0
poll_limit = 10
workers = ["soc.l3.hunt.generate:build_worker", "soc.l3.hunt.verify:build_worker"]

[l3.hunt]
# 실행기 생성 워커의 가설 생성 간격(초). 마지막 시도부터 센다
generate_interval_seconds = 86400
```

- 등록 순서대로 라운드가 돌아 생성 → 검증이 같은 라운드에서 이어진다.
- 새 환경변수는 없다.

### 4. D-030

"담당자가 정함"에서 확정(L3 절)으로 옮긴다: L3는 실행기의 L3 단계에서 생성 워커와 검증 워커로 주기 실행하고, 수동 명령(`soc.l3 hunt`)은 그대로 둔다. 기본은 꺼짐. 기록 줄은 `#245`로 쓴다.

### 순서

테스트(가짜 시계·가짜 실행) → 검증 `cancelled`·`build_worker` → 수집·생성 함수 빼기 → 생성 워커 → 설정·기본값 테스트 → D-030 → notes → 손으로 확인(사람, 맥)

## 바꿀 곳

- `src/soc/l3/hunt/verify.py`: `build_worker`, `cancelled` 처리
- `src/soc/l3/hunt/generate.py`(새 파일): 생성 워커와 `build_worker`
- `src/soc/l3/hunt/command.py`: 수집 → 가설 생성을 함수로 빼고 그 함수를 부름
- `src/soc/l3/hunt/store.py`: 마지막 가설 생성 시도 시각 조회
- `config/default.toml`: `[executor.l3] workers`, `[l3.hunt] generate_interval_seconds`, 권장값 주석
- `tests/test_l3_hunt*.py`, `tests/test_agent_executor.py`(기본값 단언)
- `docs/decisions.md`: D-030
- `docs/notes/245-l3-hunt-executor.md`

## 다른 코드와 맞물리는 곳

- 새로 만듦: `soc.l3.hunt.generate:build_worker`, `soc.l3.hunt.verify:build_worker`, 설정 키 `[l3.hunt] generate_interval_seconds`
- 바꿈: `[executor.l3] workers` 기본값(`[]` → 두 워커). `tests/test_agent_executor.py`의 `test_default_config_executor_values`(#215)는 l3 `workers` 단언만 바꾼다. `interval_seconds = 0`이라 `stages == []`는 그대로다
- 바꿈: `HuntVerifier.handle`의 `cancelled` 동작(수동 명령에도 적용)
- 그대로: 실행기·`AgentWorker` 틀(#215), `run_agent`, `HuntSettings`, `soc.l3 hunt` 출력·종료 코드, L1·L2 워커

## 범위 밖

- 가설 생성 run의 도구 제한, 2층 `l3.md` 분리(별도 이슈)
- 위협 없음 판정이 흔들리는 문제(별도 이슈)
- 도구 인자 오류 줄이기(별도 이슈)
- 운영에서 실행기를 띄우는 방법(프로세스 실행, 재시작, 로그)
- ELK 실데이터 L3 실측(#218, #234 이후)
- 실행기와 수동 명령을 동시에 돌릴 때 가설이 두 번 생성되는 것(notes에 적는다)
- 종료 대기 시간을 넘겨 Agent Log가 남지 않은 run의 별도 처리. 검증은 run이 끝난 뒤 Hunt를 갱신하므로 강제로 끝나면 `pending`·`attempts`가 그대로 남는다(notes에 적는다)

## 완료 기준

- [ ] 검증 워커의 `build_worker`와 생성 워커가 설정으로 `Executor`에 등록되고, 실행기의 등록 검사(stage, name, `poll`·`handle`)를 통과한다
- [ ] 생성 워커: 차례가 아니면 `poll`이 빈 목록, 차례이면 `["hypothesize"]`, `handle`을 두 번 불러도 한 번만 생성한다(가짜 시계·가짜 실행)
- [ ] DB의 마지막 시도(`l3_hypothesize` Agent Log)가 간격 안이면 생성하지 않고, `cancelled` run만 있으면 생성한다
- [ ] 모델을 부르기 전에 끝나는 경우(ATT&CK 없음, 모델 호출 전 실패, `handle` 중 예외)도 매 라운드 반복하지 않는다
- [ ] 수집이 실패해도 생성 워커가 저장된 뉴스로 계속한다
- [ ] `cancelled`로 끝난 검증 run은 Hunt를 바꾸지 않고 `pending`으로 남는다. 다른 실패는 지금처럼 한도에서 `failed`가 된다
- [ ] 한 라운드에서 생성 → 검증이 이어진다(등록 순서)
- [ ] `interval_seconds = 0`이면 L3 스레드가 뜨지 않는다(기본 설정에서 L3는 돌지 않는다)
- [ ] `soc.l3 hunt` 수동 명령이 그대로 동작한다(기존 테스트 통과)
- [ ] 손으로 확인(사람, 맥, Foundry): `local.toml`에서 L3를 켜고 `uv run python -m soc.agent`로 생성 → 검증이 돌고, Ctrl+C로 끝내면 진행 중인 run이 `cancelled`로 끝나며 Hunt가 `failed`가 되지 않는다. 라운드 수·비용·소요 시간을 `docs/notes/`에 적었다
- [ ] D-030이 확정으로 옮겨졌고 기록 줄이 있다
- [ ] 키·비밀 값이 코드, 테스트, 로그, notes, PR에 없다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `db` 테스트 통과
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록

## 토론으로 정한 것

- **반복 방지는 DB와 프로세스 안 기록 중 늦은 것.** 이슈의 "ATT&CK 없음"뿐 아니라 Agent Log가 남지 않는 모든 경우(모델 호출 전 `run_agent` 실패, `handle` 중 예외)를 막기 위해 `handle` 시작 때 프로세스 안 시각을 기록한다. 재시작 때 한 번 다시 도는 것은 허용한다.
- **`cancelled` 가설 생성 run은 마지막 시도로 세지 않는다.** 이슈의 조회("`l3_hypothesize`의 가장 최근 `started_at`")를 그대로 쓰면 Ctrl+C로 끊긴 생성 때문에 재시작 뒤 하루 동안 생성하지 않는다. #215의 "cancelled는 실패로 세지 않는다"에 맞췄다.
- **실패한 가설 생성 run도 한 번의 시도.** 짧은 재시도 간격은 만들지 않는다(필요하면 수동 명령).
- **수집과 생성은 한 워커.** 수동 명령과 같은 흐름이고, "차례" 판단이 하나다.
- **이름과 표시 ID:** 모듈 `soc.l3.hunt.generate`, 이름 `l3_hunt_hypothesize`, 표시 ID `"hypothesize"`. 수집 → 생성 코드는 `command.py`와 함께 쓰도록 함수로 뺀다.
- **기본값:** `generate_interval_seconds = 86400`(뉴스 창 3일, 하루 1회). L3를 켤 때 권장 `interval_seconds = 600`, `poll_limit = 10`은 주석으로만 둔다. `generate_interval_seconds`는 `HuntSettings`에 넣지 않아 수동 명령과 그 테스트에 영향이 없다.
- **검증 `cancelled`는 Hunt에 아무것도 쓰지 않는다.** `verify_failures`에도 남기지 않는다(Agent Log에 있다). 다시 하는 run은 같은 `attempt` 번호로 Agent Log에 남는다.

## 바뀐 점
