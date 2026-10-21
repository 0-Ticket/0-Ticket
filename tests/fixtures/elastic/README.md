# ELK(elastic) 어댑터 고정 자료 (#99)

**문서 기준으로 손으로 만든 자료다. attack-to-alert 랩 문서를 받으면 같은 파일 이름으로 교체한다.**

- 형식 근거: Kibana Security 알럿 문서(`.alerts-security.alerts-*`, `kibana.alert.*` 키는 점 표기)와
  Logstash grok(ECS)로 파싱한 nginx 접근로그(`logs-generic-default` 데이터 스트림).
- 각 파일은 ES `_search` 응답의 `hits.hits` 항목 목록이다(`_index`, `_id`, `_source`).
- IP는 문서용 대역(192.0.2.0/24, 198.51.100.0/24)만 쓴다. 비밀값은 없다.
- 점 키와 중첩 키를 둘 다 넣었다: 알럿 `al-3`은 `source.address`·`url.original`을 점 키로, 이벤트 `ev-4`는
  `source.address`를 점 키로 갖는다. 어댑터가 펼치면 나머지와 같은 모양이 된다.
- 이벤트 `ev-2`와 `ev-3`은 `@timestamp`가 같다(nginx 시각은 초 단위). 커서가 같은 시각 문서를 빠뜨리거나
  겹치지 않는지 확인하는 데 쓴다.

| 파일 | 내용 |
|---|---|
| `alert_hits.json` | 알럿 3건. 룰 `a2a-web-attack-juice-shop`. `al-1`·`al-2`는 같은 출발지 |
| `event_hits.json` | 접근로그 5건 |
| `bad_hits.json` | C2로 바꿀 수 없는 문서 2건(`_source`가 배열, 점 키와 중첩 키 충돌) |

`bad_hits.json`의 `_timestamp`는 가짜 ES(`tests/ingest/fake_elasticsearch.py`)만 읽는 정렬 시각이다. `_source`가 객체가
아니라 `@timestamp`가 없는 문서도 정렬 위치를 갖게 하려고 둔다. 실제 ES 응답에는 없다.
