"""Build a bounded combo from observed detail slots, not arbitrary SKU substitution."""


def default_modification(choice):
    values = []
    for group in choice.get("modification", {}).get("items", []):
        selected_count = 0
        for value in group["values"]:
            quantity = value["selectedQuantity"]
            if type(quantity) is not int or quantity < 0:
                raise ValueError("invalid_default_modification")
            if not value["minQuantity"] <= quantity <= value["maxQuantity"]:
                raise ValueError("invalid_default_modification_quantity")
            selected_count += quantity > 0
            key = value["selectedKey"] if quantity else value.get("unselectedKey")
            if key:
                values.append({"code": value["code"], "key": key, "quantity": quantity})
        if not group["minValues"] <= selected_count <= group["maxValues"]:
            raise ValueError("invalid_default_modification_group")
    return {"values": values} if values else None


def build_single_choice_combo(detail, selections):
    """Only supports one item per round; refuse more complex combos until implemented.

    selections maps actual round IDs (strings) to actual allowed choice codes.
    Keeps default condiment choices; never infers nutrition or affordability.
    """
    rounds = detail.get("rounds", [])
    if not rounds or set(selections) != {str(r["id"]) for r in rounds}:
        raise ValueError("exact_round_selection_required")
    item = {"productCode": detail["code"], "quantity": 1, "roundList": []}
    names = []
    for slot in rounds:
        if slot.get("minQuantity") != 1 or slot.get("maxQuantity") != 1:
            raise ValueError("unsupported_round_cardinality")
        choices = [c for c in slot["choices"] if c["code"] == selections[str(slot["id"])]]
        if len(choices) != 1:
            raise ValueError("invalid_slot_choice")
        if choices[0].get("maxQuantity", -1) != -1 and choices[0]["maxQuantity"] < 1:
            raise ValueError("invalid_slot_choice")
        choice = choices[0]
        selected = {"code": choice["code"], "quantity": 1}
        modification = default_modification(choice)
        if modification:
            selected["modification"] = modification
        item["roundList"].append({"round": str(slot["id"]), "comboItemList": [selected]})
        names.append(choice["name"])
    modification = default_modification(detail)
    if modification:
        item["modification"] = modification
    return {"items": [item], "names": names, "source": "live_menu", "nutrition_status": "unmatched",
            "card_status": "unknown", "recommendation_eligible": False,
            "validation_status": "structure_only_price_and_entitlement_pending"}
