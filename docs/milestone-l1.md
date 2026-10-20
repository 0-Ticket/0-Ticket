# 중간 발표 범위 (L1 시연)

중간 발표까지 만들 범위다. 이 범위 밖의 박스는 발표 후에 한다. 박스 설명은 `docs/architecture.md`, 계약은 `docs/data-contracts.md`, 결정은 `docs/decisions.md`가 기준이다.

## 목표와 시연 흐름

**목표**: 어떤 SIEM이든 받을 수 있는 구조로 Alert·Event를 가져와 L1 판정까지 시연한다.

```
SIEM (시연에서는 direct)
  → Alert·Event (RDB, 원본)
  → OCSF 정규화 (4)
  → Lookup (5)
  → 중복 제거 · 시나리오 분기 (25)
       ├─ 공격 대상 시나리오 아님 → L1 엔티티 정보 조회 (SIEM MCP · Lookup · VDB)
       │                              → 승격 (L1 승격 티켓) 또는 보류
       └─ 공격 대상 시나리오      → 시나리오 티켓
  두 티켓 모두
  → 증거 요청 큐 (26) → 전문가 Agent + MCP
  → L1 판정: 오탐 종결 / 이상 행위 L2 승격 / 보류
  → L1 결과 조회 (27)
```

- 판단에 필요한 정보 요청(SIEM MCP, Lookup, 전문가 Agent)은 모두 큐(26)로 순차 처리한다.

## 범위

| 구분 | 박스 · 항목 |
|---|---|
| 범위 안 | 3, 4, 5, 6, 7, 8, 10, 11, 12, 14, 15, 25(부분: 중복 제거·시나리오 분기), 26, 27 |
| 범위 밖 · 보류 | 25의 엔티티 추출·공용 엔티티 제거·Incident 존재 분기 (L1 구현 중 나중에) |
| | L2 승격은 "L2 승격" 상태로 끝낸다 (L2 입구 미구현) |
| | 13 Cloud, 18 ~ 24, L3(23) |
| | Slack 알림 (트리거가 L2 승인 필요 시뿐, D-033) |
| | D-034의 L2 요청 실패 처리 |
| | 실제 SIEM 어댑터 (초기 Wazuh, 확장 ELK·Splunk): SIEM 환경이 구축되면 추가한다 |

## SIEM 구조 (SIEM에 묶이지 않기)

| 항목 | 규칙 |
|---|---|
| 입구 | SIEM이 어디에 구축되든 받을 수 있는 구조만 만든다. SIEM 환경이 구축되기 전까지 시연의 입구는 `direct`다 |
| 커넥터 (3) | "마지막으로 가져온 위치(커서) 이후의 알럿·이벤트"를 요청하는 인터페이스 하나만 안다. 결과는 항상 C2다. 접속 주소와 인증은 설정과 환경변수로만 받는다. 연결 확인(health check)도 인터페이스에 둔다 |
| SIEM MCP (15) | 도구 인터페이스는 SIEM 중립적인 공통 조회 모델(엔티티, 시간 범위, 종류 `alert`/`event`)을 받고, 어댑터가 자기 SIEM 질의로 바꾼다. 읽기 전용 도구만 제공한다 |
| SIEM별 차이 | 어댑터(가져오기, 질의 변환)와 박스 4의 별칭 표에서만 흡수한다. 코어에는 SIEM 이름 분기가 없다(K66) |
| 계약 테스트 | 어댑터가 공통으로 통과할 테스트 묶음을 인터페이스와 함께 만든다. 나중에 오는 실제 어댑터도 같은 테스트로 검증한다 |

## 박스 사이 인터페이스

| 경계 | 규칙 |
|---|---|
| 25 → 10, 11 | 25가 분기 결과를 내면 시나리오 티켓을 만들거나 L1 엔티티 조회로 넘긴다 |
| 11 ↔ 26 ↔ 14 | L1이 증거 요청을 큐(26)에 넣고 전문가 결과(C14)를 받는다 |
| 15 | MCP 도구는 에이전트별 허용 목록으로만 부른다 |
| 이슈 단위 | 박스 하나. 박스 목록과 순서는 위 "범위"와 `docs/architecture.md` "구현 순서"를 따른다 |

## 계약 변경 범위

추가 위주로 한다. 절차는 `docs/data-contracts.md` "바꾸는 절차"를 따른다.

