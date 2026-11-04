---
issue: 223
date: 2026-11-04
owner: Pandyo
plan: 223-threat-hunt.md
supersedes: []
---

# L3 가설 헌팅(가설 생성 → 검증 → L3 Ticket)을 가짜 실행으로 끝까지 돌게 했다

## 한 일

- `uv run python -m soc.l3 hunt`는 수집(`collect_before`), 가설 생성 run 1회, `pending` Hunt 전부 검증을 차례로 한다. 출력은 건수와 실패 종류뿐이다. 종료 코드는 0 정상, 1 가설 생성 실패·DB 오류, 2 설정 오류다.
- 가설 생성(`soc.l3.hunt.hypothesize`)은 최근 뉴스(`COALESCE(published_at, fetched_at)` 기준)와 최근 Case를 `data`로 넘긴다. 출력 계약 `hunt_hypotheses`를 통과한 가설 가운데, 설정 버전의 ATT&CK에 있는 기법만 쓴 가설을 `pending` Hunt로 저장한다. 그 시점의 뉴스 제목·요약은 `details.sources`에 복사한다.
- 검증 워커(`soc.l3.hunt.verify.HuntVerifier`, `stage`·`name`·`poll`·`handle`)는 출력 계약 `hunt_verification`으로 결과를 받는다.
  - 근거가 모자란 `confirmed`·`rejected`는 `inconclusive`로 낮추고 `details.downgraded`에 남긴다.
  - 엔티티는 인용된 Alert·Event의 엔티티와 모델 엔티티를 합친다. 모델만 낸 엔티티는 `details.model_only_entities`에 따로 남긴다.
  - `confirmed`면 같은 트랜잭션에서 L3 Ticket(`escalated`, `alert_ids = []`, `verdict = null`)을 만든다.
- 검증 run이 실패하면 `attempts`가 오르고 `details.verify_failures`에 실패가 쌓인다. `max_attempts`에 이르면 `failed`다.
- 두 실행 모두 실행 함수(기본 `run_agent`)를 주입받는다. 테스트는 가짜 `AgentResult`와 `run_task`+가짜 모델을 함께 쓴다.

## 계획과 달라진 점

- **`poll(limit)`는 `None`도 받는다(전부).** 명령이 `pending` 전부를 한 번씩 검증하기 위해서다. #215의 `poll(limit)` 모양에 더한 것이다. SQL은 `LIMIT NULL`이다.
- **ATT&CK 버전이 없어 가설 생성을 건너뛰면 종료 코드는 0이다.** 계획은 "1 가설 생성 run 실패"만 정했다. 건너뜀은 run 실패가 아니라 데이터 준비 문제라 0으로 두고, 출력에 "수집을 먼저 한다"를 적는다.
- **`max_hypotheses` 한도를 먼저 자르고, 그다음 기법을 검사한다.** 계획에 적힌 순서다. 그래서 앞쪽 가설이 없는 기법이면 저장되는 가설이 한도보다 적을 수 있다.
- **검증 성공 시 `details`에 `model_only_entities`(빈 목록 포함)와 `missing_evidence_rows`(0 포함)를 늘 넣는다.** 계획은 "남긴다"만 적었다. 칸이 늘 있으면 읽는 쪽이 "없음"과 "확인 안 함"을 헷갈리지 않는다.
- **수집 결과 줄 앞에 `수집 `을 붙였다.** 가설 생성·검증 줄과 구분하기 위해서다.
- 워커 이름은 `l3_hunt_verify`다. 명령 본체는 `soc.l3.hunt.command.run_hunt`이고, `soc/l3/__main__.py`는 인자만 읽는다.

## 다음 사람이 알아야 할 것

- **#211 전에는 `run_task` 경로로 `confirmed`가 나오지 않는다.** 도구 결과의 `alt_`·`evt_`가 근거 장부에 들어가지 않기 때문이다. 그런 ID를 인용하면 `evidence_id_error`가 나고, 이 검증 시도는 실패로 센다(`test_citing_tool_result_alert_via_run_task_is_a_failed_attempt`). #211이 머지되면 이 테스트의 기대값(실패 → `confirmed`)을 바꿔야 한다. 테스트를 지우지 말고 기대값을 고친다.
- **가짜 모델은 `agl_` ID를 미리 알 수 없다.** `tests/test_l3_hunt_db.py`의 `fixed_agl_ids`가 `soc.agent.agent_log.new_id`를 바꿔 `agl_` ID를 순서대로 고정한다(…a1 모델, …a2 도구, …a3 모델). #211이 도구 결과에 `call_id`를 붙이면 필요 없어진다.
- **#210(머지 전)과 맞물리는 곳**
  - `TaskPrompt`가 금지 문구를 거부하게 바뀐다. 4층 프롬프트 두 개에는 그 문구가 없다. 머지 전이라 `tests/test_l3_hunt.py`에 같은 문구 목록을 임시로 두었다. #210이 머지되면 `soc.agent.types.FORBIDDEN_PHRASES`를 쓰거나 이 테스트를 지운다. 지울 때는 `TaskPrompt`가 같은 검사를 하는지 먼저 확인한다.
  - `run_task`는 새 설정 키를 읽는다. 테스트는 `soc.agent.config.load_config()`로 설정을 읽으므로 키가 늘어도 깨지지 않는다.
  - `l3.md`(2층)는 검증용 문장이지만 가설 생성 run에도 붙는다. 리뷰할 때 본다.
