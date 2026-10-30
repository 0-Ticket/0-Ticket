# Wazuh 연결 사전검증 결과 (C-02a, #112)

> **번호 없는 SIEM 커넥터 구현 완료가 아니다.** 이미 구축된 Wazuh에 연결·인증할 수 있는지와 원시 응답의 형태만 확인했다.
> 커넥터(C-02b), 정규화 매핑(C-02c), SIEM MCP(C-01b)는 이 문서의 결과를 입력으로 삼는 후속 이슈다.
> SIEM 구축·설정 변경, DB 저장, OCSF 정규화는 하지 않았다.

이 문서에는 내부 주소, 계정 이름, 비밀 값, 실제 응답의 값을 적지 않는다. 실제 실행 결과는 probe의 형태 보고서
(값 없음)를 요약해서 옮긴다. 보고서 원본은 `data/` 아래에만 두고 커밋하지 않는다.

## 1. 도구

- probe: `scripts/probe_wazuh.py` (읽기 전용. 표준 라이브러리 `urllib`·`ssl`만 쓴다)
- 테스트: `tests/ingest/test_probe_wazuh.py`, 가짜 Wazuh `tests/ingest/fake_wazuh.py`, 손 자료 `tests/fixtures/wazuh/`
  - 가짜 Wazuh는 TLS 없이 뜬다. 테스트는 `https://` URL을 쓰고, 테스트 전용 `PlainHttpsHandler`를 `main(https_handler=...)`로 넘겨 TLS 층만 바꾼다.
    CLI에는 이 인자가 없고 항상 `--ca`로 검증하는 `HTTPSHandler`를 쓴다. https 검사와 리다이렉트 차단은 테스트에서도 그대로 돈다.

```bash
uv run python scripts/probe_wazuh.py --indexer-url https://<indexer>:9200 --api-url https://<manager>:55000 --ca <root-ca.pem> --out wazuh/probe.json
```

| 대상 | 요청 | 확인하는 것 |
|---|---|---|
| `indexer` | `GET /` (Basic) | 연결, 인증, OpenSearch `version.distribution`·`version.number` |
| `alerts` | `POST /wazuh-alerts-*/_search` (Basic, 최신 N건) | 응답 엔벌롭, `_source` 키 경로·타입·등장 수, 인덱스 이름 형태 |
| `events` | `POST /wazuh-archives-*/_search` (Basic, 최신 N건) | 위와 같음. 문서가 없으면 archives 꺼짐 가능 표시 |
| `api` | `POST /security/user/authenticate` (Basic) | JWT 발급 여부만. 토큰은 바로 버리고 다른 호출에 쓰지 않는다 |

### 안전장치

- https 전용(http 거부): `--indexer-url`·`--api-url`이 `https://`가 아니면 요청을 하나도 보내지 않고 고정 문구로 멈춘다(종료 코드 2).
  평문 http는 Basic 자격증명을 그대로 보내기 때문이다. http를 허용하는 옵션은 없다(TLS 끄기 금지와 같은 원칙).
- 리다이렉트 비추종(Authorization 미전달): 3xx 응답을 따라가지 않고 `bad_response`로 분류한다. urllib 기본 동작은
  `Location`(다른 호스트 포함)으로 Authorization 헤더를 다시 보내므로, 리다이렉트를 막는 핸들러로 이 경로를 없앴다.
- 중첩 깊이 상한: `_source`는 `MAX_DEPTH`(64)단계까지만 읽는다. 더 깊으면 그 대상은 `bad_response`다. 파이썬 재귀 한도에 닿기 전에
  멈추고, `json.loads` 자체가 깊이 때문에 포기하는 경우(`RecursionError`)도 `bad_response`로 잡는다. 키·값은 보고서에 남지 않는다.
- JWT 미보유: API 응답에서는 토큰 문자열이 있는지만 bool로 계산하고 응답 참조를 바로 지운다. 토큰은 반환값·보고서·로그 어디에도 없다.
- 비밀: 환경변수 `WAZUH_INDEXER_USER`, `WAZUH_INDEXER_PASSWORD`, `WAZUH_API_USER`, `WAZUH_API_PASSWORD`
  (이름은 `--*-env` 인자로 바꿀 수 있다). 값이 비어 있으면 요청을 보내기 전에 멈춘다(종료 코드 2).
- TLS: 항상 검증한다. 검증을 끄는 옵션은 없다. Wazuh 기본 자체 서명 인증서는 `--ca`로 루트 CA를 넘긴다.
- `--out`은 `data/` 기준 상대 경로만 받는다. `data/` 밖으로 나가면 거부한다.
- 종료 코드: 0 모든 대상 ok, 1 실패한 대상 있음, 2 설정 오류(요청 없음).

## 2. 결과 분류

