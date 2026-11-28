---
issue: 399
date: 2026-11-27
owner: Juhyeok0603
supersedes: []
---

# L2 분류: host 엔티티가 없는 네트워크 탐지 알럿에서 같은 공격이 흩어지지 않게 프롬프트를 고친다

## 목표

`l2_classify.md`의 환경 비교 규칙(9·11행)이 host 엔티티가 없는 환경에서 성립 불가 상태가 되고, 모델이 "비교 불가"를 "겹침 없음"으로 읽어 매번 `new`를 고르는 것을 막는다. 전제 조건을 9행 안에 두고 그 해석을 금지하면, 공유 src만으로 묶는 기존 동작(케이스 1a)으로 돌아간다. GuardDuty 케이스 5·5b·5c의 동작은 바꾸지 않는다. 코드와 후보 payload는 고치지 않는다.

## 방법

개발 순서를 지킨다. 1단계는 별도 커밋이다.

1. **픽스처 먼저(별도 커밋).** `tests/fixtures/l2/scenarios/cases.json`에 새 케이스 `5d-same-private-src-no-host-entity`를 넣는다.
   - 입력 B(손으로 만든 ELK hit → 정규화 실행), `template: "suricata"`.
   - peer 알럿과 현재 알럿이 `source.ip = 10.0.0.21`을 공유하고, 양쪽 `destination.ip = 192.0.2.10`이 같다.
   - `expect_entities`에 `host` 엔티티가 없다(`ip src`, `ip dst`만).
   - `expect`: `coverage: complete`, `reason: paths_found`, `candidates: ["peer"]`, `llm_called: true`, `result: "new"`(가짜 모델이 항상 `new`를 반환하므로 이 값이다).
   - `llm_manual: true`, `llm_expected: "existing"`, `classification: "불일치(결함)"`.
   - 이 커밋은 프롬프트를 바꾸지 않는다. 사람이 이 커밋에서 변경 전 프롬프트로 새 케이스 기준선 10회를 돌린다(AI는 실행하지 않는다). 결과는 notes의 "변경 전 기준선"에 사람이 채운다.
2. `tests/test_l2_scenarios.py`: 새 케이스의 정규화 결과에 `host` 엔티티가 없음을 확인한다. 기존 `test_normalizer_makes_the_roles_the_case_assumes`가 `expect_entities`를 그대로 대조하므로 케이스를 넣는 것만으로 걸린다. 걸리지 않으면 전용 단언을 더한다.
3. `tests/test_l2_scenarios_db.py`: 새 케이스에서 경로가 생기고 후보 payload에 `target_hosts` 키가 **없음**을 확인한다. `test_candidate_input_carries_the_path_alerts_target_hosts`의 파라미터에 `("5d-same-private-src-no-host-entity", None)`을 더한다.
4. `src/soc/l2/prompts/l2_classify.md`를 고친다(아래 "프롬프트 문구").
5. `tests/test_l2_scenarios_llm.py` docstring의 대상 케이스 목록에 `5d`를 더한다.
6. 실제 모델 확인(사람만 실행, AI는 실행하지 않는다): `SCENARIO_LLM_RUNS=10`으로 5d, 5, 5b, 5c, 1a, 1b를 돌린다.

### 프롬프트 문구(초안)

9행을 아래로 바꾼다.

> 경로의 공유 IP(ip 엔티티 값)가 내부(사설) 주소로 보이고 **양쪽에 target host 값이 다 있을 때만** 환경을 비교한다. 후보의 `target_hosts`(경로로 연결된 알럿의 target 엔티티 host 값)와 현재 Alert `entities`에서 role이 target인 host 값을 대소문자 구분 없이 비교해, 겹치는 값이 하나도 없으면 같은 IP만으로 기존 Incident를 선택하지 않는다. **한쪽이라도 target host 값이 없으면 이 규칙을 적용하지 않고, 비교하지 못한 것을 "대상이 겹치지 않는다"로 바꿔 읽지 않는다. host 값의 부재는 new의 근거가 아니다.** 그 경우 경로의 공유 엔티티와 Incident 문맥으로 판단한다. 네트워크 탐지 알럿은 host 엔티티가 없는 것이 정상이다.

11행은 두 문장으로 나누고, 앞 문장(한쪽에 값이 없으면 …)은 9행으로 옮겼으므로 지운다. 남기는 문장:

> target host 대신 dst IP를 쓰지 않는다. dst IP 차이는 **환경 비교의 근거로** 쓰지 않는다.

- "환경 비교의 근거로"를 남겨, dst를 공격 문맥으로 읽는 것까지 막지 않는다.
- 긍정 규칙은 넣지 않는다. 10행(공개 IP), 6행(유사도는 결론이 아니다)은 그대로 둔다.
- 문구는 초안이다. 개발 중 실제 모델 결과에 맞춰 다듬을 수 있고, 뜻이 달라지면 "바뀐 점"에 적는다.

