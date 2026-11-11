---
issue: 296
date: 2026-11-11
owner: Pandyo
plan: 296-blocked-attempts-escalate.md
supersedes: []
---

# 차단된 공격 시도도 L1이 위협으로 판정하고, L2가 차단·성공을 가린다

## 한 일

- L1 프롬프트(`l1.md`)가 공격 시도의 흔적이 확인되면 차단 여부와 관계없이 `malicious`로 판정하게 했다. 방화벽·WAF가 막아 성공하지 못한 시도도 오탐이 아니라 정탐이다. 정상 활동으로 설명되는 경우만 `benign`이다.
- L1은 L2가 맡는 영향 범위(막혔는지 뚫렸는지)까지 알아내려고 추가로 조회하지 않는다. 정오탐을 가리는 조회는 그대로 한다. 판정하며 이미 본 응답 코드나 차단 기록은 근거 ID와 함께 `reason`에 사실로 적는다. 막혔는지 뚫렸는지는 L2의 일이라고 L1 프롬프트에 적었다.
- `web.md`의 "응답 코드로 성공했는지 따로 본다"를 "응답 코드만으로는 위협 여부를 가르지 않는다"로 바꿨다. 페이로드 모양은 정상 이용으로 설명되지 않을 때만 공격 시도의 흔적으로 본다. 스캔 구분 지침은 그대로다.
- L2 프롬프트가 분석 작업에서 차단·성공을 응답 코드와 이후 요청으로 확인하고(조사) 그 결과로 영향 범위를 적게(보고) 했다(`l2.md`). 조사 run은 확인한 사실을 `timeline`에 남긴다(`l2_investigate.md`). 보고서 프롬프트(`l2_report.md`)는 차단돼 성공하지 못한 것이 확인되면 `attempted`, 확인하지 못했으면 `inconclusive`(빈 `impact`, 이유는 `summary`)로 쓰게 했다. 차단됐다는 이유로 `not_threat`(Incident `dismissed`)으로 두지 않는다.
- Verdict 계약, `decide()`, 설정, 테이블은 바꾸지 않았다.

## 계획과 달라진 점

- **`l2.md` 문구.** 계획 문구는 "확인하지 못했으면 그렇다고 적는다"였다. `l2_report.md`의 기존 규칙(확인하지 못한 `impact`는 빈 문자열)과 같은 합성 지시문 안에서 부딪히지 않게 "확인하지 못했으면 조사에서는 확인하지 못했다고 쓰고, 보고에서는 verdict를 inconclusive로 두고 summary에 이유를 쓴다"로 썼다. 두 파일이 같은 표기(`inconclusive` + 빈 `impact` + `summary`)를 말한다. 이 줄은 "분석 작업의 영향 범위"로 한정해, 추가 조회가 없는 분류 작업(`l2_classify`)에 조회 지시처럼 읽히지 않게 했다.
- **`l2_report.md`에 한 문장을 더했다.** "`not_threat`은 공격 시도가 없었거나 정상 활동으로 확인될 때만 쓴다." 계획에는 "차단된 시도는 `not_threat`이 아니다"까지만 있었다. 막힌 건을 닫는 길을 막으려고 기준을 좁혔고, 룰 오작동 같은 오탐은 닫을 수 있게 "공격 시도가 없었거나"를 넣었다(리뷰 지적 뒤 사람이 정함, 계획 "바뀐 점").
- **`l2_investigate.md`를 바꿀 곳에 더했다**(계획 "바뀐 점", 2026-11-11). 보고 run(`l2_report`)은 도구를 부르지 않고 입력이 `findings`뿐이다(`make_report_task`). 조사 run이 응답 코드·차단 여부를 `timeline`에 근거 ID와 함께 남겨야 보고가 `attempted`/`succeeded`를 고를 수 있다. 확인하지 못했을 때도 그 공격 요청의 근거 ID와 함께 못 했다고 남긴다(`timeline` 항목은 근거 ID가 1개 이상 필요하다).
- **`l1.md`·`web.md`에 단서를 더했다**(리뷰 지적 뒤 사람이 정함, 계획 "바뀐 점"). `l1.md`는 흔적의 예(악성 페이로드, 악용 시도)를 들고("알려진 공격 도구나 패턴"은 `sqlmap` 같은 User-Agent만으로 페이로드 없는 스캔을 올리게 돼 확정한 4-A와 어긋나서 뺐다) "거부된 로그인 한 건처럼 흔적이 뚜렷하지 않은 것"은 흔적으로 보지 않게 했다. 도메인과 관계없는 규칙이라 단순 실패가 `malicious`로 쏠리는 것을 줄이려는 것이다. `web.md`는 페이로드 모양이 "정상 이용으로 설명되지 않으면" 흔적으로 보게 했다. 응답 코드가 걸러 주던 정상 요청(검색어에 SQL 낱말 등)의 오탐을 되살리지 않기 위해서다.
- **L2 조사·분석 문구는 HTTP에 묶지 않았다**(계획 "바뀐 점"). `l2.md`·`l2_investigate.md`는 "응답 코드나 성공·실패 기록"이라고 쓰고, 조사 줄은 "해당하는 경우"로 한정했다. L2 조사는 웹이 아닌 Incident에도 같은 프롬프트로 돈다. `l2_investigate.md`의 첫 규칙은 "확인한 사실만"을 유지하고, 차단·성공을 확인하지 못했을 때만 예외로 미확인을 `timeline`에 쓰게 했다. 미확인 사항 전부를 `timeline` 후보로 넓히면 근거 ID가 없는 항목에 억지로 ID를 붙이게 되기 때문이다. `l2_report.md`에는 `succeeded` 기준을 더했다.
- **L1이 `reason`에 적는 차단·성공 사실에는 근거 ID가 붙는다**(계획 "바뀐 점"). `l1.md`는 조회를 L2의 범위까지로 넓히지 않게 하고("L2의 범위까지 알아내려고 추가로 조회하지 않는다"), 이미 본 응답 코드·차단 기록은 그 근거 ID를 `evidence_ids`에 넣고 적게 했다. 보지 않은 것은 추측해 적지 않는다. 근거 ID가 실제로 있는지는 기존 코드 검사(`_evidence_exists`)가 본다. `web.md`는 "근거 ID와 함께"로 맞췄다.
- **샘플 파일을 따로 만들지 않았다.** 바뀐 것이 프롬프트 문구뿐이라 `tests/test_agent_prompts.py`가 합성한 지시문에 기준이 들어가는지 본다(작업 데이터는 기존 `make_task`의 손 샘플). 실제 모델이 어떻게 판정하는지는 랩 시험(사람)에서 본다.

