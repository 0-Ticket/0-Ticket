---
issue: 264
date: 2026-11-06
owner: Pandyo
supersedes: []
---

# 랩 ELK로 파이프 한 사이클 확인 (수집 → 정규화 → L1 → L2 분석)

## 목표

팀 랩 ELK(Elasticsearch·Kibana 9.5)를 원천으로 수집 → 정규화 → Ticket → L1 판정 → L2 분류 → L2 분석(Incident Artifact, 사람 검토 대기)과 L3 Ticket → L2 분류가 막히지 않고 한 바퀴 도는지 확인한다. 판정 품질은 보지 않는다.

이 계획은 두 단계로 나눈다.

- **이 PR(개발 세션):** 랩 모양을 줄인 손 샘플, 가짜 ELK, 가짜 모델로 한 바퀴를 테스트로 확인하고, 자체 서명 HTTPS ELK에 붙을 수 있게 CA 인증서 경로 설정을 더하고, 서버에서 시험할 절차를 notes에 남긴다.
- **서버 확인(사람, 후속):** Azure 서버에 사람이 랩과 우리 스택을 구성해 실제로 한 사이클을 돌리고, 결과를 후속 기록 파일에 건수로 남긴다.

## 방법

### 시험 환경 (사실과 전제)

- 시험은 Azure 서버에서 사람이 한다. 랩 기동, 공격 시나리오 실행, 서버 구성은 사람이 한다. 개발 세션은 랩을 띄우거나 시나리오를 실행하지 않고, 랩 파일을 읽거나 레포에 넣지 않는다.
- 랩에서 확인한 사실(사람이 랩 파일을 읽어 알려 줌, 공격 스크립트는 실행하지 않음)만 근거로 쓴다.
  - Elasticsearch·Kibana 9.5(무료 Basic). 로그는 모두 Filebeat가 `filebeat-*`로 보낸다: nginx 모듈(접근 로그, ECS `http.request.method`·`url.original`·`http.response.status_code`·`source.ip`), suricata 모듈, ModSecurity 감사(사용자 정의 `transaction.*`, `source.ip` 복사), Prowler.
  - 탐지 룰 12개(Elastic Security, 1분 주기)가 `.alerts-security.alerts-default`에 알럿을 쌓는다. query 9개 + threshold 3개이고 EQL·ES|QL과 alert suppression은 없다. threshold 묶음 필드는 로그인 무차별 대입 `source.ip`(10), WAF 반복차단 `transaction.client_ip`(8), IDS 반복 고위험 `source.ip`(5)다.
  - 룰의 MITRE `threat` 필드는 비어 있고 기법은 `tags`(`attack.T1190`, `attack.T1110`)에만 있다.
  - 읽기 전용 계정 스크립트는 사용자·비밀번호(soc-reader)만 만들고 API 키는 만들지 않는다. 운영 설치는 HTTPS(자체 서명 가능), 로컬은 HTTP.
  - 랩의 responder는 알림 인덱스를 보고 공격자 IP를 iptables로 차단한다(랩 자체 기능). 서버 시험에서는 끄고 시작한다.

### 1. CA 인증서 경로 설정 (수집 #218, SIEM 도구 #212)

자체 서명 HTTPS ELK에 붙기 위해 수집과 SIEM 도구가 CA 인증서 파일 경로를 받는다. 경로는 비밀이 아니므로 설정 키이고, 새 환경변수는 만들지 않는다. 실제 값은 `config/local.toml`에 둔다.

