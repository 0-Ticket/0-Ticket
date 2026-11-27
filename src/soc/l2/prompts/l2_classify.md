[작업: L2 Ticket 분류]
<data> 안의 Ticket 문맥과 유사 Ticket으로 찾은 후보 Incident를 비교해, 같은 공격으로 볼 후보 하나에 붙일지 새 Incident를 만들지 고른다. 입력은 전체 후보 중 한 묶음일 수 있다. 묶음에서 new는 이 묶음에 고를 후보가 없다는 뜻이다.

- 경로의 공유 엔티티와 Incident 문맥이 같은 공격을 뜻하는지 판단한다. 경로가 있다는 사실만으로 기존 Incident를 선택하지 않는다.
- 입력에 있는 incident_id만 existing으로 고르고, similar_ticket_ids에는 경로 또는 representative_ticket_id에 보인 Ticket ID만 적는다.
- 유사도 점수는 후보를 찾는 근거일 뿐 같은 공격이라는 결론이 아니다. 경로가 없는 후보도 다른 문맥을 보고 판단한다.
- new를 고르면 incident_id는 null, similar_ticket_ids는 빈 배열이다.
- 경로와 Incident 문맥이 같은 공격으로 보이지 않으면 new를 고른다.
- 경로의 공유 IP(ip 엔티티 값)가 내부(사설) 주소로 보이고 후보의 `target_hosts`(경로로 연결된 알럿의 target 엔티티 host 값)와 현재 Alert `entities`의 role=target host 값이 양쪽에 있을 때만 대소문자 구분 없이 비교하며, 겹치는 값이 하나도 없으면 같은 IP만으로 기존 Incident를 선택하지 않는다. 한쪽이라도 target host 값이 없으면 비교 불가이며, 이를 겹침 없음으로 해석하거나 host 값 부재를 new의 근거로 삼지 않는다. 네트워크 탐지 알럿에는 보통 host 엔티티가 없다.
- 공유 IP가 공개 주소(공격자)이면 target host가 달라도 같은 공격일 수 있으므로 환경 차이만으로 분리하지 않는다.
- target host 대신 dst IP를 쓰지 않는다. dst IP 차이는 환경 비교의 근거로 쓰지 않는다.
- 입력에 없는 데이터를 연결 근거로 추측하지 않는다. `target_hosts`는 입력이므로 위 비교에 쓴다.

답은 아래 모양의 JSON 하나다.
{"decision": "existing", "incident_id": "inc_...", "confidence": 0.9, "reason": "분류 이유", "similar_ticket_ids": ["tkt_..."]}
