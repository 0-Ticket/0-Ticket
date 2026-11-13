---
issue: 280
date: 2026-11-11
owner: Interludeal
plan: 280-executor-tool-stability.md
supersedes: ["215-executor-l1-e2e.md"]  # "취소가 동작하는 방식과 한계"(86·88행)가 낡았다
---

# 동기 도구를 별도 스레드로 돌리고, 죽은 단계를 알아채고, 라운드 지표를 남기고, LLM 클라이언트를 닫는다

## 한 일

- **취소가 도구를 기다리지 않는다(C4).** DB·SIEM 같은 동기 도구 핸들러는 호출마다 전용 데몬 스레드에서 돈다. 실행기가 취소를 보내면 run은 바로 `cancelled`로 끝난다(가짜 모델 재현에서 이전에는 도구 시간만큼, 3초짜리 도구에 2.50초 늦었다). 진행 중이던 DB 문장·HTTP 요청은 끝까지 두고 결과만 버린다. 이렇게 버려진 스레드가 있으면 `soc.agent.executor` 로그에 도구 이름과 경과 시간만 WARNING 한 줄로 남는다. 데몬이라 프로세스 종료를 막지 않는다.
- **단계 스레드가 죽어도 알 수 있다(C6).** `poll`·`handle`의 `Exception`·`CancelledError`·`SystemExit`은 예외 종류만 로그에 남기고 다음 건으로 간다. 그 밖의 `BaseException`(예: `KeyboardInterrupt`)과 단계 스레드 자체의 오류는 그 단계를 죽은 것으로 표시하고, `main`이 이를 보고 다른 단계를 정리한 뒤 종료 코드 3으로 끝낸다. 다시 시작하지 않는다. 예외를 스레드 밖으로 올리지 않아 메시지가 든 트레이스백이 stderr에 찍히지 않는다.
- **라운드 지표를 남긴다(C7).** 받은 건이 있는 라운드마다 워커별 한 줄을 INFO로 남긴다(아래 "읽는 법"). 대기 시간·DB·화면 지표는 #295로 뺐다.
- **LLM 클라이언트를 닫는다(C8).** `run_agent`가 run마다 만든 클라이언트를, 정상·실패·취소·시작 전 실패 어느 경로로 끝나도 `finally`에서 같은 스레드의 기본 루프로 닫는다. `build_model`의 시그니처와 반환은 그대로이고, 클라이언트만 따로 만드는 `build_client`가 생겼다.

### 종료 코드(`uv run python -m soc.agent`)

| 코드 | 뜻 |
|---|---|
| 0 | 정상 종료(Ctrl+C·SIGTERM으로 끝냈고 모든 단계가 시간 안에 끝남). 등록된 워커가 없을 때도 0 |
| 1 | 종료 대기 시간(`[executor] shutdown_timeout_seconds`) 안에 끝나지 않은 단계가 있음 |
| 2 | 설정 오류(워커 등록 실패 포함) |
| 3 | 단계 스레드가 죽음(D-050). 죽은 단계와 종료 대기 초과가 겹쳐도 3 |

레포 안에서 실행기 종료 코드에 기대는 곳(`.github`, `scripts`, compose·Docker 파일, README·CONTRIBUTING, `docs/*.md`, `prompts/`, `.claude/skills`, `.agents`)은 없었다. `executor.main` docstring과 `tests/test_agent_executor.py`의 `main` 테스트, `config/default.toml` 주석을 고쳤다.

### 라운드 로그 줄과 읽는 법

```text
round stage=l1 worker=<워커 이름> polled=10 limit=10 handled=9 failed=1 total_ms=48210 max_ms=9120
```