| | 수집 `[ingest] ca_cert_path` | SIEM 도구 `[tools.siem] ca_cert_path` |
|---|---|---|
| 기본값 | `""`: 지금과 같다(httpx 기본 신뢰 저장소) | 같다 |
| 값이 있을 때 | `ssl.create_default_context(cafile=경로)`로 만든 SSLContext를 `httpx.Client(verify=...)`에 넘긴다 | 호출마다 같은 방식으로 만든다 |
| 파일이 없거나 PEM으로 읽을 수 없을 때 | 실행 시작에서 설정 오류, 종료 코드 2. 원본 저장·체크포인트·실행 이력을 쓰지 않는다 | 호출할 때 `TOOL_ERROR` `failed`, reason `config`(#212 기록처럼 값은 호출할 때 검사한다). 요청은 나가지 않는다 |
| 값이 문자열이 아닐 때 | 설정 오류, 종료 코드 2 | `failed`, reason `config` |
| http 주소 | 무시한다(httpx가 http에는 검증을 쓰지 않는다) | 같다 |

- httpx 0.28에서 `verify="경로"`(문자열)는 폐기 예정이라 쓰지 않는다.
- 오류 메시지·로그·Agent Log에 경로나 파일 내용을 넣지 않는다(기존 규칙처럼 종류 코드만).

### 2. 한 바퀴 테스트 (db 마커)

`tests/fixtures/lab_cycle/`에 랩 모양을 줄인 손 샘플을 두고, 아래 흐름을 한 테스트로 확인한다. IP는 문서용 대역, 이름은 가짜다. 랩에서 확인되지 않은 필드(예: `event.dataset` 값, threshold 알럿의 문서 모양)는 가정으로 넣고 notes에 가정이라고 적는다.

- 샘플
  - 알럿: query 룰 1건(원본 필드 복사, `source.ip` 있음, tags `attack.T1190`, 빈 `threat`), threshold 3건(로그인 무차별 대입 `source.ip`, WAF 반복차단 `transaction.client_ip`만 있고 `source.ip` 없음, IDS 반복 고위험 `source.ip`). threshold 하나는 `kibana.alert.original_time`을 빼서 `@timestamp`로 넘어가는 동작을 확인한다.
  - 이벤트: nginx 접근 로그 2~3건(`_index`는 `.ds-filebeat-9.5.0-…` 모양), ModSecurity 감사 1건(`transaction.*`, `source.ip`), 그 밖의 모듈 1건.
- 흐름
  1. 가짜 ELK(`httpx.MockTransport`)로 `soc.ingest.run.run`을 돌린다(대상: 알럿 alias, `filebeat-*`).
  2. `soc.normalize.run.run`, `soc.l1.ticketing.run`을 차례로 돌린다.
  3. L1 판정 워커(`L1JudgeWorker`)를 가짜 모델로 `run_agent`까지 태운다. 모델은 `get_alert`로 실행 중에 만들어진 Alert를 읽고 malicious 판정을 낸다(시나리오는 테스트 안에서 만든다). 도구는 테스트가 만든 읽기 계정으로 접속한다.
  4. L2 분류 워커를 가짜 임베더·가짜 벡터 저장소로, L2 분석 워커를 가짜 `run`으로 돌린다.
  5. `incident_artifacts`에 1행이 생기고 Incident가 `awaiting_review`다.
  6. 같은 순서를 한 번 더 돌려 RawRecord·Ticket이 늘지 않는다.
- 단언
  - 알럿 4건이 모두 Alert로 정규화되고, WAF 반복차단 Alert의 ip Entity가 0개다.
  - **알려진 문제를 고정한다:** `filebeat-*`의 nginx 샘플은 HTTP Activity(4002)가 아니라 Base Event(0)가 되고 4002는 0건이다. 정규화를 고치는 사람이 이 단언을 바꾼다(테스트 이름과 notes에 적는다).
  - 정규화 실패 건수는 0이다.
- L3 Ticket → L2 분류는 별도 db 테스트로 확인한다. 가짜 모델로 L3 검증이 만든 `origin = l3`, `escalated` Ticket을 L2 분류 워커가 Incident에 붙인다.

### 3. 서버 시험 절차 (notes)

`docs/notes/264-lab-cycle.md`에 값 없이 적는다.

- `config/local.toml` 예시: `[[ingest.sources]]`(알럿 alias와 `filebeat-*`, 목록 전체를 다시 적어야 함), `[[tools.siem.targets]]`(`web_access`의 index를 `filebeat-*`로, 나머지 대상도 다시 적음), `ca_cert_path`, LLM·실행기 설정(L3 꺼짐).
- 랩에서 읽기 전용 API 키를 발급하는 절차: 관리자가 `POST /_security/api_key` 또는 soc-reader로 `POST /_security/api_key/grant`. 권한은 `.alerts-security.alerts-default`와 `filebeat-*`의 `read`. `encoded` 값만 `.env`의 `ELK_API_KEY`에 넣는다.
- TLS: CA 파일 위치와 `ca_cert_path`. ES 인증서의 SAN에 `ELK_URL` 호스트가 있어야 한다는 점. 임시 방법으로 `SSL_CERT_FILE`(공개 CA와 랩 CA를 합친 번들, 프로세스 전체 영향)을 함께 적는다.
- 확인 쿼리: `event.dataset`·`_index` 모양, threshold 알럿 1건(WAF 반복차단)의 모양.
- 단계별 확인 SQL: `raw_records` kind별, 대상별 최근 `ingest_runs.outcome`, `normalize_status` 코드별, `events` `ocsf_class`별, `tickets` origin·status별, `incidents`, `incident_artifacts`, `agent_logs`의 `tokens_in`·`tokens_out` task별 합.
- 실행 순서와 간격: 수집 → 정규화(`candidates=0`이 될 때까지 반복하거나 `batch_size`를 올림) → Ticket → 실행기. 셸 루프와 cron 예. 새 명령은 만들지 않는다.
- 자산 표 시험 데이터 SQL 예시(웹서버·공격자 IP, 정규화된 값 형식).
- 발견한 문제(후속 이슈 후보)

## 바꿀 곳

- `src/soc/ingest/config.py`: `Settings.ca_cert_path` 추가, 읽기·검사
- `src/soc/ingest/elk.py`: `make_client`가 CA 경로로 SSLContext를 만들어 `verify`에 넘김
- `src/soc/ingest/__main__.py`: CA 파일을 읽지 못하면 설정 오류(종료 코드 2)
- `src/soc/tools/siem.py`: `_search`가 CA 경로로 SSLContext를 만들어 `verify`에 넘김, 실패하면 `failed`/`config`
- `config/default.toml`: `[ingest]`·`[tools.siem]`에 `ca_cert_path = ""`와 설명 주석
- `tests/ingest/unit/`, `tests/test_tools_siem.py`: CA 설정 테스트
- `tests/test_lab_cycle_db.py`(새로): 한 바퀴 테스트, L3 Ticket → L2 분류 테스트
- `tests/fixtures/lab_cycle/`(새로): 랩 모양 손 샘플
- `tests/fixtures/tls/`(새로): 테스트용 공개 CA 인증서 PEM 하나(개인 키 없음). 만든 명령은 notes에 적는다
- `docs/notes/264-lab-cycle.md`: 개발 기록과 서버 시험 절차

## 다른 코드와 맞물리는 곳

담당 확인은 PR 리뷰에서 받는다(토론 6). 아래를 사람이 확정해 원칙 7을 충족한다.

- **수집(#218):** `soc.ingest.config.Settings`에 `ca_cert_path: str` 칸이 생긴다. `Settings`를 직접 만드는 코드(테스트 도우미 `tests/ingest/fake_elk.py`의 `make_settings` 등)는 이 칸을 넘겨야 한다(기본값을 두지 않으면). `soc.ingest.elk.make_client`가 CA 경로를 쓴다. 시그니처는 바꾸지 않는다.
- **SIEM 도구(#212):** `soc.tools.siem._search`가 `[tools.siem] ca_cert_path`를 읽는다. 도구 인자, 결과 모양, `check_config`는 바꾸지 않는다.
- **공통 설정:** `config/default.toml`의 `[ingest]`·`[tools.siem]`에 새 키 `ca_cert_path`. 기본값이 빈 문자열이라 기존 동작은 같다.
- 정규화, L1, L2, L3, 실행기, 계약, DB 마이그레이션은 바꾸지 않는다.

## 범위 밖

- 정규화 변경(`event.dataset`으로 웹 접근 로그를 가리는 것). 이번에는 고치지 않고 "발견한 문제"로 남긴다(토론 1)
- 판정 품질, 모델·프롬프트 조정, L3 품질 문제
- UI 통합, 서버 배포(운영 3서버, 계정 발급, 프로세스 관리)
- 연속 실행 명령과 서비스화(서버 배포 이슈)
- 알럿↔이벤트 연결 코드(#218 후속), 자산 표를 채우는 코드
- MITRE 기법(tags)을 Alert에 옮기는 것
- 랩 자체 수정, 랩 파일을 레포에 넣는 것
- Cloud MCP(#214), 알림

## 완료 기준

### 이 PR

- [ ] `[ingest]`·`[tools.siem]`의 `ca_cert_path`가 위 표대로 동작하고, 빈 값·정상 PEM·없는 파일·PEM 아님·문자열 아님을 테스트로 확인한다
- [ ] 한 바퀴 테스트(db 마커)가 수집 → 정규화 → Ticket → L1(가짜 모델, `run_agent`) → L2 분류 → L2 분석 Artifact(`awaiting_review`)까지 확인하고, 2회차에 RawRecord·Ticket이 늘지 않는다
- [ ] 한 바퀴 테스트가 WAF 반복차단 Alert의 ip Entity 0개와 nginx 샘플의 4002 0건(알려진 문제)을 단언한다
- [ ] L3 검증이 만든 Ticket이 L2 분류에 들어가는 것을 가짜 모델 db 테스트로 확인한다
- [ ] notes에 `local.toml` 예시(알럿 소스 포함), API 키 발급 절차, TLS(CA·SAN·`SSL_CERT_FILE` 임시 방법), 확인 쿼리, 단계별 SQL(4002 건수 포함), 실행 순서·셸 루프·cron 예, 자산 표 SQL 예, 발견한 문제(4002 0건, WAF 알럿 Entity 없음, MITRE tags 미반영, SIEM 도구 `web_access` 혼재)가 있다
- [ ] 랩 계정·키·파일·내부 주소가 코드, 테스트, 로그, notes, PR에 없다
- [ ] 새 환경변수가 없다(`.env.example` 변경 없음)
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run pytest -m "db or qdrant"` 통과
- [ ] PR 본문은 `Refs #264`(이슈를 닫지 않음)이고 남은 서버 확인 항목을 옮겨 적는다

### 서버 확인(사람, 후속)

이 PR이 머지된 뒤 사람이 Azure에서 한다. 결과는 새 기록 파일 `docs/notes/264-lab-cycle-server.md`(이번 기록 `264-lab-cycle.md`를 가리킴)에 건수로 남기고, 그 기록을 넣는 후속 PR이 이슈를 닫는다.

- [ ] 랩 ELK에서 알럿과 웹 이벤트가 수집된다(건수 표, `ingest_runs` ok)
- [ ] 정규화 실패 건은 코드별 건수와 이유를 적고, `ocsf_class = 4002` 건수를 함께 적는다(0건 예상, 발견한 문제)
- [ ] 실제 `_index`·`event.dataset` 모양과 threshold 알럿 1건(WAF 반복차단)의 모양(묶음 필드 위치, `source.ip` 유무, `original_time` 유무, Entity 수)을 확인한다
- [ ] 실제 모델로 Alert → Ticket → L1 → L2 분류 → L2 분석 Artifact(사람 검토 대기)까지 한 건 이상 이어진다
- [ ] L3 검증이 만든 Ticket이 L2 분류에 들어간다
- [ ] 같은 명령을 다시 돌려도 중복 RawRecord·Ticket이 생기지 않는다
- [ ] HTTPS(자체 서명) 구성이면 `ca_cert_path`로 수집과 SIEM 도구가 붙는다
- [ ] 단계별 건수, 소요 시간, 비용(토큰)을 적는다
- [ ] 서버에서 흐름을 막는 수정이 나오면 같은 이슈 번호의 후속 계획(`docs/plans/264-lab-cycle-server.md`)을 확정한 뒤 후속 PR에 넣는다. 막지 않는 문제는 "발견한 문제"로 모은다

## 토론으로 정한 것

- **시험 환경:** 이슈의 "맥인지 별도 서버인지"는 Azure 서버로 정했다. 개발 세션은 가짜 ELK와 손 샘플로 서버에서 시험할 수 있는 상태까지 만든다.
- **1. 정규화는 고치지 않는다.** 정규화는 `_index` 이름(`logs-(nginx|apache).access-`)으로만 웹 이벤트를 가려, `filebeat-*`(데이터 스트림이면 `_index`가 `.ds-filebeat-…`)의 nginx 로그는 Base Event로 성공 처리된다. `event.dataset`으로 가리는 안이 있었지만 이번에는 고치지 않고 4002 0건을 기록하고 "발견한 문제"로 남긴다. 단계 2 통과 기준은 실패 건수로 두고 4002 건수를 같이 적는다.
- **2. TLS CA를 이 이슈에서 한다(이슈 본문 변경).** 이슈 "범위 밖"은 TLS CA를 서버 배포로 뺐지만, 수집·SIEM 도구의 `ca_cert_path` 설정은 이 이슈에서 한다. `SSL_CERT_FILE` 방식은 프로세스 전체 신뢰 저장소를 바꿔(실행기 안 L3 뉴스 수집까지) 임시 방법으로만 notes에 적는다. 이슈 본문 수정 문구는 사람이 반영한다.
- **3. 연결 값 위치:** `config/default.toml`은 바꾸지 않고, 알럿 소스를 포함한 `local.toml` 예시를 notes에 둔다.
- **4. 한 바퀴 테스트:** 수집부터 L2 분석까지 db 테스트 하나로 확인하고, L1은 가짜 모델로 `run_agent`까지 태운다. 랩 필드가 모델 도구까지 닿는 곳이 L1이기 때문이다.
- **5. 룰 종류:** query 9 + threshold 3. WAF 반복차단 threshold 알럿은 `source.ip`가 비어 Entity가 빌 수 있어 그 모양을 샘플에 넣고, 서버에서 실제 알럿 1건으로 확인한다.
- **6. 담당 확인:** PR 리뷰에서 받는다. 수집(#218)·SIEM 도구(#212)에서 고치는 부분을 이 계획에 적고 사람이 확정해 원칙 7을 충족한다.
- **7. PR과 서버 확인 순서:** 이 세션 몫으로 먼저 PR을 낸다(`Refs #264`). 서버 결과는 후속 기록 파일, 서버에서 나온 수정은 후속 PR이다. 이슈 완료 기준은 "이 PR"과 "서버 확인(사람, 후속)"으로 나눈다.
- **8. 브랜치:** 최신 `origin/main`에서 `feat/264-lab-cycle`을 만들어 로컬에만 커밋한다. push하지 않는다(`AGENTS.md` 금지 사항).
- 기본값 그대로 정한 것: 우리 코드는 API 키 인증만 유지하고 랩 쪽 발급 절차를 notes에 적는다. 이벤트는 nginx 접근 로그만 HTTP 이벤트로 정규화하는 것을 목표로 하고, 그 밖의 문서는 Base Event로 두며 실패로 세지 않는다. 연속 실행은 새 명령 없이 notes에 적는다. 자산 표는 SQL 예시만 둔다.
- MITRE `threat`가 비어 있어도 우리 코드는 `threat`·tags를 읽지 않아 흐름을 막지 않는다. 기법 정보가 Alert에 남지 않는 것은 "발견한 문제"로 둔다.
- `docs/decisions.md`에는 새 결정을 넣지 않는다. 새 도구나 방식이 아니라 이 이슈의 범위와 설정 키에 관한 것이다.

## 바뀐 점