- **운영에서는 가설 생성 run도 L3 도구를 받는다.** 도구는 `stage`로만 정해지고 작업별로 뺄 수 없다(#209). 가설 생성 run이 도구를 불러 턴을 쓸 수 있다.
- **L2가 알아야 할 것.** L3 Ticket은 `status = escalated`인데 `verdict = null`이고 `alert_ids = []`다. 근거는 `hunt_id`로 Hunt의 `evidence_ids`를 따라간다. Ticket `entities`에는 근거 레코드에 없는(모델만 낸) 엔티티가 섞일 수 있고, 그것은 Hunt `details.model_only_entities`에 따로 있다.
- **`handle`의 동시 실행.** 모델 실행은 트랜잭션 밖에서 한다. 갱신은 `status = 'pending' AND attempts = <읽은 값>` 조건이라, 먼저 끝난 실행만 반영된다. Ticket INSERT는 savepoint 안에서 해서, `tickets_hunt_id_key` 위반이면 이미 있는 Ticket을 쓴다. 다른 제약 위반은 그대로 올린다.
- **뉴스도 Case도 없어도 가설 생성 run은 LLM을 부른다.** 막는 규칙은 계획에 없어 만들지 않았다.
- **테스트 샘플의 뉴스 `id`는 고정이다.** `threat_news.id`는 `GENERATED ALWAYS`라 테스트 헬퍼가 `OVERRIDING SYSTEM VALUE`로 넣는다. 운영 코드는 `id`를 넣지 않는다.
- **출력 계약 승인.** `hunt_hypotheses`·`hunt_verification`이 `CONTRACT_NAMES`에 늘었다. L3 담당과 계약 모듈(#192) 담당의 승인이 필요하고, 다른 담당에게는 PR로 알린다(계획 완료 기준).
- 실행기 등록, 주기 실행, 실제 모델 확인은 아직이다(계획 "범위 밖").

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run python scripts/generate_contracts.py --check`: 통과
- `uv run pytest`: 492건 통과
- `DATABASE_URL=… uv run pytest -m db`: 143건 통과(임시 `postgres:17.6` 컨테이너, trust 인증)
- 테스트를 먼저 쓰고, 구현 전에 `soc.l3.hunt` 모듈이 없어 수집 단계에서 실패하는 것을 봤다
- 주요 테스트
  - `tests/test_l3_hunt.py`: 설정 기본값과 틀린 설정 거부, 결과 낮추기 규칙 8가지(`decide`), 엔티티 합치기, 프롬프트 버전 해시, 금지 문구 없음
  - `tests/test_l3_hunt_db.py`
    - 가설 생성: 뉴스 스냅샷, 기간·정렬·한도, 없는 기법, ATT&CK 없음, 실패
    - `run_task` 경로: 지시문이 든 뉴스 제목이 `data`에만 있음, Agent Log `hrn_`
    - 검증: `confirmed` → Ticket, 작업 입력, `rejected`·`inconclusive`, 결과 낮추기 3가지, 없는 근거 행, 재시도 → `failed`, 두 번 `handle`, 이미 있는 Ticket, 실행 중 다른 실행이 먼저 처리, `poll`
    - `run_task` 경로 검증: `agl_` 근거 `rejected`와 Agent Log `hnt_`, `agl_`만 인용한 `confirmed` → `inconclusive`, 도구 결과 `alt_` 인용 → 실패
    - 명령: 건수만 출력, 가설 생성 실패에도 재시도 대기 검증(종료 1), 수집 실패에도 계속, ATT&CK 없음, 설정 오류(종료 2), DB 오류(종료 1, 주소 없음)
- `contracts` 샘플: `hunt_hypotheses` 올바른 3·틀린 10, `hunt_verification` 올바른 4·틀린 9
- 손으로 확인(임시 DB, `collect_before = false`, 운영 경로 `run_agent`)
  - ATT&CK이 없을 때: 가설 생성 건너뜀, 종료 코드 0
  - 기법 1건을 넣은 뒤: 가설 생성 `provider_error`(LLM 설정 없음), 종료 코드 1