- 받은 건이 있는 라운드에만 남는다(빈 라운드는 조용하다). 로거는 `soc.agent.executor`, INFO다. subject ID·예외 메시지는 없다.
- `polled == limit`이면 그 라운드에 `poll_limit`만큼 꽉 받았다는 뜻이라 밀리고 있을 수 있다는 신호다. 몇 건이 밀렸는지는 알 수 없다(대기 시간·대기열 길이는 #295).
- `total_ms`는 그 워커의 `handle` 합, `max_ms`는 건당 최대다. `total_ms`가 `interval_seconds`보다 계속 길면 그 단계는 간격을 못 맞추고 있다.
- `handled`는 성공 건수, `failed`는 실패 건수다. 종료 요청으로 라운드가 일찍 끝나면 지금까지의 값으로 남아 `handled + failed`가 `polled`보다 작다.
- 버려진 도구 스레드 경고 모양: `취소로 버려진 도구 스레드: tool=<도구 이름> elapsed=<초>s`.

### 결정

- **D-049** 동기 도구 핸들러(DB·SIEM)는 호출마다 전용 데몬 스레드에서 돌리고 `asyncio.wrap_future`로 기다린다. `async def` 핸들러(SSH)는 루프에서 그대로 await한다. 취소는 기다림만 끊는다. `asyncio.to_thread`와 async 클라이언트는 쓰지 않는다.
- **D-050** 단계 스레드의 예외 처리와 종료 코드(위). 죽은 스레드는 재시작하지 않는다.

## 계획과 달라진 점

없음. 작은 것만 적는다.

- **`handled`는 성공 건수다.** 종료로 라운드가 일찍 끝나면 `handled + failed`가 `polled`보다 작을 수 있다(위).
- **로거 이름을 레지스트리 모듈이 직접 쓴다.** 버려진 도구 스레드 경고는 `registry.py`가 `logging.getLogger("soc.agent.executor")`로 남긴다. 운영자가 실행기 로그 한 곳에서 보게 하려는 것이다(계획에 있다). 도구 계층이 실행기 로거 이름을 아는 점은 어색하지만 이름만 알고 실행기 코드를 부르지는 않는다.
- **`build_client`를 새로 두었다.** 계획의 "클라이언트를 따로 만드는 함수(이름·모양은 개발 때 정한다)"다. `run_agent`만 쓴다.
- **종료 코드 테스트를 `tests/test_agent_executor.py`로 옮겼다.** 처음 새 파일에 썼다가 기존 `main` 테스트 옆으로 옮겼다. 로그·지표 테스트는 `tests/test_agent_executor_stability.py`다.

## 다음 사람이 알아야 할 것

- **동기 도구는 호출마다 데몬 스레드에서 돈다.** 새 도구(#214 등)는 `ctx`와 자기 인자 밖의 스레드 로컬·`contextvars`에 기대지 않는다. 핸들러 시그니처·`ToolSpec`은 바뀌지 않았다. 스레드에서 부른 결과가 awaitable이면 루프에서 await한다. 스레드 이름은 `soc-tool-<도구 이름>`이다.
- **취소는 기다림만 끊는다.** 진행 중인 요청은 끝까지 돌고 결과는 버려진다. 취소된 호출은 `report_tool`·장부 갱신을 하지 않는다(그 둘은 await 뒤에서만 한다). 그래서 취소된 run의 Agent Log에는 그 도구 호출의 tool 줄이 없고 #278의 종료 줄이 붙는다.
- **`poll`·`handle`이 `SystemExit`·`CancelledError`를 내도 실행기는 계속 돈다.** 같은 건이 계속 나오면 매 라운드 경고가 남는다. 시도 횟수는 워커가 센다(215 기록 "워커 틀"). `sys.exit`로 프로세스를 끝내게 하는 용도로 쓸 수 없다.
- **한 단계가 죽으면 전체가 종료 코드 3으로 내려간다.** 다시 시작은 프로세스 관리자(이 레포에는 없다)의 몫이다.
- **215 기록 "취소가 동작하는 방식과 한계"의 두 줄이 낡았다.** 86행("동기 DB 도구가 도는 중이면 취소가 그 문장이 끝날 때까지 늦다")은 이 이슈로 바뀌었다. 88행("종료 대기 시간 안에 못 끝나면 그 run의 Agent Log가 남지 않는다")은 #278이 이미 바꿨다. 나머지(루프 기본 등록에 기대는 취소, 0.2초마다 다시 보내기)는 그대로다. 212 기록 39행과 213 기록 35행의 "동기 도구가 이벤트 루프를 막는다"도 같은 이유로 낡았다.
- **`Executor.dead_stages()`가 생겼다.** 죽은 단계 → 예외 종류 딕셔너리다. `main`과 테스트가 쓴다.

### 기술 부채

- **버려진 스레드를 멈추지 못한다.** DB 도구는 접속 5초 + 문장 5초(`read_many`는 문장마다) 안에, SIEM 도구는 `deadline_seconds`(15초) 안에 끝난다. 하지만 **DB 서버가 얼면 스레드가 남는 시간에 제한이 없다**(libpq에 클라이언트 읽기 제한이 없다, #278 기록 47행). 취소가 반복되면 스레드가 쌓일 수 있다. 경고 로그로 보인다.
- **DB 서버 쪽 문장 취소와 DB가 얼었을 때의 동작은 실제 PostgreSQL로 확인하지 못했다.** psycopg 3.3.7에 `cancel_safe`가 있다는 것만 확인했다. 이 PC에 PostgreSQL·Docker가 없다. 도구 테스트는 `psycopg.connect`를 이벤트로 막는 가짜로 한다. `db` 마커 테스트는 CI의 `db` 단계에서 돈다.
- **워커의 DB 접속에는 시간 제한이 없다**(`soc/l1/judge.py`, `soc/l2/analyze/worker.py`, `soc/l2/branch/worker.py`, `soc/l3/hunt/*.py`의 `psycopg.connect`). 다른 담당 코드라 고치지 않았고 담당 댓글만 올린다(#278 기록 62행이 #280으로 넘긴 것). 워커가 DB 접속에서 멈추면 이번 변경으로도 취소가 닿지 않아 `stop()`이 종료 대기 시간 초과(종료 코드 1)로 끝난다.
- **한 단계가 죽으면 전체가 3으로 내려가고 재시작이 없다.** 위.

### 후속

- 대기 시간(대상이 생긴 뒤 처리될 때까지)·대기열 길이, DB 표, 화면 API는 **#295**다. `AgentWorker`(`soc/agent/types.py`)에 선택 메서드를 더할지, 각 워커 표를 읽을지는 L1·L2·L3 담당과 정한다. 이 이슈는 L1·L2·L3·`contracts/` 코드를 바꾸지 않았다.

### 관찰(이번 범위 밖)

- `runner._before_start`가 시작 전 실패 줄을 쓰려고 `_writer(sink, config)`가 틀리면 `_writer(sink, {})`로 다시 만든다. 그 안의 `build_redactor({})`까지 실패하면 예외가 `run_task` 밖으로 나갈 수 있다(#279에서 생긴 동작, "어떤 실패에도 예외를 밖으로 내지 않는다"는 약속과 어긋난다). 실제로는 빈 설정에서 실패하기 어렵다. 이 경우에도 LLM 클라이언트는 `finally`로 닫힌다. 후속 이슈로 올릴지는 사람이 정한다. 이슈는 만들지 않았다.

### 확인하지 못한 것

- `db`·`qdrant` 마커 테스트는 이 PC에서 돌리지 못했다(PostgreSQL·Docker 없음). 이 변경은 DB 코드를 바꾸지 않았고, DB 도구 경로의 취소는 가짜 `psycopg.connect`로만 봤다.
- 프런트엔드 검사(`pnpm lint`·`pnpm test`·`pnpm build`)는 돌리지 않았다. 프런트엔드를 바꾸지 않았다.
- 실제 ELK·SSH 호스트·LLM에는 접속하지 않았다.

## 확인 방법

- `uv run ruff format --check .`: 328개 파일이 이미 포맷되어 있음
- `uv run ruff check .`: 통과
- `uv run pytest`: 1,510건 통과, 1건 실패, 453건 제외(`db`·`llm`·`qdrant`·`embedder`·`elk`·`ssh` 마커). 실패 1건은 `tests/test_migrate.py::test_name_ending_in_newline_is_not_a_migration`이고 Windows가 줄바꿈이 든 파일명을 만들지 못해 난다. 이 변경과 무관함을 `origin/main`(`7167ed3`)의 임시 작업 폴더(`git worktree`)에서 같은 테스트만 돌려 같은 `OSError`로 실패하는 것으로 확인했다(임시 폴더는 지웠다). 이 실패는 #212·#213·#278 기록에도 있다.
- 새 테스트를 먼저 썼고 구현 전에 실패하는 것을 봤다. C4: 취소 뒤 `cancelled`까지 약 10초(막힌 도구가 풀릴 때까지). C6·C7: `dead_stages`가 없고 라운드 줄이 없어 실패. C8: `build_client`가 없어 실패(7건 중 6건).
- 주요 테스트
  - `tests/test_tools_cancel.py`(10건): 느린 가짜 DB·SIEM(`MockTransport`)에서 취소 시 1.5초 안에 `cancelled`, 막힌 스레드가 데몬이고 이름이 `soc-tool-<도구>`, 버려진 스레드 경고가 도구 이름·경과 시간만 담음(인자·주소·키·예외 메시지 없음), 정상 호출은 경고 없음, 동기 핸들러는 도구 스레드에서·`async def`는 루프에서, awaitable을 돌려주는 동기 핸들러, 취소된 호출은 `report_tool`과 장부를 건드리지 않음
  - `tests/test_agent_executor_stability.py`(10건): `SystemExit`·`CancelledError`·`RuntimeError`가 단계를 계속 돌게 함(종류만 로그에, 메시지 없음), `poll`의 `CancelledError`, `KeyboardInterrupt`가 단계를 죽은 것으로 표시하고 `threading.excepthook`이 불리지 않으며 다른 단계는 계속 돎, 라운드 지표 줄(건수·`limit`·시간, 빈 라운드 줄 없음, 포화, 실패 건수, 종료로 일찍 끝나도 남음)
  - `tests/test_agent_executor.py`(2건 추가): 단계가 죽으면 `main`이 3을 돌려주고 다른 단계가 정리됨, 정상 종료는 0
  - `tests/test_agent_llm_close.py`(7건): `run_agent`를 5번 연속 실행해도 열린 클라이언트 0, 계약 위반·401·429 실패, 시작 전 실패(가림 준비 실패, 도구 설정 오류), 취소, 닫기 실패(예외 종류만 로그에), `build_model` 호환
- 새 테스트 4개 파일을 3번 반복해 모두 통과했다(63건). `_close_client` 호출을 빼 보니 C8 테스트가 실패했다.
- 재현(레포 밖 스크립트, 가짜 모델): 3초 동기 도구 취소 → 이전 2.50초 뒤 `cancelled`. `asyncio.to_thread`는 취소 0.00초이지만 종료 훅이 2.50초 뒤에 돌았고, 데몬 스레드는 취소 0.00초·종료 훅 0.00초. psycopg async는 Windows 기본 루프에서 `InterfaceError`.
