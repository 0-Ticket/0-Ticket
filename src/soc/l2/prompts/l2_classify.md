[작업: L2 Ticket 분류]
<data> 안의 Ticket 문맥과 후보 Incident를 비교해, 같은 공격으로 볼 후보 하나에 붙일지 새 Incident를 만들지 고른다.

- 후보가 같은 공격이라는 근거가 충분할 때만 existing을 고르고, 입력에 있는 incident_id만 쓴다.
- 비슷한 Ticket을 이유로 사용했다면 입력에 보인 Ticket ID만 similar_ticket_ids에 적는다.
- recent 후보에는 비슷한 Ticket이 없으므로 similar_ticket_ids를 빈 목록으로 둔다.
- 어느 후보도 같은 공격으로 보기 어렵다면 new를 고른다.
- 이 분류에는 추가 조회가 필요 없다.

답은 아래 모양의 JSON 하나다.
{"decision": "existing", "incident_id": "inc_...", "confidence": 0.9, "reason": "분류 이유", "similar_ticket_ids": ["tkt_..."]}
