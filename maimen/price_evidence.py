"""Conservative evidence labels; a successful calculation is not entitlement proof."""


def inspect_menu_offer(product):
    """Never infer card ownership from an offered card purchase or low menu price."""
    conditional = bool(product.get("withOrder") or product.get("canWithOrder"))
    discount = product.get("discountType") or ""
    card_related = any(word in discount for word in ("麦金卡", "早餐卡", "持卡"))
    return {
        "card_status": "unknown",
        "card_status_source": "no_explicit_entitlement_evidence",
        "requires_offer_review": conditional or card_related or bool(discount),
        "includes_card_purchase_offer": conditional,
        "discount_description": discount,
        "menu_price_is_payable_price": False,
    }


def inspect_calculation(payload, items):
    """Check the limited fields echoed by MCP; do not claim child selections verified."""
    if payload.get("success") is not True or payload.get("code") != 200:
        raise ValueError("price_business_failure")
    data = payload.get("data", {})
    amount = data.get("price")
    if type(amount) is not int or amount < 0:
        raise ValueError("price_must_be_integer_cents")
    expected = sorted((i["productCode"], i["quantity"]) for i in items)
    actual = sorted((i.get("productCode", ""), i.get("quantity", 0)) for i in data.get("productList", []))
    if actual != expected:
        raise ValueError("quoted_products_do_not_match_request")
    return {
        "status": "provider_reported_not_independently_verified",
        "reported_amount_cents": amount,
        "parent_products_match": True,
        "child_selections_verified": False,
        "card_status": "unknown",
        "recommendation_eligible": False,
        "blocking_reasons": ["menu_detail_and_offer_context_not_provided", "candidate_rules_not_evaluated"],
    }
