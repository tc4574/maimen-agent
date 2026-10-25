CREATE TABLE assistant_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    role TEXT NOT NULL,
    content TEXT NOT NULL
);
CREATE INDEX assistant_messages_session ON assistant_messages(session_id, id);
CREATE TABLE assistant_receipts (
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    request_id TEXT NOT NULL,
    request_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    PRIMARY KEY(session_id, request_id)
);
