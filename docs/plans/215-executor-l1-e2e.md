---
issue: 215
date: 2026-11-05
owner: Pandyo
supersedes: []
---

# 실행기 만들고 실제 모델로 L1 종단 확인하기

## 목표

`soc.agent`에 `AgentWorker` Protocol과 단계별 스레드 실행기를 만든다. L1·L2 워커가 실행기에 줄 최소한의 틀(Protocol, 등록 함수, 지킬 약속)을 정해 각 담당에게 넘긴다. 워커 없이 L1 판정 작업을 `run_agent`에 직접 넣어 Foundry `gpt-oss-120b`로 도구 호출 → Verdict → Agent Log를 끝까지 돌리고, 턴·토큰·비용을 실측한다.

## 방법

설계 출처: 연구 레포 `0-Ticket/soc-incident-response-research` 커밋 `84a6139`(`Interludeal` 브랜치에만 있고 main에는 없다), `05-implementation/Agent SDK/`의 `설계/08-실행기.md`, `설계/02-인터페이스.md`, `설계/01-SDK와 모델.md`, `설계/03-에이전트 내부.md`, `파이프 전달 사항.md`.

### 1. 워커 틀 (L1·L2·L3 공통)

```python
class AgentWorker(Protocol):
    stage: Literal["l1", "l2", "l3"]
    name: str

    def poll(self, limit: int) -> Sequence[str]: ...
    def handle(self, subject_id: str) -> None: ...


def build_worker(config: dict[str, Any]) -> AgentWorker: ...  # 각 담당 모듈에 둔다
```

| 항목 | 약속 |
|---|---|
| 등록 | `[executor.<stage>] workers = ["soc.<모듈>:build_worker"]`. `soc.` 아래 모듈만 받는다. 시작할 때 `worker.stage`가 등록한 단계와 다르거나, 가져오지 못하거나, 같은 단계에 `name`이 겹치면 실행기가 시작하지 않는다 |
| `config` | 기본 설정 위에 `local.toml`을 덮어쓴 설정 전체(dict). 워커는 자기 절만 읽는다. 비밀 값·DB 주소는 워커가 환경변수에서 직접 읽는다 |
| `poll` | 실행기는 항상 정수 `poll_limit`을 넘긴다. 결과가 기록된 건은 다시 내지 않는다. #223 HuntVerifier의 `poll(limit: int \| None)`도 이 Protocol을 만족하므로 바꾸지 않는다 |
| `handle` | 멱등이다. `run_agent`(동기)를 부르고 결과를 자기 테이블에 쓴다 |
| 예외 | `poll`·`handle`의 예외는 실행기가 잡고 워커 이름·subject ID·예외 종류만 로그에 남긴다(메시지는 밖에서 온 문자열일 수 있어 남기지 않는다). 같은 건이 계속 실패하면 매 라운드 다시 나오므로 시도 횟수는 워커가 센다 |
| 종료 | 진행 중인 `run_agent`는 `failure = "cancelled"`로 돌아온다. 실패 횟수에 넣지 않고 다음 실행에서 다시 하기를 권한다 |
| 스레드 | `handle`은 단계 스레드에서 돈다. `asyncio.run`처럼 이벤트 루프를 새로 만들거나 바꾸는 코드를 쓰지 않는다. DB 연결은 `handle`마다 연다 |

L1·L2 워커 코드는 이 이슈에서 만들지 않는다. 각 담당이 만든다.

### 2. 실행기 (`soc.agent.executor`, 실행 `uv run python -m soc.agent`)

- 설정의 `[executor.<stage>]`마다 등록 워커를 `build_worker(config)`로 만든다. 워커가 없거나 `interval_seconds = 0`인 단계는 스레드를 띄우지 않는다(`poll`도 부르지 않는다).
- 단계마다 스레드 하나. 스레드는 시작할 때 asyncio 이벤트 루프를 하나 만들어 그 스레드의 기본 루프로 등록한다. `Runner.run_sync`(openai-agents 0.24.0)는 스레드의 기본 루프를 그대로 쓰므로, 실행기는 이 루프로 진행 중인 run을 취소할 수 있다.
- 라운드: 등록 순서대로 워커마다 `poll(poll_limit)` → 받은 ID마다 `handle`. 라운드가 끝나면 `interval_seconds`만큼 쉰다(종료 신호를 받으면 바로 깬다). 단계 안 동시 실행은 1건이다.
- 종료(SIGINT·SIGTERM 또는 `stop()`): 새 건을 시작하지 않는다. 진행 중인 `handle`이 끝날 때까지 0.2초마다 그 스레드 루프의 작업을 `call_soon_threadsafe`로 취소한다. `run_agent`는 `asyncio.CancelledError`를 `cancelled`로 바꿔 Agent Log를 쓰고 돌아온다(코어 코드는 바꾸지 않는다). `shutdown_timeout_seconds`를 넘기면 끝나지 않은 단계를 로그에 남기고 끝낸다(스레드는 daemon).
- 동기 DB 도구가 도는 중이면 취소는 문장 시간 상한(`statement_timeout_ms`)까지 늦을 수 있다. 모델 호출은 바로 끊긴다.