## 다음 사람이 알아야 할 것

- **`web.md`는 지금도 L1 프롬프트에 합성되지 않는다.** 어떤 `AgentTask`도 `domains`를 넘기지 않는다. 효과는 `l1.md`가 낸다. `web.md`는 나중에 `domains`가 연결돼도 모순이 없게만 고쳤다. 연결은 별도 이슈다(Alert가 웹인지 판별할 기준이 필요하다).
- **프롬프트가 바뀌어 `prompt_version`(해시)이 바뀐다.** L1·L2 Agent Log를 이전 것과 비교할 때 달라 보이는 것은 정상이다.
- **모델이 "L2의 범위까지 알아내려고 추가로 조회하지 않는다"를 지키는지는 확인하지 못했다.** 랩 시험에서 Agent Log의 L1 도구 호출 수가 늘지 않았는지 본다. 늘었으면 `l1.md` 문구를 다시 본다.
- **L2가 `inconclusive`만 낼 수 있다.** 랩 nginx 로그가 HTTP Activity(4002)로 정규화되지 않아 `query_http_flow`·`summarize_http_flow`가 0건을 줄 수 있다(`docs/notes/264-lab-cycle.md` 발견한 문제 1). 랩 시험에서 `inconclusive`가 나오면 프롬프트 탓인지 이 문제 탓인지 도구 결과로 먼저 가른다.
- **`l2_investigate.md`는 #267(`data.related`, `max_range_days`)과 같은 파일이다.** 상류는 파일 끝 두 줄을, 이 이슈는 `L3`·`L5`를 바꿔 충돌 없이 합쳐졌다. 조회 도구는 호출마다 `max_range_days`일 이내의 구간만 받으므로, 차단·성공을 "이후 요청"으로 확인하려면 호출이 여러 번 필요할 수 있다. 랩에서 조사 run이 `max_turns`(12) 안에 끝나는지도 같이 본다.
- **막힌 시도를 모두 올리면 Ticket과 사람 검토 대기가 늘 수 있다.** 페이로드 없는 단순 스캔의 판정은 이번에 바꾸지 않았다. 랩 결과를 보고 따로 정한다.
- **개발용 시드(`tests/fixtures/l1_e2e/dev_seed.json`)의 `task_prompt`는 바꾸지 않았다.** 이 프롬프트의 "공격 흔적이 확인된다"는 새 기준과 부딪히지 않고, 2층 `l1.md`는 여기에도 합성된다.
- **아직 안 한 것(사람, 랩).** 완료 기준의 랩 시험 두 가지: 403으로 막힌 공격에서 Ticket `escalated`와 L2 `verdict`, 정상에 가까운 알럿의 `benign`. 결과는 건수로 PR에 적는다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run pytest`: 1493건 통과(`db`·`qdrant` 마커 457건은 기본 실행에서 빠진다). #298(#267)이 머지된 `origin/main` 위로 rebase한 뒤 `uv run pytest -m "db or qdrant"`도 돌렸다(로컬 PostgreSQL·Qdrant 컨테이너, `QDRANT_URL`은 셸에서 지정): 427건 + qdrant 22건 통과
- 새 테스트(`tests/test_agent_prompts.py`, 모두 네트워크 없음): `test_l1_prompt_escalates_blocked_attempts`(`domains` 없음·`("web",)`), `test_l1_prompt_leaves_impact_to_l2`, `test_web_domain_does_not_make_success_a_threat_criterion`, `test_l2_stage_prompt_checks_blocked_or_succeeded_in_analysis`, `test_l2_report_prompt_keeps_blocked_attempts_open`, `test_l2_investigate_prompt_records_block_or_success_in_timeline`, (단언은 문장 전체가 아니라 핵심어 위주다). 변경 전 프롬프트로 되돌려 보면 앞의 6건이 실패하고, 이후 보강한 `l1.md`·`web.md`·`l2.md`·`l2_investigate.md`·`l2_report.md` 단언도 보강 전에 실패하는 것을 확인했다. L1·L2 프롬프트에 "헌팅"이 없다는 단어 부재 테스트는 경계를 보호하지 못해 뺐다(경계는 계획 "범위 밖"에 있다).
- `contracts/`와 `src/soc/l1/`에는 변경이 없다(`git diff --stat`로 확인).
- 실제 모델과 랩 ELK로는 확인하지 않았다.
