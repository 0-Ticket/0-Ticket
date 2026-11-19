-- alerts.ocsf는 Detection Finding(2004)이거나 해석할 수 없는 원본의 폴백 Base Event(0)다(#338, D-065).
-- ocsf에 class_uid가 없는 행(옛 형식)은 NULL이라 통과한다. severity CHECK(0~6)는 바꾸지 않는다.

ALTER TABLE alerts
    ADD CONSTRAINT alerts_ocsf_class_check CHECK ((ocsf ->> 'class_uid') IN ('2004', '0'));
