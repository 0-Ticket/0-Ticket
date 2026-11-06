---
issue: 264
date: 2026-11-06
owner: Pandyo
plan: 264-lab-cycle.md
supersedes: []
---

# 랩 ELK 모양으로 파이프 한 바퀴를 테스트로 확인하고, 자체 서명 HTTPS ELK에 붙을 수 있게 했다

## 한 일

- 수집(`[ingest]`)과 SIEM 도구(`[tools.siem]`)가 `ca_cert_path`(CA 인증서 PEM 경로, 비밀 아닌 설정 키)를 받는다. 빈 값이면 지금과 같고, 값이 있으면 그 CA만 믿는 SSLContext로 접속한다. 파일을 읽지 못하면 수집은 연결 전에 종료 코드 2, SIEM 도구는 요청 없이 `failed`(reason `config`)다. 새 환경변수는 없다.
- 랩에서 확인한 사실로 만든 손 샘플(`tests/fixtures/lab_cycle/`: 알럿 4건 = query 1 + threshold 3, `filebeat-*` 이벤트 5건)로 수집 → 정규화 → Ticket → L1(가짜 모델, `run_agent`, `get_alert` 도구) → L2 분류 → L2 분석 Artifact(`awaiting_review`)까지 한 테스트로 확인하고, 같은 명령을 다시 돌려도 아무것도 늘지 않는 것을 확인했다(`tests/test_lab_cycle_db.py`).
- 같은 샘플로 L3 검증이 만든 `origin = l3` Ticket이 L2 분류에 들어가는 것을 확인했다.
- 막힌 곳은 없었다. 다만 정규화가 랩의 nginx 로그를 HTTP 이벤트로 바꾸지 못하는 것(4002 0건)을 테스트로 고정하고 "발견한 문제"로 남겼다.
- 서버(Azure)에서 사람이 시험할 절차를 아래 "서버 시험 절차"에 적었다. 서버 결과는 후속 기록 `264-lab-cycle-server.md`에 남긴다.

## 계획과 달라진 점

- `Settings.ca_cert_path`는 기본값 `""`을 둔 칸으로 만들었다. 기본값이 있어 `Settings`를 직접 만드는 기존 코드는 바꾸지 않아도 된다. 테스트 도우미 `tests/ingest/fake_elk.py`의 `make_settings`에는 `ca_cert_path` 인자를 더했다.
- `[ingest] ca_cert_path` 키가 설정에 없으면 빈 값으로 본다(다른 `[ingest]` 키는 필수). 기존 `local.toml`이나 테스트가 만든 설정 표가 이 키 없이도 그대로 돈다. `[tools.siem]`도 같다.
- 수집 명령은 CA 파일을 `elk.tls_verify`로 연결 전에 한 번 읽어 보고, `make_client`도 같은 함수로 다시 읽는다. `make_client`의 시그니처를 바꾸지 않으려는 선택이다.
- 계획에 적은 L1 워커 이름은 `L1JudgeWorker`였지만 실제 클래스는 `soc.l1.judge.L1Worker`다.
- 계획의 "정규화를 `candidates=0`이 될 때까지 반복"은 정규화 출력 기준으로 `claimed=0`이다(`candidates=`는 Ticket 명령의 출력).
- 한 바퀴 테스트는 `tests/test_lab_cycle_db.py` 하나에 두 테스트(한 바퀴 + 2회차, L3 → L2)로 두었다.

## 다음 사람이 알아야 할 것

- **테스트용 CA 인증서(`tests/fixtures/tls/ca.pem`)는 공개 인증서만 있다.** 개인 키는 만든 뒤 바로 지웠다. 다시 만들 때 명령(개인 키는 임시 폴더에 두고 지운다):

  ```bash
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
    -keyout <임시 폴더>/key.pem -out tests/fixtures/tls/ca.pem -days 3650 \
    -subj "/CN=0-Ticket test CA" -addext "basicConstraints=critical,CA:TRUE"
  ```

  테스트는 TLS 연결을 하지 않고, `httpx.Client`에 넘긴 SSLContext가 이 CA를 담았는지만 본다. 실제 TLS 연결은 서버 확인 항목이다.
