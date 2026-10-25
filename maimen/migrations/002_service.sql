CREATE TABLE session_credentials (
    session_id TEXT PRIMARY KEY REFERENCES sessions(session_id),
    token_hash TEXT NOT NULL
);
CREATE TABLE command_receipts (
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    command_id TEXT NOT NULL,
    request_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    PRIMARY KEY(session_id, command_id)
);
