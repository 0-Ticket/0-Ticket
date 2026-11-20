---
issue: 362
date: 2026-11-20
owner: Pandyo
plan: 362-l2-candidate-environment.md
supersedes: []
---

# L2 분류가 후보 알럿의 target host를 받아, 환경이 다른 같은 사설 IP를 구분하도록 입력과 프롬프트를 바꿨다

## 한 일

- 후보 Incident 요약(`task.data["candidates"][i]`)에 `target_hosts`를 더했다. 현재 Ticket과 `src` 엔티티를 공유해 경로를 만든 후보 알럿들의 `type=host, role=target` 값(계정 ID·인스턴스 ID)을 소문자·공백 제거로 정규화해 중복 없이 정렬하고 10개까지 담는다(`graph.py`의 `MAX_TARGET_HOSTS`). 값이 없으면 키가 없다.
- 전체 알럿 엔티티는 `_match_row`가 새 키 `alert_entities`로 따로 싣는다. 경로 계산이 쓰는 `entities`(매칭된 엔티티 하나)는 그대로다. Hunt 출처 peer는 싣지 않는다.
- `GraphCandidate`·`Candidate`에 `target_hosts`(기본값 `()`)를 추가했다. `worker.py`가 옮긴다.
- `l2_classify.md`: 공유 IP가 사설로 보이면 `target_hosts`와 현재 Alert의 target host를 대소문자 구분 없이 비교하고, 양쪽에 값이 있는데 겹치는 값이 없으면 같은 IP만으로 기존 Incident를 선택하지 않는다. 공개 IP이면 환경 차이만으로 분리하지 않고, 한쪽에 값이 없거나 dst IP만 다른 경우는 근거로 쓰지 않는다. "경로에 포함되지 않은 데이터" 줄은 "입력에 없는 데이터"로 고치고 `target_hosts`는 입력이라고 명시했다.
- 시나리오: 케이스 5의 공유 IP를 `10.0.0.21`로 바꾸고, 같은 환경의 5b와 공개 IP·다른 환경의 5c(`203.0.113.60`, GuardDuty INBOUND)를 추가했다.

## 계획과 달라진 점

없음.

## 다음 사람이 알아야 할 것

- **환경 비교 결과는 아직 모른다.** 케이스 5가 `new`가 되는지는 사람이 실제 모델로 확인해야 한다(아래 칸). 프롬프트 문구는 초안 그대로이고 모델 결과에 따라 다듬을 수 있다.
- **사설·공개 판별은 모델이 IP 값으로 한다.** 5c는 문서용 대역(`203.0.113.60`)이라 모델이 공개 주소로 읽을지 불확실하다. 5c가 기준에 못 미치면 프롬프트에 문서용 대역 처리를 쓰는 안이 있다.
- **후보 환경은 경로로 연결된 알럿의 것뿐이다.** Incident의 다른 알럿 환경은 입력에 없다(SQL 변경이 필요해 범위 밖이다). Hunt 출처 peer는 `target_hosts`에 기여하지 않는다.
- 겹침 해석: 같은 계정의 다른 인스턴스는 계정 값이 겹쳐 `existing`이 유지된다.
- `prompt_version`(프롬프트 해시)이 바뀐다. Agent Log `details`에 기록만 되고 비교하는 코드는 없다.
- 케이스 5의 입력 IP가 `198.51.100.21`에서 `10.0.0.21`로 바뀌어 #356 기록의 5회 결과와 직접 비교할 수 없다. 샘플 IP는 `docs/security.md` "데이터"의 문서용 대역 규칙에 대한 예외다(5·5b만, 사람이 승인, 계획 "토론으로 정한 것").
- 케이스 5 입력 변경이 다른 테스트의 기대값에 준 영향: 없음. `cases.json`을 읽는 `tests/test_l2_scenarios.py`, `tests/test_l2_scenarios_db.py`(5·5b·5c 포함 그래프 결과 `paths_found`, 후보 `peer`, LLM 호출됨)가 모두 통과했다. 가짜 모델 테스트는 입력 IP 값을 보지 않는다.
- 이 환경의 `.env`는 `DATABASE_URL`이 없는 DB(`zt_dev`)를 가리켰다. `db` 테스트는 같은 서버의 `zt` DB 이름으로 바꿔 실행했다(`.env`는 고치지 않았다).

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run pytest`: 2661건 통과
- `uv run pytest -m db`(DB 이름만 `zt`로 바꿔 실행): 629건 통과
- 새·바뀐 테스트: `tests/test_l2_graph.py`의 `test_target_hosts_*` 4건, `tests/test_l2_scenarios.py`의 `test_candidate_summary_adds_target_hosts_only_when_there_are_values`와 수정한 `test_candidate_summary_has_paths_but_no_entity_roles`, `tests/test_l2_scenarios_db.py`의 `test_candidate_input_carries_the_path_alerts_target_hosts`(5·5b·5c는 값이 있고 1a는 키가 없다)
- 실제 모델 확인은 실행하지 않았다(사람이 한다).

## 실제 모델 확인 (사람이 채움, AI는 실행하지 않는다)

실행: `DATABASE_URL=… LLM_API_KEY=… SCENARIO_LLM_RUNS=10 uv run pytest -m llm -s tests/test_l2_scenarios_llm.py`

### 변경 전 기준선

픽스처 변경 커밋 `f9ccd42`(프롬프트·코드 변경 전)에서 실행한다.

| 케이스 | 기대 | 10회 결과(`existing`/`new`) | 입력·출력 토큰 평균 | 메모 |
|---|---|---|---|---|
| 5 | new | | | |
| 5b | existing | | | |
| 5c | existing | | | |

### 변경 후

| 케이스 | 기대 | 완료 기준 | 10회 결과 | 입력·출력 토큰 평균 | 메모 |
|---|---|---|---|---|---|
| 5 | new | new 8/10 이상 | | | |
| 5b | existing | existing 8/10 이상 | | | |
| 5c | existing | existing 8/10 이상 | | | |
| 1a | existing | existing 7/10 이상 | | | |
| 1b | existing | existing 9/10 이상 | | | |

기준이 경계에 걸리면 기준은 바꾸지 않고 결과와 `reason`을 여기에 적어 담당이 판단한다.
