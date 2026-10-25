"""Single-event-loop service; transactions never span provider awaits."""
import asyncio
import hashlib
import hmac
import json
import secrets

from .contracts import CommandResult, Snapshot
from .fixtures import candidates
from .harness import Harness, Rejected
from .providers import FixtureModel, FixtureQuoteProvider
from .store import encode


class Service:
    def __init__(self, store, model=None, quotes=None, timeout=10):
        self.store = store
        self.harness = Harness(store)
        self.model = model or FixtureModel()
        self.quotes = quotes or FixtureQuoteProvider()
        self.timeout = timeout

    def create(self):
        token = secrets.token_urlsafe(32)
        with self.store.transaction():
            sid = self.harness.create()
            self.harness.show_cards(sid, candidates())
            self.store.connection.execute("INSERT INTO session_credentials VALUES (?, ?)",
                                          (sid, hashlib.sha256(token.encode()).hexdigest()))
        return {"session_token": token, "snapshot": self.snapshot(sid).model_dump()}

    def authorize(self, sid, token):
        row = self.store.connection.execute("SELECT token_hash FROM session_credentials WHERE session_id=?", (sid,)).fetchone()
        return bool(row and hmac.compare_digest(row[0], hashlib.sha256(token.encode()).hexdigest()))

    def snapshot(self, sid):
        state = self.harness.state(sid)
        fields = {key: state[key] for key in Snapshot.model_fields if key != "can_undo"}
        return Snapshot(**fields, can_undo=bool(state["undo"]))

    def check_versions(self, sid, expected):
        state = self.harness.state(sid)
        if any(state[key] != getattr(expected, key) for key in ("scene_revision", "plan_revision")):
            raise Rejected("stale_client_versions")
        return state

    def begin(self, sid, expected):
        self.check_versions(sid, expected)
        return self.harness.begin_turn(sid)

    def receipt(self, sid, command):
        row = self.store.connection.execute(
            "SELECT request_json, response_json FROM command_receipts WHERE session_id=? AND command_id=?",
            (sid, command.command_id)).fetchone()
        if row:
            if row[0] != encode(command.model_dump()):
                raise Rejected("command_id_reused")
            return CommandResult.model_validate(json.loads(row[1]))

    async def command(self, sid, command):
        cached = self.receipt(sid, command)
        if cached:
            return cached
        state = self.check_versions(sid, command)
        context = state["turn_context"]
        if not context or context["turn_id"] != command.turn_id:
            raise Rejected("stale_or_invalid_turn")
        action = command.action.model_dump()
        if action["type"] == "text":
            try:
                action = await asyncio.wait_for(self.model.propose(action["text"], context, state), self.timeout)
            except TimeoutError:
                raise Rejected("model_timeout") from None
            except ValueError:
                raise Rejected("unsupported_demo_text") from None
            except Exception:
                raise Rejected("model_failed") from None
        # Another request may have completed while the provider was running.
        cached = self.receipt(sid, command)
        if cached:
            return cached
        with self.store.transaction():
            state = self.check_versions(sid, command)
            if state["turn_context"] != context:
                raise Rejected("stale_or_invalid_turn")
            if command.action.type == "collect":
                self.harness.collect(sid, command.action.name)
                self.harness.interrupt(sid)
            else:
                self.harness.apply(context, action)
            result = CommandResult(command_id=command.command_id, snapshot=self.snapshot(sid))
            self.store.connection.execute("INSERT INTO command_receipts VALUES (?, ?, ?, ?)",
                (sid, command.command_id, encode(command.model_dump()), encode(result.model_dump())))
        return result

    async def quote(self, sid, expected):
        self.check_versions(sid, expected)
        ticket = self.harness.request_quote(sid)
        try:
            result = await asyncio.wait_for(self.quotes.calculate(ticket), self.timeout)
            accepted = self.harness.accept_quote(ticket, result)
        except asyncio.CancelledError:
            self.harness.finish_quote(ticket, "cancelled")
            raise
        except TimeoutError:
            self.harness.finish_quote(ticket, "expired")
            raise Rejected("quote_timeout") from None
        except Exception:
            self.harness.finish_quote(ticket, "failed")
            raise Rejected("quote_failed") from None
        return {"accepted": accepted, "snapshot": self.snapshot(sid).model_dump()}
