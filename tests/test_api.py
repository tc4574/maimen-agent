import unittest
from fastapi.testclient import TestClient
from maimen.api import create_app


class APITests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(":memory:"))
        self.client.__enter__()
        created = self.client.post("/api/sessions", json={}).json()
        self.state = created["snapshot"]
        self.url = "/api/sessions/" + self.state["session_id"]
        self.headers = {"Authorization": "Bearer " + created["session_token"]}

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def act(self, action, key):
        version = {k: self.state[k] for k in ("scene_revision", "plan_revision")}
        turn = self.client.post(self.url + "/turns", json=version, headers=self.headers).json()
        response = self.client.post(self.url + "/commands", headers=self.headers,
            json={**version, "turn_id": turn["turn_id"], "command_id": key, "action": action})
        self.assertEqual(200, response.status_code, response.text)
        self.state = response.json()["snapshot"]

    def test_full_text_edit_undo_collect_flow(self):
        self.act({"type": "text", "text": "选第二张"}, "select")
        original = self.state["draft"]
        self.act({"type": "text", "text": "饮料换无糖"}, "replace")
        self.assertEqual("demo-zero", self.state["draft"]["items"][2]["sku"])
        self.act({"type": "text", "text": "撤回上一步"}, "undo")
        self.assertEqual(original, self.state["draft"])
        self.act({"type": "collect", "name": "周五快乐餐"}, "favorite")
        self.assertEqual(1, len(self.state["collections"]))
        self.assertEqual(self.state, self.client.get(self.url, headers=self.headers).json())
        version = {k: self.state[k] for k in ("scene_revision", "plan_revision")}
        quote = self.client.post(self.url + "/quotes", json=version, headers=self.headers).json()
        self.assertTrue(quote["accepted"])
        self.assertEqual(2400, quote["snapshot"]["quote"]["amount_cents"])

    def test_session_auth_and_cross_origin(self):
        self.assertEqual(401, self.client.get(self.url).status_code)
        self.assertEqual(401, self.client.get(self.url, headers={"Authorization": "Bearer wrong"}).status_code)
        self.assertEqual(403, self.client.post("/api/sessions", json={}, headers={"Origin": "https://untrusted.example"}).status_code)

    def test_invalid_input_and_stale_versions(self):
        self.assertEqual(422, self.client.post("/api/sessions", json={"mode": "live"}).status_code)
        response = self.client.post(self.url + "/turns", headers=self.headers, json={"scene_revision": 0, "plan_revision": 0})
        self.assertEqual("stale_client_versions", response.json()["error"]["code"])

    def test_event_cursor_does_not_repeat_history(self):
        self.act({"type": "select_card", "ordinal": 1}, "select")
        events = self.client.get(self.url + "/events", headers=self.headers).json()
        after = events[-1]["sequence"]
        self.assertEqual([], self.client.get(self.url + f"/events?after={after}", headers=self.headers).json())
