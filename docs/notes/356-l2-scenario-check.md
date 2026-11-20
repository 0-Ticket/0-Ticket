---
issue: 356
date: 2026-11-20
owner: Pandyo
plan: 356-l2-scenario-check.md
supersedes: []
---

# 새 정규화 구조에서 L2 분류가 시나리오를 맞게 묶는지 확인했다 (결함 1건·케이스 2개 확인, 수정은 별도 이슈)

## 한 일

시나리오 18개를 손으로 만들어 L2 분류의 그래프 단계를 임시 DB에서 저장까지 확인했다(`tests/test_l2_scenarios_db.py`). 케이스 1b·2·5·7은 손으로 만든 원본(ELK hit)을 실제 정규화기로 변환해 만든 행을 쓴다(정규화기가 만든 role은 DB 없는 `tests/test_l2_scenarios.py`가 따로 고정한다). 에이전트 입력 모양과 폴백은 가짜 모델로 확인했다. 실제 모델 확인용 `llm` 테스트(`tests/test_l2_scenarios_llm.py`)를 만들었고 AI는 실행하지 않았다.

결과: 18개 중 12개는 기대와 일치한다. 4개(2a, 2b, 5, 7c)는 D-027대로 동작하지만 기대와 달라 결정 제안으로 남긴다. **2개(1c2, 1c4)는 같은 원인의 결함으로 확인했다(코드가 D-027과 다르게 동작).** 수정은 그래프 SQL을 건드리므로 이 이슈에서 하지 않고 별도 이슈에서 한다(이슈 번호는 PR에서 기입). 이 두 테스트는 `strict xfail`로 두었다.

## 케이스 비교 표

샘플은 `tests/fixtures/l2/scenarios/cases.json`이다. IP는 문서용 대역만 쓴다. "기대"는 사람이 시나리오마다 적은 값이고, "현재 결과(그래프)"는 2026-11-20 로컬 임시 DB 실행 결과다. "에이전트 단계"는 후보가 있어 LLM까지 가는 케이스만 해당한다.

| # | 입력 | 기대 | 현재 결과(그래프) | 에이전트 단계 | 분류 | 근거 |
|---|---|---|---|---|---|---|
| 1a | A | 한 Incident | `paths_found`, 후보 1 | LLM 호출 → 사람이 확인(칸 아래) | 일치 | D-027 |
| 1b | B | 한 Incident | `paths_found`, 후보 1 | LLM 호출 → 사람이 확인 | 일치 | D-027, D-059·D-062 (client_ip와 source.ip가 모두 src) |
| 1c1 | A | 묶임 | `paths_found` | LLM 호출(가짜) | 일치 | SQL이 앞뒤 공백을 뗀다 |
| 1c2 | A | 묶임 | **`no_path`** | 호출 안 함 | **불일치(결함) → #358에서 해결** | D-027 "정규화 값이 같을 때". 저장 값이 비정규 IPv6(`2001:0DB8:0:0:0:0:0:50`)면 현재 Ticket(`2001:db8::50`)과 안 맞았다. **#358에서 해결: 이제 `paths_found`이고 xfail 표시를 지웠다** |
| 1c3 | A | 묶임 | `paths_found` | LLM 호출(가짜) | 일치 | 지금 쪽 값은 파이썬이 정규형으로 바꾼다 |
| 1c4 | B | 묶임 | **`no_path`** | 호출 안 함 | **불일치(결함) → #358에서 해결** | 정규화기는 원본 IPv6 표기를 그대로 저장한다(#302). 1c2와 같은 원인. **#358에서 해결: 이제 `paths_found`이고 xfail 표시를 지웠다** |
| 2a | B | 묶여야 함 | `no_path` | 호출 안 함 | 불일치(규칙의 결과) | D-027·D-062: 공격자 IP가 한쪽 src, 다른 쪽 dst라 공유 src가 없다 |
| 2b | B | 묶여야 함 | `no_path` | 호출 안 함 | 불일치(규칙의 결과) | D-064: OUTBOUND는 로컬이 src, 원격이 dst |
| 3 | A | 분리 | `no_path` | 호출 안 함 | 일치 | D-027 |
| 4 | A | 연결 없음 | `no_path` | 호출 안 함 | 일치 | D-027, #329 |
| 5 | B | 분리 | `paths_found`, 후보 1 | LLM 호출 → 사람이 확인 | 불일치(규칙의 결과) | D-064·#329: 로컬 IP가 src이고 사설·공개 구분이 없다. 그래프는 후보를 만들고 에이전트가 거르는지가 관건 |
| 6a | A | 가득 찬 Incident 제외 | `no_path`, 새 Incident | 호출 안 함 | 일치 | D-027 `max_incident_tickets` |
| 6b | A | 탐색 불완전 | `incomplete/candidate_limit`, 새 Incident | 호출 안 함 | 일치 | D-027 |
| 6c | A | 저장 직전 재확인 | `incident_full`, 새 Incident | LLM 호출(가짜) | 일치 | D-027 |
| 7a | B | 묶임 | `paths_found` | LLM 호출(가짜) | 일치 | #326: host.name이 없어도 src 연결은 그대로 |
| 7b(새) | B | 분리 | `no_path` | 호출 안 함 | 일치 | #329 |
| 7b(옛) | A | 분리 | `no_path` | 호출 안 함 | 일치 | 옛 구조 행도 role이 src가 아닌 host·domain·url은 연결하지 않는다 |
| 7c | B | 묶여야 함 | `no_path` | 호출 안 함 | 불일치(규칙의 결과) | src 엔티티가 없으면 어떤 Ticket과도 연결되지 않는다. actor·target은 연결 근거가 아니다 |

