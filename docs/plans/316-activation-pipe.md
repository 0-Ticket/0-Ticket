---
issue: 316
date: 2026-11-13
owner: Pandyo
supersedes: []
---

# 활성화 파이프 실행: 정규화·Ticket 생성·L1·L2를 대기 상태로 한 번에 띄우기

## 목표

명령 하나(`uv run python -m soc.pipeline`)로 정규화, Ticket 생성, L1, L2를 한 프로세스에서 띄워 대기시킨다. 수집은 사람이 따로 실행하고 L3는 이 명령에서 항상 꺼져 있다. 기동 때 준비 점검(DB·마이그레이션·Qdrant·임베더·LLM·도구 설정)을 항목별 OK/FAIL로 출력하고, 하나라도 FAIL이면 단계를 띄우지 않고 끝낸다. 시험이 "수집 명령 한 번 → 결과 확인"으로 줄고 설정 오류가 첫 건이 아니라 기동 때 드러난다.

## 방법

데이터가 흐르는 순서는 지금과 같다. 단계는 DB를 거쳐 이어지고(원칙 2) 앞 단계가 만든 건을 뒤 단계가 다음 라운드에 집는다. 새로 만드는 것은 단계를 한 프로세스에 묶는 층과 준비 점검이다.

**1. 실행기에 단계 이름 두 개를 더한다 (`src/soc/agent/executor.py`)**
- 실행기 안에서만 쓰는 `EXECUTOR_STAGES = (*STAGES, "normalize", "ticketing")`를 두고 `read_settings`가 허용 키와 순회에 이것을 쓴다. `soc.agent.types.STAGES`·`Stage`·`AgentTask`는 바꾸지 않는다(`AgentTask.stage`와 Agent Log 단계는 l1·l2·l3 그대로).
- `[executor.normalize]`·`[executor.ticketing]` 절이 없으면 지금처럼 돌지 않는 단계다. `config/default.toml`의 `[executor]`는 바꾸지 않으므로 `python -m soc.agent`는 그대로다.
- `main()`을 둘로 나눈다. 시그널 연결·시작·대기 루프(죽은 단계 감지)·종료·종료 코드는 `run_executor(config, ...)`로 빼고, `main()`은 설정을 읽어 그것을 부른다. `main()`의 동작·메시지·종료 코드(0·1·2·3)는 그대로다. 파이프도 `run_executor`를 쓴다.

