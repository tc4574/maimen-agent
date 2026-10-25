import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from maimen.adapters.mcd import call_smoke_tool, discover
from maimen.mcp_probe import tool_status, write_private_report


class ProbeTests(unittest.TestCase):
    def test_business_failure_is_not_successful_transport(self):
        for payload in ({"success": False, "code": 401}, {"success": True, "code": 500}):
            with self.subTest(payload=payload):
                result = SimpleNamespace(is_error=False, structured_content=payload)
                self.assertEqual(tool_status(result), "business_error")

    def test_missing_business_envelope_is_unverified(self):
        result = SimpleNamespace(is_error=False, structured_content={"data": "ambiguous"})
        self.assertEqual(tool_status(result), "unverified_response")

    def test_report_redacts_credential_even_if_server_echoes_it(self):
        secret = "unit-test-fake-credential"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            write_private_report(path, {"error": "echo " + secret, "nested": [secret]}, secret)
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(secret, text)
            self.assertEqual(json.loads(text)["nested"], ["[REDACTED]"])


class ProbeBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_mutating_tool_is_rejected_before_remote_call(self):
        client = SimpleNamespace(call_tool=AsyncMock())
        with self.assertRaisesRegex(ValueError, "read-only"):
            await call_smoke_tool(client, "create-order", {}, [])
        client.call_tool.assert_not_awaited()

    async def test_repeated_cursor_cannot_loop_forever(self):
        page = SimpleNamespace(tools=[], next_cursor="same")
        client = SimpleNamespace(list_tools=AsyncMock(return_value=page))
        with self.assertRaisesRegex(ValueError, "Repeated"):
            await discover(client)
        self.assertEqual(client.list_tools.await_count, 2)
