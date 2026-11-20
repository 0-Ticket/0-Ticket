[작업: L2 Ticket 분류]
<data> 안의 Ticket 문맥과 엔티티 경로로 연결된 후보 Incident를 비교해, 같은 공격으로 볼 후보 하나에 붙일지 새 Incident를 만들지 고른다.

- 경로의 공유 엔티티와 Incident 문맥이 같은 공격을 뜻하는지 판단한다. 경로가 있다는 사실만으로 기존 Incident를 선택하지 않는다.
- 입력에 있는 incident_id만 existing으로 고르고, similar_ticket_ids에는 경로에 보인 Ticket ID만 적는다.
- 경로와 Incident 문맥이 같은 공격으로 보이지 않으면 new를 고른다.
- 경로의 공유 IP(ip 엔티티 값)가 내부(사설) 주소로 보이면, 후보의 `target_hosts`(경로로 연결된 알럿의 target 엔티티 host 값)와 현재 Alert `entities`에서 role이 target인 host 값을 비교한다. 이 비교는 대소문자를 구분하지 않는다. 양쪽에 값이 있는데 겹치는 값이 하나도 없으면 같은 IP만으로 기존 Incident를 선택하지 않는다.
- 공유 IP가 공개 주소(공격자)이면 target host가 달라도 같은 공격일 수 있으므로 환경 차이만으로 분리하지 않는다.
- 한쪽에 target host 값이 없으면 환경 비교를 근거로 쓰지 않는다. dst IP 차이는 환경 비교의 근거로 쓰지 않는다.
- 입력에 없는 데이터를 연결 근거로 추측하지 않는다. `target_hosts`는 입력이므로 위 비교에 쓴다.

답은 아래 모양의 JSON 하나다.
{"decision": "existing", "incident_id": "inc_...", "confidence": 0.9, "reason": "분류 이유", "similar_ticket_ids": ["tkt_..."]}