- **`ca_cert_path`가 상대 경로면 명령을 실행한 폴더 기준이다.** 서버에서는 절대 경로를 쓴다.
- **httpx는 transport를 직접 넘기면 `verify`를 쓰지 않는다.** SIEM 도구 테스트는 `httpx.MockTransport`를 쓰므로, `verify` 값은 `httpx.Client`를 감싼 spy로 확인한다.
- **CA를 넣어도 호스트 이름이 맞아야 한다.** ES 인증서의 SAN에 `ELK_URL`의 호스트(Azure의 IP나 이름)가 없으면 CA가 맞아도 TLS 검사에서 실패한다(수집은 `network`, SIEM 도구는 `unavailable`/`network`). 확인 방법은 아래 "TLS".
- **한 바퀴 테스트의 샘플에는 가정이 들어 있다.** 랩에서 확인한 사실은 nginx ECS 필드 4개(`http.request.method`·`url.original`·`http.response.status_code`·`source.ip`), 룰 종류(query 9 + threshold 3)와 threshold 묶음 필드, MITRE가 tags에만 있다는 것, ModSecurity 문서에 `transaction.*`과 `source.ip`가 있다는 것이다. 아래는 가정이다(서버에서 확인).
  - nginx 문서의 `event.dataset`이 `nginx.access`다(Filebeat 모듈의 표준 동작).
  - `_index`가 데이터 스트림 뒷받침 인덱스 `.ds-filebeat-9.5.0-<날짜>-000001` 모양이다(Filebeat 9 기본 출력).
  - 알럿 문서의 `_index`는 `.internal.alerts-security.alerts-default-000001`이고 `kibana.alert.*`는 점이 든 평평한 키다.
  - threshold 알럿은 묶음 필드를 문서 맨 위에 두고 `kibana.alert.threshold_result`를 가진다. 로그인 무차별 대입 샘플은 `kibana.alert.original_time`을 뺐다(이 경우 정규화는 `@timestamp`를 쓴다).
- **테스트가 고정한 "알려진 문제".** `filebeat-*`의 nginx 샘플은 Base Event(0)가 되고 4002는 0건이다. 정규화를 고치는 사람은 `test_lab_shaped_alert_flows_to_incident_artifact_and_rerun_adds_nothing`의 `{0: 5}` 단언을 바꾼다.
- **한 바퀴 테스트의 L2는 가짜다.** L2 분류는 recent 경로·가짜 임베더·메모리 벡터 저장소, L2 분석은 가짜 실행이다. L1만 가짜 모델로 `run_agent`(도구 등록, 근거 장부, Agent Log)를 거친다. 실제 bge-m3·Qdrant·모델은 서버 확인 항목이다.
- **L1 도구 테스트에는 읽기 계정이 필요하다.** 테스트가 `soc_agent_reader` 멤버 임시 LOGIN 역할을 만들고 끝나면 지운다(`tests/test_tools_db.py`와 같은 방식). 역할은 클러스터 전체에 생기므로 이름에 랜덤 꼬리를 붙인다.
- **이 환경에서는 Qdrant 테스트(`-m qdrant`)를 돌리지 못했다.** 이 이슈는 Qdrant 코드를 바꾸지 않았고, CI의 db job이 PostgreSQL·Qdrant로 돌린다.

## 발견한 문제 (후속 이슈 후보)

흐름을 막지 않아 고치지 않았다.

