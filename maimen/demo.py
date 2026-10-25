"""Run: python -m maimen.demo. Scripted, synthetic data, no network calls."""
import argparse
import asyncio
import json
from pathlib import Path

from .fixtures import CATALOG, candidates
from .harness import Harness
from .providers import FixtureModel, FixtureQuoteProvider
from .store import Store


async def run(database, report_path=None):
    store = Store(database)
    try:
        harness, model, provider = Harness(store), FixtureModel(), FixtureQuoteProvider()
        session = harness.create()
        harness.show_cards(session, candidates())
        print("离线脚本演示：虚构餐品与价格，无模型、无 MCP 网络调用。")
        for text in ("选第二张", "饮料换无糖", "撤回上一步"):
            turn = harness.begin_turn(session)
            operation = await model.propose(text, turn, harness.state(session))
            draft = harness.apply(turn, operation)
            print(text + " → " + "、".join(CATALOG[i["sku"]]["name"] for i in draft["items"]))

        old_ticket = harness.request_quote(session)
        old_result = await provider.calculate(old_ticket)
        turn = harness.begin_turn(session)
        harness.apply(turn, await model.propose("饮料换无糖", turn, harness.state(session)))
        stale_accepted = harness.accept_quote(old_ticket, old_result)
        print("旧报价迟到 → " + ("错误接受" if stale_accepted else "已丢弃"))

        ticket = harness.request_quote(session)
        harness.accept_quote(ticket, await provider.calculate(ticket))
        harness.collect(session, "演示周五餐")
        # Scripted demonstration of the separate user-confirmation boundary.
        harness.confirm(session, ticket["id"])
        result = harness.checkout_preview(session)
        report = {"mode": "demo", "uses_live_mcp": False, "uses_llm": False,
                  "session_id": session, "stale_quote_accepted": stale_accepted,
                  "checkout": result, "replay_matches": store.replay(session) == harness.state(session),
                  "events": store.events(session)}
        print(f"演示金额：{result['amount_cents'] / 100:.2f} 元；没有创建真实订单。")
        print("SQLite 事件回放一致：" + str(report["replay_matches"]))
        if report_path:
            path = Path(report_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/demo.sqlite3")
    parser.add_argument("--report")
    args = parser.parse_args()
    asyncio.run(run(args.db, args.report))


if __name__ == "__main__":
    main()
