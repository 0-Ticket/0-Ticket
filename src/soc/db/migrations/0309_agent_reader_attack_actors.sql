-- 에이전트 DB 읽기 역할(0003)이 get_attack_actor(#389, D-052)를 위해 읽는 표. 읽기만 준다.
-- threat_news에는 여전히 권한이 없다(0302와 같다).

GRANT SELECT ON attack_actors, attack_actor_techniques TO soc_agent_reader;
