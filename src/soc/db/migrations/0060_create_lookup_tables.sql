-- Box 5 (#60): Lookup tables (C4). Loaded whole from CSV; RDB only (D-002).
-- A row is valid for valid_from <= at < valid_to; null is an open end.

-- C4 AssetInfo. match is the text as loaded; network is the same value as cidr
-- (an IP becomes /32 or /128) so containment can be searched.
CREATE TABLE lookup_assets (
    id bigserial PRIMARY KEY,
    match text NOT NULL,
    network cidr NOT NULL,
    hostname text NOT NULL,
    criticality smallint NOT NULL CONSTRAINT lookup_assets_criticality
        CHECK (criticality BETWEEN 1 AND 5),
    owner text,
    zone text,
    shared boolean NOT NULL,
    valid_from bigint,
    valid_to bigint,
    extensions jsonb NOT NULL,
    CONSTRAINT lookup_assets_valid_range
        CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_to > valid_from)
);

CREATE INDEX lookup_assets_network ON lookup_assets USING gist (network inet_ops);
CREATE INDEX lookup_assets_hostname ON lookup_assets (lower(hostname));

-- C4 UserInfo. valid_from and valid_to are table columns only; UserInfo has no such fields.
CREATE TABLE lookup_users (
    id bigserial PRIMARY KEY,
    user_name text NOT NULL,
    dept text,
    privileged boolean NOT NULL,
    valid_from bigint,
    valid_to bigint,
    extensions jsonb NOT NULL,
    CONSTRAINT lookup_users_valid_range
        CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_to > valid_from)
);

CREATE INDEX lookup_users_user_name ON lookup_users (user_name);
