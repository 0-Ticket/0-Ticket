-- 에이전트 DB 읽기 역할(0003)이 근거 발급(#382, D-085)으로 저장한 원문을 읽는 열.
-- 이벤트를 정규화하지 않으므로 events 행은 class 0 포인터이고 원문은 raw_records.original_text에
-- 있다. get_raw가 그것을 돌려준다. 열 단위 SELECT만 주고 쓰기 권한은 없다.
-- siem_ref와 siem_profile은 주지 않는다. siem_ref에는 인덱스 이름이 들어 있고, 모델에게 인덱스
-- 이름을 보이지 않는 것이 이 설계의 전제다(원문 가져오기는 워커가 도구 세션의 맵으로 한다).
-- 0003 헤더의 "raw_records에는 권한을 주지 않는다"는 이 열들에 한해 바뀌었다.

GRANT SELECT (id, kind, fetched_at, original_text) ON raw_records TO soc_agent_reader;
