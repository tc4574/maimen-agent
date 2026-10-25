"""Atomic snapshot + audit-event persistence; not a network authentication layer."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class ConflictError(RuntimeError):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Store:
    def __init__(self, path=":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path))
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self.connection.execute("PRAGMA journal_mode = WAL")
        schema = Path(__file__).with_name("migrations") / "001_initial.sql"
        self.connection.executescript(schema.read_text(encoding="utf-8"))
        for migration in sorted(schema.parent.glob("*.sql")):
            version = int(migration.name.split("_")[0])
            if not self.connection.execute("SELECT 1 FROM schema_versions WHERE version=?", (version,)).fetchone():
                self.connection.executescript("BEGIN;\n" + migration.read_text(encoding="utf-8")
                                              + f"\nINSERT INTO schema_versions(version) VALUES ({version});\nCOMMIT;")
        self._transaction_index = 0

    @contextmanager
    def transaction(self):
        self._transaction_index += 1
        name = f"unit_{self._transaction_index}"
        self.connection.execute(f"SAVEPOINT {name}")
        try:
            yield
        except BaseException:
            self.connection.execute(f"ROLLBACK TO {name}")
            self.connection.execute(f"RELEASE {name}")
            raise
        else:
            self.connection.execute(f"RELEASE {name}")

    def create(self, state):
        with self.transaction():
            self.connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?)",
                (state["session_id"], 0, encode(state)),
            )
            self.connection.execute(
                "INSERT INTO events(session_id, revision, kind, payload_json, state_json) VALUES (?,0,'created','{}',?)",
                (state["session_id"], encode(state)),
            )

    def load(self, session_id):
        row = self.connection.execute(
            "SELECT state_json FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise KeyError("unknown_session")
        return json.loads(row[0])

    def commit(self, state, kind, payload, expected_revision):
        # A failed optimistic update must not leave a misleading audit event.
        with self.transaction():
            updated = self.connection.execute(
                "UPDATE sessions SET revision=?, state_json=? WHERE session_id=? AND revision=?",
                (state["revision"], encode(state), state["session_id"], expected_revision),
            )
            if updated.rowcount != 1:
                raise ConflictError("concurrent_session_update")
            self.connection.execute(
                "INSERT INTO events(session_id, revision, kind, payload_json, state_json) VALUES (?,?,?,?,?)",
                (state["session_id"], state["revision"], kind, encode(payload), encode(state)),
            )

    def events(self, session_id):
        return [
            {"revision": row[0], "kind": row[1], "payload": json.loads(row[2])}
            for row in self.connection.execute(
                "SELECT revision, kind, payload_json FROM events WHERE session_id=? ORDER BY revision",
                (session_id,),
            )
        ]

    def replay(self, session_id):
        """Restore the last recorded post-state; this is snapshot-log replay."""
        rows = self.connection.execute(
            "SELECT revision, state_json FROM events WHERE session_id=? ORDER BY revision", (session_id,)
        ).fetchall()
        if not rows:
            raise KeyError("unknown_session")
        for expected, (revision, _) in enumerate(rows):
            if revision != expected:
                raise ValueError("audit_revision_gap")
        return json.loads(rows[-1][1])

    def close(self):
        self.connection.close()

