-- 사용자 계정·세션·권한(#284, D-020). API 전용 테이블이라 contracts/의 계약이 아니다.
-- soc_agent_reader에는 권한을 주지 않는다(0003). 에이전트 도구는 이 테이블을 읽지 못한다.
-- id는 계약 밖 UUID다(ids.py의 접두사 ID를 쓰지 않는다).
-- 세션 토큰 원문은 저장하지 않고 SHA-256(hex)만 둔다. 비밀번호는 Argon2id 해시(D-047)만 둔다.

CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    username text NOT NULL UNIQUE CHECK (username ~ '^[a-z0-9._-]{3,64}$'),
    display_name text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 100),
    password_hash text NOT NULL,
    -- 승인 전(pending)과 거절(rejected)에는 역할이 없다
    role text CHECK (role IN ('admin', 'analyst')),
    status text NOT NULL CHECK (status IN ('pending', 'active', 'rejected', 'disabled')),
    must_change_password boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_at timestamptz,
    approved_by uuid REFERENCES users (id),
    CHECK ((status IN ('active', 'disabled')) = (role IS NOT NULL))
);

CREATE TABLE user_sessions (
    token_hash text PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

CREATE INDEX user_sessions_user_id ON user_sessions (user_id);

-- admin은 행 없이 모든 권한을 갖는다. 권한 이름은 코드의 목록(soc.auth.permissions)에서만 받는다
CREATE TABLE user_permissions (
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    permission text NOT NULL,
    granted_by uuid REFERENCES users (id),
    granted_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, permission)
);
