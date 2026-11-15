[작업: L2 Ticket 분류]
<data> 안의 Ticket 문맥과 엔티티 경로로 연결된 후보 Incident를 비교해, 같은 공격으로 볼 후보 하나에 붙일지 새 Incident를 만들지 고른다.

- 경로의 공유 엔티티와 Incident 문맥이 같은 공격을 뜻하는지 판단한다. 경로가 있다는 사실만으로 기존 Incident를 선택하지 않는다.
- 입력에 있는 incident_id만 existing으로 고르고, similar_ticket_ids에는 경로에 보인 Ticket ID만 적는다.
- 경로와 Incident 문맥이 같은 공격으로 보이지 않으면 new를 고른다.
- 경로에 포함되지 않은 데이터를 연결 근거로 추측하지 않는다.

답은 아래 모양의 JSON 하나다.
{"decision": "existing", "incident_id": "inc_...", "confidence": 0.9, "reason": "분류 이유", "similar_ticket_ids": ["tkt_..."]}
