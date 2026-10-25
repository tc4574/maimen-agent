"""Deterministic offline harness: scene binding, revisions, quote gates and undo.

No remote calls, credentials, checkout implementation or browser authentication.
"""
import copy
import hashlib
import time
import uuid

from .fixtures import CATALOG
from .store import encode


class Rejected(ValueError):
    pass


def fresh_id():
    return uuid.uuid4().hex


class Harness:
    def __init__(self, store, clock=time.time):
        self.store = store
        self.clock = clock

    def create(self, store_id="demo-store-a"):
        if store_id not in {"demo-store-a", "demo-store-b"}:
            raise Rejected("unknown_demo_store")
        state = {
            "session_id": fresh_id(), "revision": 0, "mode": "demo", "store_id": store_id,
            "plan_revision": 0, "scene_revision": 0, "turn_id": None, "turn_context": None,
            "cards": [], "draft": None, "undo": [], "quote": None, "approval": None,
            "pending_quotes": {}, "latest_quote_request": None, "collections": [],
        }
        self.store.create(state)
        return state["session_id"]

    def state(self, session_id):
        return self.store.load(session_id)

    def _commit(self, state, kind, payload):
        previous = state["revision"]
        state["revision"] += 1
        self.store.commit(state, kind, payload, previous)

    @staticmethod
    def _validate_items(items):
        if not isinstance(items, list) or not 1 <= len(items) <= 12:
            raise Rejected("invalid_item_count")
        for item in items:
            if not isinstance(item, dict) or set(item) != {"sku", "quantity"}:
                raise Rejected("invalid_item_schema")
            if not isinstance(item["sku"], str) or item["sku"] not in CATALOG:
                raise Rejected("unknown_demo_sku")
            if type(item["quantity"]) is not int or not 1 <= item["quantity"] <= 10:
                raise Rejected("invalid_quantity")

    @staticmethod
    def _invalidate(state):
        state["plan_revision"] += 1
        state["quote"] = None
        state["approval"] = None
        state["latest_quote_request"] = None

    @staticmethod
    def _fingerprint(state):
        return hashlib.sha256(encode({
            "session_id": state["session_id"], "mode": state["mode"], "store_id": state["store_id"],
            "plan_revision": state["plan_revision"], "draft": state["draft"],
        }).encode("utf-8")).hexdigest()

    def show_cards(self, session_id, candidates):
        if not isinstance(candidates, list) or not 1 <= len(candidates) <= 3:
            raise Rejected("one_to_three_candidates_required")
        state = self.state(session_id)
        cards = []
        for candidate in candidates:
            if not isinstance(candidate, dict) or set(candidate) != {"label", "items"}:
                raise Rejected("invalid_candidate_schema")
            if not isinstance(candidate.get("label"), str) or not 1 <= len(candidate["label"]) <= 80:
                raise Rejected("invalid_card_label")
            self._validate_items(candidate["items"])
            cards.append({"id": fresh_id(), "label": candidate["label"], "items": copy.deepcopy(candidate["items"])})
        state["cards"] = cards
        state["scene_revision"] += 1
        self._commit(state, "scene_presented", {"card_ids": [c["id"] for c in cards]})
        return copy.deepcopy(cards)

    def begin_turn(self, session_id):
        state = self.state(session_id)
        context = {"session_id": session_id, "turn_id": fresh_id(), "scene_revision": state["scene_revision"],
                   "plan_revision": state["plan_revision"],
                   "card_ids": [c["id"] for c in state["cards"]]}
        state["turn_id"] = context["turn_id"]
        state["turn_context"] = context
        self._commit(state, "turn_started", context)
        return copy.deepcopy(context)

    def interrupt(self, session_id):
        state = self.state(session_id)
        state["turn_id"] = None
        state["turn_context"] = None
        self._commit(state, "turn_interrupted", {})

    def apply(self, context, operation):
        state = self.state(context["session_id"])
        if state["turn_context"] != context or context["turn_id"] != state["turn_id"]:
            raise Rejected("stale_or_invalid_turn")
        if state["scene_revision"] != context["scene_revision"]:
            raise Rejected("scene_changed_during_turn")
        if state["plan_revision"] != context.get("plan_revision"):
            raise Rejected("plan_changed_during_turn")
        if not isinstance(operation, dict):
            raise Rejected("invalid_operation")
        kind = operation.get("type")
        fields = {
            "select_card": {"type", "ordinal"},
            "replace_item": {"type", "from_sku", "to_sku"},
            "undo": {"type"},
        }
        if not isinstance(kind, str) or kind not in fields or set(operation) != fields[kind]:
            raise Rejected("operation_not_allowed_or_invalid")

        if kind == "select_card":
            ordinal = operation["ordinal"]
            if type(ordinal) is not int or not 1 <= ordinal <= len(context["card_ids"]):
                raise Rejected("invalid_card_reference")
            selected_id = context["card_ids"][ordinal - 1]
            card = next(c for c in state["cards"] if c["id"] == selected_id)
            if state["draft"]:
                state["undo"].append(copy.deepcopy(state["draft"]))
            state["draft"] = copy.deepcopy(card)
        elif kind == "replace_item":
            if not state["draft"]:
                raise Rejected("select_a_card_first")
            source, target = operation["from_sku"], operation["to_sku"]
            if not isinstance(source, str) or not isinstance(target, str) or source not in CATALOG or target not in CATALOG:
                raise Rejected("unknown_demo_sku")
            if source == target:
                raise Rejected("replacement_has_no_effect")
            if CATALOG[source]["category"] != CATALOG[target]["category"]:
                raise Rejected("fixture_category_mismatch")
            if sum(i["sku"] == source for i in state["draft"]["items"]) != 1:
                raise Rejected("ambiguous_or_missing_item")
            state["undo"].append(copy.deepcopy(state["draft"]))
            for item in state["draft"]["items"]:
                if item["sku"] == source:
                    item["sku"] = target
        else:
            if not state["undo"]:
                raise Rejected("nothing_to_undo")
            state["draft"] = state["undo"].pop()
        state["undo"] = state["undo"][-20:]
        self._invalidate(state)
        # One operation per model proposal in this prototype; duplicate execution is rejected.
        state["turn_context"] = None
        self._commit(state, "operation_applied", operation)
        return copy.deepcopy(state["draft"])

    def change_store(self, session_id, store_id):
        if store_id not in {"demo-store-a", "demo-store-b"}:
            raise Rejected("unknown_demo_store")
        state = self.state(session_id)
        state.update(store_id=store_id, cards=[], draft=None, undo=[], turn_id=None, turn_context=None)
        state["scene_revision"] += 1
        self._invalidate(state)
        self._commit(state, "store_changed", {"store_id": store_id})

    def request_quote(self, session_id):
        self.expire_quotes(session_id)
        state = self.state(session_id)
        if not state["draft"]:
            raise Rejected("no_draft")
        if len(state["pending_quotes"]) >= 8:
            raise Rejected("pending_quote_budget_exceeded")
        ticket = {"id": fresh_id(), "session_id": session_id, "mode": state["mode"],
                  "store_id": state["store_id"], "plan_revision": state["plan_revision"],
                  "fingerprint": self._fingerprint(state), "turn_id": state["turn_id"],
                  "items": copy.deepcopy(state["draft"]["items"]), "requested_at": self.clock()}
        state["pending_quotes"][ticket["id"]] = ticket
        state["latest_quote_request"] = ticket["id"]
        # Once a fresh quote is requested, a previous approval cannot authorize its result.
        state["quote"] = None
        state["approval"] = None
        self._commit(state, "quote_requested", {"ticket_id": ticket["id"]})
        return copy.deepcopy(ticket)

    def finish_quote(self, ticket, reason):
        if reason not in {"failed", "cancelled", "expired"}:
            raise Rejected("invalid_quote_terminal_reason")
        state = self.state(ticket["session_id"])
        stored = state["pending_quotes"].get(ticket["id"])
        if stored is None:
            return False
        if stored != ticket:
            raise Rejected("unknown_or_modified_quote_ticket")
        del state["pending_quotes"][ticket["id"]]
        if state["latest_quote_request"] == ticket["id"]:
            state["latest_quote_request"] = None
        self._commit(state, "quote_" + reason, {"ticket_id": ticket["id"]})
        return True

    def expire_quotes(self, session_id):
        for ticket in self.state(session_id)["pending_quotes"].values():
            if not 0 <= self.clock() - ticket["requested_at"] <= 60:
                self.finish_quote(ticket, "expired")

    def accept_quote(self, ticket, result):
        state = self.state(ticket["session_id"])
        stored = state["pending_quotes"].get(ticket["id"])
        if stored != ticket:
            raise Rejected("unknown_or_modified_quote_ticket")
        del state["pending_quotes"][ticket["id"]]
        fresh = (ticket["fingerprint"] == self._fingerprint(state)
                 and ticket["id"] == state["latest_quote_request"]
                 and ticket["turn_id"] == state["turn_id"]
                 and 0 <= self.clock() - ticket["requested_at"] <= 60)
        if not fresh:
            self._commit(state, "quote_discarded", {"ticket_id": ticket["id"], "reason": "stale"})
            return False
        if result.source != state["mode"] or type(result.amount_cents) is not int or result.amount_cents < 0:
            raise Rejected("invalid_quote_source_or_amount")
        state["quote"] = {"id": ticket["id"], "fingerprint": ticket["fingerprint"],
                          "amount_cents": result.amount_cents, "source": result.source,
                          "evidence_id": result.evidence_id, "expires_at": self.clock() + 60}
        state["approval"] = None
        self._commit(state, "quote_accepted", {"quote_id": ticket["id"], "amount_cents": result.amount_cents})
        return True

    def _valid_quote(self, state):
        quote = state["quote"]
        if (not quote or quote["fingerprint"] != self._fingerprint(state)
                or self.clock() >= quote["expires_at"]):
            raise Rejected("current_valid_quote_required")
        return quote

    def confirm(self, session_id, quote_id):
        """UI/user confirmation boundary. This action is never exposed to ModelProvider."""
        state = self.state(session_id)
        quote = self._valid_quote(state)
        if quote["id"] != quote_id:
            raise Rejected("confirmation_quote_mismatch")
        state["approval"] = {"quote_id": quote_id, "fingerprint": quote["fingerprint"]}
        self._commit(state, "demo_quote_confirmed", {"quote_id": quote_id})

    def checkout_preview(self, session_id):
        state = self.state(session_id)
        quote = self._valid_quote(state)
        if state["approval"] != {"quote_id": quote["id"], "fingerprint": quote["fingerprint"]}:
            raise Rejected("explicit_confirmation_required")
        return {"status": "demo_only_no_order_created", "source": "demo", "amount_cents": quote["amount_cents"],
                "items": state["draft"]["items"], "payment_url": None}

    def collect(self, session_id, name):
        state = self.state(session_id)
        if not state["draft"] or not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
            raise Rejected("draft_and_short_name_required")
        entry = {"id": fresh_id(), "name": name.strip(), "source": "demo", "kind": "favorite_recipe",
                 "items": copy.deepcopy(state["draft"]["items"])}
        state["collections"].append(entry)
        self._commit(state, "recipe_collected", {"collection_id": entry["id"]})
        return entry

