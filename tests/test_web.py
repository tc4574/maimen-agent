"""Verify the static app shares the guarded API origin without exposing config."""
import tempfile
import unittest
from fastapi.testclient import TestClient
from maimen.api import create_app


class WebTests(unittest.TestCase):
    def test_pages_and_capabilities(self):
        with tempfile.TemporaryDirectory() as directory:
            with TestClient(create_app(f"{directory}/web.sqlite3", live_enabled=False)) as client:
                page = client.get("/")
                self.assertEqual(page.status_code, 200)
                self.assertIn('id="bot"', page.text)
                self.assertEqual(client.get('/app.js').status_code, 200)
                self.assertFalse(client.get('/api/capabilities').json()['recommendations'])
                self.assertEqual(client.get('/.env').status_code, 404)
                self.assertEqual(client.get('/api/capabilities', headers={'Origin':'https://example.com'}).status_code, 403)
