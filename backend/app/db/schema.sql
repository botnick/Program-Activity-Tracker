CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    exe_path   TEXT NOT NULL,
    pid        INTEGER NOT NULL,
    pid_create_time REAL,
    created_at TEXT NOT NULL,
    status     TEXT NOT NULL,
    capture    TEXT NOT NULL,
    capture_error TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    ts           TEXT NOT NULL,
    kind         TEXT NOT NULL,
    pid          INTEGER,
    ppid         INTEGER,
    path         TEXT,
    target       TEXT,
    operation    TEXT,
    details_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_session_ts   ON events (session_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_session_kind ON events (session_id, kind);
CREATE INDEX IF NOT EXISTS idx_events_session_pid  ON events (session_id, pid);
