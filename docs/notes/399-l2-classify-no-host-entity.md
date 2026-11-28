---
issue: 399
date: 2026-11-27
owner: Juhyeok0603
plan: 399-l2-classify-no-host-entity.md
supersedes: []
---

# host 엔티티가 없는 네트워크 탐지 알럿에서 L2 분류가 환경 비교를 건너뛰게 프롬프트를 고쳤다

## 한 일

- `l2_classify.md` 9행을 고쳐, 환경 비교(후보 `target_hosts` ↔ 현재 Alert의 role=target host)를 **양쪽에 값이 다 있을 때만** 하도록 전제 조건을 같은 행 안에 넣었다. 같은 행에서 "비교 불가"를 "겹침 없음"으로 읽는 것과 host 값의 부재를 `new`의 근거로 삼는 것을 금지하고, 네트워크 탐지 알럿에는 보통 host 엔티티가 없다고 적었다.
- 11행에서 전제 조건 문장을 빼고 dst IP 관련 금지만 남겼다. "target host 대신 dst IP를 쓰지 않는다"와 "dst IP 차이는 환경 비교의 근거로 쓰지 않는다"로, 환경 비교에 한정해 금지한다(dst를 공격 문맥으로 읽는 것은 막지 않는다).
- 시나리오 케이스 `5d-network-detection-shared-src`를 추가했다. 수리카타 알럿 두 건이 같은 사설 src(`10.0.0.21`)와 같은 dst(`192.0.2.10`)를 공유하고 host 엔티티가 없다. 정규화기를 실제로 돌려 엔티티가 `ip src`·`ip dst` 둘뿐임을 확인한다.
- `tests/test_l2_scenarios_db.py`의 `test_candidate_input_carries_the_path_alerts_target_hosts`에 이 케이스를 넣어, 후보 payload에 `target_hosts` 키가 없음을 확인한다.

## 계획과 달라진 점

- **케이스 이름을 `5d-same-private-src-no-host-entity`에서 `5d-network-detection-shared-src`로 바꿨다.** `scenario_support.py:155`가 후보 Incident 제목을 `"<케이스명> <peer 라벨>"`로 만들어 **모델이 그 문자열을 본다**. 계획의 이름에는 "no-host-entity"(시험 대상 결함)와 "same-private-src"가 들어 있어, 유일한 검증 수단인 `llm` 측정을 오염시킬 수 있다. 다른 케이스 이름도 제목에 새지만(`1a-same-source-same-src-ip` 등) 결함 이름을 직접 적지는 않는다.
- **긍정 규칙을 넣지 않았다**는 계획대로다. 따라서 이 수정은 `new`를 고를 거짓 근거를 없애는 것이고 `existing`을 보증하지는 않는다. 보증은 `llm` 측정으로만 확인한다.

## 다음 사람이 알아야 할 것

