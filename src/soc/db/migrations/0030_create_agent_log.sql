CREATE TABLE agent_steps (
    subject_type text NOT NULL CHECK (subject_type IN ('alert', 'ticket', 'incident', 'hunt')),
    subject_id text NOT NULL,
    step integer NOT NULL CHECK (step >= 1),
    created_at bigint NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    PRIMARY KEY (subject_type, subject_id, step)
);

CREATE INDEX agent_steps_subject_chronological_idx
    ON agent_steps (subject_type, subject_id, created_at, step);

CREATE TABLE agent_step_artifacts (
    subject_type text NOT NULL,
    subject_id text NOT NULL,
    step integer NOT NULL,
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    artifact_path text NOT NULL,
    PRIMARY KEY (subject_type, subject_id, step),
    FOREIGN KEY (subject_type, subject_id, step)
        REFERENCES agent_steps (subject_type, subject_id, step)
        ON DELETE CASCADE
);
