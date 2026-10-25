"""Explicit read-only menu investigation. Reports remain local, not public artifacts."""
import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .adapters.mcd import connect, discover, load_token
from .adapters.menu import PickupMenu
from .mcp_probe import safe_error_types, write_private_report
from .price_evidence import inspect_calculation


async def run(args):
    token = load_token()
    report = {"source": "live_mcp", "checked_at": datetime.now(timezone.utc).isoformat(),
              "operation": args.operation, "store_code": args.store, "be_type": 1,
              "order_type": 1, "account_scope": "current_local_token_only", "card_status": "unknown"}
    try:
        async with asyncio.timeout(90):
            async with connect(token) as client:
                menu = PickupMenu(client, await discover(client))
                if args.operation == "search":
                    result = await menu.search(args.city, args.keyword)
                elif args.operation == "meals":
                    result = await menu.meals(args.store)
                elif args.operation == "detail":
                    result = await menu.detail(args.store, args.code)
                elif args.operation == "coupons":
                    result = await menu.coupons(args.store)
                else:
                    items = json.loads(Path(args.items).read_text(encoding="utf-8-sig"))
                    result = await menu.calculate(args.store, items)
                    report["price_evidence"] = inspect_calculation(result, items)
                report.update(status="success", result=result)
    except Exception as error:
        report.update(status="failed", error_types=safe_error_types(error))
    write_private_report(args.report, report, token)
    print(json.dumps({k: v for k, v in report.items() if k != "result"}, ensure_ascii=False))
    return 0 if report["status"] == "success" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["search", "meals", "detail", "calculate", "coupons"])
    parser.add_argument("--city", default="上海")
    parser.add_argument("--keyword", default="麦当劳总部")
    parser.add_argument("--store")
    parser.add_argument("--code")
    parser.add_argument("--items")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    if args.operation != "search" and not args.store:
        parser.error("--store required")
    if args.operation == "detail" and not args.code:
        parser.error("--code required")
    if args.operation == "calculate" and not args.items:
        parser.error("--items required")
    logging.disable(logging.CRITICAL)
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
