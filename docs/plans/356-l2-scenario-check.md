---
issue: 356
date: 2026-11-20
owner: Pandyo
supersedes: []
---

# Incident 분류 검증: 새 정규화 구조에서 공격 시나리오가 사건 단위로 묶이는지 확인

## 목표

새 정규화 구조(최상위 OCSF 문서 + `details`, 엔티티 role 규칙)에서 L2 분류가 시나리오 케이스를 기대대로 묶거나 분리하는지 확인하고, 기대와 현재 결과를 비교한 표를 `docs/notes/`에 남긴다. 코드가 D-027과 다르게 동작하는 것(결함)만 이 이슈에서 고치고, D-027대로인데 결과가 불리한 것(규칙의 결과)은 코드를 바꾸지 않고 결정 제안으로 기록한다.

## 방법

### 검증 범위

| 단계 | 방법 | 실행 주체 |
|---|---|---|
| 그래프(`l2/branch/graph.py`)와 출력 검증(`decide.py`) | LLM 없이 로컬 DB 테스트(`db` 마커)로 확정적으로 검증 | 개발자(AI)가 구현·실행 |
| 에이전트 입력 모양과 폴백 | 가짜 모델로 `alert_model_input`·`make_task`·후보 요약을 확인(DB 불필요) | 개발자(AI)가 구현·실행 |
| 실제 모델 `existing`/`new` 판단 | `llm` 마커 테스트(키 환경변수가 없으면 skip). 케이스 1·5를 케이스당 여러 번 돌려 결과와 비용을 notes에 기록 | **사람만 실행. AI는 에이전트와 비용을 실행하지 않는다** |

후보가 없으면 워커가 LLM을 호출하지 않는다(`worker.py`: `coverage == "complete"`이고 후보가 있을 때만 호출).

### 케이스 목록

"입력"의 A는 `alerts`·`tickets` 행에 손으로 만든 엔티티를 직접 삽입(기존 DB 테스트 방식), B는 손으로 만든 raw 레코드를 `soc.normalize`로 정규화해서 만든 행이다. "예측"은 코드를 읽고 한 추측이며 실행 결과로 대체한다. "LLM"은 후보가 생겨 에이전트까지 가는지다.

| # | 내용 | 입력 | 기대 | 예측(추측) | LLM |
|---|---|---|---|---|---|
| 1a | 같은 소스(ModSecurity)의 알럿 여러 개가 같은 공격자 IP를 `src`로 가짐 | A | 한 Incident | 경로 있음 | 호출 |
| 1b | 서로 다른 소스(ModSecurity와 Suricata)에서 같은 공격자 IP가 둘 다 `src`로 정규화됨 | **B** | 한 Incident | 경로 있음 | 호출 |
| 1c | 같은 공격자인데 값 표기가 다름(IPv6 축약형·0 채움, 앞뒤 공백, host·domain 대소문자 등) | A | 한 Incident | IPv4와 대소문자·공백은 연결. IPv6 비정규 표기는 SQL이 ip 정규형을 맞추지 않아(`graph.py` SQL은 ip에 `btrim`만 적용) 안 묶일 수 있음 | 경로가 있을 때만 |
| 2a | 웹쉘 체인: ModSecurity(공격자 `src`, 피해 호스트 `dst`) + Suricata(침해 호스트 `src`, 공격자 `dst`) | **B** | 묶여야 함 | 공유 `src` 없음, 경로 없음. 불일치 중 규칙의 결과 | 호출 안 함 |
| 2b | 2a와 같으나 두 번째 알럿이 GuardDuty OUTBOUND | **B** | 묶여야 함 | 2a와 같음 | 호출 안 함 |
| 3 | 서로 다른 공격자와 무관한 Ticket | A | 별도 Incident | 경로 없음 | 호출 안 함 |
| 4 | `dst`·`target`·`actor`·`null` role만 공유 | A | 연결 없음 | 경로 없음 | 호출 안 함 |
| 5 | 서로 다른 환경(다른 계정 ID·인스턴스)의 같은 로컬 IP가 GuardDuty OUTBOUND에서 `src`. IP는 `198.51.100.x`를 쓰고 notes에 "사설 IP 상당"이라고 적는다 | **B** | 분리 | 그래프가 경로를 만들어 후보 생성 → 에이전트가 거르는지가 관건 | 호출 |
| 6a | Incident당 Ticket 10개 가득 참 | A | 가득 찬 Incident는 후보에서 제외, 새 Incident | 후보 없음 | 호출 안 함 |
| 6b | 후보가 `max_candidates`(5)를 넘음 | A | `incomplete/candidate_limit`, 새 Incident | 후보 0개 | 호출 안 함 |
| 6c | 모델이 고른 뒤 저장 직전에 Incident가 가득 참 | A | `incident_full`로 새 Incident | 기존 테스트가 있음 | 가짜 모델만 |
| 7 | 새 구조에서 엔티티가 줄어든 경우: 새 구조(정규화기 산출)와 직접 만든 옛 구조(`host.name` 포함, domain·url role null) 엔티티 행의 연결을 비교 | 새 구조 **B**, 옛 구조 A | 연결 근거가 있는 Ticket이 남음 | 같은 `src` IP가 있으면 연결, host만 같던 쌍은 근거가 사라짐 | 경로가 있을 때만 |

