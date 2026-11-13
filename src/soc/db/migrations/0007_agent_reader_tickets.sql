-- 에이전트 DB 읽기 역할(0003)이 유사 사례 검색 도구(#313, D-053)를 위해 읽는 열.
-- 열 단위 SELECT만 준다. tickets.details(계약 밖 값), incidents의 제목·요약·엔티티, cases의
-- 승인자·담당자·요약은 읽지 못한다. 쓰기 권한도 없다.
-- 0003 헤더의 "tickets, incidents, cases에는 권한을 주지 않는다"는 이 열들에 한해 바뀌었다.
-- 사용자 테이블(0005)처럼 이 역할이 읽으면 안 되는 표는 그대로 권한이 없다.

GRANT SELECT (id, status, verdict, entities, alert_ids, created_at) ON tickets TO soc_agent_reader;
GRANT SELECT (id, ticket_ids, status) ON incidents TO soc_agent_reader;
GRANT SELECT (id, incident_id) ON cases TO soc_agent_reader;
