import copy
import tempfile
import unittest
from pathlib import Path

from maimen.fixtures import candidates
from maimen.harness import Harness, Rejected
from maimen.providers import QuoteResult
from maimen.store import ConflictError, Store


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.now = 1000.0
        self.harness = Harness(self.store, clock=lambda: self.now)
        self.session = self.harness.create()
        self.harness.show_cards(self.session, candidates())
        self.command({"type": "select_card", "ordinal": 2})

    def tearDown(self):
        self.store.close()

    def command(self, operation):
        return self.harness.apply(self.harness.begin_turn(self.session), operation)

    def quote(self):
        ticket = self.harness.request_quote(self.session)
        self.harness.accept_quote(ticket, QuoteResult(2400, "demo", "test-fixture"))
        return ticket

    def replace(self):
        self.command({"type": "replace_item", "from_sku": "demo-drink", "to_sku": "demo-zero"})

    def test_replacement_preserves_other_items(self):
        before = self.harness.state(self.session)["draft"]["items"]
        self.replace()
        after = self.harness.state(self.session)["draft"]["items"]
        self.assertEqual(before[:2], after[:2])
        self.assertEqual(after[2], {"sku": "demo-zero", "quantity": 1})

    def test_late_quote_after_edit_cannot_be_used(self):
        ticket = self.harness.request_quote(self.session)
        self.replace()
        self.assertFalse(self.harness.accept_quote(ticket, QuoteResult(1, "demo", "stale")))
        self.assertIsNone(self.harness.state(self.session)["quote"])

    def test_undo_restores_food_but_not_old_quote_or_approval(self):
        ticket = self.quote()
        self.harness.confirm(self.session, ticket["id"])
        original = self.harness.state(self.session)["draft"]
        self.replace()
        self.command({"type": "undo"})
        restored = self.harness.state(self.session)
        self.assertEqual(restored["draft"], original)
        self.assertIsNone(restored["quote"])
        self.assertIsNone(restored["approval"])
        with self.assertRaises(Rejected):
            self.harness.checkout_preview(self.session)

    def test_old_scene_reference_rejected(self):
        turn = self.harness.begin_turn(self.session)
        self.harness.show_cards(self.session, list(reversed(candidates())))
        with self.assertRaisesRegex(Rejected, "scene_changed"):
            self.harness.apply(turn, {"type": "select_card", "ordinal": 2})

    def test_changed_scene_payload_cannot_change_ordinal_mapping(self):
        turn = self.harness.begin_turn(self.session)
        turn["card_ids"].reverse()
        with self.assertRaises(Rejected):
            self.harness.apply(turn, {"type": "select_card", "ordinal": 1})

    def test_interrupt_rejects_pending_model_proposal_and_quote(self):
        turn = self.harness.begin_turn(self.session)
        ticket = self.harness.request_quote(self.session)
        self.harness.interrupt(self.session)
        with self.assertRaises(Rejected):
            self.harness.apply(turn, {"type": "select_card", "ordinal": 1})
        self.assertFalse(self.harness.accept_quote(ticket, QuoteResult(1, "demo", "stale")))

    def test_store_change_rejects_old_store_quote(self):
        ticket = self.harness.request_quote(self.session)
        self.harness.change_store(self.session, "demo-store-b")
        self.assertFalse(self.harness.accept_quote(ticket, QuoteResult(1, "demo", "old-store")))
        self.assertIsNone(self.harness.state(self.session)["draft"])

    def test_hallucinated_sku_does_not_mutate_draft(self):
        turn = self.harness.begin_turn(self.session)
        before = self.harness.state(self.session)
        with self.assertRaises(Rejected):
            self.harness.apply(turn, {"type": "replace_item", "from_sku": "demo-drink", "to_sku": "invented"})
        self.assertEqual(before, self.harness.state(self.session))

    def test_agent_cannot_confirm_or_create_order(self):
        for kind in ("confirm", "create-order", "execute_python"):
            with self.assertRaises(Rejected):
                self.command({"type": kind})

    def test_duplicate_operation_rejected(self):
        turn = self.harness.begin_turn(self.session)
        operation = {"type": "select_card", "ordinal": 1}
        self.harness.apply(turn, operation)
        with self.assertRaises(Rejected):
            self.harness.apply(turn, operation)

    def test_quote_requires_separate_matching_confirmation(self):
        ticket = self.quote()
        with self.assertRaises(Rejected):
            self.harness.checkout_preview(self.session)
        with self.assertRaises(Rejected):
            self.harness.confirm(self.session, "wrong-quote")
        self.harness.confirm(self.session, ticket["id"])
        self.assertEqual(self.harness.checkout_preview(self.session)["status"], "demo_only_no_order_created")

    def test_quote_expires_even_after_confirmation(self):
        ticket = self.quote()
        self.harness.confirm(self.session, ticket["id"])
        self.now += 61
        with self.assertRaisesRegex(Rejected, "valid_quote"):
            self.harness.checkout_preview(self.session)

    def test_newer_quote_request_wins_even_if_draft_is_identical(self):
        old = self.harness.request_quote(self.session)
        new = self.harness.request_quote(self.session)
        self.assertTrue(self.harness.accept_quote(new, QuoteResult(2500, "demo", "new")))
        self.assertFalse(self.harness.accept_quote(old, QuoteResult(100, "demo", "old")))
        self.assertEqual(self.harness.state(self.session)["quote"]["amount_cents"], 2500)

    def test_quote_source_must_match_mode(self):
        ticket = self.harness.request_quote(self.session)
        with self.assertRaises(Rejected):
            self.harness.accept_quote(ticket, QuoteResult(1, "live", "not-a-live-receipt"))

    def test_quote_ticket_cannot_cross_sessions_or_change_items(self):
        ticket = self.harness.request_quote(self.session)
        altered = copy.deepcopy(ticket)
        altered["session_id"] = self.harness.create()
        with self.assertRaises(Rejected):
            self.harness.accept_quote(altered, QuoteResult(1, "demo", "fixture"))
        altered = copy.deepcopy(ticket)
        altered["items"][0]["quantity"] = 10
        with self.assertRaises(Rejected):
            self.harness.accept_quote(altered, QuoteResult(1, "demo", "fixture"))

    def test_duplicate_quote_response_rejected(self):
        ticket = self.quote()
        with self.assertRaises(Rejected):
            self.harness.accept_quote(ticket, QuoteResult(1, "demo", "duplicate"))

    def test_optimistic_write_conflict_leaves_no_audit_event(self):
        stale = self.harness.state(self.session)
        self.harness.begin_turn(self.session)
        count = len(self.store.events(self.session))
        stale["revision"] += 1
        with self.assertRaises(ConflictError):
            self.store.commit(stale, "stale_writer", {}, stale["revision"] - 1)
        self.assertEqual(len(self.store.events(self.session)), count)

    def test_pending_quote_budget_is_bounded(self):
        for _ in range(8):
            self.harness.request_quote(self.session)
        with self.assertRaisesRegex(Rejected, "budget"):
            self.harness.request_quote(self.session)


class PersistenceTests(unittest.TestCase):
    def test_restart_recovers_collection_and_audit_without_price_in_recipe(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "test.sqlite3"
            store = Store(database)
            h = Harness(store)
            sid = h.create()
            h.show_cards(sid, candidates())
            h.apply(h.begin_turn(sid), {"type": "select_card", "ordinal": 1})
            h.collect(sid, "周五餐")
            expected = h.state(sid)
            store.close()
            reopened = Store(database)
            try:
                self.assertEqual(reopened.load(sid), expected)
                self.assertEqual(reopened.replay(sid), expected)
                recipe = expected["collections"][0]
                self.assertEqual(recipe["kind"], "favorite_recipe")
                self.assertNotIn("price", recipe)
                self.assertNotIn("consumed", recipe)
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