- 케이스 2·5·7과 1b는 실제 정규화기가 만든 role로 확인한다(이 이슈의 출발점이 정규화 포맷 변경이기 때문).
- 매핑표가 없어 정규화 샘플을 만들 수 없는 소스는 표에 "검증 불가"로 적는다. 알럿 매핑표가 있는 소스는 suricata·modsecurity·guardduty뿐이다.
- Ticket은 `escalated`로 직접 삽입한다(L1은 거치지 않는다).
- 케이스 2의 Suricata 샘플은 손으로 만든 것이다. 그 결과는 "정규화기 규칙 기준"이고 실제 센서가 `source`·`destination` 방향을 이렇게 채우는지는 별도 확인이 필요하다고 notes에 명시한다. Suricata의 role은 소스 전용 항목 없이 `common.yaml`의 ECS 공통 항목(`source.ip` src, `destination.ip` dst)이 만든다.

### notes 표의 분류

일치 / 불일치(결함: 코드가 D-027과 다르게 동작) / 불일치(규칙의 결과: D-027대로인데 기대와 다름) / 검증 불가. 각 행에 근거(결정 번호, 파일·줄)를 적는다. 그래프 단계 결과와 에이전트 단계 결과는 열을 나눈다.

### 정리 항목

DB가 필요한 항목은 notes에 "사람이 채울 칸"으로 두고 건수만 적는다. 계획의 쿼리는 읽기 전용이며 맨 위에 `SET default_transaction_read_only = on;`을 둔다. 컬럼 이름은 마이그레이션(0001·0004·0103·0108)과 `l2/analyze/worker.py`에서 읽은 것이고 실제 DB에서 확인하지 못했다고 notes에 적는다.

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

AI가 직접 채우는 정리 항목은 둘이다. #269가 가리키는 함수(`read_incidents_by_ids`·`read_recent_incidents`·`ticket_branch`)가 코드에서 사라졌는지(grep 결과), 그리고 문서·주석 차이 목록(D-063·#334 계획의 "임베딩은 옛 기준일 수 있다", #329 이슈 본문과 확정 계획의 차이)이다.

## 바꿀 곳

- `tests/fixtures/l2/scenarios/` (새 폴더): 케이스별 샘플과 기대값. 1b·2·5·7용 raw hit도 여기에 둔다. IP는 문서용 대역(`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`)만 쓴다.
- `tests/test_l2_scenarios_db.py` (`db` 마커): 그래프 단계 검증. B 입력은 `normalize(RawRow)`가 만든 행을 `alerts`에 넣는다.
- `tests/test_l2_scenarios.py`: 가짜 모델로 입력 모양(`alert_model_input`, `make_task`, 후보 요약)과 폴백 확인.
- `tests/test_l2_scenarios_llm.py` (`llm` 마커): 케이스 1·5를 실제 모델에 넣는 확인용. 키 환경변수가 없으면 skip한다. 키·비밀 값은 코드·로그·notes에 남기지 않는다(환경변수 이름만).
- `docs/notes/356-l2-scenario-check.md`: 비교 표와 정리 항목.
- 결함이 확인되면 그 코드와 재현 테스트. 단, 수정이 `alert_model_input`, 그래프 SQL, `[l2.branch]` 설정 키를 바꾸게 되면 멈추고 사람에게 알린 뒤 "바뀐 점"에 적고 계속한다(원칙 7).

## 다른 코드와 맞물리는 곳

없음. 결함 수정이 위 세 가지(분류 입력 모양, 그래프 SQL, `[l2.branch]` 설정 키)를 건드리면 멈추고 L1·L2·L3·UI 담당 승인을 받는다.

## 범위 밖

- D-027·D-062·D-066 등 규칙 변경의 구현(`src` 외 role 연결, 자산 기준 묶기 포함). 근거와 함께 결정 제안으로만 기록한다.
- #269를 닫는 댓글 초안. 이 이슈는 현재 상태를 notes에 적는 데까지다.
- 랩 로그와 실제 알럿 사용.
- AI가 실제 모델(에이전트)을 실행하거나 비용을 쓰는 일.

## 완료 기준

