---
issue: 316
date: 2026-11-13
owner: Pandyo
plan: 316-activation-pipe.md
supersedes: []
---

# 활성화 파이프: 명령 하나로 정규화·Ticket 생성·L1·L2를 띄우고, 점검이 실패하면 띄우지 않는다

## 한 일

- `uv run python -m soc.pipeline`이 준비 점검을 항목별로 출력한 뒤, 통과하면 정규화·Ticket 생성·L1·L2를 실행기 단계로 띄우고 "준비 완료, 수집 명령을 실행하세요"를 출력한 채 대기한다. 수집과 L3는 뜨지 않는다. 점검이 하나라도 FAIL이면 단계를 만들지 않고 종료 코드 4로 끝난다.
- 정규화·Ticket 생성은 기존 `soc.normalize.run.run`·`soc.l1.ticketing.run`을 그대로 부르는 배치 워커(`soc.pipeline.workers`)다. `poll`은 처리할 것이 있을 때만 고정 토큰(`batch`)을 돌려주므로 빈 반복에는 `handle`도 라운드 로그도 없다.
- 실행기(`soc.agent.executor`)에 단계 이름 `normalize`·`ticketing`을 `EXECUTOR_STAGES`로 더하고, `main()`의 시작·대기·종료를 `run_executor`로 뺐다. `STAGES`·`AgentTask`·`main()`의 동작과 종료 코드는 그대로다. `soc.db.migrate`에는 읽기만 하는 `unapplied_migrations`를 더했다.
- 간격은 `[pipeline]`(정규화·Ticket 3초, 종료 대기 30초)이고 L1·L2는 `[executor.l1|l2]`를 그대로 쓴다. 파이프는 `[executor.l3] interval_seconds`를 0으로 고정한 설정을 실행기에 넘긴다.

## 계획과 달라진 점

- 없음. 작은 선택: 점검 항목에 `agent_db`(도구가 쓰는 읽기 역할 접속)를 넣었다. 계획의 "DB 연결"에 가깝지만, 이 접속이 안 되면 도구가 첫 호출에서 `unavailable`이 되어 L1이 3번 실패하고 `held`로 가기 때문이다. 내부 도구를 허용한 단계가 없으면 SKIP이다.
- 점검 환경변수 확인은 `run_checks`가 받는 `environ`으로 하고, 실제 프로브(`Probes` 기본값)는 `os.environ`을 읽는다. 테스트가 가짜 프로브와 가짜 환경을 넣는 자리다.

## 다음 사람이 알아야 할 것

- **정규화·Ticket 배치는 종료 신호로 멈추지 못한다.** `run()` 안에서 종료 플래그를 보지 못한다. 종료 대기 시간(30초) 안에 끝나지 않으면 프로세스가 내려가고, 정규화는 임대(`lease_seconds` 기본 600초)가 풀릴 때까지 다음 기동이 그 건을 집지 못한다. 건별 저장이라 데이터는 안전하다. Ticket 생성은 후보 쿼리에 LIMIT이 없어 쌓인 건을 한 번에 처리한다.
- **임베더가 여러 번 올라갈 수 있다.** 점검의 `embedder`가 모델을 로드해 임베딩 1건을 만들고(파일이 없으면 약 2.27GB를 내려받는다) 지나간다. L2 분류 워커와 유사 사례 서비스(`install_service`)는 각자 `BgeM3Embedder`를 만든다. 인스턴스마다 첫 호출에서 세션을 올리므로 `vector` 경로에서는 메모리에 모델이 두 번 이상 있을 수 있다. 맥 실측에서 프로세스 메모리를 재서 이 기록에 적는다(아직 안 쟀다).
- **LLM 점검은 `max_tokens=16`인 고정 문자열 한 건이다.** 응답을 받으면 OK이고 내용은 보지 않는다. `max_tokens`를 받지 않는 제공자에서는 FAIL이 날 수 있는데, 그때는 코드가 아니라 제공자 설정 문제다(아직 Foundry로 확인하지 않았다).
- **`tools_config`는 네트워크에 닿지 않는다.** 허용 도구 이름이 레지스트리에 있는지, SIEM 도구를 허용한 단계가 있으면 `[tools.siem]`의 환경변수 두 개가 있고 `ca_cert_path`를 읽을 수 있는지만 본다. ELK가 실제로 열려 있는지는 보지 않는다.
- **`qdrant`·`embedder`는 L2 후보 경로가 `vector`이거나 `search_similar_cases`가 허용돼 있을 때만 본다.** 아니면 SKIP이다. 그래도 L2 분류 워커의 `build_worker`는 `[store]` 설정을 읽는다.
- 파이프와 `python -m soc.agent`를 동시에 띄우면 L1·L2가 같은 건을 두 번 모델에 보낼 수 있다. 상태 확인이 있어 데이터는 안 깨지지만 막지는 않는다.
- 정규화 failed 재시도(`run_failed`)는 이 명령에 없다. 실패한 원본은 `normalize_status`에 `failed`로 남고 이 명령이 다시 집지 않는다.
- `Ticket 생성`은 `soc.l1.ticketing._CANDIDATE_IDS`를 읽기만 하는 EXISTS 질의로 `poll`한다. 그 이름이나 조건을 바꾸면 `tests/test_pipeline_db.py`의 poll 일치 테스트가 깨진다.
- 정규화 워커는 설정을 `load_settings()`(저장소 `config/`)로 읽는다. 실행기 워커 팩토리가 설정 폴더 인자를 받지 못하기 때문이다. `main(config_dir=...)`을 쓰는 테스트는 팩토리를 주입한다.
- `docs/decisions.md`에 중복 ID(D-049, D-050)가 남아 있다. 이 이슈에서는 머지 충돌 표식만 지웠다(별도 커밋).

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`(1897건 통과), `uv run pytest -m "db or qdrant"`(541건 통과, 임시 DB는 로컬 PostgreSQL, Qdrant는 `QDRANT_URL`을 로컬 컨테이너로 두고 실행).
- 주요 테스트: `tests/test_pipeline_config.py`(설정, L3 고정, 기본 설정 불변), `test_pipeline_check.py`(항목별 FAIL·SKIP, 값 비출력, 환경변수 없음), `test_pipeline_main.py`(종료 코드 4, 네 단계만 뜸, 예외 격리, 빈 반복, 트레이싱 끔), `test_pipeline_db.py`(마이그레이션 읽기, poll 조건 일치, 수집 결과가 Incident Artifact까지 이어짐, 재기동 후 늘지 않음, 종료 시 L1 대기 상태 유지). 이어짐 테스트는 `tests/fixtures/lab_cycle/` 샘플과 `tests/test_lab_cycle_db.py`의 가짜 모델·가짜 임베더를 재사용한다.
- 기존 실행기·마이그레이션 테스트(`test_agent_executor*.py`, `test_migrate.py`)는 그대로 통과했다.
- **손으로 확인하지 못한 것(사람이 한다).** L3 수동 명령으로 만든 `escalated` Ticket이 떠 있는 L2에 들어가는지(코드로는 L2 분류 `poll`이 `status='escalated'`를 집는다), 맥 + Foundry에서 파이프를 띄우고 다른 터미널에서 수집을 실행해 L2 분석까지 이어지는지, 소요 시간·건수·비용(토큰). 숫자는 건수로만 이 기록에 적는다.