| outcome | 뜻 | 판단 근거 |
|---|---|---|
| `ok` | 성공 | 2xx + 기대한 JSON 모양 (`_search`는 문서 1건 이상) |
| `unreachable` | 연결 불가 | DNS 실패, 연결 거부 등 `URLError`·`OSError` |
| `timeout` | 시간 초과 | `TimeoutError` (`--timeout`초) |
| `tls_error` | TLS 실패 | `ssl.SSLError` (인증서 검증 실패, 프로토콜 불일치) |
| `auth_failed` | 인증 실패 | HTTP 401 |
| `forbidden` | 권한 없음 | HTTP 403 (읽기 role에 없는 인덱스) |
| `index_missing` | 인덱스·문서 없음 | HTTP 404, 또는 와일드카드 패턴이 문서를 하나도 찾지 못함(200, 0건) |
| `bad_response` | 쓸 수 없는 응답 | 그 밖의 HTTP 상태(3xx 리다이렉트 포함, 따라가지 않음), JSON 아님, 중첩 깊이 상한 초과, 기대한 키 없음, 5 MiB 초과 |

연결 성공·실패와 인증 오류는 `unreachable`·`timeout`·`tls_error` / `auth_failed`·`forbidden`으로 갈린다(완료 기준 #1).
예외 메시지와 응답 본문은 분류에 쓰지 않고 출력하지도 않는다.

**검증 범위:** `tls_error`는 판정 로직만 단위 테스트(`test_tls_failure_is_classified_as_tls_error`)로 확인한다.
실제 TLS 핸드셰이크 실패는 가짜 서버로 재현하지 않았다. 표준 라이브러리로는 인증서를 만들 수 없고 개인 키를 고정 자료로 커밋하지 않기
위해서다. 실제 TLS 동작은 아래 3절의 수동 실행에서만 확인한다.

## 3. 실제 Wazuh 실행 결과

> **미기록.** 사람이 `.env`를 불러온 자기 셸에서 probe를 실행하고 형태 보고서를 공유하면 이 절을 채운다.
> 그전까지 아래 표는 비어 있고, 완료 기준 #2(테스트 환경에서 Alert·Event 원시 응답 확인)는 충족되지 않은 상태다.

| 항목 | 값 |
|---|---|
| Wazuh 버전 (docker 이미지 태그 등으로 사람이 확인) | 미기록 (4.x) |
| indexer 배포판·버전 (`indexer.distribution`·`version`) | 미기록 |
| TLS (`--ca` 사용 여부) | 미기록 |
| `indexer` | 미기록 |
| `alerts` (total, 인덱스 이름 형태) | 미기록 |
| `events` (total, archives 켜짐 여부) | 미기록 |
| `api` (JWT 발급) | 미기록 |
| 일부러 틀린 비밀번호로 실행 → `auth_failed` | 미기록 |
| 닫힌 포트로 실행 → `unreachable`/`timeout` | 미기록 |
| `--ca` 없이 실행 → `tls_error` | 미기록 |

archives(logall_json)가 꺼져 있으면 `events`가 `index_missing`이 되고 보고서 `notes`에 표시된다. 이때는
"이벤트 수집에 Wazuh 설정 변경이 필요하다"는 사실만 적고 설정은 바꾸지 않는다(완료 기준 #6).

## 4. 원시 응답 형태 (손 자료 기준, 실제 실행 후 대조)

`_search` 응답은 문서를 엔벌롭으로 감싼다.

```
took, timed_out, _shards, hits{ total{value, relation}, max_score, hits[ {_index, _id, _score, _source, sort} ] }
```

- `_index`: 날짜별 인덱스. `wazuh-alerts-4.x-<date>`, `wazuh-archives-4.x-<date>` (`<date>` = `YYYY.MM.DD`)
- `_id`: indexer가 붙인 문서 ID. 같은 문서를 다시 읽으면 같다.

Alert `_source` (6 OCSF 별칭 표 `ait_wazuh_alert`가 찾는 필드):

| 필드 | 타입 | 비고 |
|---|---|---|
| `@timestamp` | str (ISO 8601, UTC) | 별칭 표 `time`. 커서 후보 |
| `timestamp` | str (`+0000` 오프셋) | 매니저 시각. 별칭 표는 쓰지 않음 |
| `agent.id`, `agent.name`, `agent.ip` | str | `agent.ip`는 별칭 표 `dst_ip` 마지막 후보. 매니저 자신(`000`)은 `ip` 없음 |
| `rule.id` | str | 별칭 표 `rule_id` |
| `rule.level` | int (0~15) | 별칭 표 `severity_id` 변환표 |
| `rule.description` | str | 별칭 표 `rule_name` |
| `rule.mitre.id[]` | list[str] | 별칭 표 `techniques`. 없는 룰도 있음 |
| `data.srcip` / `data.src_ip` | str | 디코더마다 이름이 다름 (Apache·sshd / Suricata eve) |
| `data.dstip` / `data.dest_ip` | str | fast.log 경유 IDS 알럿의 `data.dstip`는 `IP:포트` |
| `data.srcport` / `data.src_port`, `data.dest_port` | str | 문자열 숫자 |
| `data.id`, `data.url`, `data.protocol`, `data.event_type` | str | `data.id`는 접근 로그에서 응답 코드, 오류 로그에서 오류 코드 |
| `location`, `decoder.name`, `full_log`, `id`, `manager.name`, `input.type` | str | `full_log`는 원문 한 줄(공격자 문자열 가능) |

이벤트(archives) `_source`는 알럿과 같은 구조에서 `rule`이 없다. 디코더가 해석하지 못한 줄은 `data`도 없고
`full_log`·`predecoder`만 있다.

## 5. 커넥터 계약 대조 (C-02b 입력)

| 항목 | 현재 인터페이스 | Wazuh에서 확인된 것 / 제안 |
|---|---|---|
| 가져오기 | `SiemConnector.fetch(cursor, limit) -> FetchBatch(items, next_cursor, skipped)` (`src/soc/ingest/siem/base.py`) | indexer `_search`를 `@timestamp` 오름차순으로 읽는다. 알럿·이벤트 두 패턴 |
| C2 `kind` | `alert` / `event` | `wazuh-alerts-*` → `alert`, `wazuh-archives-*` → `event` |
| C2 `scenario` | 별칭 표 이름 | 알럿은 기존 `ait_wazuh_alert` 표로 표현되는지 실제 응답과 대조. 안 되면 C-02c |
| C2 `raw_ids` | 커넥터가 정하는 고유값 | 후보 `raw_wazuh_<_index>_<_id>` (elastic의 `raw_es_<index>_<_id>`와 같은 방식) |
| C2 `fields` | SIEM 원본 그대로 | `_source` 그대로. Wazuh는 점 표기 키를 쓰지 않는 것으로 보이나 실제 응답으로 확인 |
| 커서 | 어댑터가 정하는 문자열 | 후보: 패턴별 마지막 `@timestamp` + 그 시각에 읽은 `_id` 목록 (elastic 커서와 같은 방식, `_id` 정렬 안 함) |
| 연결 확인 | `health_check() -> HealthStatus(ok, detail)` | 후보: indexer `GET /` 또는 `GET /<alert pattern>/_search?size=0`. `detail`은 2절 분류 이름만 |
| 비밀 | `read_secret(settings.token_env, environ)` | Wazuh는 Basic(사용자 + 비밀번호)이라 환경변수가 둘 필요 |
| 주소 | `[siem] base_url` 하나 | indexer와 API 주소가 다름. 커넥터는 indexer만 필요, API는 SIEM MCP(C-01b)에서 필요할 수 있음 |

기존 `[siem]`은 `base_url` 하나 + `token_env` 하나(Bearer·ApiKey) 모델이라 Wazuh에는 부족하다. C-02b에서 검토할
설정 키 후보(이번에는 `config/default.toml`을 바꾸지 않는다):

```toml
[siem.wazuh]
# indexer 주소 (base_url 대신 또는 base_url을 indexer로 해석)
indexer_url = ""
# server API 주소 (커넥터는 쓰지 않음. SIEM MCP용)
api_url = ""
user_env = "WAZUH_INDEXER_USER"
password_env = "WAZUH_INDEXER_PASSWORD"
# 자체 서명 루트 CA 파일. verify_tls는 true 유지
ca_file = ""
alert_index = "wazuh-alerts-*"
event_index = "wazuh-archives-*"
```

## 6. 후속 범위 (원래 Wazuh 계획 1–3)

| 단계 | 이슈 | 범위 | 상태 |
|---|---|---|---|
| (1) | C-02a #112 | 접속·인증·원시 응답 사전 점검 (이 문서) | 이번 작업. 3절 실제 실행 결과는 미기록 |
| (2) | C-02b | 번호 없는 Wazuh Alert·Event C2 커넥터. 5절 대조표와 설정 키 후보가 입력 | 후속 |
| (3) | C-02c | 6 OCSF의 Wazuh 시나리오별 정규화 매핑. **조건부**: 실제 응답이 기존 별칭·시나리오로 처리되지 않을 때만 등록 | 3절 결과에 따라 결정 |
| 관련 | C-01b | 14·28·42의 Wazuh 읽기 전용 SIEM MCP 어댑터 | 후속 |

이번 spike는 (1)만이다. `tests/checklist.md`의 K3·K66은 🟡 그대로 둔다.
