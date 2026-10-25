"""Entirely invented demo foods/prices. Not official menu or MCP responses."""

CATALOG = {
    "demo-burger-a": {"name": "演示鸡肉堡", "category": "main", "price_cents": 1400},
    "demo-burger-b": {"name": "演示蔬菜堡", "category": "main", "price_cents": 1500},
    "demo-burger-c": {"name": "演示鱼肉堡", "category": "main", "price_cents": 1600},
    "demo-side": {"name": "演示小食", "category": "side", "price_cents": 500},
    "demo-drink": {"name": "演示饮料", "category": "drink", "price_cents": 400},
    "demo-zero": {"name": "演示无糖饮料", "category": "drink", "price_cents": 400},
}


def candidates():
    return [
        {"label": label, "items": [
            {"sku": sku, "quantity": 1},
            {"sku": "demo-side", "quantity": 1},
            {"sku": "demo-drink", "quantity": 1},
        ]}
        for label, sku in [("演示候选 A", "demo-burger-a"), ("演示候选 B", "demo-burger-b"), ("演示候选 C", "demo-burger-c")]
    ]