- **자동 테스트는 모델의 판단을 검증하지 못한다.** `pyproject.toml`의 `addopts`가 기본 실행에서 `db`·`llm` 마커를 빼고, `tests/test_l2_scenarios_db.py`의 가짜 모델은 모든 케이스에 `"decision": "new"`를 반환한다. 그래서 `cases.json`의 `expect.result`는 **가짜 모델의 출력**이고 바라는 결과가 아니다. 바라는 결과는 `llm_expected`에 있고 사람이 `-m llm`으로 재야 한다.
- 그래서 이 이슈에는 "먼저 실패하는 테스트"가 없다. 픽스처 테스트는 입력·경로·payload를 고정하는 성격의 테스트이고 처음부터 통과한다. 바뀌는 것이 프롬프트 문장이라 프롬프트 문구를 대조하는 테스트는 동어반복이어서 쓰지 않았다.
- **같은 공격이 한 Incident로 다 묶이지는 않는다.** `max_incident_tickets = 10`(D-027)이 `candidates.py`·`graph.py`·`store.py` 세 곳에서 걸리므로, 운영에서 본 14건은 아무리 잘 분류돼도 최소 2개 Incident가 된다. 상한 제거와 L2 분석 입력 상한은 별도 이슈다(계획 "범위 밖").
- **픽스처의 사설 IP는 예외다.** `10.0.0.21`은 손으로 만든 가짜 값이고 `docs/security.md` "데이터"의 문서용 대역 규칙에 대한 예외다(5d만, 사람이 승인, 계획 "토론으로 정한 것"). 규칙이 "공유 IP가 사설일 때"만 발동하므로 문서용 대역으로는 시험 자체가 불가능하다. #362가 케이스 5·5b에 같은 예외를 받았다. dst는 문서용 대역이다.
- `prompt_version`(프롬프트 해시)이 바뀐다. Agent Log `details`에 기록만 되고 비교하는 코드는 없다.
- **긍정 규칙을 넣을 수 없는 이유**(다시 시도하려는 사람을 위해): 후보 payload의 `summary`는 분기 단계가 만든 Incident에서 빈 문자열이다(`store.py:123`이 열을 `None`으로 두고 `decide.py:103`이 `(... or "")[:500]`으로 바꾼다), `title`은 첫 알럿 제목이라(`store.py:174`) 통과 룰 이름이고 흩어진 Incident들이 전부 동일하다. 그래프 경로는 `role='src'` 엔티티만 씨앗으로 쓰므로 dst 공유는 경로에 실리지 않는다. 쓸 수 있는 근거를 늘리려면 후보 payload를 바꿔야 하고 그것은 별개 안건이다.
- **과대분류를 막는 장치가 이 환경에는 남아 있지 않다.** 바뀌기 전에는 host 값이 없으면 무조건 new였으므로 같은 사설 IP(NAT·프록시)에서 온 서로 다른 공격이 버그 덕분에 분리됐다. 이제는 4·8행의 일반 판단만 남고, 모델이 받는 구분 재료는 후보 `title`(후보 Incident 첫 알럿 제목)뿐이다. `summary`는 빈 문자열이고 경로에는 공유 src만 실린다. 이 환경의 Elastic 룰 `External Alerts`는 수리카타 알럿을 그대로 감싸 올리는 통과 룰이라 **모든 네트워크 알럿의 제목이 같다.** 따라서 같은 사설 IP에서 온 다른 공격을 구분할 재료가 0이다.
- **그 반대 방향(과대분류)을 보는 테스트가 없다.** 새 케이스 5d는 "묶여야 한다"는 양성만 본다. 같은 사설 src를 공유하지만 서로 다른 공격인 음성 케이스는 넣지 않았다(계획 완료 기준 밖, 사람이 별도 이슈로 돌리기로 정했다). 실제 모델 측정에서 5d가 `existing`으로 가도 과대분류 위험은 측정되지 않은 상태다.
- 이 브랜치의 diff를 Codex(`gpt-6-sol`, 읽기 전용)로 리뷰해 위 두 가지를 지적받았다. P1은 "실모델 결과가 비어 있어 자동 검사가 전부 통과해도 운영 모델은 여전히 흩어뜨릴 수 있다"였고, 아래 측정 표를 사람이 채우기 전까지 그대로 열려 있다.

## 확인 방법

- `uv run ruff format .`: 바뀐 파일 없음. `uv run ruff check .`: 통과
- `uv run pytest`: 2,695건 통과(838건은 `db`·`llm` 등 마커로 제외)
- `uv run pytest -m db`: 795건 통과. `.env`가 pytest 프로세스로 자동 주입되지 않아 `set -a && . ./.env && set +a` 뒤에 실행했다
- 새·바뀐 테스트: `tests/test_l2_scenarios.py::test_normalizer_makes_the_roles_the_case_assumes[5d-network-detection-shared-src-0/-1]`(수리카타 샘플에 host 엔티티가 없음), `tests/test_l2_scenarios_db.py::test_candidate_input_carries_the_path_alerts_target_hosts[5d-network-detection-shared-src-None]`(그래프 `target_hosts`가 비고 모델 후보 payload에 `target_hosts` 키가 없음)
- 실제 모델 확인은 하지 않았다(유료, 사람이 실행). 아래 표가 비어 있는 동안 모델 판정 회귀는 미확인이다

## 실제 모델 확인 (사람이 실행, AI는 실행하지 않는다)

실행: `DATABASE_URL=… QDRANT_URL=… LLM_API_KEY=… SCENARIO_LLM_RUNS=10 uv run pytest -m llm -s tests/test_l2_scenarios_llm.py`

### 변경 전 기준선

픽스처 커밋(프롬프트 변경 전)에서 사람이 돌린다.

| 케이스 | 기대 | existing | new | 입력 토큰 합 | 출력 토큰 합 |
|---|---|---|---|---|---|
| 5d | existing | | | | |

### 변경 후

| 케이스 | 기대 | 완료 기준 | existing | new | 입력 토큰 합 | 출력 토큰 합 | 판정 |
|---|---|---|---|---|---|---|---|
| 5d | existing | existing 8/10 이상 | | | | | |
| 5 | new | new 8/10 이상 | | | | | |
| 5b | existing | existing 8/10 이상 | | | | | |
| 5c | existing | existing 8/10 이상 | | | | | |
| 1a | existing | existing 7/10 이상 | | | | | |
| 1b | existing | existing 9/10 이상 | | | | | |
