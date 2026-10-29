# Wazuh 연결 사전검증 고정 자료 (#112, C-02a)

**손으로 만든 자료다. 실제 Wazuh 응답을 복사하지 않았다.** Wazuh 4.x indexer(OpenSearch)의 `_search` 응답과
server API 인증 응답의 형태만 따랐고, 값은 모두 지어냈다.

- IP는 문서용 대역(192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24), 호스트는 `example.com`, 계정은 `test-user-*`·`test-reader-*`만 쓴다.
- 알럿 `_source` 필드는 박스 4 별칭 표 `ait_wazuh_alert`가 찾는 이름(`@timestamp`, `rule.*`, `agent.*`,
  `data.srcip`·`data.src_ip`, `data.dest_ip`, `data.srcport`·`data.src_port`, `data.dest_port`, `data.url`)을 쓴다.
- JWT는 가짜 문자열이다. 비밀 값은 없다.
- 가짜 Wazuh(`tests/ingest/fake_wazuh.py`)가 이 파일을 응답으로 돌려준다. probe가 값을 보고서에 옮기지 않는지 이 값으로 확인한다.

| 파일 | 내용 |
|---|---|
| `alert_search.json` | `wazuh-alerts-*` `_search` 응답. 알럿 3건(웹 31104, Suricata 86601, sshd 5710). IP 필드 이름이 디코더마다 다르다 |
| `archive_search.json` | `wazuh-archives-*` `_search` 응답. 이벤트 2건. archives 문서에는 `rule`이 없다 |
| `indexer_root.json` | indexer `GET /` 응답. `version.distribution`·`version.number`는 OpenSearch 쪽 값이다(Wazuh 버전 아님) |
| `authenticate_ok.json` | server API `POST /security/user/authenticate` 성공 응답 |
| `error_401.json` | 인증 실패 본문 |
| `error_403.json` | 권한 없음 본문(읽기 role에 없는 인덱스) |
| `error_404_index.json` | 인덱스 없음 본문 |
