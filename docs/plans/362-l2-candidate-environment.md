---
issue: 362
date: 2026-11-20
owner: Pandyo
supersedes: []
---

# L2 분류: 후보 Incident의 계정·인스턴스를 모델 입력에 추가해, 환경이 다른 같은 IP를 구분

## 목표

L2 브랜치 판단 모델이 후보 Incident 쪽 알럿의 target host 값을 입력으로 받고, 프롬프트가 그 값을 현재 Alert와 비교하게 한다. 비교는 공유 IP가 내부(사설) 주소로 보일 때만 적용한다. 환경이 다른 같은 사설 IP(#356 케이스 5)는 `new`로, 같은 환경이거나 환경 값이 없는 같은 IP(1a·1b·5b)와 공개 IP(5c)는 `existing`으로 유지한다. 그래프 단계(SQL, D-027)는 바꾸지 않는다.

## 방법

개발 순서는 아래 번호 순서를 지킨다. 1단계는 별도 커밋이다.

1. **픽스처 먼저(별도 커밋).** `tests/fixtures/l2/scenarios/cases.json`에서 케이스 5·5b·5c를 만들거나 고친다(`llm_manual: true`).
   - 5: 공유 IP를 RFC1918 `10.x.x.x`로 바꾼다. 계정·인스턴스가 다르다(`new` 기대).
   - 5b(새): 공유 IP `10.x.x.x`, 계정·인스턴스가 같다(`existing` 기대).
   - 5c(새): 공유 src가 문서용 대역의 공개 IP(공격자)이고 양쪽 target host가 서로 다르다(`existing` 기대). GuardDuty INBOUND 템플릿을 쓸 계획이나 템플릿이 있는지는 개발 때 확인한다.
   - 이 커밋은 프롬프트·코드를 바꾸지 않는다. 사람이 이 커밋에서 변경 전 프롬프트로 5, 5b, 5c 기준선을 각 10회 로컬에서 돌린다(AI는 실행하지 않는다). 결과는 notes의 "변경 전 기준선" 칸에 사람이 채운다.
2. `graph.py`: `_match_row`가 덮어쓰기 전의 알럿 `entities`를 새 키 `alert_entities`로 따로 싣는다(`entities` 키는 그대로 두어 경로 생성이 변하지 않는다). `peer_kind == "alert"`일 때만 싣고 Hunt 출처 peer는 싣지 않는다.
3. `classify_graph`: 경로를 만든 match의 `alert_entities`에서 `type == "host"`, `role == "target"`인 값을 모은다. `normalize_entity_value`로 정규화하고 중복을 없앤 뒤 정렬하고 코드 상수 `MAX_TARGET_HOSTS = 10`개까지 자른다. 결과를 `GraphCandidate.target_hosts`(기본값 `()`)에 넣는다.
4. `decide.py`: `Candidate.target_hosts`(기본값 `()`)를 추가하고 `worker.py`가 옮긴다. `_candidate_data`는 비어 있지 않을 때만 `"target_hosts"` 키를 넣는다.
5. `l2_classify.md`: 비교 지침을 추가하고 마지막 줄을 조정한다(아래 "프롬프트 문구").
6. 실제 모델 확인(사람만 실행, AI는 실행하지 않는다): `SCENARIO_LLM_RUNS=10`으로 5, 5b, 5c, 1a, 1b를 돌린다. 반복 횟수 변수는 이미 있어 코드는 바꾸지 않고 `tests/test_l2_scenarios_llm.py` docstring의 실행 예시만 고친다.

### 프롬프트 문구(초안)

- 추가: "경로의 공유 IP(ip 엔티티 값)가 내부(사설) 주소로 보이면, 후보의 `target_hosts`(경로로 연결된 알럿의 target 엔티티 host 값)와 현재 Alert `entities`에서 role이 target인 host 값을 비교한다. 이 비교는 대소문자를 구분하지 않는다. 양쪽에 값이 있는데 겹치는 값이 하나도 없으면 같은 IP만으로 기존 Incident를 선택하지 않는다. 공유 IP가 공개 주소(공격자)이면 target host가 달라도 같은 공격일 수 있으므로 환경 차이만으로 분리하지 않는다. 한쪽에 값이 없으면 환경 비교를 근거로 쓰지 않는다. dst IP 차이는 환경 비교의 근거로 쓰지 않는다."
- 조정: "경로에 포함되지 않은 데이터를 연결 근거로 추측하지 않는다." → "입력에 없는 데이터를 연결 근거로 추측하지 않는다. `target_hosts`는 입력이므로 위 비교에 쓴다."
- 사설·공개 판별은 코드가 아니라 모델이 IP 값으로 한다. 코드는 판별 결과를 입력에 넣지 않는다.
- 문구는 초안이다. 개발 중 실제 모델 결과에 맞춰 다듬을 수 있고, 뜻이 달라지면 "바뀐 점"에 적는다.

## 바꿀 곳

- `src/soc/l2/branch/graph.py`, `decide.py`, `worker.py`: 위 방법 2~4
- `src/soc/l2/prompts/l2_classify.md`: 지침 추가와 문구 조정
- `tests/test_l2_scenarios.py`: `test_candidate_summary_has_paths_but_no_entity_roles`의 키 집합 수정, 값이 없을 때 키가 없는 테스트 추가
- `tests/test_l2_graph.py` 또는 `tests/test_l2_branch_db.py`: `target_hosts` 수집·정규화·중복 제거·상한·Hunt 제외
- `tests/fixtures/l2/scenarios/cases.json`: 5·5b·5c
- `tests/test_l2_scenarios_llm.py`: 실행 예시(docstring)

## 다른 코드와 맞물리는 곳

- `GraphCandidate`·`Candidate`: 필드 추가. 기본값이 있어 기존 생성자 호출(`worker.py`, `tests/test_l2_scenarios.py`, `tests/test_l2_decide.py`)이 깨지지 않는다.
- 모델 입력 `task.data["candidates"][i]`: `target_hosts` 키가 생길 수 있다. 읽는 곳은 테스트뿐이다. 원칙 7 대상이 아니다.
- `prompt_version`(프롬프트 해시): 프롬프트가 바뀌면 값이 바뀐다. Agent Log `details`에 기록만 되고 비교하는 코드는 없다.
- `cases.json`의 케이스 5 입력 IP가 바뀐다. 이 파일을 읽는 DB·가짜 모델 테스트의 기대값이 깨지는지는 개발 때 확인해서 notes에 적는다.
- 없음: 그래프 SQL, D-027, `paths`, `details.l2_branch`, Incident 상세 API·UI, `alert_model_input`, `[l2.branch]` 설정 키.

## 범위 밖

- 그래프 단계에서 환경이 다르면 연결하지 않기(D-027 변경).
- 계정과 인스턴스를 타입으로 구분하기.
- Hunt 출처 peer의 환경 값(필드 생략).
- Incident의 경로 밖 알럿의 환경 값 노출.
- 사설·공개 IP 판별을 코드로 하기.
- 실제 알럿에서 이 상황이 얼마나 생기는지 측정.

## 완료 기준

- [ ] 케이스 5가 실제 모델(`llm` 테스트, 사람이 `SCENARIO_LLM_RUNS=10`으로 실행)에서 10회 중 8회 이상 `new`다
- [ ] 같은 환경의 새 케이스 5b가 10회 중 8회 이상 `existing`이다
- [ ] 공개 IP·다른 target host의 새 케이스 5c가 10회 중 8회 이상 `existing`이다
- [ ] 케이스 1a는 10회 중 7회 이상, 1b는 10회 중 9회 이상 `existing`이다
- [ ] 위 기준이 경계에 걸리면 기준을 바꾸지 않고 결과를 notes에 적어 담당이 판단한다
- [ ] 후보 쪽에 환경 값이 없을 때 `target_hosts` 키가 없고 입력 오류가 없다(가짜 모델 테스트)
- [ ] 후보 요약 테스트를 새 모양에 맞게 고치고 기존 L2 테스트가 통과한다
- [ ] L2 담당 승인(담당 본인)
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run pytest -m db` 통과
- [ ] 변경 전 기준선(5, 5b, 5c 각 10회)과 변경 후 결과, 토큰 사용량을 notes에 적었다(사람이 실행, AI는 실행하지 않는다)
- [ ] 케이스 5 입력 IP 변경이 다른 테스트(DB·가짜 모델)의 기대값에 준 영향을 notes에 적었다
- [ ] notes에 한계를 적었다: 경로 밖 알럿 환경은 안 보임, Hunt peer 제외, 프롬프트 해시 변경, 사설 판별은 모델 몫이라 문서용 대역 값을 모델이 어떻게 읽는지 불확실(5c), 케이스 5 입력 IP 변경으로 #356 기준선과 직접 비교 불가

## 토론으로 정한 것

- 계정/인스턴스를 구분하지 않고 `target` host 값 목록으로 요약한다. 엔티티에 계정 타입이 없고 값 모양 구분은 소스가 늘면 깨진다.
- 후보 환경 값은 경로로 연결된 알럿(`matches`)의 합집합이다. Incident의 다른 알럿은 안 보이며 notes에 한계로 적는다. `_match_row`가 덮어쓰는 `entities`는 건드리지 않고 `alert_entities`로 따로 싣는다.
- 값은 정규화·중복 제거·정렬 후 상한 10개(코드 상수, 설정 키 없음). 값이 없으면 필드를 생략하고 프롬프트에 "한쪽에 값이 없으면 환경 비교를 근거로 쓰지 않는다"를 넣는다.
- 겹침 해석: 양쪽에 값이 있는데 겹치는 값이 하나도 없을 때만 분리한다. 같은 계정의 다른 인스턴스는 겹침으로 본다. 프롬프트에 "대소문자 구분 안 함"을 명시한다.
- 환경 비교는 공유 IP가 사설일 때만 적용한다. 공개 IP(공격자)는 target host가 달라도 같은 공격일 수 있어 환경 차이만으로 분리하지 않는다. 판별은 모델이 IP 값으로 한다. 회귀 케이스 5c를 넣는다.
- **샘플 IP 예외(`docs/security.md` "데이터")**: 케이스 5·5b 샘플에 한해 RFC1918 `10.0.0.0/8`(손으로 만든 가짜 값)을 쓴다. 해당 규칙은 실제 내부 주소를 커밋하지 못하게 막는 것이고 가짜 `10.x`는 식별 정보가 없다. 문서용 대역으로는 사설·공개 구분이 안 되어 새 지침을 시험할 수 없다. `docs/security.md`는 고치지 않는다. 5c는 문서용 대역을 쓴다. 사람이 승인했다.
- 개발 순서: 케이스 5·5b·5c 픽스처 변경을 프롬프트·코드 변경보다 먼저 별도 커밋으로 둔다. 사람이 그 커밋에서 변경 전 프롬프트로 기준선을 돌릴 수 있게 하기 위해서다. 기준선 결과는 notes의 "변경 전 기준선" 칸에 사람이 채운다.
- 완료 기준을 케이스당 10회로 바꾼다(이슈 본문은 사람이 수정). 5 new 8/10, 5b existing 8/10, 5c existing 8/10, 1a existing 7/10, 1b existing 9/10. 경계에 걸리면 기준은 그대로 두고 notes에 기록한다. 이유: 5회는 1a의 기존 변동(4/5)만으로도 경계다.
- 원칙 7은 해당 없음으로 본다(후보 요약은 `task.data`에만 있고 읽는 곳이 테스트뿐이다). L2 담당 승인은 완료 기준에 그대로 둔다.
- Hunt 출처 peer는 이번 범위에서 제외한다.

## 바뀐 점