설정(`config/default.toml`):

```toml
[executor]
shutdown_timeout_seconds = 30

[executor.l1]
interval_seconds = 10
poll_limit = 10
workers = []

[executor.l2]
interval_seconds = 10
poll_limit = 10
workers = []

[executor.l3]
interval_seconds = 0
poll_limit = 10
workers = []
```

### 3. strict 기본값

`[llm] strict_mode` 기본값을 `false`로 바꾼다. Foundry는 도구 정의에 strict를 켜면 최종 답이 빈 문자열로 온다(#224 실측). 빈 응답을 다른 형식 오류와 구분해 기록하는 것은 범위 밖이다.

### 4. L1 종단 확인 (워커 없이)

- 샘플: `tests/fixtures/l1_e2e/`에 손으로 만든 Alert 6건과 관련 Event·RawRecord. 정상 2(예정된 작업, 알려진 서비스 계정), 위협 2(인코딩된 PowerShell 다운로드, 웹 공격 성공 응답), 애매 2. 문서용 IP(192.0.2.0/24 등)와 `example.com`만 쓴다.
- 측정용 개발 명령 `uv run python -m soc.agent.dev_l1`
  - `seed`: 이전 측정 시드를 지우고 샘플을 개발 DB에 넣는다. 시각은 넣는 시점 기준이다
  - `run`: 시드 Alert마다 L1 AgentTask(`stage = "l1"`, `subject_type = "alert"`, `output_contract = "verdict"`, `cited_ids = evidence_ids`)를 만들어 `run_agent`를 부른다. 출력은 Alert마다 숫자와 `decision`·`failure`만(이유 본문 없음)
  - `remove`: 시드만 지운다. Agent Log는 남긴다
  - 4층 작업 프롬프트와 `data` 모양은 측정용이다. L1 코드가 아니며 L1 담당이 정할 모양과 다를 수 있다. Alert에 판정 결과(`triage`)를 쓰지 않는다
- `llm` 마커 테스트 1건(`tests/test_l1_e2e_llm.py`): 임시 DB에 시드를 넣고 위협 Alert 1건을 `run_agent`로 돌려, 결과가 `ok`이고 Verdict가 계약을 통과하며 인용 ID가 근거 장부 안에 있고 Agent Log가 남는지 본다. `decision` 값은 단언하지 않는다.
- 실측은 사람이 맥에서 한다: `seed` → `run` 3라운드(6건 × 3 = 18 run) → 집계 SQL → `remove`. 명령 순서와 집계 SQL(본문 없이 숫자만)은 `docs/notes/215-executor-l1-e2e.md`에 적는다.
- 비교 기준: 평균 L1 작업 약 1.1만~1.8만 토큰, 약 $0.0035(설계 추정).

### 5. 예산 판단

실측 뒤 사람이 판단한다. 제안 기준: `budget_exceeded` 0건이고 `max_turns`(6)에 닿은 run이 없으면 그대로 둔다. 바꾸면 `config/default.toml`과 문서의 값을 함께 고치고, 연구 레포 설계 문서 수정 사항은 notes의 알림 목록에 적는다.

### 순서

샘플 → 실행기 테스트(가짜 워커) → 실행기 → strict 기본값 → L1 시드·명령 테스트 → L1 시드·명령 → `llm` 테스트 → notes

## 바꿀 곳

- `src/soc/agent/types.py`·`__init__.py`: `AgentWorker` Protocol
- `src/soc/agent/executor.py`, `src/soc/agent/__main__.py`: 실행기와 실행 명령
- `src/soc/agent/dev_l1.py`: L1 측정용 시드·실행 명령(개발 DB 전용)
- `config/default.toml`: `[executor]`, `[llm] strict_mode = false`
- `tests/fixtures/l1_e2e/`, `tests/test_agent_executor.py`, `tests/test_agent_dev_l1*.py`, `tests/test_l1_e2e_llm.py`
- `docs/decisions.md`: 기본 LLM(D-009)·에이전트 구조(D-024) 메모
- `docs/notes/215-executor-l1-e2e.md`

## 다른 코드와 맞물리는 곳

- 새로 만듦: `AgentWorker` Protocol, `build_worker(config)` 등록 규칙, `[executor]` 설정 키, `uv run python -m soc.agent`. L1 담당, L2-A-3(#228), L3 3-c가 따른다
- 바꿈: `[llm] strict_mode` 기본값 `true` → `false`(모든 단계)
- 그대로: `run_agent`·`run_task`, HuntVerifier

## 범위 밖

- L1·L2 워커 코드(각 담당), L1 판정 결과 조건(D-025)
- 실행기 훅(L3 3-c). 확장 지점만 notes에 적는다
- HuntVerifier의 `cancelled` 처리(지금은 시도 횟수에 넣는다, L3 3-c)
- strict 빈 응답을 다른 형식 오류와 구분해 기록하기
- 실제 모델 호출(사람이 맥에서 한다)

## 완료 기준

- [ ] 가짜 워커 2개로 단계 간 병렬, 단계 안 순차 실행을 확인한다
- [ ] 한 워커의 예외가 다른 워커를 멈추지 않는다
- [ ] `interval_seconds = 0`인 단계는 `poll`이 불리지 않는다
- [ ] 종료 시 진행 중인 `run_agent`(가짜 모델)가 `cancelled`로 끝나고 Agent Log 줄이 남는다
- [ ] 잘못된 모듈 경로, `soc.` 밖 모듈, 단계 불일치는 시작할 때 거부한다
- [ ] 손으로 확인(사람, 맥): 실제 호출에서 Verdict가 계약 검증과 근거 장부 검사를 통과한다
- [ ] 실측한 턴·토큰·비용을 `docs/notes/`에 적었다
- [ ] 예산 값을 바꿨으면 설정과 문서의 [기본값]을 함께 고쳤다(연구 레포 수정은 알림 목록에)
- [ ] 워커 틀과 L1·L2 담당 알림 초안이 notes에 있다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록

## 토론으로 정한 것

- **워커는 각 담당이 만든다.** 이 이슈는 워커가 실행기에 줄 틀(Protocol, `build_worker(config)`, 지킬 약속)만 정한다. L1 워커가 없으므로 L1 종단 확인은 워커 없이 `run_agent`에 L1 작업을 직접 넣는다(이슈의 "L1 시나리오를 끝까지"를 도구 호출 → Verdict → Agent Log까지로 좁힘. Alert에 판정 결과를 쓰는 것은 L1 워커의 일).
- **취소는 실행기가 스레드 루프를 쥐고 한다.** 코어(`run_task`)에 취소 인자를 더하는 안은 모델 호출 도중에는 끊지 못해 고르지 않았다. 에이전트 구조(D-024) 메모의 "스레드마다 이벤트 루프를 따로 띄우지 않는다"를 고친다.
- **`strict_mode` 기본값을 `false`로.** #224에서 코어 담당 안건으로 남겼던 것을 이 이슈에서 정했다. 기본 LLM(D-009) 메모를 고친다.
- **등록은 `"모듈:build_worker"` 문자열**, `soc.` 아래만. 클래스 경로를 인자 없이 만드는 안은 HuntVerifier처럼 생성자 인자가 필요한 워커를 받지 못해 고르지 않았다.
- **AgentWorker `poll`은 설계 그대로 `limit: int`.** HuntVerifier의 `int | None`도 만족한다.
- **L1 샘플 6건 × 3라운드.** 실행기 기본값은 L1·L2 10초·10건, L3 0, 종료 대기 30초.

## 바뀐 점

- 2026-11-05 · 맥 실측에서 L1 모델 호출의 38~48%가 빈 응답이라, 측정 입력에 코드가 계산한 조회 구간(`window_start_ms`·`window_end_ms`)을 넣고 프롬프트가 그 값을 그대로 쓰게 함. 고친 뒤 1라운드(6 run)를 다시 잼(사람이 정함)
