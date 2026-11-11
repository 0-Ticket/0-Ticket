-- 주변 기록 조회가 time 범위로 거르므로 시간 인덱스를 둔다(#267).
-- 일반 CREATE INDEX다. 실행기(src/soc/db/migrate.py)가 파일마다 트랜잭션을 열어
-- CONCURRENTLY를 쓸 수 없고, 빌드 동안 해당 테이블 쓰기가 대기한다.
-- 운영 규모 데이터에서 다시 만들어야 하면 실행기에 파일별 autocommit 표식을 먼저 더한다.
CREATE INDEX alerts_time_idx ON alerts (time);
CREATE INDEX events_time_idx ON events (time);
