-- W04 정책 저장과 Alert당 Ticket 하나를 보장한다(#246).

-- 검사부터 제약 추가까지 다른 실행기가 Ticket을 바꾸지 못하게 한다.
LOCK TABLE tickets IN ACCESS EXCLUSIVE MODE;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM tickets
        WHERE origin IN ('auto', 'scenario', 'l1')
          AND cardinality(alert_ids) <> 1
    ) THEN
        RAISE EXCEPTION
            '0104_l1_ticketing: auto, scenario, and l1 Tickets must have exactly one alert_id; resolve existing rows before retrying';
    END IF;

    IF EXISTS (
        SELECT u.alert_id
        FROM tickets AS t
        CROSS JOIN LATERAL unnest(t.alert_ids) AS u(alert_id)
        WHERE t.origin IN ('auto', 'scenario', 'l1')
        GROUP BY u.alert_id
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            '0104_l1_ticketing: an alert_id is referenced by multiple auto, scenario, or l1 Tickets; resolve existing rows before retrying';
    END IF;
END
$$;

CREATE TABLE ticketing_policy (
    id smallint PRIMARY KEY CHECK (id = 1),
    mode text NOT NULL CHECK (mode IN ('auto', 'scenario')),
    scenario_rule_ids text[] NOT NULL CHECK (array_position(scenario_rule_ids, NULL) IS NULL)
);

ALTER TABLE tickets
    ADD CONSTRAINT tickets_auto_scenario_l1_single_alert_check
    CHECK (origin = 'l3' OR cardinality(alert_ids) = 1);

CREATE UNIQUE INDEX tickets_auto_scenario_l1_alert_uidx
    ON tickets ((alert_ids[1]))
    WHERE origin IN ('auto', 'scenario', 'l1');