| 구분 | 내용 |
|---|---|
| 추가 | Ticket 출처 구분(D-038)과 보류·L2 승격 상태 (C6) |
| | 분기 결과 (C21, 박스 25) |
| | 증거 요청 항목 (C22, 박스 26) |
| | L1 승격·보류 기록 (C23, 박스 27) |
| | 원본·정규화 결과 분리 (C5·C13·C2) |
| 미룸 | `handling_type`, `awaiting_human`·`awaiting_human_at`, C9, C7 `needs_human`의 삭제는 발표 후. 이슈 #37에서는 현재 계약을 보존하고 v2 흐름에서 새로 사용하지 않는다 |
| 주의 | 필수 필드를 추가하면 fixture와 화면 영향을 계획에 적는다 |
| 발표 후 | 발표 후로 미루는 계약 정리: C9 HumanReview와 awaiting_human 삭제, Incident 묶음 필드(correlation 기반) 정리, 탐지 룰 제안을 Incident 기준으로 변경, VectorDoc 기본 컬렉션 정리 |

## 시연 데이터 (#79)

시연은 AIT 데이터셋의 russellmitchell 시나리오에서 웹셸 공격 3분을 잘라 `direct`로 재생한다. 설정은 `config/demo/`(설명: `config/demo/README.md`)에 있다.

### 출처와 라이선스

| 데이터 | 쓰는 것 | 라이선스 |
|---|---|---|
| AIT Log Data Set V2.0 (Zenodo) | russellmitchell `gather/intranet_server/logs/apache2/intranet.smith.russellmitchell.com-access.log.2` (이벤트), `labels/` (공격 시각 확인) | CC BY-NC-SA 4.0 |
| AIT Alert Data Set (AIT-ADS, Zenodo) | `russellmitchell_wazuh.json` (Wazuh 알럿, JSON Lines) | CC BY 4.0 |

원본은 커밋하지 않는다. 받은 파일은 `data/ait/`(LDS는 `data/ait/russellmitchell/`, ADS는 `data/ait/ads/`)에 두고, 잘라낸 재생 파일은 `data/demo/`에 둔다. 둘 다 `.gitignore`의 `data/` 아래다. `config/demo/`의 사설 IP·호스트명·계정은 이 데이터셋의 가상 회사 값이다.

### 구간과 고른 이유

- 구간: 2022-01-24 03:56:40 ~ 03:59:50 UTC (시작 포함, 끝 제외).
- 레이블(LDS `labels/`, ADS `ait_ads_labels.csv`) 기준 공격 단계: service_scans 03:56:46, dirb 03:57:25, wpscan 03:57:48, webshell 03:58:19 ~ 03:59:22(업로드 POST 03:58:20, 웹셸 명령 03:58:23부터). 이 흐름 전체가 들어가는 가장 짧은 구간이다.
- 알럿은 Wazuh(AIT-ADS)를 쓴다. LDS의 Suricata(`inet-firewall`)는 공격자가 VPN 안쪽으로 들어와 웹 공격 단계를 보지 못한다. 이 구간의 Suricata 알럿은 Nmap User-Agent 3건과 SMTP·TLS 이상 4건뿐이다.
- 공격자는 VPN을 거쳐 들어와 인트라넷 서버의 로그에는 VPN 서버 IP `172.19.131.174`로 남는다. 외부 스캔은 `192.168.230.122`에서 온다.

| 시연 경로 | 알럿 | 근거 |
|---|---|---|
| 시나리오 티켓 | 31104 Common web attack (dirb 요청, 03:57:26) | 시나리오 규칙 `demo_web_attack`. 웹셸 단계에는 Wazuh 웹 알럿이 없어서, 업로드는 Web 전문가가 흐름 조회로 찾아야 한다 |
| L1 엔티티 조회 | 31516 Suspicious URL access, 31151, 30305, 30306, 31122, 5706, 86601 등 | 31516은 L1 승격 사례로 쓰려고 시나리오에서 뺐다 |
| 중복 제거 | 31101 Web server 400 error code 7,105건 → 대표 7건 | 같은 rule_id·같은 엔티티가 10분(`branch.dedup_window_minutes`) 안에 반복된다 |

### 잘라내기

받는 파일과 위치:

- LDS: Zenodo의 russellmitchell에서 `gather/intranet_server/logs/apache2/`와 `labels/`만 받아 `data/ait/russellmitchell/` 아래에 같은 경로로 둔다.
- ADS: Zenodo에서 `russellmitchell_wazuh.json`을 받아 `data/ait/ads/`에, 공격 단계 시각이 적힌 레이블 CSV를 `data/ait/ait_ads_labels.csv`로 둔다.

```bash
uv run python scripts/demo_slice_ait.py slice \
  --wazuh data/ait/ads/russellmitchell_wazuh.json --drop-rule 20100,20101,20151,20152 \
  --apache data/ait/russellmitchell/gather/intranet_server/logs/apache2/intranet.smith.russellmitchell.com-access.log.2 \
  --drop-status 404 \
  --window 2022-01-24T03:56:40+00:00/2022-01-24T03:59:50+00:00 --out data/demo
# data/demo/wazuh_alert.jsonl: kept 7754 / intranet...access.log.2: kept 79
uv run python scripts/demo_slice_ait.py summary --wazuh data/demo/wazuh_alert.jsonl   # rule.id별 건수·중복 수
```

