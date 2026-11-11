---
issue: 280
date: 2026-11-11
owner: Interludeal
supersedes: []
---

# 실행기와 도구 호출이 멈추거나 새지 않게 하기

## 목표

- (C4) 동기 도구(DB·SIEM)가 도는 중에 취소를 보내도 run이 도구 시간만큼 기다리지 않고 바로 `cancelled`로 끝난다.
- (C6) 단계 스레드가 `Exception`이 아닌 예외로 끝나도 예외 종류가 실행기 로그에 남고, 어느 경우에도 "프로세스는 실행 중인데 그 단계는 멈춘" 상태가 없다.
- (C7) 실행기가 라운드마다 워커별 받은 건수·처리 건수·처리 시간을 실행기 로그에 남긴다. 대기 시간·DB·화면 지표는 새 이슈(#TBD)로 뺀다.
- (C8) `run_agent`가 만든 LLM 클라이언트가 run이 어떻게 끝나든 닫힌다.

## 방법

기준은 `origin/main`(`7167ed3`, #278·#279 머지 뒤)이다. 이슈 본문은 `5a9ab2d` 기준이다. 그 뒤 #278이 머지돼서 C4의 "Agent Log가 남지 않는다"는 영향은 진행 중이던 호출 하나의 줄이 없고 그 run이 `incomplete`로 보이는 정도로 줄었다. `executor.py`·`llm.py`는 기준 커밋 이후 바뀌지 않았고 C4·C6·C7·C8은 모두 그대로다. 재현은 가짜 모델로 확인했다(C4: 취소가 2.50초 늦음, C6: `SystemExit`·`KeyboardInterrupt`·`poll`의 `CancelledError`가 스레드를 끝내고 로그에 아무것도 없음, C8: 클라이언트가 열린 채 쌓임).

### C4. 동기 도구 핸들러를 호출마다 전용 데몬 스레드에서 돌린다 (후보 C)

- `ToolSession.invoke`(`registry.py`)가 핸들러를 부르는 자리에서, `async def` 핸들러는 지금처럼 이벤트 루프에서 await한다(SSH). 그 밖의 핸들러는 호출마다 새 데몬 스레드에서 부르고 `concurrent.futures.Future` + `asyncio.wrap_future`로 기다린다(`agent_log.RowWriter._spawn`과 같은 방식). 스레드에서 부른 결과가 awaitable이면 루프에서 await한다.
- `asyncio.to_thread`는 쓰지 않는다. 기본 실행기 스레드는 프로세스가 끝날 때 합류돼 종료가 도구 시간만큼 붙잡힌다(#278 기록 48행). 재현: `to_thread`는 취소가 0.00초에 닿지만 종료 훅은 2.50초 뒤에 돌았고, 데몬 스레드는 취소 0.00초·종료 훅 0.00초였다.
- async 클라이언트(psycopg async, `httpx.AsyncClient`)로 바꾸지 않는다. psycopg async는 Windows 기본 이벤트 루프(`ProactorEventLoop`)에서 `InterfaceError`로 거부된다(재현함). 고치려면 단계 스레드 루프를 바꿔야 하고, `siem.py`·`internal.py`·`web.py`·`fake_siem.py`가 넓게 바뀌며 #281·#214와 겹친다.
- 취소의 뜻: 기다림만 끊고 진행 중인 DB 문장·HTTP 요청은 끝까지 둔다. 결과는 버린다. 취소된 호출은 `report_tool`·장부 갱신을 하지 않는다(이 둘은 await 뒤 루프 쪽에서만 한다). 핸들러는 스레드에서 `ctx`만 쓴다. `ctx.fits`는 순수 함수다.
- **취소로 버려진 스레드가 있으면 `soc.agent.executor` 로거에 WARNING 한 줄을 남긴다.** 도구 이름과 취소까지 경과 시간(초)만 적고 인자·예외 메시지·호출 ID는 적지 않는다. 레지스트리 모듈이 로거 이름 `soc.agent.executor`를 직접 쓴다(운영자가 실행기 로그 한 곳에서 보게 하기 위해서다).
- 스레드 이름은 `soc-tool-<도구 이름>`, 데몬이다. 핸들러가 낸 `BaseException`은 `Future`에 담아 루프에서 다시 낸다(지금 동기 핸들러가 루프에서 직접 내던 것과 같은 효과이고, 처리는 C6이 한다).
- 테스트(먼저 쓴다): 느린 가짜 DB 도구(`psycopg.connect`를 이벤트로 막는 가짜)와 느린 가짜 SIEM 도구(`MockTransport` 처리기가 이벤트로 막음)가 도는 중에 `_cancel_all`을 보내고 제한 시간 안에 `cancelled`·Agent Log 종료 줄을 확인한다. 막힌 스레드는 테스트 끝에 풀어 준다. 데몬 스레드임, 경고 로그에 도구 이름·경과 시간만 있고 인자·메시지가 없음, 취소가 없는 정상 호출은 경고가 없음, async 핸들러는 스레드를 만들지 않음, 기존 동기 도구 테스트가 그대로 통과함을 본다.

### C6. 예외 종류별로 나눈다 (후보 A1)

- `_StageThread._round`: `poll`·`handle` 모두 `Exception`·`asyncio.CancelledError`·`SystemExit`을 잡는다. 예외 종류(`type(exc).__name__`)만 로그에 남기고 다음 건(`poll`이면 다음 워커)으로 간다. 한 건이 파이프를 멈추게 하지 않는다. 같은 건이 다시 나오는 것은 지금 `Exception`과 같고 시도 횟수는 워커가 센다(215 기록 "워커 틀").
- `_StageThread._run`: 그 밖의 `BaseException`(`KeyboardInterrupt`, `GeneratorExit` 등)과 `_round` 밖의 실행기 자체 오류를 맨 위에서 잡는다. 종류만 `logger.error`로 남기고 **다시 올리지 않는다**(다시 올리면 `threading.excepthook`이 메시지가 든 트레이스백을 stderr에 찍는다, `docs/security.md`). 그 단계를 죽은 것으로 표시한다. 기존 `finally`(루프 정리)는 그대로 돈다.
- `Executor`에 죽은 단계와 예외 종류를 돌려주는 메서드를 하나 둔다(테스트가 `main`의 설정 로딩 없이 보게 하려는 것이다).
- `main` 메인 루프: 0.5초 틱마다 죽은 단계가 있는지 본다. 있으면 "종료 중"과 같은 정리 길(`executor.stop()`)로 다른 단계를 취소하며 끝내고 **종료 코드 3**으로 돌려준다. 죽은 단계도 있고 종료 대기 초과도 있으면 3이다. 종료 코드는 0 정상, 1 종료 대기 시간 초과, 2 설정 오류, 3 단계 스레드가 죽음이 된다.
- 재시작은 하지 않는다. `BaseException` 뒤의 상태를 믿을 수 없고, 같은 건이 다시 나와 무한히 재시작될 수 있으며, 이 레포에는 프로세스 관리자가 없다. 한 단계가 죽으면 다른 단계도 같이 내려가는 것은 알고 가는 대가다.
- 실행기 종료 코드에 기대는 곳을 `.github`, `scripts`, compose·Docker 파일, README·CONTRIBUTING, `docs/*.md`, `prompts/`, `.claude/skills`, `.agents`에서 찾았다. 없다(`executor.main` docstring과 `tests/test_agent_executor.py`의 `main` 테스트만 있다). `main` docstring과 모듈 docstring의 "poll·handle의 예외" 문장, 실행기 테스트를 함께 고친다. `docs/notes/215-...`는 고치지 않는다(지난 기록).
- 테스트(먼저 쓴다): `handle`의 `SystemExit`·`CancelledError`, `poll`의 `CancelledError`가 로그에 종류만 남기고 같은 스레드가 다음 건·다음 라운드를 계속 돈다. `KeyboardInterrupt`는 단계가 죽은 것으로 표시되고 예외 종류만 로그에 남으며 stderr에 트레이스백이 없다. 죽은 단계가 있으면 `main`이 3을 돌려주고 다른 단계가 정리된다. 로그에 예외 메시지가 없다.

### C7. 실행기 로그에 라운드 지표만 남긴다 (후보 D)

- `_round`가 워커마다 INFO 한 줄을 남긴다. 받은 건이 있을 때만 남긴다(빈 라운드는 조용히 둔다). 모양: `round stage=<단계> worker=<이름> polled=<n> limit=<poll_limit> handled=<n> failed=<n> total_ms=<ms> max_ms=<ms>`. `polled == limit`이면 밀리고 있다는 신호다(다른 담당 표를 읽지 않고 셀 수 있다). `total_ms`는 그 워커의 `handle` 합, `max_ms`는 건당 최대다. 종료 요청으로 일찍 끝난 라운드도 지금까지의 값으로 남긴다. subject ID·예외 메시지는 넣지 않는다.
- `poll` 실패와 `handle` 실패의 기존 경고 줄은 유지한다.
- 이 이슈에서 하지 않는 것: 대상이 생긴 뒤 처리될 때까지의 대기 시간, DB 표, 화면 API. `AgentWorker` 프로토콜에 선택 메서드를 더하거나 L1·L2·L3 표를 읽어야 해서 각 담당과 정할 일이다. 새 이슈로 뺀다. 이슈 번호는 사람이 만들어 알려 주고, 그때까지 문서에는 `#TBD`로 둔다. 다른 담당 코드(`src/soc/l1/`, `l2/`, `l3/`, `contracts/`)는 바꾸지 않는다.
- 테스트(먼저 쓴다): 가짜 워커로 로그 줄의 필드 값(받은 건수, `limit`, 처리·실패 건수, 시간이 0 이상), 빈 라운드에는 줄이 없음, 일부가 실패해도 줄이 남음, 종료로 일찍 끝나도 줄이 남음.

### C8. run마다 LLM 클라이언트를 만들고 끝날 때 닫는다 (후보 A)

- `llm.py`에 클라이언트를 따로 만드는 함수(이름·모양은 개발 때 정한다)를 두고, `build_model`의 시그니처와 반환 `(모델, 모델 이름)`은 그대로 둔다(호출은 `runner.py`와 `tests/test_agent_llm.py`뿐). `run_agent`는 클라이언트를 직접 받아 모델을 만들고, `run_task`가 끝난 뒤(시작 전 실패 경로 포함: 가림·Agent Log 설정·프롬프트·도구 설정 오류) `finally`에서 닫는다. `run_task`와 `build_model` 쪽 테스트는 바뀌지 않는다.
- 닫기는 그 스레드의 기본 이벤트 루프로 한다(`Runner.run_sync`가 쓰는 루프와 같은 루프). 다른 루프(`asyncio.run`)로 닫지 않는다. 기본 루프가 없으면 만들어서 닫고 정리한다. 종료 중 `_cancel_all`이 닫는 작업을 취소할 수 있으므로 `CancelledError`를 포함한 예외를 삼키고 `run_agent`는 예외를 내지 않는다(예외 종류만 남기고 메시지는 남기지 않는다).
- 단계 스레드마다 하나를 두는 안(B)은 하지 않는다. httpx2 기본 `keepalive_expiry`가 5초라 재사용 이득이 5초 안에 이어지는 호출뿐이고, 실행기 밖 호출자(`dev_l1`, `soc.l3 hunt`)의 수명 관리가 필요하다.
- 테스트(먼저 쓴다): `build_model`·클라이언트 생성 함수를 가짜 전송(`httpx2.MockTransport`)을 넣는 것으로 바꿔 `run_agent`를 여러 번 연속 실행한 뒤 만든 클라이언트가 모두 `is_closed()`인지 본다. 정상 종료, 계약 위반 등 실패, 취소, 시작 전 실패(LLM 설정 없음, 가림 준비 실패)를 모두 포함한다.

### 문서와 기록

- `docs/decisions.md`: D-049(동기 도구 핸들러 스레드), D-050(단계 스레드 예외 처리와 종료 코드)를 더하고 "기록"에 한 줄을 쓴다.
- 개발 기록 `docs/notes/280-executor-tool-stability.md`: `supersedes: ["215-executor-l1-e2e.md"]`(그 기록의 "취소의 한계"가 바뀐다), 계획과 달라진 점, 다음 사람이 알아야 할 것, 기술 부채, 새 이슈 번호(C7을 뺀 이슈. 정해지기 전에는 `#TBD`로 두고 마지막 답변에 바꿀 줄을 적는다), 확인하지 못한 것.
  - 기술 부채에 적을 것: 취소로 버려진 스레드가 남는 한계(DB는 접속 5초 + 문장 5초 안에, SIEM은 약 15초 안에 끝나지만 DB가 얼면 제한이 없다), 서버 쪽 문장 취소(`cancel_safe`는 psycopg 3.3.7에 있다)와 DB 정지 동작을 실제 PostgreSQL로 확인하지 못했다는 것, 워커의 DB 접속 시간 제한(질문 5, 아래), 한 단계가 죽으면 프로세스 전체가 종료 코드 3으로 끝나는 것과 재시작이 프로세스 관리자의 몫이라는 것.
  - 215 기록 "취소의 한계" 중 86행(동기 DB 도구가 도는 중이면 취소가 늦다)과 88행(종료 대기 초과 시 Agent Log가 남지 않는다 — #278이 이미 바꿈)을 이 기록이 바꾼다고 적는다.

## 바꿀 곳

- `src/soc/tools/registry.py`: 핸들러 호출을 데몬 스레드로, 취소로 버려진 스레드 경고 로그(C4)
- `src/soc/agent/executor.py`: `_round` 예외 처리와 라운드 지표 로그, `_run` 최상위 처리, 죽은 단계 표시와 조회, `main` 루프의 감지와 종료 코드 3, docstring(C6·C7)
- `src/soc/agent/llm.py`: 클라이언트를 따로 만드는 함수(C8). `build_model`은 유지
- `src/soc/agent/runner.py`: `run_agent`가 클라이언트를 받아 모든 경로에서 닫음(C8)
- `tests/test_tools_registry.py`, `tests/test_agent_executor.py`, `tests/test_agent_llm.py`(필요하면 새 테스트 파일): 위 테스트
- `docs/decisions.md`, `docs/plans/280-executor-tool-stability.md`, `docs/notes/280-executor-tool-stability.md`

## 다른 코드와 맞물리는 곳

- **도구 핸들러 규칙(도구를 만드는 사람 — #214, #281 등).** 동기 핸들러는 이벤트 루프 스레드가 아닌 별도 스레드에서 돈다. `ctx`와 자기 인자 밖의 스레드 로컬·`contextvars`에 기대지 않는다. 핸들러 시그니처와 `ToolSpec`은 바뀌지 않는다. `async def` 핸들러는 지금과 같다.
- **`AgentWorker` 계약(L1·L2·L3 워커 담당).** `handle`·`poll`이 `SystemExit`·`CancelledError`를 내도 실행기는 `Exception`처럼 로그만 남기고 계속 돈다. 시그니처·등록 방법은 바뀌지 않는다. 같은 건이 계속 나오면 시도 횟수는 워커가 센다.
- **실행기 종료 코드(운영).** 3이 새로 생긴다. 레포 안에서 종료 코드에 기대는 곳은 없다.
- **실행기 로그(운영).** 라운드 지표 INFO 줄과 버려진 도구 스레드 WARNING 줄이 `soc.agent.executor`에 더해진다.
- `build_model`의 시그니처·반환은 그대로다. 설정 키·테이블·데이터 형식은 바뀌지 않는다.

## 범위 밖

- async 클라이언트(psycopg async, `httpx.AsyncClient`)로 바꾸기(C4 후보 B)
- 서버 쪽 DB 문장 취소(`cancel_safe`)를 쓰기, 도구 호출 전체 마감 시간을 새로 두기
- 죽은 단계 스레드 재시작(C6 후보 B)
- 단계 스레드마다 LLM 클라이언트 하나(C8 후보 B)
- 대기 시간·대기열 길이 지표, DB 표, 화면 API(C7 후보 B·C): 새 이슈(#TBD)
- 워커의 DB 접속 시간 제한(`soc/l1/judge.py:177`, `soc/l2/analyze/worker.py:54`, `soc/l2/branch/worker.py:75`, `soc/l3/hunt/*.py`): 다른 담당 코드라 바꾸지 않고 담당 댓글만 올린다. C4를 고쳐도 워커가 DB에서 멈추면 `stop()`이 시간 초과로 끝난다는 점은 개발 기록에 적는다.
- `src/soc/l1/`, `l2/`, `l3/`, `contracts/` 변경

## 완료 기준

- [ ] (C4) 느린 가짜 DB 도구와 느린 가짜 SIEM 도구(`MockTransport`)가 도는 중에 취소를 보내면, run이 정한 시간 안에 `cancelled`로 끝남을 테스트로 확인한다. 막힌 스레드가 데몬이고, 버려진 스레드에 대해 `soc.agent.executor`에 도구 이름·경과 시간만 있는 WARNING 한 줄이 남음을 테스트로 확인한다
- [ ] (C6) `handle`의 `SystemExit`, `poll`의 `CancelledError`가 예외 종류만 로그에 남기고 단계를 계속 돌게 하며, 그 밖의 `BaseException`은 단계를 죽은 것으로 표시해 `main`이 다른 단계를 정리하고 종료 코드 3으로 끝남을 테스트로 확인한다. 로그와 stderr에 예외 메시지가 없다
- [ ] (C7) 가짜 워커로 라운드 지표 줄(받은 건수·`limit`·처리·실패 건수·시간)이 `soc.agent.executor`에 남고 빈 라운드에는 없음을 테스트로 확인한다. 대기 시간·DB·화면은 새 이슈로 뺐고, 그 번호를 개발 기록에 적는다(정해지기 전에는 `#TBD`)
- [ ] (C8) 가짜 전송 계층으로 `run_agent`를 여러 번 연속 실행(정상·실패·취소·시작 전 실패 포함)한 뒤, 만든 클라이언트가 모두 닫혀 있음을 테스트로 확인한다
- [ ] `main` docstring의 종료 코드 목록(0·1·2·3)과 실행기 문서 문장이 고쳐졌다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록(`supersedes`에 `215-executor-l1-e2e.md`, 기술 부채, 확인하지 못한 것)

## 토론으로 정한 것

이슈 본문의 "정하지 못함" 네 항목과 새 질문 하나를 사람이 아래처럼 정했다(2026-11-11).

- **C4: 후보 C(호출마다 전용 데몬 스레드), D-049.** 본문의 A(`asyncio.to_thread`)·B(async 클라이언트)가 아니다. 이유: A는 종료가 도구 시간만큼 붙잡히고 DB가 얼면 제한이 없다(#278 기록 48행, 재현 확인). B는 Windows에서 psycopg async가 동작하지 않고 `siem.py`·`fake_siem.py`·#281·#214와 넓게 겹친다. 취소하면 진행 중인 요청은 끝까지 두고 결과만 버린다. 사람이 더한 것: 버려진 스레드가 생기면 `soc.agent.executor`에 WARNING 한 줄(도구 이름·경과 시간만), 한계와 "DB가 얼면 제한 없음", 서버 쪽 문장 취소·DB 정지 동작을 확인하지 못했다는 것을 기술 부채에 적는다.
- **C6: A1, D-050.** 본문의 A·B·C와 다르다. `Exception`·`CancelledError`·`SystemExit`은 종류만 로그에 남기고 계속 돈다. 그 밖의 `BaseException`과 스레드 자체 오류는 그 단계를 죽은 것으로 표시하고 메인 루프가 감지해 다른 단계를 정리한 뒤 종료 코드 3으로 끝난다. 이유: `SystemExit`을 치명으로 두면 한 건이 프로세스를 죽이고 재시작해도 같은 건이 다시 나와 무한 재시작이 된다. 재시작(B)은 `BaseException` 뒤 상태를 믿을 수 없고 숨은 결함을 가린다. 로그만(C)은 이미 죽은 스레드를 고치지 못한다. 사람이 더한 것: 종료 코드 3을 넣기 전에 레포 안 의존처를 grep으로 확인한다(없음, 위 C6), `main` docstring과 관련 문서의 종료 코드 목록을 함께 고친다.
- **C7: 후보 D(실행기 로그만, 나머지는 새 이슈).** 이슈 본문의 "이 이슈에서 할지 따로 뺄지"를 따로 빼는 쪽으로 정했다. 사람이 새 이슈를 만들어 번호를 알려 준다. 그때까지 `#TBD`. 새 이슈 본문 초안과 L1·L2·L3 담당 댓글 초안은 확정 때 낸다.
- **C8: 후보 A(run마다 만들고 닫기).** 이유: B의 재사용 이득은 5초 안에 이어지는 호출뿐이고(`keepalive_expiry` 5초), 실행기 밖 호출자의 수명 관리가 필요하다. `build_model`의 시그니처·반환은 유지한다.
- **질문 5(새): 워커 DB 접속 시간 제한은 후보 B(담당 댓글만).** 다른 담당 코드는 바꾸지 않는다. 댓글 초안은 확정 때 낸다.
- **원래 이슈와 달라진 점.** #278 머지로 C4의 영향이 줄었다(위 "방법"). C4·C6은 이슈에 없던 후보(C4-C, C6-A1)를 택했다. 결정 목록에 D-049·D-050을 올렸다.

## 바뀐 점

