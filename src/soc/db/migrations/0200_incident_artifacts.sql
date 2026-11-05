CREATE TABLE incident_artifacts (
    id text PRIMARY KEY,
    incident_id text NOT NULL REFERENCES incidents (id),
    analysis_round integer NOT NULL CHECK (analysis_round >= 1),
    verdict text NOT NULL CHECK (
        verdict IN ('not_threat', 'attempted', 'succeeded', 'inconclusive')
    ),
    summary text NOT NULL CHECK (summary <> ''),
    assessed_severity smallint NOT NULL CHECK (assessed_severity BETWEEN 0 AND 6),
    timeline jsonb NOT NULL CHECK (jsonb_typeof(timeline) = 'array'),
    techniques jsonb NOT NULL CHECK (jsonb_typeof(techniques) = 'array'),
    impact text NOT NULL,
    cause text NOT NULL,
    further_risk text NOT NULL,
    evidence_ids text[] NOT NULL CHECK (array_position(evidence_ids, NULL) IS NULL),
    created_at timestamptz NOT NULL,
    UNIQUE (incident_id, analysis_round)
);

CREATE INDEX incident_artifacts_incident_idx ON incident_artifacts (incident_id);

CREATE TABLE incident_proposals (
    id text PRIMARY KEY,
    artifact_id text NOT NULL REFERENCES incident_artifacts (id),
    kind text NOT NULL CHECK (kind IN ('detection_rule', 'response_action')),
    seq integer NOT NULL CHECK (seq >= 1),
    body text NOT NULL CHECK (body <> ''),
    created_at timestamptz NOT NULL,
    UNIQUE (artifact_id, kind, seq)
);

CREATE INDEX incident_proposals_artifact_idx ON incident_proposals (artifact_id);
