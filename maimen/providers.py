"""Provider boundaries; only the deterministic fixture implementations exist."""
from dataclasses import dataclass
from typing import Protocol

from .fixtures import CATALOG


class ModelProvider(Protocol):
    async def propose(self, text: str, turn: dict, state: dict) -> dict:
        """Return one bounded operation. The harness owns all state mutations."""
        ...


class FixtureModel:
    """A finite script for replay. It does NOT understand arbitrary language."""
    async def propose(self, text, turn, state):
        operations = {
            "选第二张": {"type": "select_card", "ordinal": 2},
            "饮料换无糖": {"type": "replace_item", "from_sku": "demo-drink", "to_sku": "demo-zero"},
            "撤回上一步": {"type": "undo"},
        }
        if text not in operations:
            raise ValueError("fixture_only: supported inputs are " + " / ".join(operations))
        return operations[text]


@dataclass(frozen=True)
class QuoteResult:
    amount_cents: int
    source: str
    evidence_id: str


class QuoteProvider(Protocol):
    async def calculate(self, ticket: dict) -> QuoteResult:
        ...


class FixtureQuoteProvider:
    async def calculate(self, ticket):
        if ticket["mode"] != "demo":
            raise ValueError("fixture_cannot_quote_live")
        return QuoteResult(
            amount_cents=sum(CATALOG[item["sku"]]["price_cents"] * item["quantity"] for item in ticket["items"]),
            source="demo",
            evidence_id="synthetic-fixture-v1",
        )