**2. 파이프 패키지 (`src/soc/pipeline/`, 새로)**
- `__main__.py`: `uv run python -m soc.pipeline`.
  1. 설정을 읽는다(`load_full_config`).
  2. 파이프용 설정을 만든다. `[pipeline]` 값으로 `[executor.normalize]`·`[executor.ticketing]`을 채우고, `[executor.l3] interval_seconds`를 0으로 고정하고, `[executor] shutdown_timeout_seconds`를 `[pipeline]` 값으로 덮는다. L1·L2 절은 그대로 둔다.
  3. 진입점에서 `set_tracing_disabled(True)`를 부른다(D-022).
  4. 준비 점검을 돌린다. FAIL이 하나라도 있으면 단계를 만들지 않고 종료 코드 4로 끝낸다.
  5. 통과하면 `install_service(config)`를 워커 생성 전에 부르고(L1 색인, #313), `Executor`를 만들고, "준비 완료, 수집 명령을 실행하세요"를 출력하고, 종료 신호까지 대기한다.
- `workers.py`: 정규화·Ticket 생성 워커 두 개(`stage = "normalize"`·`"ticketing"`). 등록은 `soc.pipeline.workers:build_normalize_worker`·`build_ticketing_worker`다.
  - 둘 다 "건"이 아니라 "배치" 단위다. `poll`은 처리할 것이 있을 때만 고정 토큰 하나를 돌려주고(없으면 빈 목록이라 라운드 지표 로그도 남지 않는다), `handle`이 기존 `run()`을 한 번 부른다. 로직을 새로 쓰지 않는다.
  - 정규화: `soc.normalize.run.run(settings, conn, owner)`. `poll`은 `store.py`의 claim 조건과 같은 조건의 EXISTS 질의로 대기 원본 유무만 본다(조건이 어긋나지 않게 테스트로 묶는다). pending만 처리하고 failed 재시도(`run_failed`)는 하지 않는다.
  - Ticket 생성: `soc.l1.ticketing.run(conn)`. `poll`은 `ticketing._CANDIDATE_IDS`를 읽기만 하는 EXISTS 질의다.
  - 연결은 `poll`·`handle`마다 열고 닫는다(autocommit). 실패한 건은 기존 `RunResult`의 건수·실패 코드를 INFO·WARNING으로만 남기고 예외 메시지·원문은 남기지 않는다. `run()`이 예외를 내면 실행기가 종류만 로그에 남기고 다음 라운드로 간다.
- `check.py`: 준비 점검. 항목마다 `OK <이름>` 또는 `FAIL <이름> (<실패 종류 코드>)`만 출력하고, FAIL이 나와도 나머지 항목을 모두 돌린다. 주소·계정·키 값과 예외 메시지는 출력하지 않는다(환경변수 이름은 낼 수 있다). 항목:
  - `stages`: L1·L2 단계의 `interval_seconds`가 0보다 크고 워커가 비어 있지 않다.
  - `db`: `DATABASE_URL`로 접속해 `SELECT 1`.
  - `migrations`: 적용하지 않은 마이그레이션이 없다(읽기만).
  - `agent_db`: 도구가 쓰는 `AGENT_DATABASE_URL`(읽기 역할 계정)로 접속. 도구 설정에서 내부 도구를 허용한 단계가 있을 때만 본다.
  - `qdrant`·`embedder`: L2 후보 경로가 `vector`이거나 `search_similar_cases`가 허용돼 있을 때만 본다. 아니면 `SKIP`으로 출력한다. `qdrant`는 직접 접속해 컬렉션 목록을 읽는다(L2 분류 워커의 `build_worker`는 Qdrant 오류를 경고로 넘기므로 워커 생성은 점검이 아니다). `embedder`는 모델을 로드해 짧은 문장 하나를 임베딩한다. 파일이 없으면 "약 2.27GB를 내려받는 중" 한 줄을 먼저 출력하고 받는다(D-044).
  - `llm`: `build_client`로 설정(주소·모델·키 환경변수 존재)을 확인하고, 고정 문자열 한 건을 한 번 보내 응답을 받는다. 로그·DB 값은 보내지 않는다. 키가 틀리면 L1이 첫 건부터 실패를 세어 3회째에 `held`로 두기(D-025) 때문에 기동 때 먼저 거른다.
  - `tools_config`: `[tools.allowed]`의 모든 이름이 레지스트리에 있다. SIEM 조회 도구를 허용한 단계가 있으면 SIEM 접속 환경변수가 있고 `ca_cert_path`가 있으면 파일을 읽을 수 있다. 네트워크 접속은 하지 않는다.
- `config.py`: `[pipeline]` 읽기·검사와 파이프용 설정 만들기.

**3. 마이그레이션 상태 읽기 (`src/soc/db/migrate.py`)**
- `migrate()`는 적용까지 하므로 점검이 쓸 수 없다. 적용하지 않은 파일 이름을 돌려주는 읽기 전용 함수를 새로 더한다. `migrate()`와 같은 기준(번호와 내용 해시)으로 `schema_migrations`와 `find_migrations()`를 비교한다. 기존 함수는 바꾸지 않는다.

**4. 설정 (`config/default.toml`)**

```toml
[pipeline]
normalize_interval_seconds = 3
ticketing_interval_seconds = 3
shutdown_timeout_seconds = 30
```

각 키의 뜻과 `python -m soc.agent`와의 관계를 주석으로 적는다. L1·L2 간격은 `[executor.l1|l2]`를 그대로 쓴다. 새 환경변수는 없다(`.env.example` 변경 없음).

**5. 종료와 취소**
- Ctrl+C·SIGTERM은 실행기의 종료 절차 그대로다. 새 건을 시작하지 않고 진행 중인 run을 `cancelled`로 끝내며 기다린다.
- L1(`judge.py:207`)·L2 분류(`branch/worker.py:95`)·L2 분석(`analyze/worker.py:109`, `:128`)은 `cancelled`면 아무것도 쓰지 않고 돌아오므로 대상이 `pending`·`new`·`escalated`·`analyzing`에 그대로 남아 다음 기동에서 이어진다. 되돌리는 코드는 새로 만들지 않고 테스트로 고정한다.
- 재기동 시 중복 처리 방지도 기존 상태 확인(`normalize_status`, `_existing_ticket`, L1 상태 조건)으로 이미 막혀 있으므로 테스트로 고정한다.
- 정규화·Ticket 배치는 `run()` 안에서 종료 신호를 보지 못한다. 배치가 종료 대기 시간 안에 끝나지 않으면 프로세스가 내려가고, 정규화는 임대 시간(`lease_seconds`, 기본 600초)이 풀릴 때까지 다음 기동이 그 건을 집지 못할 수 있다. 건별 저장이라 데이터는 안전하다. 이 한계를 notes에 적는다.

**6. 종료 코드**
기존 0 정상, 1 종료 대기 시간 초과, 2 설정 오류, 3 단계 스레드가 죽음(실행기 종료 코드, D-050)을 그대로 쓰고, 준비 점검 실패를 4로 한다.

## 바꿀 곳

- `src/soc/agent/executor.py`: `EXECUTOR_STAGES`, `main()`에서 `run_executor` 분리
- `src/soc/pipeline/__init__.py`, `__main__.py`, `config.py`, `check.py`, `workers.py`: 새로
- `src/soc/db/migrate.py`: 적용하지 않은 마이그레이션을 읽기만 하는 함수 추가
- `config/default.toml`: `[pipeline]` 절 추가
- `tests/test_pipeline_config.py`, `tests/test_pipeline_check.py`, `tests/test_pipeline_executor.py`, `tests/test_pipeline_db.py`(db), `tests/test_migrate.py`(읽기 함수 추가분): 새 테스트. 샘플은 `tests/fixtures/lab_cycle/`의 손 샘플과 `tests/test_lab_cycle_db.py`의 도우미·가짜 SIEM·가짜 모델을 재사용하고, 필요하면 손 샘플을 `tests/fixtures/pipeline/`에 더한다
- `docs/decisions.md`: D-054와 기록(이 계획 커밋에서 추가, 머지 충돌 표식 제거는 별도 커밋)
- `docs/plans/316-activation-pipe.md`, `docs/notes/316-activation-pipe.md`

## 다른 코드와 맞물리는 곳

- **`soc.agent.executor`(실행기, L1·L2·L3 담당이 쓴다).** 허용하는 `[executor.<단계>]` 키가 `normalize`·`ticketing`으로 늘고 `main()`이 `run_executor`를 부르도록 나뉜다. `main()`의 동작·메시지·종료 코드, `StageSettings`·`Executor` 시그니처, `AgentWorker`, `STAGES`, `AgentTask`는 바뀌지 않는다. 기존 실행기 테스트(`tests/test_agent_executor.py`, `test_agent_executor_stability.py`)가 그대로 통과해야 한다.
- **`soc.db.migrate`.** 함수 하나가 늘 뿐 기존 함수·마이그레이션 실행은 바뀌지 않는다.
- **`config/default.toml`.** 새 절 `[pipeline]`만 늘고 기존 키·기본값은 바뀌지 않는다.
- **`soc.l1.ticketing`.** `_CANDIDATE_IDS`를 읽기만 한다. 이 이름을 바꾸면 파이프 테스트가 깨지도록 테스트로 묶는다. 코드는 바꾸지 않는다.
- 정규화, L1·L2·L3 워커, 계약, DB 테이블·마이그레이션, 도구 레지스트리는 바꾸지 않는다. 새 환경변수는 없다.

## 범위 밖

- 수집을 파이프에 넣는 것, L3 단계를 이 명령에서 켜는 것
- 정규화 failed 재시도(`run_failed`)
- 파이프와 `python -m soc.agent`를 동시에 띄우는 것을 막는 장치(notes에 경고만 쓴다)
- 정규화·Ticket 배치를 종료 신호로 중단할 수 있게 만드는 것(`run()` 시그니처 변경)
- 임베더를 내려받는 별도 명령, 프로세스 관리·서비스화, 알림
- 도구 점검의 SIEM 실접속
- `docs/decisions.md`의 중복 D-049·D-050 ID 정리(해당 이슈 담당 몫, 이 이슈는 머지 충돌 표식 3줄만 지웠다)
- 판정 품질, 모델·프롬프트 조정

## 완료 기준

- [ ] 명령 하나로 정규화, Ticket 생성, L1, L2 단계가 떠서 대기하고, 수집과 L3는 뜨지 않는다
- [ ] 준비 점검이 항목별 OK/FAIL을 출력하고, 하나라도 실패하면 단계를 띄우지 않고 종료 코드 4로 끝나는 테스트가 있다(가짜 연결로 실패 항목을 만든다)
- [ ] 준비 점검 출력에 키·주소·계정 값이 없는 테스트가 있다(비밀 값처럼 보이는 표식 값을 환경변수·설정에 넣고 출력에 없음을 단언한다)
- [ ] L1 또는 L2의 `interval_seconds`가 0이거나 워커가 비어 있으면 점검이 FAIL인 테스트가 있다
- [ ] 진입점이 `set_tracing_disabled(True)`를 부르며, 환경변수 없이도 트레이싱이 꺼지는 테스트가 있다
- [ ] 가짜 SIEM·가짜 모델로, RawRecord가 쌓이면 정규화 → Ticket → L1 판정 → L2 분류까지 사람의 추가 조작 없이 이어지는 db 테스트가 있다
- [ ] 한 단계의 워커가 예외를 내도 다른 단계가 계속 도는 테스트가 있다
- [ ] 처리할 건이 없을 때 대기하고(빈 반복에서 `handle`을 부르지 않고 라운드 지표 로그가 남지 않는다), 건이 쌓이면 설정 간격 안에 가져가는 테스트가 있다
- [ ] 재기동 후 이미 처리된 건이 다시 처리되지 않는 테스트가 있다
- [ ] 종료 시 진행 중이던 L1·L2 판정이 실패·보류로 남지 않고 처리 대기 상태로 돌아가는 테스트가 있다
- [ ] `[executor.l3]`의 `interval_seconds`를 0보다 크게 해도 이 명령에서는 L3가 돌지 않는 테스트가 있다
- [ ] 적용하지 않은 마이그레이션을 읽기만 하는 함수가 `migrate()`와 같은 기준(번호·내용 해시)으로 동작하는 db 테스트가 있다
- [ ] 정규화·Ticket 워커의 `poll` 조건이 기존 `run()`이 집는 대상과 어긋나지 않는 db 테스트가 있다
- [ ] L3 수동 명령으로 만든 Ticket(`escalated`)이 떠 있는 L2에 들어가는지 손으로 확인했다
- [ ] 손으로 확인(맥, Foundry): 파이프를 띄우고 다른 터미널에서 수집 명령을 실행하면 L2 분석까지 이어지는 것을 보고, 소요 시간·건수·비용을 `docs/notes/`에 건수로 적었다(사람이 숫자를 준다)
- [ ] 기존 한 번 실행 명령(`soc.normalize`, `soc.l1.ticketing`, `soc.agent`, `soc.l3 hunt`)이 그대로 동작한다(기존 테스트 통과)
- [ ] 키·비밀 값이 코드, 테스트, 로그, notes, PR에 없다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run pytest -m "db or qdrant"` 통과
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록

## 토론으로 정한 것

- **정규화·Ticket 생성은 실행기 단계로 넣는다(질문 1 A).** 단계 이름은 `executor.py` 안에만 둔다. `STAGES`는 `AgentTask.stage` 검증에도 쓰여서 거기에 넣으면 에이전트 작업이 `normalize`를 받을 수 있게 된다. 별도 스레드를 따로 만드는 안(B)은 종료·죽음 처리가 둘로 갈려 버렸다.
- **간격은 `[pipeline]`에 둔다(질문 2 A).** 정규화·Ticket 3초, 종료 대기 30초. L1·L2는 기존 `[executor.l1|l2]`를 쓴다. `[executor.normalize]` 기본값을 0보다 크게 두면 `python -m soc.agent`도 정규화를 띄워 "기존 명령 그대로"가 깨지기 때문이다. 이슈 본문의 "단계별 간격을 `config/default.toml`에" 요구는 `[pipeline]`과 기존 `[executor.l1|l2]`로 충족한다.
- **준비 점검의 깊이(질문 3).** LLM은 설정 확인 + 고정 문자열 실호출 1회다. 이슈의 "실호출을 할지"에 대한 답이다. 틀린 키로 기동하면 L1이 쌓인 알럿을 몇 라운드 만에 `held`로 만들 수 있고(L1에는 L2와 같은 쿨다운이 없다) 비용은 수 토큰이다. SIEM·도구는 네트워크 없이 설정만 본다. 실접속 코드를 새로 만들지 않아도 되고 접속 실패는 도구가 `TOOL_ERROR`로 이미 처리한다.
- **임베더 파일이 없으면 점검이 내려받는다(질문 6 A).** 내려받기 명령이 없고(내려받기는 `embedder.py`의 첫 로드 안에서만 일어난다), 안 받으면 첫 L2 건에서 L2 스레드가 같은 다운로드에 멈추기 때문이다. 점검 중 진행을 알리는 한 줄을 출력한다. 점검에서 올린 임베더를 워커가 다시 올리는지(메모리 두 배)는 개발 때 확인하고 notes에 적는다.
- **정규화 failed 재시도는 넣지 않는다(질문 4 A).** 같은 실패가 반복돼 로그만 늘 수 있고 이슈 범위 밖이다. `soc.normalize.__main__.main`도 pending만 돌린다.
- **`docs/decisions.md` 머지 충돌 표식은 이 이슈에서 별도 커밋으로 지운다(질문 5).** 추천은 "별도 이슈로 뺀다"였으나 사람이 이번 이슈에서 하기로 정했다. 표식 3줄만 지우고 양쪽 기록 줄은 모두 남겼다. 중복 ID는 고치지 않았다.
- **"취소된 판정을 대기 상태로 되돌리는 방법"은 새 코드가 없다.** L1·L2 모두 `cancelled`면 쓰지 않고 돌아오므로 L3 검증과 같은 방식이다. 테스트로 고정한다.
- **결정 목록.** D-054를 확정으로 추가했다(실행기 단계, 준비 점검, 종료 코드 4, 정규화 임대 지연 한계).
- 기본안으로 정한 것: 종료 코드 4, 점검 출력 형식(항목 + OK/FAIL + 실패 종류 코드), FAIL이 나와도 나머지 항목을 끝까지 돌림, Qdrant·임베더는 필요할 때만 점검(아니면 SKIP), L1·L2 간격 0이면 점검 FAIL, 배치 단위 워커(`poll`은 토큰 하나), 라운드마다 DB 연결, 인스턴스 중복은 막지 않고 notes에 경고, 종료 때 정규화·Ticket 배치는 중단하지 않음.

## 바뀐 점