자를 때 빼는 것과 영향:

- **IDS 중복 알럿(20100, 20101, 20151, 20152 "IDS event")**: Suricata `fast.log`를 Wazuh가 다시 올린 것이다. 같은 내용이 eve.json 경유 86601로 이미 있다. 또 `data.dstip`가 `IP:포트` 형식이라 IP로 쓸 수 없다.
- **Apache 404 줄 (창 안 전부)**: Web 전문가의 흐름 조회(`query_http_flow`)는 오래된 줄부터 최대 500건(`mcp.max_query_limit`)만 읽는다. 업로드 전까지 공격자의 줄이 7,660건(대부분 dirb·wpscan의 404)이라, 404를 두면 업로드와 웹셸 명령 줄이 조회 결과에 들어가지 않는다. 404를 빼면 공격자 줄은 76건이다. `specialist.flow_window_minutes`를 줄여도 창 시작이 스캔 이전이라 해결되지 않는다.
  - 영향: 31101(400 오류) 알럿 대부분에 대응하는 Apache 줄이 재생 데이터에 없다. 알럿이 가리키는 요청을 이벤트에서 찾을 수 없고, 31101 판정 근거는 알럿 자체와 SIEM 조회뿐이다.

### 실행 순서

PostgreSQL을 띄우고 레포 루트에서 실행한다. `soc.l1`은 Ollama(`granite4-micro-16k`, `bge-m3`)와 Qdrant도 필요하다. `granite4-micro-16k`는 `granite4:micro`에 문맥 길이 16,384를 준 시연 모델이다(`config/demo/Modelfile`, #89). Ollama 기본 문맥 4,096에서는 입력이 잘린다.

```bash
ollama create granite4-micro-16k -f config/demo/Modelfile
export ZT_CONFIG=config/demo/settings.toml
uv run python -m soc.db.migrate
uv run python -m soc.normalize.lookup.load assets config/demo/assets.csv
uv run python -m soc.normalize.lookup.load users config/demo/users.csv
uv run python -m soc.ingest --all
uv run python -m soc.normalize --all
uv run python -m soc.branch --all
uv run python -m soc.l1 --all
```

### 기대 결과표

`config/demo/expected.csv`는 중복 제거 뒤 남는 대표 알럿 34건의 기대 경로(C21 `path`)와 판정이다. `config/demo/expected_counts.csv`는 rule_id별 알럿·대표·중복 수다. 키 `raw_id`는 재생 파일 이름과 줄 번호라 다시 재생해도 같다. 시연 러너(#81)가 두 표와 비교한다.

판정 기대값은 참고값이다. L1 임계값·프롬프트 점검(#80)에서 실제 결과를 보고 조정한다.

| 그룹 | 알럿 | 알럿 결정 | 티켓 판정 | 이유 |
|---|---|---|---|---|
| A (9건) | 공격자 → 인트라넷 서버(`10.143.2.4`), 시나리오 티켓 포함 | `l1_escalated` (시나리오는 `-`) | `l2_escalated` | Web 전문가 흐름에 업로드·웹셸 명령이 있다 |
| B (22건) | 공격자의 다른 호스트 스캔 (5706, 31101, 31151, 30305, Nmap 86601) | `l1_escalated` | `held` | 다른 호스트의 Apache 로그는 재생하지 않아 흐름 증거가 없다 |
| C (3건) | 서버 → 공격자 SMTP 이상 응답(86601) | `held` | `-` | 공격 근거가 아닌 프로토콜 이상 |

### 실행 결과 (2026-10-19, 노트북 로컬, 새 DB)

| 단계 | 결과 | 걸린 시간 |
|---|---|---|
| ingest | 원본 7,833건 (알럿 7,754, 이벤트 79) | 6초 |
| normalize | 알럿 7,754 · 이벤트 79, 실패(C12) 0 | 33초 |
| branch | scenario_ticket 1, l1_entity_lookup 37, deduplicated 7,716 | 1,519초 |
| soc.l1 --all | 38건 처리. 전부 보류(`llm_failure`) | 2,335초 |

- **분기**: 기대 대표 34건은 모두 기대 경로와 같다. 대표 알럿의 `count` 합은 7,754로 빠진 알럿이 없다. 86601에서 대표가 4건 더 나왔다(줄 31, 40, 58, 73). 중복 비교는 방향 없는 엔티티 집합인데, 이전 알럿 후보를 새 알럿의 `src_ip`로만 찾아서 방향이 반대인 같은 두 IP 쌍(7↔31, 8↔40, 41↔58, 67↔73)을 찾지 못했다. #87에서 고쳤다(아래).
- **분기 속도**: 알럿마다 같은 출발지 후보를 최대 500건 읽고 나서 `rule_id`로 걸렀다. 공격자 알럿이 수천 건이라 뒤로 갈수록 느려졌다(초당 5건 → 1~2건). #87의 비교 기준이다.
- **Web 전문가 흐름 조회**: 시나리오 티켓의 `query_http_flow`(공격자 IP, 알럿 앞뒤 30분)가 76건을 돌려줬다. 업로드 POST(03:58:20, 200)와 웹셸 명령 32건(03:58:23 ~ 03:59:48)이 모두 들어 있다. Agent Log의 출력 발췌는 2,000자에서 잘려 같은 조회를 읽기 전용으로 다시 실행해 확인했다.
- **LLM**: `granite4:micro` 호출 대부분이 제공자 제한 시간 60초에 걸렸다(`provider_unavailable`). 끝난 2건은 입력이 약 4,300 ~ 4,500 토큰으로 모델 문맥 4,096을 넘어 `verdict` 없이 돌아왔다(`required`). 그래서 L1 판정은 모두 보류, Web 전문가 finding은 대체값(`succeeded` = `unknown`, `confidence` 0)이다. 판정 기대값과 맞는 것은 그룹 C(3건)뿐이다. 입력 크기와 모델은 #80에서 다룬다.

### 대표 알럿 표로 바꾼 뒤 (#87, 2026-10-20, 같은 노트북, 새 DB)

중복 판정이 알럿마다 후보를 읽는 대신 대표 알럿 표(`alert_dedup_representatives`, 마이그레이션 0094)를 한 번 조회한다. 키는 `rule_id`와 방향 없는 엔티티 집합의 해시다.

| 단계 | 결과 | 걸린 시간 |
|---|---|---|
| ingest | 원본 7,833건 | 7초 |
| normalize | 알럿 7,754 · 이벤트 79, 실패 0 | 38초 |
| branch | scenario_ticket 1, l1_entity_lookup 33, deduplicated 7,720 | 62초 (전 1,519초) |

- 대표 34건이 `config/demo/expected.csv`와 같고, `expected_counts.csv`의 rule_id별 건수도 모두 맞다. `count` 합은 7,754다.
- #79 실행(DB `zt_demo79`)과 알럿별로 비교하면 다른 것은 86601 줄 31·40·58·73뿐이다. 넷 다 `deduplicated`가 됐고, 그 중복은 방향이 반대인 첫 알럿(줄 7·8·41·67)의 `count`로 옮겨 갔다.
- 0094 이전에 분기한 DB는 대표 알럿 표가 비어 있어 업그레이드 직후 창(10분) 안의 알럿이 대표를 한 번 더 만들 수 있다. 보충하지 않으므로 그런 DB는 새 DB에서 처음부터 다시 돌린다.

### L1 판정 품질 기준선 (#80)

아래 기준선은 2026-10-20 리드 노트북에서 `granite4-micro-16k`로 실행한 결과다(이슈 #80 기록). 프롬프트·임계값 조정 뒤의 비교 결과는 같은 지표로 새 행에 추가한다.

| 모델·실행 | L1 형식 실패 | LLM 호출 | 전체 시간 | Alert 결과 | Ticket 결과 | Web 전문가 | expected.csv 일치 (Alert / Ticket) |
|---|---:|---:|---:|---|---|---|---|
| `granite4-micro-16k` 기준선 | 0건 | 79회 | 4,814초 | 승격 33, 보류 0 | 종결 6, L2 승격 28 | 13건 중 `unknown` 3건 (시간 초과 1, 형식 오류 1, 근거 오류 1) | 31/34 / 9/34 |

## 시연 완료 기준

- [ ] `direct`(또는 가짜 SIEM)로 데이터가 들어오고, SIEM을 바꿔도 코어 코드가 바뀌지 않는다는 것을 가짜 SIEM 교체 테스트로 보인다
- [ ] 정규화 결과가 원본과 별도 테이블에 저장된다
- [ ] 중복이 제거된다
- [ ] 시나리오 분기가 규칙대로 동작한다
- [ ] 확신도 0.8(설정 값) 기준으로 승격·보류가 나뉜다
- [ ] 시나리오 티켓이 큐를 거쳐 전문가 + MCP 조사 후 오탐 종결 또는 L2 승격으로 끝난다
- [ ] LLM 실패와 큐 실패는 보류된다
- [ ] Agent Log가 남는다
- [ ] L1 결과 조회 화면이 읽기 전용으로 승격·보류·판정을 보여 준다

체크리스트 항목은 `tests/checklist.md` "중간 발표 범위"에 모았다.
