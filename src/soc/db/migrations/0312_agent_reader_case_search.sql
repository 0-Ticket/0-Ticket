-- 에이전트 DB 읽기 역할(0003)이 L3 Case 검색 도구(#392, D-087)를 위해 읽는 열.
-- 열 단위 SELECT만 준다. 쓰기 권한은 없다.
-- 막는 것: cases의 confirmed_by·assignee·resolved_at·details(사람 계정 이름과 내부 값), tickets의
-- details·hunt_id·updated_at, incident_artifacts의 summary(cases.summary와 같은 문장)·assessed_severity
-- (cases.severity와 같은 값)·created_at, incident_proposals의 id·created_at. incident_reviews(사람이 쓴
-- 반려 사유, D-082)와 case_index_jobs(0310)에는 여전히 권한이 없다.
-- 0003 머리말과 0007 머리말의 "읽지 못한다"가 이 열들에 한해 바뀐다. incidents·alerts는 0007·0003으로 충분하다.
-- incident_artifacts의 id·incident_id·analysis_round는 최신 Artifact를 고르는 WHERE·ORDER BY에도 쓰인다.

GRANT SELECT (title, summary, severity, entities, confirmed_at, status) ON cases TO soc_agent_reader;
GRANT SELECT (title, origin) ON tickets TO soc_agent_reader;
GRANT SELECT (
    id, incident_id, analysis_round, verdict, timeline, techniques,
    impact, cause, further_risk, evidence_ids
) ON incident_artifacts TO soc_agent_reader;
GRANT SELECT (artifact_id, kind, seq, priority, title, detail, rationale)
    ON incident_proposals TO soc_agent_reader;
