-- 에이전트 DB 읽기 역할(#211). 에이전트 도구는 alerts·events만 읽는다(docs/security.md "에이전트 도구의 한계").
-- soc_agent_reader는 NOLOGIN 그룹 역할이다. 접속용 LOGIN 역할과 비밀번호는 여기에 넣지 않고 운영자가 따로 만든다:
--   CREATE ROLE <이름> LOGIN PASSWORD '<비밀번호>' IN ROLE soc_agent_reader;
-- 그 계정의 주소를 환경변수 AGENT_DATABASE_URL에 넣는다(docs/notes/211-tool-registry.md).
-- 역할은 클러스터 전체에서 하나라 다른 DB의 마이그레이션이 이미 만들었을 수 있다. 없을 때만 만든다.
-- 이 파일을 적용하는 계정에는 CREATEROLE이 필요하다.
-- raw_records, tickets, incidents, cases, agent_logs, hunts, L3 테이블, schema_migrations에는 권한을 주지 않는다.
-- 공통 대역(D-035)이므로 공통 테이블 alerts·events의 권한만 다룬다.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'soc_agent_reader') THEN
        CREATE ROLE soc_agent_reader NOLOGIN;
    END IF;
END
$$;

GRANT SELECT ON alerts, events TO soc_agent_reader;
