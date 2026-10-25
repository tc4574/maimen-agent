import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from maimen.api import create_app
from test_recommender import Provider, NOW
from maimen.recommender import Recommender


class RecommendationAPITests(unittest.TestCase):
    def test_disabled_and_unauthenticated_requests_do_not_connect(self):
        with TestClient(create_app(":memory:")) as client:
            created = client.post("/api/sessions", json={}).json()
            url = "/api/sessions/" + created["snapshot"]["session_id"] + "/recommendations"
            self.assertEqual(401, client.post(url, json={}).status_code)
            response = client.post(url, json={}, headers={"Authorization": "Bearer " + created["session_token"]})
            self.assertEqual(503, response.status_code)

    def test_restart_feedback_preserves_constraints_and_enforces_ownership(self):
        requests = []
        async def runner(req):
            requests.append(req)
            return await Recommender(Provider(), clock=lambda: NOW).recommend(req)
        with tempfile.TemporaryDirectory() as folder:
            database = str(Path(folder) / "test.db")
            with TestClient(create_app(database, live_enabled=True, recommendation_runner=runner)) as client:
                created = client.post("/api/sessions", json={}).json()
                headers = {"Authorization": "Bearer " + created["session_token"]}
                url = "/api/sessions/" + created["snapshot"]["session_id"]
                before = client.get(url, headers=headers).json()
                response = client.post(url + "/recommendations", headers=headers,
                                       json={"budget_cents": 2000, "max_energy_kcal": 450})
                self.assertEqual(200, response.status_code, response.text)
                first = response.json()
                self.assertEqual(before, client.get(url, headers=headers).json())
            with TestClient(create_app(database, live_enabled=True, recommendation_runner=runner)) as client:
                response = client.post(url + "/recommendations/feedback", headers=headers, json={
                    "run_id": first["run_id"], "changes": {"keep_codes": ["beef"]}})
                self.assertEqual(200, response.status_code, response.text)
                self.assertEqual(1, len(response.json()["cards"]))
                self.assertEqual(2000, requests[-1].budget_cents)
                self.assertEqual(450, requests[-1].max_energy_kcal)
                self.assertEqual("no_sugar", requests[-1].drink)
                other = client.post("/api/sessions", json={}).json()
                other_url = "/api/sessions/" + other["snapshot"]["session_id"] + "/recommendations/feedback"
                response = client.post(other_url, headers={"Authorization": "Bearer " + other["session_token"]},
                                       json={"run_id": first["run_id"]})
                self.assertEqual(404, response.status_code)

    def test_provider_failure_is_stable_error_without_private_details(self):
        async def failed(req):
            raise RuntimeError("private-server-details")
        with TestClient(create_app(":memory:", live_enabled=True, recommendation_runner=failed)) as client:
            created = client.post("/api/sessions", json={}).json()
            response = client.post("/api/sessions/" + created["snapshot"]["session_id"] + "/recommendations",
                headers={"Authorization": "Bearer " + created["session_token"]}, json={})
            self.assertEqual(502, response.status_code)
            self.assertNotIn("private-server-details", response.text)