### 에이전트 단계: 실제 모델 확인

사람이 로컬에서 실행한 결과다(2026-11-20). AI는 모델을 실행하지 않았다. `uv run pytest -m llm -s tests/test_l2_scenarios_llm.py`는 판단과 토큰만 출력하고 `reason`을 출력하지 않아서, `reason`을 보려고 레포 밖 일회용 스크립트로 같은 방식(`build_case` → `L2BranchWorker` → `run_agent` 결과 가로채기)을 돌렸다. 코드와 테스트는 바꾸지 않았다.

- 조건: 로컬 Postgres 17.6, 케이스당 5회(15번 호출). 모델은 `config/local.toml`의 `[llm] model = "gpt-oss-120b"`.
- 비용: 입력 약 109,700 토큰, 출력 약 10,800 토큰(15번 합계). 소요 약 72초. 케이스별 평균 입력은 아래 표에 있다.

| 케이스 | 기대 판단 | 실행 횟수 | existing | new | 토큰 | 비고 |
|---|---|---|---|---|---|---|
| 1a | existing | 5 | 4 | 1 | 평균 입력 약 9,100(두 번째 턴 1회 포함) | new 1회의 reason은 "IP 하나만으로는 증거 부족" 취지, 신뢰도 0.4 |
| 1b | existing | 5 | 5 | 0 | 평균 입력 약 6,300 | 기대와 같다 |
| 5 | new | 5 | **5** | 0 | 평균 입력 약 6,500 | **기대와 반대.** 신뢰도 0.9~0.95 |

케이스 5의 `reason`: 5회 모두 "같은 IP를 공유하고 경로로 연결됨 → 같은 공격"이다. 계정·인스턴스를 비교한 이유는 한 번도 없다. 1회는 "서로 다른 환경"이라고 언급하고도 같은 시나리오 규칙이라는 이유로 묶었다. 샘플 제목("outbound environment two")에서 나온 문장으로 보이며(추정), 실제 알럿에는 이 제목이 없다.

#### 원인 조사(읽기 전용, 가설)

- 모델은 현재 Alert의 계정 ID·인스턴스 ID를 입력으로 받는다(`entities`의 `host`/`target`). 후보 쪽은 `incident_id`·`title`·`ticket_count`·`duration_ms`·`paths`만 받고 `paths`는 노드 id뿐이라 비교할 환경 값이 입력에 없다. 후보 Alert의 값은 L2 도구 `get_alert`로 경로의 alert id를 조회해야 볼 수 있는데 프롬프트는 그렇게 하라고 하지 않는다.
- `src/soc/l2/prompts/l2_classify.md`에는 환경·계정·리전·인스턴스 지침이 없다. 같은 IP를 근거로 어떻게 판단하라는 기준도 없다. "경로에 포함되지 않은 데이터를 연결 근거로 추측하지 않는다"는 줄(L7)은 "경로 밖 정보를 쓰지 말라"로도 읽힐 수 있다.
- 위는 입력과 `reason`을 맞춰 본 가설이다. 후보 쪽에 환경 필드를 줬을 때 `new`로 가는지는 확인하지 않았다.
- 1a의 `new` 1회는 1a가 이미 한 번은 "근거 부족"으로 갈라진다는 뜻이다. 아래 선택지 A·B가 1a·1b를 깨뜨릴 수 있는지 볼 때 이 점을 고려한다.

## 결정 제안 (이 이슈에서 코드를 바꾸지 않았다)

