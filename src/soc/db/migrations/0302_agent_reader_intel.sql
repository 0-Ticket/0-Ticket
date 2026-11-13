-- 에이전트 DB 읽기 역할(0003)이 로컬 ATT&CK·KEV 조회 도구(#311, D-052)를 위해 읽는 표.
-- threat_news에는 권한을 주지 않는다: 0300의 방침은 그 표에 그대로 남는다.
-- 사용자 테이블(0005)처럼 이 역할이 읽으면 안 되는 표는 그대로 권한이 없다.

GRANT SELECT ON attack_techniques, kev_entries, intel_source_state TO soc_agent_reader;
