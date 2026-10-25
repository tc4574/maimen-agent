import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

from maimen.contracts import Command, Versions
from maimen.fixtures import candidates
from maimen.harness import Rejected
from maimen.providers import FixtureQuoteProvider
from maimen.service import Service
from maimen.store import Store


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store()
        self.service = Service(self.store, timeout=0.01)
        self.sid = self.service.create()["snapshot"]["session_id"]

    def tearDown(self):
        self.store.close()

    def versions(self):
        state = self.service.snapshot(self.sid)
        return Versions(scene_revision=state.scene_revision, plan_revision=state.plan_revision)

    def command(self, action, key="command-1"):
        version = self.versions()
        turn = self.service.begin(self.sid, version)
        return Command(**version.model_dump(), turn_id=turn["turn_id"], command_id=key, action=action)

    async def select(self):
        await self.service.command(self.sid, self.command({"type": "select_card", "ordinal": 2}))

    async def test_repeated_command_returns_receipt_without_new_events(self):
        command = self.command({"type": "select_card", "ordinal": 2})
        first = await self.service.command(self.sid, command)
        events = self.store.events(self.sid)
        self.assertEqual(first, await self.service.command(self.sid, command))
        self.assertEqual(events, self.store.events(self.sid))
        changed = command.model_copy(update={"action": Command(**{**command.model_dump(), "action": {"type": "undo"}}).action})
        with self.assertRaisesRegex(Rejected, "command_id_reused"):
            await self.service.command(self.sid, changed)

    async def test_receipt_failure_rolls_back_business_state(self):
        command = self.command({"type": "select_card", "ordinal": 2})
        before = self.service.harness.state(self.sid)
        self.store.connection.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON command_receipts BEGIN SELECT RAISE(ABORT, 'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.service.command(self.sid, command)
        self.assertEqual(before, self.service.harness.state(self.sid))
        self.assertEqual(before, self.store.replay(self.sid))

    async def test_timeout_and_failure_release_quote_budget(self):
        await self.select()
        class Slow:
            async def calculate(self, ticket):
                await asyncio.sleep(1)
        class Failed:
            async def calculate(self, ticket):
                raise RuntimeError("private provider details")
        for provider, code in [(Slow(), "quote_timeout"), (Failed(), "quote_failed")]:
            self.service.quotes = provider
            with self.assertRaisesRegex(Rejected, code):
                await self.service.quote(self.sid, self.versions())
            self.assertEqual({}, self.service.harness.state(self.sid)["pending_quotes"])
        self.service.quotes = FixtureQuoteProvider()
        self.assertTrue((await self.service.quote(self.sid, self.versions()))["accepted"])

    async def test_cancelled_quote_releases_budget(self):
        await self.select()
        started = asyncio.Event()
        class Slow:
            async def calculate(self, ticket):
                started.set()
                await asyncio.Event().wait()
        self.service.quotes = Slow()
        task = asyncio.create_task(self.service.quote(self.sid, self.versions()))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual({}, self.service.harness.state(self.sid)["pending_quotes"])

    async def test_late_quote_after_edit_is_discarded(self):
        await self.select()
        started, release = asyncio.Event(), asyncio.Event()
        class Delayed:
            async def calculate(self, ticket):
                started.set()
                await release.wait()
                return await FixtureQuoteProvider().calculate(ticket)
        self.service.quotes = Delayed()
        self.service.timeout = 2
        task = asyncio.create_task(self.service.quote(self.sid, self.versions()))
        await started.wait()
        await self.service.command(self.sid, self.command({"type": "replace_item", "from_sku": "demo-drink", "to_sku": "demo-zero"}, "edit"))
        release.set()
        self.assertFalse((await task)["accepted"])
        self.assertIsNone(self.service.snapshot(self.sid).quote)

    async def test_interruption_rejects_late_model(self):
        started, release = asyncio.Event(), asyncio.Event()
        class Model:
            async def propose(self, text, turn, state):
                started.set()
                await release.wait()
                return {"type": "select_card", "ordinal": 1}
        self.service.model = Model()
        self.service.timeout = 2
        task = asyncio.create_task(self.service.command(self.sid, self.command({"type": "text", "text": "选第二张"})))
        await started.wait()
        self.service.harness.interrupt(self.sid)
        release.set()
        with self.assertRaisesRegex(Rejected, "stale_or_invalid_turn"):
            await task
        self.assertIsNone(self.service.snapshot(self.sid).draft)

    async def test_expired_orphan_quotes_are_reaped(self):
        await self.select()
        now = [100.0]
        self.service.harness.clock = lambda: now[0]
        for _ in range(8):
            self.service.harness.request_quote(self.sid)
        now[0] += 61
        self.service.harness.request_quote(self.sid)
        self.assertEqual(1, len(self.service.harness.state(self.sid)["pending_quotes"]))

    async def test_plan_revision_protects_turn(self):
        await self.select()
        context = self.service.harness.begin_turn(self.sid)
        state = self.service.harness.state(self.sid)
        state["plan_revision"] += 1
        self.service.harness._commit(state, "background_edit", {})
        with self.assertRaisesRegex(Rejected, "plan_changed"):
            self.service.harness.apply(context, {"type": "undo"})

    async def test_restart_preserves_auth_and_deduplication(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.db"
            store = Store(path)
            service = Service(store)
            created = service.create()
            sid = created["snapshot"]["session_id"]
            version = Versions(scene_revision=1, plan_revision=0)
            context = service.begin(sid, version)
            command = Command(**version.model_dump(), turn_id=context["turn_id"], command_id="retry", action={"type": "select_card", "ordinal": 1})
            result = await service.command(sid, command)
            store.close()
            store = Store(path)
            try:
                service = Service(store)
                self.assertTrue(service.authorize(sid, created["session_token"]))
                self.assertEqual(result, await service.command(sid, command))
            finally:
                store.close()

    async def test_v1_database_upgrade_preserves_session(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.db"
            old = sqlite3.connect(path)
            sql = Path(__file__).parents[1] / "maimen/migrations/001_initial.sql"
            old.executescript(sql.read_text())
            state = self.service.harness.state(self.sid)
            from maimen.store import encode
            old.execute("INSERT INTO sessions VALUES (?, ?, ?)", (self.sid, state["revision"], encode(state)))
            old.commit()
            old.close()
            upgraded = Store(path)
            try:
                self.assertEqual(state, upgraded.load(self.sid))
                self.assertEqual([(1,), (2,), (3,), (4,)], upgraded.connection.execute("SELECT version FROM schema_versions ORDER BY version").fetchall())
            finally:
                upgraded.close()