## 바꿀 곳

- `src/soc/l2/prompts/l2_classify.md`: 9행 재작성, 11행 분리
- `tests/fixtures/l2/scenarios/cases.json`: 새 케이스 `5d-same-private-src-no-host-entity`
- `tests/test_l2_scenarios_db.py`: `target_hosts` 파라미터에 5d 추가
- `tests/test_l2_scenarios.py`: 필요하면 host 부재 단언 추가
- `tests/test_l2_scenarios_llm.py`: docstring의 대상 케이스 목록

## 다른 코드와 맞물리는 곳

- `prompt_version`(프롬프트 해시)이 바뀐다. Agent Log `details`에 기록만 되고 비교하는 코드는 없다.
- 그 밖에는 없음: 그래프 SQL, D-027, 후보 payload(`decide.py`), `details.l2_branch`, Incident 상세 API·화면, `[l2.branch]` 설정 키, 엔티티 추출 규칙.

## 범위 밖

- **Incident당 Ticket 상한(`max_incident_tickets = 10`) 제거와 L2 분석 입력 상한.** 별도 이슈로 관리한다. D-027 변경이고, `analyze/context.py`의 `investigate_data()`가 Incident의 모든 Ticket·Alert를 OCSF 전문으로 담기 때문에 분석 입력 상한을 함께 정해야 한다.
- **긍정 규칙(이슈 본문 "어떻게" 4번).** 후보 쪽에 근거로 쓸 필드가 없다("토론으로 정한 것" 참조).
- **후보 묶음 분할.** `worker.py`의 `_classify`가 이미 초기 묶음 전체를 돌며 `winners`를 모으고 winners만으로 final 라운드를 다시 묻는다. 모든 묶음이 `new`를 냈을 뿐이고 D-027도 "후보 개수만으로 새 Incident를 만들지 않는다"고 정해 뒀다.
- **엔티티 추출 규칙 변경.** 네트워크 알럿에서 대상 호스트를 뽑는 길(`url` 엔티티의 호스트 부분, 자산 조회로 IP→호스트명 역인)은 `common.yaml`과 D-062를 건드린다.
- **`decide.py`의 후보 payload 변경.** `target_hosts`는 값이 있을 때 이미 전달된다(`decide.py:112`). 코드는 의도대로 동작한다.
- **알럿 OCSF에 URL 경로가 없는 것.** 분류 모델이 `_search` 폴링과 `.env` 탐색을 구분할 재료가 없다.
- **서버 재생산.** DB를 비우고 파이프라인을 다시 돌려 전·후를 비교하는 것은 이 이슈 밖이고, 추후 사람이 직접 한다.
- L1 미결 비율, L2 조사 단계의 로그 조회 부족.

## 완료 기준