- [ ] 시나리오별 기대와 현재 결과를 비교한 표가 `docs/notes/`에 있다(일치 / 불일치(결함) / 불일치(규칙의 결과) / 검증 불가, 근거 포함)
- [ ] 케이스별 샘플과 기대값이 `tests/fixtures/l2/scenarios/`에 있고, 그래프 단계를 검증하는 `db` 테스트가 통과한다
- [ ] 케이스 1b·2·5·7(새 구조)의 알럿은 `soc.normalize`가 만든 행이다
- [ ] 케이스 1에 같은 소스 조합(1a), 서로 다른 소스 조합(1b), 값 표기 차이(1c)가 모두 있고 결과가 표에 적혔다
- [ ] 새 구조 Alert(`alert_model_input`을 거친 값)가 에이전트 입력으로 들어가는 모양과 폴백을 가짜 모델로 확인하는 테스트가 있다
- [ ] 결함으로 확인된 것은 고쳐졌고 각각 재현 테스트가 있다
- [ ] 규칙 변경이 필요한 것은 근거(케이스, 결과)와 함께 결정 제안으로 정리됐고 이 이슈에서 코드를 바꾸지 않았다
- [ ] 정리 항목(#269, `held` 반복, 문서 차이, `reprocess --all`, 자산 행 수)의 현재 상태가 notes에 있다. DB 항목은 사람이 채울 칸으로 두고, 컬럼 이름을 실제 DB에서 확인하지 못했다고 적었다
- [ ] 케이스 2의 결과가 "정규화기 규칙 기준"이고 실제 센서 방향 확인은 별도라고 notes에 명시했다
- [ ] 손으로 확인(사람): 케이스 1·5에서 실제 모델의 `existing`/`new` 판단을 케이스당 여러 번 돌려 결과와 비용을 notes에 적었다
- [ ] 분류 입력 모양(`alert_model_input`), 그래프 SQL, `[l2.branch]` 설정 키를 바꾸는 경우 원칙 7에 따라 L1·L2·L3·UI 담당 승인을 받았다
- [ ] 키·비밀 값이 코드, 테스트, 로그, notes, PR에 없다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run pytest -m db`가 통과한다. 이 이슈와 무관한 Qdrant 실패는 기존 실패와 구분해 notes에 적는다
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록이 있다

## 토론으로 정한 것

- 결함과 규칙 변경의 경계: 코드가 D-027과 다르게 동작하면 결함, D-027대로인데 결과가 불리하면 규칙 변경. notes 표에 근거를 적는다.
- "묶여야 한다"의 기준: 시나리오마다 기대값과 근거를 적는다. 케이스 2의 기대는 "묶여야 함"이고 "불일치 중 규칙의 결과"로 분류한다.
- 입력 방식: 기본은 `alerts`·`tickets` 행 직접 삽입(A). 케이스 1b·2·5·7은 손으로 만든 raw를 `soc.normalize`로 정규화한다(B). 1b는 확정 뒤 추가됐다.
- 케이스 1에 서로 다른 소스(ModSecurity·Suricata)에서 같은 공격자 IP가 둘 다 `src`가 되는 조합과, 값 표기 차이로 안 묶이는 경우(1c)를 포함한다.
- 데이터: 문서용 IP 샘플만 쓰고 랩 로그는 쓰지 않는다. 케이스 5는 `198.51.100.x`를 쓰고 notes에 "사설 IP 상당"이라고 적는다.
- 케이스 7은 직접 만든 옛 엔티티 행을 비교군으로 쓴다.
- 실제 모델 확인 대상은 이슈의 "케이스 2·3"에서 "케이스 1·5"로 바꾼다. 2와 3은 후보가 없어 LLM이 호출되지 않기 때문이다. `llm` 마커 테스트로 두고 AI는 실행하지 않는다.
- 정리 항목은 현재 상태를 notes에 적는 데까지다. DB가 필요한 것은 사람이 채울 칸이고 쿼리는 `SET default_transaction_read_only = on;`으로 시작한다. #269 닫는 댓글 초안은 만들지 않는다.
- `-m db`는 필수이고 무관한 Qdrant 실패는 기존 실패와 구분해 notes에 적는다.
- 케이스 2의 Suricata 샘플은 손으로 만든 것이라 결과는 "정규화기 규칙 기준"이며, 실제 센서가 방향을 이렇게 채우는지는 별도 확인이라고 notes에 명시한다.
- `docs/decisions.md`에 올릴 새 결정은 없다(이번 토론은 이 이슈의 검증 방식에 대한 것이다).

## 바뀐 점

- 2026-11-20: 브랜치 이름의 type을 `test` 대신 `chore`로 했다. 기존 브랜치 `test`가 있어 `test/…` 이름을 만들 수 없다.
- 2026-11-20: 케이스 1c2·1c4(IPv6 표기 차이로 연결 안 됨)는 결함으로 확인했지만 이 이슈에서 고치지 않고 별도 이슈로 분리한다. 수정 방향은 그래프 SQL의 ip 비교를 정규형 기준으로 바꾸는 것(저장 방식은 바꾸지 않음). 이 이슈에서는 두 테스트를 strict xfail로 둔다. 완료 기준의 "결함으로 확인된 것은 고쳐졌고 각각 재현 테스트가 있다"는 "재현 테스트가 strict xfail로 있고 수정은 별도 이슈"로 바뀐다.