1. **정규화가 `filebeat-*`의 nginx 접근 로그를 HTTP Activity(4002)로 바꾸지 못한다.** 정규화(`src/soc/normalize/mapping.py`의 `_WEB_INDEX`)는 `_index`가 `logs-(nginx|apache).access-`로 시작할 때만 웹 이벤트로 본다. 랩은 모든 로그가 `filebeat-*`에 섞여 있어 nginx 로그가 Base Event(0)로 **성공** 처리되고, 실패 건수에는 나타나지 않는다. 그래서 L1·L2의 `query_http_flow`·`summarize_http_flow`(4002만 읽음)가 0건을 돌려준다. 안: `event.dataset`이 `nginx.access`·`apache.access`이면 웹 이벤트로 본다(기존 인덱스 판별은 유지). 정규화 담당(#234·#249)과 정한다.
2. **WAF 반복차단 threshold 알럿의 Entity가 비어 있다.** 묶음 필드가 `transaction.client_ip`뿐이고 정규화의 Entity 필드 목록(`source.ip`, `host.name`, `user.name`, `url.domain`, `url.original`)에 없다. L2 분류의 임베딩 문장과 L2 분석의 시작 Entity가 빈다. 서버에서 실제 알럿으로 확인한 뒤 매핑을 더할지 정한다.
3. **MITRE 기법이 Alert에 남지 않는다.** 랩 룰은 `threat`가 비어 있고 기법은 `kibana.alert.rule.tags`(`attack.T1190`)에만 있다. 정규화는 `threat`도 tags도 읽지 않는다.
4. **SIEM 도구의 `web_access`를 `filebeat-*`로 두면 다른 모듈 문서가 섞인다.** suricata·ModSecurity·Prowler 문서도 `source_ip` 필터에 걸려 나온다. 대상별 `event.dataset` 필터가 없다.
5. **`filebeat-*` 첫 수집은 전 기간의 모든 모듈 문서를 읽고, 정규화는 한 번에 200건씩 오래된 것부터 처리한다.** 새 알럿이 쌓인 이벤트 뒤로 밀려 Ticket이 늦게 생길 수 있다. 지금은 아래 실행 순서처럼 정규화를 `claimed=0`까지 반복하거나 `[normalize] batch_size`를 올려 피한다.

## 서버 시험 절차 (사람, Azure)

값(주소, 계정, 키)은 이 파일과 PR에 쓰지 않는다. `.env`와 `config/local.toml`(둘 다 커밋 안 함)에만 둔다. 결과는 건수만 `264-lab-cycle-server.md`에 적는다(`docs/security.md` "데이터").

### 0. 랩 준비

- 랩의 responder는 끈다. 켜 두면 공격자 IP가 차단돼 2회차 로그가 끊긴다.
- 시나리오는 `02_sqli`, `03_xss`, `04_lfi_rce`, `05_bruteforce` 중에서 고른다. `06_auto_block`과 `all`은 쓰지 않는다.
- 우리 쪽: `docker compose up -d`(PostgreSQL·Qdrant), `uv sync`, `uv run python -m soc.db.migrate`. L2 분류 워커는 처음 시작할 때 bge-m3(약 2.27GB)를 받는다.

### 1. 읽기 전용 API 키 발급 (랩 관리자)

우리 코드는 API 키만 쓴다. 랩의 soc-reader 계정 스크립트는 사용자·비밀번호만 만들므로, 관리자가 Kibana Dev Tools에서 키를 따로 만든다. 무료 Basic 라이선스에서도 된다. 둘 중 하나를 쓴다.

- 관리자 이름으로 만들기(권한을 키에 직접 적는다):

  ```text
  POST /_security/api_key
  {
    "name": "0-ticket-reader",
    "role_descriptors": {
      "soc_read": {
        "indices": [
          {"names": [".alerts-security.alerts-default", "filebeat-*"], "privileges": ["read"]}
        ]
      }
    }
  }
  ```

- soc-reader 이름으로 만들기(키 권한이 soc-reader 권한을 넘지 않는다. 호출하는 관리자에게 `grant_api_key` 권한이 필요하다):

  ```text
  POST /_security/api_key/grant
  {"grant_type": "password", "username": "soc-reader", "password": "<soc-reader 비밀번호>",
   "api_key": {"name": "0-ticket-reader"}}
  ```

응답의 `encoded` 값만 `.env`의 `ELK_API_KEY`에 넣는다. 응답 화면을 캡처하거나 어디에 붙여 넣지 않는다. PIT(수집)도 `read`로 충분하다.

### 2. TLS (HTTPS 자체 서명일 때)

- ES의 CA 인증서 파일을 우리 서버로 복사한다. ES 9.x의 보안 자동 설정은 보통 `config/certs/http_ca.crt`를 만든다(도커면 `docker cp <es 컨테이너>:/usr/share/elasticsearch/config/certs/http_ca.crt <경로>`). 실제 위치는 랩 구성을 따른다.
- `config/local.toml`의 `[ingest]`·`[tools.siem]`에 같은 절대 경로를 `ca_cert_path`로 적는다.
- SAN 확인: `openssl s_client -connect <ES 호스트>:9200 -CAfile <CA 경로> </dev/null 2>/dev/null | openssl x509 -noout -ext subjectAltName`. `ELK_URL`의 호스트가 목록에 없으면 SAN에 넣어 인증서를 다시 만들거나, 목록에 있는 이름으로 접속한다(`/etc/hosts`).
- **임시 방법(`SSL_CERT_FILE`):** 코드 설정 대신 환경변수로 신뢰 저장소를 바꿀 수 있다(httpx 0.28.1은 기본 검증일 때 이 값을 쓴다). 프로세스 전체의 신뢰 저장소가 바뀌어 실행기 안의 L3 뉴스 수집 같은 공개 HTTPS도 영향을 받으므로, 공개 CA와 랩 CA를 합친 번들을 쓴다.

  ```bash
  cat "$(uv run python -c 'import certifi; print(certifi.where())')" <CA 경로> > <번들 경로>
  ```

  그 뒤 `SSL_CERT_FILE=<번들 경로>`를 붙여 명령을 실행한다. `ca_cert_path`가 있으면 그쪽이 우선한다.

### 3. `config/local.toml` 예시

`[[ingest.sources]]`·`[[tools.siem.targets]]`는 표의 배열이라 `local.toml`에 적으면 기본값 목록 **전체**를 대신한다. 알럿 대상도 다시 적는다.

```toml
[llm]
base_url = "https://<리소스 이름>.openai.azure.com/openai/v1/"
model = "<배포 이름>"
api_key_env = "LLM_API_KEY"

[ingest]
ca_cert_path = "<CA 절대 경로>"   # HTTP면 지운다

[[ingest.sources]]
kind = "alert"
key = ".alerts-security.alerts-default"
time_field = "@timestamp"

[[ingest.sources]]
kind = "event"
key = "filebeat-*"
time_field = "@timestamp"

[tools.siem]
ca_cert_path = "<CA 절대 경로>"   # HTTP면 지운다

[[tools.siem.targets]]
name = "alerts"
index = ".alerts-security.alerts-default"
time_field = "@timestamp"

[[tools.siem.targets]]
name = "web_access"
index = "filebeat-*"
time_field = "@timestamp"
# cloudtrail은 랩에 없어 뺀다. 모델이 고르면 invalid_argument다

[normalize]
batch_size = 1000   # 첫 수집 뒤 쌓인 이벤트를 빨리 넘기려면 올린다(발견한 문제 5)

[executor.l3]
interval_seconds = 0   # 단계 4에서는 L3를 끈다(기본값과 같음)
```

`.env`에는 `DATABASE_URL`, `AGENT_DATABASE_URL`, `LLM_API_KEY`, `ELK_URL`, `ELK_API_KEY`, `QDRANT_URL`이 필요하다(`.env.example`).

### 4. 랩 문서 모양 확인 (건수만 적는다)

Kibana Dev Tools에서 실행한다. 결과의 값은 옮겨 적지 않고 건수와 필드 유무만 적는다.

```text
GET filebeat-*/_search
{"size": 0, "aggs": {"dataset": {"terms": {"field": "event.dataset"}},
                     "index": {"terms": {"field": "_index", "size": 5}}}}
```

- `nginx.access`가 있는지, `_index`가 `.ds-filebeat-…` 모양인지 본다.

```text
GET .alerts-security.alerts-default/_search
{"size": 1, "query": {"term": {"kibana.alert.rule.type": "threshold"}},
 "_source": ["kibana.alert.rule.name", "kibana.alert.original_time", "kibana.alert.threshold_result.terms.field",
             "source.ip", "transaction.client_ip"]}
```

- WAF 반복차단 알럿 1건으로 묶음 필드가 문서 맨 위에 있는지, `source.ip`·`original_time`이 있는지 본다. 같은 알럿의 정규화 결과에서 Entity 수를 센다(아래 SQL).

### 5. 실행 순서와 간격

```bash
set -a; source .env; set +a
uv run python -m soc.ingest
normalize_all() {
  # 맡을 원본이 없을 때까지(claimed=0) 정규화를 반복한다. DB 오류로 출력이 없어도 끝나게 횟수를 둔다
  for _ in $(seq 1 50); do
    out=$(uv run python -m soc.normalize); echo "$out"
    case "$out" in "claimed=0 "*|"") break ;; esac
  done
}
normalize_all
uv run python -m soc.l1.ticketing
uv run python -m soc.agent        # L1·L2 실행기. Ctrl+C로 끝낸다
```

- 수집·정규화·Ticket은 한 번 실행하고 끝나는 명령이다. 이어서 돌릴 때는 셸 루프나 cron을 쓴다(연속 실행 명령과 서비스화는 서버 배포 이슈에서 한다).
- 셸 루프 예(룰 주기 1분에 맞춰 60초 간격):

  ```bash
  set -a; source .env; set +a
  while true; do
    uv run python -m soc.ingest
    normalize_all          # 위에서 정의한 함수
    uv run python -m soc.l1.ticketing
    sleep 60
  done
  ```

- cron 예(겹쳐 돌지 않게 `flock`. 앞 명령이 실패해도 뒤 명령은 돈다):

  ```text
  * * * * * cd <레포 경로> && flock -n /tmp/0-ticket-pipe.lock sh -c 'set -a; . ./.env; set +a; uv run python -m soc.ingest; uv run python -m soc.normalize; uv run python -m soc.l1.ticketing' >> <로그 경로> 2>&1
  ```

- 실행기(`soc.agent`)는 따로 계속 띄워 둔다.
- L3 → L2(단계 5)는 `uv run python -m soc.l3 hunt`(뉴스·CISA·MITRE 수집에 인터넷, 실제 모델 필요)로 한다. 만들어진 `origin = l3` Ticket은 실행기의 L2 분류가 가져간다.

### 6. 단계별 확인 SQL

```sql
-- 1 수집
SELECT kind, count(*) FROM raw_records GROUP BY kind;
SELECT DISTINCT ON (source_kind, source_key) source_kind, source_key, outcome, pages, inserted
FROM ingest_runs ORDER BY source_kind, source_key, started_at DESC;
-- 2 정규화(실패 코드별, 클래스별. 4002는 0건 예상: 발견한 문제 1)
SELECT status, error_code, count(*) FROM normalize_status GROUP BY 1, 2;
SELECT ocsf_class, count(*) FROM events GROUP BY 1;
SELECT title, jsonb_array_length(entities) AS entity_count FROM alerts ORDER BY time DESC LIMIT 20;
-- 3·4 Ticket, L1, L2
SELECT origin, status, count(*) FROM tickets GROUP BY 1, 2;
SELECT status, count(*) FROM incidents GROUP BY 1;
SELECT verdict, count(*) FROM incident_artifacts GROUP BY 1;
-- 비용(토큰)과 시간
SELECT stage, details->>'task' AS task, count(DISTINCT run_id) AS runs,
       sum(tokens_in) AS tokens_in, sum(tokens_out) AS tokens_out,
       min(started_at) AS first_at, max(started_at) AS last_at
FROM agent_logs WHERE kind = 'model' GROUP BY 1, 2;
```

### 7. 자산 표 시험 데이터 (선택)

정규화가 Entity에 자산 정보를 붙이는지 볼 때만 넣는다. `entity_value`는 `soc.entities.normalize_entity_value`로 정규화한 값이어야 한다(IP는 표준 표기, host·domain은 소문자). 값은 랩의 실제 IP로 바꾸되 이 파일에는 쓰지 않는다.

```sql
WITH web AS (
  INSERT INTO assets (name, criticality, owner) VALUES ('lab-web', 4, 'lab') RETURNING asset_id
)
INSERT INTO asset_identifiers (asset_id, entity_type, entity_value)
SELECT asset_id, 'ip', '<웹서버 IP>' FROM web;

WITH attacker AS (
  INSERT INTO assets (name, criticality, owner) VALUES ('lab-attacker', 1, 'lab') RETURNING asset_id
)
INSERT INTO asset_identifiers (asset_id, entity_type, entity_value)
SELECT asset_id, 'ip', '<공격자 IP>' FROM attacker;
```

자산은 정규화할 때 붙으므로, 넣기 전에 정규화된 Alert·Event에는 붙지 않는다.

### 8. 서버 확인 항목

계획 `docs/plans/264-lab-cycle.md` "완료 기준 → 서버 확인(사람, 후속)"을 따른다. 결과는 `docs/notes/264-lab-cycle-server.md`(이 파일을 가리킴)에 건수로 적고, 그 기록을 넣는 후속 PR이 #264를 닫는다.

## 확인 방법

(마무리에서 채운다)