- [ ] `l2_classify.md` 9행 안에 "양쪽에 값이 있을 때만"이라는 전제 조건이 있고, "비교 불가 → 겹침 없음" 해석과 "host 값 부재가 new의 근거"를 금지하는 문장이 같은 행에 있다
- [ ] dst IP 금지는 11행에 분리해 적고, **환경 비교의 근거로만** 금지한다
- [ ] 긍정 규칙을 넣지 않았다
- [ ] 새 케이스 `5d-same-private-src-no-host-entity`가 `cases.json`에 있다(suricata 템플릿, 공유 src `10.0.0.21`, 양쪽 dst `192.0.2.10`, host 엔티티 없음, `llm_manual: true`, `llm_expected: existing`)
- [ ] 새 케이스의 정규화 결과에 `host` 엔티티가 없음을 자동 테스트가 확인한다
- [ ] 새 케이스에서 경로가 생기고(`paths_found`, 후보 `peer`) 후보 payload에 `target_hosts` 키가 없음을 자동 테스트가 확인한다
- [ ] 픽스처 커밋이 프롬프트 커밋보다 앞의 별도 커밋이다
- [ ] (사람, `llm`, `SCENARIO_LLM_RUNS=10`) 새 케이스 5d가 10회 중 8회 이상 `existing`이다
- [ ] (사람, `llm`) 회귀: 5가 8회 이상 `new`, 5b가 8회 이상 `existing`, 5c가 8회 이상 `existing`, 1a가 7회 이상 `existing`, 1b가 9회 이상 `existing`이다
- [ ] 위 기준이 경계에 걸리면 기준을 바꾸지 않고 결과를 notes에 적어 담당이 판단한다
- [ ] 변경 전 기준선(5d 10회)과 변경 후 결과, 토큰 사용량을 notes에 적었다(사람이 실행, AI는 실행하지 않는다)
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run pytest -m db` 통과
- [ ] (사람) Kibana에서 문제의 14건 안쪽 수리카타 시그니처·URL이 같은지 확인하고 결과를 notes에 적었다. 다르면 "구분 정보가 파이프라인에 전달되지 않는다"는 별개 문제이고 이 수정의 근거는 그대로 유지된다
- [ ] notes에 한계를 적었다: 기본 `pytest`와 가짜 모델 DB 테스트는 모델 판단을 검증하지 못함 / `max_incident_tickets = 10` 때문에 같은 공격 14건은 최소 2개 Incident로 나뉨 / 픽스처의 사설 IP 예외 / 서버 재생산은 이 이슈 밖 / 프롬프트 해시 변경

## 토론으로 정한 것

- **긍정 규칙(이슈 "어떻게" 4번)을 넣지 않는다.** 근거로 쓸 필드가 없다. 후보 `summary`는 분기 단계가 만든 Incident에서 항상 `None`이고(`store.py:123`), `title`은 첫 알럿 제목이라(`store.py:174`) 이 환경에선 통과 룰 이름이고 흩어진 8개가 전부 동일하다. 픽스처에서는 `title`이 `"<케이스명> peer"`라는 합성 문자열이고 `summary`는 `None`이다(`scenario_support.py:158`). 또한 그래프 경로는 `role='src'` 엔티티만 씨앗으로 쓰므로 dst 공유는 경로에 실리지 않는다.
  대신 **케이스 1a가 같은 실행 안의 대조군**이라는 근거를 쓴다. 1a는 공유 src가 공개 IP이고 host 엔티티가 없는데 같은 프롬프트에서 10/10 `existing`이다(`docs/notes/362-l2-candidate-environment.md`). 실패한 운영 케이스와의 유일한 차이는 공유 IP가 사설이라 9행이 발동했다는 점이다. 9행의 거짓 분기만 막으면 1a의 동작으로 돌아간다.
- **후보 묶음 분할은 원인이 아니므로 범위 밖.** `worker.py:178-229`를 읽어 확인했다.
- **샘플 IP 예외(`docs/security.md` "데이터")**: 새 케이스 5d에 한해 RFC1918 `10.0.0.21`(손으로 만든 가짜 값)을 쓴다. 규칙이 "공유 IP가 사설일 때"만 발동하므로 문서용 대역으로는 시험 자체가 불가능하다. 가짜 `10.x`에는 식별 정보가 없다. #362가 케이스 5·5b에 같은 예외를 받은 선례가 있다. `docs/security.md`는 고치지 않는다. dst는 문서용 대역(`192.0.2.10`)을 쓴다. 사람이 승인했다.
- **자동 테스트로는 모델 판단을 검증할 수 없음을 받아들인다.** `pyproject.toml:66`이 기본 실행에서 `db`·`llm` 마커를 빼고, `tests/test_l2_scenarios_db.py:83`의 가짜 모델은 모든 케이스에 `"decision": "new"`를 반환한다. 그래서 완료 기준을 #362와 같은 N/10 임계값으로 쓰고, 자동 테스트는 입력·경로·payload만 확인한다. 프롬프트 문장을 대조하는 테스트는 동어반복이라 쓰지 않는다.
- **완료 기준의 "하나의 Incident로 묶이는지"를 고쳤다.** `max_incident_tickets = 10`(D-027 확정, `config/default.toml:373`)이 `candidates.py:69`·`graph.py:188`·`store.py:71`에서 걸리므로 14건이 한 Incident에 들어가는 일은 일어나지 않는다. 서버 재생산 자체를 이 이슈 밖으로 옮겼다.
- **Ticket 상한 제거는 별도 이슈로 관리한다.** 처음에는 이 이슈에 넣기로 했다가, 상한이 L2 분석 입력을 묶는 유일한 장치라는 것을 확인하고(`analyze/context.py:83-105`가 Incident의 모든 Ticket·Alert를 `alert_model_input`으로 담고 `[l2.analyze]`에는 크기 상한이 없다) 분리했다. 상한을 없애면 설정 계약(`l2/config.py:12`), D-027, 시나리오 `6a`·`6c`, `test_l2_branch_db.py`의 `test_full_incident_is_excluded_before_candidate_limit`·`test_save_rechecks_incident_ticket_limit_after_model_run`, `scenario_support.fill_incident`가 함께 바뀐다.
- 외부 의견(Codex, `gpt-6-sol`)을 받았다. 프롬프트 수정이 1차 수정으로 맞고, 긍정 규칙은 근거 필드가 없어 넣지 말고, 묶음 분할은 범위 밖이고, 유료 실행 없이는 입력과 경로만 검증할 수 있고, 픽스처를 먼저 커밋하라는 것이 그 요지였다. 서버 완료 기준이 상한과 부딪힌다는 지적도 여기서 나왔다.

## 바뀐 점