- **제안 1: `src`끼리만 연결하는 규칙(D-027)이 침해 후 나가는 통신을 못 잇는다(2a, 2b).** 근거: 같은 공격 체인인데 공격자 IP가 첫 알럿에서 src, 둘째에서 dst다. 후보 규칙에는 "한쪽의 src가 다른 쪽의 dst와 같음"처럼 방향을 가로지르는 연결이 있다. 다만 #329가 수집기 host·dst 허브가 무관한 Ticket 23개를 한 Incident로 엮은 사례(host 1개, dst 사설 IP 6건)를 근거로 role 제한을 넣었으므로, 방향 교차 연결은 같은 허브 문제를 되살릴 수 있다. 결정은 사람이 한다.
- **제안 2: src 엔티티가 없는 Ticket(7c)은 연결 방법이 없다.** 같은 계정(actor)과 같은 계정 ID(target)를 공유하는 GuardDuty 알럿 두 건이 서로 묶이지 않는다. actor·target 연결은 D-027이 막은 범위라 규칙 변경이다.
- **제안 3: 환경이 다른 같은 로컬 IP(5).** 그래프는 후보 경로를 만들고 에이전트가 거른다. 실제 모델(`gpt-oss-120b`)은 5회 모두 `existing`을 골라 잘못 묶었다(위 "에이전트 단계"). 원인은 후보 쪽에 환경 값이 없고 프롬프트에 환경 지침이 없는 것으로 보인다(가설). **결정은 아직 나지 않았다.** 선택지와 영향은 아래와 같다. 1a·1b(같은 환경의 같은 src IP는 묶여야 함)를 깨뜨릴 위험을 같이 적는다.
  - **A. 프롬프트 지침 추가**: `l2_classify.md`만 바뀐다. 후보 입력이 그대로면 "경로의 alert id를 `get_alert`로 읽어 계정·인스턴스를 비교하라"까지 써야 하고 도구 호출 비용이 늘며 모델이 따를지는 불확실하다. 다른 코드가 부르는 대상이 아니라 원칙 7 대상은 아니라고 보지만 확정된 계획과 L2 담당 확인이 필요하다. 1a·1b 위험은 중간이다. 1a·1b에는 환경 필드가 양쪽에 없어서, "다르면 분리"를 세게 쓰면 dst IP 차이 등으로 `new`가 늘 수 있다(1a가 이미 5회 중 1회 `new`).
  - **B. 후보 요약에 환경 필드 추가(`task.data`에만)**: `decide.py`의 `_candidate_data`와 후보 Alert 엔티티를 가져오는 `graph.py`가 바뀐다. 현재 Alert 쪽에는 이미 환경 값이 있어 `alert_model_input` 변경은 필요 없어 보인다(호출처는 확인하지 않았다). 모델 입력 모양이 바뀌므로 원칙 7 대상이다(#356 계획도 이 모양을 승인 대상으로 적었다). `test_candidate_summary_has_paths_but_no_entity_roles`의 키 집합을 고쳐야 한다. `paths`에 넣으면 `details.l2_branch`, Incident 상세 API, L2 분석, 화면까지 번진다. 1a·1b 위험은 낮음~중간이다. 환경 필드가 없는 쪽이 "다름"으로 읽히지 않게 생략하거나 "없음"으로 적어야 한다.
  - **C. 그래프 단계에서 환경이 다르면 연결하지 않기**: `graph.py`의 SQL이 바뀌고 D-027("src 타입·정규화 값이 같을 때만 후보 경로")을 고치는 새 결정이 필요하다. 계정 ID는 `host`/`target`이라 호스트명과 타입으로 구분되지 않고, 같은 공격자가 두 계정을 치는 정상 묶음도 끊길 수 있다. 규칙 설계에 달려 있다. "양쪽에 target host가 있고 서로 다르면 분리"는 1a·1b에 영향이 없다(둘 다 target 없음). "target host가 같아야 연결"은 1a·1b를 깨뜨린다.
  - **D. 현재 동작 유지, 결정 제안으로만 기록**: 코드·프롬프트 변경 없음, 1a·1b 위험 없음. 케이스 5는 잘못 묶인 채로 남는다.
  - 어느 쪽이든 고친 뒤에는 1a·1b·5를 실제 모델로 다시 여러 번 돌려야 한다. 결정은 사람이 한다.

## 계획과 달라진 점

- 계획의 "예측" 중 하나가 틀렸다. 1c4에서 정규화기가 IPv6 값을 정규형으로 바꿀 줄 알았지만 원본 표기를 그대로 저장한다. 그래서 1c4도 결함(1c2와 같은 원인)으로 분류했다.
- 결함 케이스(1c2, 1c4)의 `expect`는 D-027대로일 때의 결과이고, 테스트는 `strict xfail`이다. 결함을 고치면 이 표시를 지운다(strict라 고치면 테스트가 오류로 알려 준다).
- 계획은 "테스트를 먼저 쓰고 실패를 확인"이지만, 이 이슈의 테스트는 현재 동작을 확인하는 성격이라 대부분 처음부터 통과한다. 실패한 것은 결함으로 확인된 2개다.
- 브랜치 type이 `test`가 아니라 `chore`다(기존 브랜치 `test`와 이름이 충돌).
- 케이스 수가 계획 표와 조금 다르다. 7b를 새 구조(B)와 옛 구조(A) 둘로 나눴고 1c를 네 개로 나눴다.

## 다음 사람이 알아야 할 것

- **(#358에서 해결: 그래프 SQL의 ip 비교를 `inet` 정규형 기준으로 바꾸고 `entity_value_sql`은 삭제했다. 아래는 #356 당시 기록이다.)** **결함 수정은 이 이슈에서 하지 않았다.** `graph.py`의 SQL이 ip 값을 `btrim`만 해서 비교하고 파이썬은 `ipaddress` 정규형으로 비교한다. 고치는 방법은 SQL의 ip 비교를 정규형 기준으로 바꾸는 쪽(그래프 SQL 변경)으로 정했고, 저장 값을 바꾸는 방법(#302의 "원본 값 보존"과 충돌)은 쓰지 않는다. 원칙 7에 따라 L2 담당 승인이 필요해 별도 이슈에서 한다(이슈 번호는 PR에서 기입). 그 이슈가 xfail를 지운다. 마커는 `cases.json`에서 `classification`이 `불일치(결함)`인 케이스에 `test_l2_scenarios_db.py`의 `params()`가 붙이므로, 두 케이스의 `classification`을 `일치`로 바꾸면 된다. `entities.py`의 `entity_value_sql`도 "ip 정규형은 맞추지 않는다"는 같은 한계를 가진다. 이번에는 읽기만 했고 별도 이슈에서 함께 검토한다. 실제 IPv6 알럿이 얼마나 되는지는 측정하지 않았다.
- 이 이슈는 그래프 SQL, `alert_model_input`, `[l2.branch]` 설정 키를 바꾸지 않았다.
- **케이스 2의 Suricata 샘플은 손으로 만든 것이다.** 이 결과는 정규화기 규칙 기준이다. Suricata의 role은 소스 전용 항목 없이 `common.yaml`의 ECS 항목(`source.ip` src, `destination.ip` dst)이 만들고, 실제 센서가 `source`·`destination` 방향을 이렇게 채우는지는 별도 확인이 필요하다. `suricata.yaml` 자체가 "suricata.eve.* 값은 샘플로 확인한 것이 없다"고 적고 있다.
- ModSecurity 매핑표로는 나가는 통신을 만들 수 없다(client_ip src, host_ip·hostname dst만 있다). GuardDuty는 방향에 따라 src·dst가 바뀐다.
- 케이스 6a에서 가득 찬 Incident만 후보였으면 `reason`이 `no_path`로 기록된다. 가득 찼기 때문인지 연결이 없어서인지 `l2_branch` 상세만으로는 구분되지 않는다.
- 케이스 1c1~1c4는 IPv4·IPv6 표기만 다룬다. 정규화기가 src로 만드는 타입은 ip뿐이라 host·domain 대소문자 차이는 연결에 영향이 없다.
- 케이스 5의 `198.51.100.21`은 사설 IP 상당이다. 보안 규칙상 샘플은 문서용 대역만 쓰고, #329 이후 코드는 사설·공개를 구분하지 않아 결과가 같다.
- `tests/test_l2_scenarios_llm.py`는 AI가 실행하지 못했다(키 없이 `-m llm`: 3 skipped). 사람이 같은 방식의 일회용 스크립트로 돌렸다. 이 테스트는 판단과 토큰만 출력하고 `reason`을 출력하지 않는다. `reason`을 보려면 스크립트나 Agent Log(`agent_logs`)를 읽어야 한다.

## 정리 항목

### #269

`read_incidents_by_ids`, `read_recent_incidents`, `ticket_branch`는 `src`, `tests`, `config`, 마이그레이션에서 찾지 못했다(`tests/normalize/test_alert_skeleton_db.py`의 테스트 이름 `..._through_the_ticket_branch`는 다른 뜻이다). #269가 가리키는 코드는 없어졌다. **닫을지 결정: 미결정, 사람이 정한다**(댓글 초안은 만들지 않는다).

### 문서·주석 차이

- D-063·#334 계획의 "임베딩(`similar/index.py`, `l2/branch/embed.py`)은 옛 `title`·엔티티 기준일 수 있다": `l2/branch/embed.py`의 `embedding_text`는 `src` 안에서 부르는 곳이 없고 `tests/test_l2_branch.py`만 쓴다. L2 분류가 이 임베딩을 쓰지 않는다는 D-027과 맞다. `similar/index.py`는 이번에 읽지 않았다.
- #329 이슈 본문과 확정 계획: 본문은 `src` 공개 IP 허용 여부를 (A)/(B)로 열어 두었고 확정 계획과 D-027은 (A)로 정했다. 본문은 `graph.py:117`을 "공개 IP를 무조건 건너뛴다"고 적었지만 지금은 그 코드가 없다.

### DB가 필요한 항목: 해당 없음

아래 다섯 항목은 확인하던 테스트 서버가 삭제되어 확인하지 못한다. 쿼리는 참고용으로 남긴다. 실제 DB가 생기면 새 노트에서 확인한다.

읽기 전용 계정으로 아래 쿼리를 돌려 건수만 적는다. **컬럼 이름은 마이그레이션(0001, 0004, 0103, 0108)과 `l2/analyze/worker.py`에서 읽은 것이고 실제 DB에서 확인하지 못했다.** 쿼리가 오류를 내면 스키마를 먼저 확인한다.

```sql
SET default_transaction_read_only = on;

-- (a) held Incident 현황: 23 Ticket 덩어리가 아직 있는지
SELECT id, status, cardinality(ticket_ids) AS tickets, analysis_round,
       details->'l2_analyze' AS l2_analyze, updated_at
FROM incidents WHERE status = 'held' ORDER BY cardinality(ticket_ids) DESC;

-- (b) 쿨다운(1시간) 이상 간격을 두고 두 번 돌려 analysis_round가 늘었는지 비교
SELECT id, status, analysis_round, updated_at
FROM incidents WHERE cardinality(ticket_ids) >= 10 ORDER BY updated_at DESC;

-- (c) reprocess --all 실행 여부: 알럿의 outcome 분포
SELECT outcome, source, count(*) FROM normalize_status
WHERE result_kind = 'alert' GROUP BY 1, 2 ORDER BY 1, 2;

-- (d) 옛 행 잔존: ocsf에 class_uid가 없는 알럿 수
SELECT (ocsf->>'class_uid') IS NULL AS old_row, count(*) FROM alerts GROUP BY 1;

-- (e) 자산 인벤토리 행 수
SELECT (SELECT count(*) FROM assets) AS assets,
       (SELECT count(*) FROM asset_identifiers) AS identifiers;
```

| 항목 | 결과(건수만) | 확인한 사람·날짜 |
|---|---|---|
| (a) held Incident 수, 최대 Ticket 수 | 해당 없음(확인하던 테스트 서버가 삭제됨) | — |
| (b) 1시간 이상 간격 두 번의 analysis_round 증가 여부 | 해당 없음(확인하던 테스트 서버가 삭제됨) | — |
| (c) alert outcome 분포(NULL 포함) | 해당 없음(확인하던 테스트 서버가 삭제됨) | — |
| (d) class_uid 없는 알럿 수 | 해당 없음(확인하던 테스트 서버가 삭제됨) | — |
| (e) assets / asset_identifiers 행 수 | 해당 없음(확인하던 테스트 서버가 삭제됨) | — |

## 확인 방법

- `uv run ruff format --check .`: 461개 통과. `uv run ruff check .`: 통과.
- `uv run pytest`: 2638개 통과, 634개 제외.
- `uv run pytest -m db`(로컬 Postgres, 임시 DB를 만들고 지움): 595개 통과, xfail 2개(1c2, 1c4). 로컬 `.env`의 DB 이름이 컨테이너에 없어 DB 이름만 바꿔 접속했다.
- `uv run pytest -m qdrant`(로컬 Qdrant 컨테이너, `QDRANT_URL`을 지정): 24개 통과. 이 이슈와 무관한 Qdrant 실패는 없었다.
- `-m llm`: AI는 키 없이 3개 건너뜀만 확인했고 실제 모델은 실행하지 않았다. 실제 모델 결과는 사람이 로컬에서 돌려 위 "에이전트 단계: 실제 모델 확인"에 적었다.
- 주요 테스트: `test_scenario_matches_the_graph_rules[케이스 이름]`, `test_normalizer_makes_the_roles_the_case_assumes`, `test_agent_input_keeps_the_flat_alert_shape_with_roles`, `test_candidate_summary_has_paths_but_no_entity_roles`, `test_bad_agent_answers_fall_back_to_a_new_incident`.
