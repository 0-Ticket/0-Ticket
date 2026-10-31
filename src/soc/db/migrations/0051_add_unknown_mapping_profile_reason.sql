-- Box 4: allow the C12 reason for missing or mismatched mapping profiles.
ALTER TABLE normalize_failures
    DROP CONSTRAINT normalize_failures_reason_check;

ALTER TABLE normalize_failures
    ADD CONSTRAINT normalize_failures_reason_check
    CHECK (reason IN (
        'unknown_scenario',
        'unknown_mapping_profile',
        'missing_required',
        'bad_value'
    ));
