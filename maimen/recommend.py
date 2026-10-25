"""CLI and live connection boundary for the structured recommendation engine."""
import argparse
import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path

from .adapters.mcd import connect, discover, load_token
from .adapters.menu import PickupMenu
from .mcp_probe import safe_error_types, write_private_report
from .recommendation_contracts import RecommendationRequest
from .recommender import Recommender


class BoundedProvider:
    def __init__(self, provider, calls, limit=80):
        self.provider, self.calls, self.limit = provider, calls, limit

    async def _invoke(self, name, *args):
        if len(self.calls) >= self.limit:
            raise ValueError("recommendation_tool_budget_exceeded")
        record = {"method": name, "arguments_hash": hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()}
        self.calls.append(record)
        start = time.monotonic()
        try:
            async with asyncio.timeout(30):
                value = await getattr(self.provider, name)(*args)
            record.update(status="success", server_timestamp=value.get("datetime"))
            return value
        except Exception as error:
            record.update(status="failed", error_types=safe_error_types(error))
            raise
        finally:
            record["elapsed_ms"] = round((time.monotonic() - start) * 1000)

    async def search(self, city, location):
        return await self._invoke("search", city, location)

    async def meals(self, store):
        return await self._invoke("meals", store)

    async def coupons(self, store):
        return await self._invoke("coupons", store)

    async def nutrition(self):
        return await self._invoke("nutrition")

    async def detail(self, store, code):
        return await self._invoke("detail", store, code)

    async def calculate(self, store, items):
        return await self._invoke("calculate", store, items)


async def run_live(request, progress=None):
    token = load_token()
    calls = []
    async with asyncio.timeout(180):
        async with connect(token) as client:
            provider = BoundedProvider(PickupMenu(client, await discover(client)), calls)
            result = await Recommender(provider, progress=progress).recommend(request)
    result["tool_calls"] = calls
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, help="Structured JSON request file")
    parser.add_argument("--report", default="artifacts/local/recommendation.json")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    request = RecommendationRequest.model_validate_json(Path(args.request).read_text(encoding="utf-8-sig"))
    try:
        report = asyncio.run(run_live(request, progress=lambda text: print(text, flush=True)))
    except Exception as error:
        report = {"status": "failed", "source": "live_mcp", "error_types": safe_error_types(error), "cards": []}
    write_private_report(args.report, report, load_token())
    print(json.dumps({"status": report["status"], "cards": [
        {"id": c["id"], "offer": c["offer_name"], "foods": [i["name"] for i in c["components"]],
         "amount_cents": c["amount_cents"], "nutrition": c["nutrition"], "coupon": c["coupon"]}
        for c in report.get("cards", [])], "coverage": report.get("coverage")}, ensure_ascii=False, indent=2))
    raise SystemExit(1 if report["status"] == "failed" else 0)


if __name__ == "__main__":
    main()
