-- events.ocsf는 저장한 이벤트 클래스(0 Base Event, 2003, 3002, 4001, 4002, 4003, 6003)의 문서다(#347, D-068).
-- ocsf에 class_uid가 없는 행(옛 형식)은 NULL이라 통과한다. 어긋나는 기존 행이 있으면 아래 CHECK 추가가
-- 실패해 마이그레이션이 멈춘다(말없이 지우거나 고치지 않는다).

ALTER TABLE events
    ADD CONSTRAINT events_ocsf_class_uid_check
    CHECK ((ocsf ->> 'class_uid') IN ('0', '2003', '3002', '4001', '4002', '4003', '6003'));
