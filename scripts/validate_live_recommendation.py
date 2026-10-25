"""Explicit live, read-only API acceptance: recommend then keep a main item."""
import json
import sys
from pathlib import Path

# Script works when launched from the repository root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from maimen.api import create_app


def main():
    if sys.argv[1:] != ["--live"]:
        raise SystemExit("Use --live to explicitly allow real read-only MCP queries.")
    root = Path("artifacts/local")
    root.mkdir(parents=True, exist_ok=True)
    request = json.loads(Path("examples/recommendation.json").read_text(encoding="utf-8"))
    with TestClient(create_app("data/recommendation-acceptance.sqlite3", live_enabled=True)) as client:
        created = client.post("/api/sessions", json={}).json()
        headers = {"Authorization": "Bearer " + created["session_token"]}
        url = "/api/sessions/" + created["snapshot"]["session_id"] + "/recommendations"
        response = client.post(url, json=request, headers=headers)
        if response.status_code != 200:
            raise SystemExit("Initial recommendation failed: " + str(response.status_code))
        first = response.json()
        (root / "recommendation-api-first.json").write_text(json.dumps(first, ensure_ascii=False, indent=2), encoding="utf-8")
        if not first["cards"]:
            raise SystemExit("No initial candidates; inspect local report.")
        main = next(i for i in first["cards"][0]["components"] if i["category"] in {"burger", "chicken"})
        response = client.post(url + "/feedback", headers=headers,
            json={"run_id": first["run_id"], "changes": {"keep_codes": [main["code"]]}})
        if response.status_code != 200:
            raise SystemExit("Feedback failed: " + str(response.status_code))
        second = response.json()
        (root / "recommendation-api-feedback.json").write_text(json.dumps(second, ensure_ascii=False, indent=2), encoding="utf-8")
        assert second["cards"], "No candidates preserved the selected main"
        for card in first["cards"] + second["cards"]:
            assert card["amount_cents"] <= request["budget_cents"]
            assert card["nutrition"]["totals"]["protein_g"] >= request["min_protein_g"]
            assert card["nutrition"]["totals"]["energy_kcal"] <= request["max_energy_kcal"]
        for card in second["cards"]:
            assert main["code"] in [i["code"] for i in card["components"]]
        print(json.dumps({"initial_status": first["status"], "initial_cards": [
            {"foods": [i["name"] for i in card["components"]], "price_cents": card["amount_cents"],
             "nutrition": card["nutrition"]["totals"]} for card in first["cards"]],
            "feedback_status": second["status"], "kept": main["name"], "feedback_count": len(second["cards"]),
            "constraints_preserved": all(second["request"][k] == request[k] for k in request if k != "seed"),
            "coupon_status": first["coupon_status"], "tool_calls": [len(first["tool_calls"]), len(second["tool_calls"])]},
            ensure_ascii=False, indent=2))


if __name__ == "__main__":
    import logging
    logging.disable(logging.CRITICAL)
    main()
