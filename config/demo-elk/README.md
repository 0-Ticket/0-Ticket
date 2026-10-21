# ELK 시연 설정 (#99)

[attack-to-alert](https://github.com/0-Ticket/attack-to-alert) 랩의 Elasticsearch에서 Kibana 탐지 알럿과 nginx 접근로그를 읽어 우리 파이프라인(수집 → 정규화 → Lookup → 분기)에 넣는다. AIT 시연(`config/demo/`)과는 별개이고, 중간 발표 시연 범위(L1) 밖의 선택 항목이다.

| 파일 | 내용 |
|---|---|
| `settings.toml` | `[siem] adapter = "elastic"`, `base_url = "http://localhost:9200"`, `token_env = "SIEM_TOKEN"`, 시나리오 규칙 폴더 |
| `rules/scenarios.toml` | 랩 룰 `a2a-web-attack-juice-shop`을 시나리오 `elk_web_attack`(`handling_type = "web_attack"`, `specialist = "web"`)으로 둔다 |

어댑터가 읽는 것:

| 종류 | 인덱스 (설정 `[siem.elastic]`) | 시나리오 (별칭 표) |
|---|---|---|
| 알럿 | `alert_index = ".alerts-security.alerts-*"` | `elastic_security_alert` |
| 이벤트 | `event_index = "logs-*"` | `elastic_access_event` |

## 필요한 환경변수

| 이름 | 내용 |
|---|---|
| `SIEM_TOKEN` | 읽기 전용 ES API 키(아래에서 만든 `encoded` 값). `.env`에만 둔다 |
| `DATABASE_URL` | PostgreSQL 접속 주소(`.env.example`) |
| `ZT_CONFIG` | `config/demo-elk/settings.toml` (주소를 바꿨다면 `config/local.elk.toml`) |

## 읽기 전용 ES API 키 만들기

이 어댑터는 ES를 읽기만 한다. 키에는 알럿 인덱스와 `logs-*`의 `read`, `view_index_metadata` 권한만 준다.

- 이 명령은 ES가 떠 있는 서버(랩 서버)에서 실행한다. `elastic` 비밀번호는 랩 `.env`의 `ELASTIC_PASSWORD`다.

```bash
# 관리자 비밀번호는 명령에 쓰지 않는다. -u elastic만 주면 curl이 비밀번호를 묻는다.
curl -u elastic -X POST "http://localhost:9200/_security/api_key" \
  -H "Content-Type: application/json" -d '{
  "name": "zt-soc-readonly",
  "role_descriptors": {
    "zt_soc_read": {
      "cluster": [],
      "indices": [{
        "names": [".alerts-security.alerts-*", "logs-*"],
        "privileges": ["read", "view_index_metadata"]
      }]
    }
  }
}'
```

- 응답의 `encoded` 값이 키다. 이 값은 `.env`의 `SIEM_TOKEN`(설정 `token_env`)에만 넣는다.
- 키 값은 설정 파일, 커밋, 로그, 이슈·PR에 남기지 않는다. 어댑터도 키를 로그·오류 메시지·health 결과에 쓰지 않는다.
- 어댑터는 `Authorization: ApiKey <encoded>` 헤더로 보낸다.
- 키를 만든 뒤 health_check가 403이면, Kibana 알럿이 실제로 저장되는 인덱스(`.internal.alerts-security.alerts-*`)에도 같은 권한을 줘야 하는 경우다. `names`에 그 패턴을 더해 키를 다시 만든다.
  (랩 확인 결과: 아직 없음. 확인하면 필요 여부와 최종 `names` 목록을 여기에 적는다)

키가 읽히는지 응답 코드로만 확인한다(키 값은 출력하지 않는다):

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: ApiKey $SIEM_TOKEN" \
  "http://localhost:9200/.alerts-security.alerts-*/_search?size=0"
```

## 주소 바꾸기

`base_url` 기본값은 `http://localhost:9200`이다. ES가 다른 서버에 있으면 `config/demo-elk/settings.toml`을 `config/local.elk.toml`로 복사해 `[siem] base_url`(HTTPS면 필요에 따라 `verify_tls`)만 바꾸고 `export ZT_CONFIG=config/local.elk.toml`로 고른다. `ZT_CONFIG`는 파일 하나만 기본 설정 위에 덮어쓰므로 복사해서 고친다. `config/local.*`은 커밋하지 않는다(`.gitignore`).

## 실행 순서

1. 랩에서 `make up`, `make detections`, `bash scripts/attack-sim.sh`를 실행한다(랩 레포 README). 공격 재현은 사람이 랩에서만 한다.
2. **attack-sim이 끝나고 1~2분 기다린다.** Kibana 룰이 1분 주기로 돌아 알럿을 만들고, Logstash가 접근로그 색인을 마칠 시간이다.
3. 레포 루트에서 한 번에 돌린다.

```bash
set -a; source .env; set +a                     # SIEM_TOKEN, DATABASE_URL
export ZT_CONFIG=config/demo-elk/settings.toml
uv run python -m soc.db.migrate
uv run python -m soc.ingest --all
uv run python -m soc.normalize --all            # Lookup(박스 5)은 정규화 중에 붙는다
uv run python -m soc.branch --all
```

- Lookup 표(자산·사용자)는 선택이다. 랩의 IP는 환경마다 달라 시연 CSV를 두지 않았다. 필요하면 `uv run python -m soc.normalize.lookup.load assets <CSV>`로 normalize 전에 넣는다.
- 기대 결과: `a2a-web-attack-juice-shop` 알럿 중 첫 알럿(같은 출발지에서 10분 안의 반복은 중복 제거)이 `scenario_ticket`으로 분기된다. 랩 알럿에는 목적지 IP가 없어 `dst_ip` 없이 엔티티 집합 {출발지 IP}로 중복 제거된다.
- L1까지 돌리려면 LLM 설정이 필요하다(`docs/milestone-l1.md` 참고: Ollama, 모델, Qdrant).
- 새 DB에서 돌리려면 `DATABASE_URL`의 DB 이름만 바꾼다. 커서는 어댑터 이름(`elastic`)별로 저장되어 같은 DB에서 다시 돌리면 이어서 가져온다.

## 한계

- **늦게 색인된 이벤트**: 커서는 인덱스마다 마지막으로 읽은 `@timestamp`를 기억한다. 그보다 이른 `@timestamp`로 나중에 색인된 문서는 가져오지 못한다. 그래서 시연은 attack-sim 뒤 1~2분 기다렸다가 한 번에 돌린다.
- **알럿 상태 필드**: Kibana가 나중에 바꾸는 알럿 필드(`kibana.alert.workflow_status`, `kibana.alert.status`, `kibana.alert.last_detected` 등)는 C2에 넣지 않는다. 같은 알럿을 다시 읽어도 `source_record_id`가 같게 하려는 것이다. 목록은 `src/soc/ingest/siem/elastic.py`의 `MUTABLE_ALERT_FIELDS` 한 곳에 있다.
- **host**: 랩의 `host.name`은 수집기(Logstash)일 수 있어 별칭 표에 매핑하지 않았다(`unmapped`에 남는다). 랩 확인 후 필요하면 별칭 표에 한 줄 더한다.

## 랩 확인 항목 (PR ① 머지 전, 결과는 PR 본문에)

1. 커서: `@timestamp` + 이미 본 `_id` 목록 방식으로 같은 초의 문서가 빠지거나 겹치지 않는다(`fetched` 합 = 랩 알럿 수 + 이벤트 수).
2. 점 키·중첩 키: 실제 알럿·이벤트 문서가 어느 표기든 정규화 실패(C12)가 없다.
3. `host.name`이 무엇을 가리키는지.
4. `MUTABLE_ALERT_FIELDS`가 실제 알럿에서 바뀌는 필드와 맞는지(Kibana에서 알럿을 acknowledged로 바꾼 뒤 다시 읽어 `source_record_id`가 같은지).
5. 위 권한으로 health_check가 통과하는지. 403이면 `.internal.alerts-security.alerts-*`를 더한다.
6. 실제 ES에서 alert `query_siem`이 400 없이 동작하고 오래된 순으로 나온다(런타임 정렬 스크립트, PR ②).

고정 자료 `tests/fixtures/elastic/`은 지금 문서 기준으로 손으로 만든 자료다. 랩 문서를 받으면 같은 파일을 랩 기반(IP는 문서용 대역, 비밀값 삭제)으로 바꾼다.
