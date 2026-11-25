-- Ticket 생성 모드의 기본 모드 이름을 auto에서 default로 바꾼다(#297, D-033).
-- ticketing_policy.mode의 CHECK를 바꾸고 기존 auto 행을 default로 고친다.
-- tickets.origin의 auto(D-026)는 건드리지 않는다.
-- 파이프·API·python -m soc.l1.ticketing을 멈춘 뒤 적용한다. 새 코드는 auto를, 옛 코드는 default를 거부한다.

LOCK TABLE ticketing_policy IN ACCESS EXCLUSIVE MODE;

ALTER TABLE ticketing_policy DROP CONSTRAINT ticketing_policy_mode_check;

UPDATE ticketing_policy SET mode = 'default' WHERE mode = 'auto';

ALTER TABLE ticketing_policy
    ADD CONSTRAINT ticketing_policy_mode_check CHECK (mode IN ('default', 'scenario'));
