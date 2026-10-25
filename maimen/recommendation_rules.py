"""Bounded deterministic candidate construction from official menu/detail data."""
import copy
import hashlib
import itertools
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation

from .menu_candidates import build_single_choice_combo, default_modification
from .nutrition import summarize_nutrition
from .store import encode

RULE_VERSION = "pickup-v1"
SHANGHAI = timezone(timedelta(hours=8))


def menu_cents(value):
    try:
        number = Decimal(str(value)) * 100
        if not number.is_finite() or number < 0 or number != number.to_integral_value():
            return None
        return int(number)
    except (ValueError, InvalidOperation):
        return None


DRINK_FAMILIES = (
    ("water", ("纯悦", "矿泉水", "饮用水")),
    ("cola", ("可乐",)),
    ("citrus", ("雪碧", "怡泉")),
    ("tea", ("红茶", "绿茶", "奶茶")),
    ("coffee", ("咖啡", "美式", "奶铁", "拿铁")),
    ("juice", ("果汁", "苹果汁", "橙橙", "柠柠")),
    ("blended", ("麦炫酷", "奶昔")),
)


def budget_distance(cents, budget):
    """Smaller is closer to the budget. Amounts above the budget sort after amounts within it."""
    if cents <= budget:
        return budget - cents
    return 10**9 + cents - budget


def drink_family(name):
    # Used only to stop one cheap drink from occupying every card.
    for label, words in DRINK_FAMILIES:
        if any(word in name for word in words):
            return label
    return "other"


def category(name):
    # Classification hints only, never ingredient/allergen or nutrition claims.
    if any(word in name for word in ("周边", "徽章", "帽", "玩具", "毛绒", "按摩", "麦金卡", "早餐卡")):
        return "non_food"
    if any(word in name for word in ("汉堡", "牛堡", "鸡腿堡", "鱼堡", "月堡", "麦香鸡", "麦香鱼", "巨无霸", "麦满分", "卷")):
        return "burger"
    if any(word in name for word in ("可乐", "雪碧", "红茶", "咖啡", "美式", "奶铁", "牛奶", "燕麦奶", "奶昔", "怡泉", "纯悦", "果汁", "苹果汁", "橙橙", "柠柠", "麦炫酷")):
        return "drink"
    if any(word in name for word in ("鸡翅", "鸡排", "麦乐鸡", "脆汁鸡", "V翅", "炸鸡")):
        return "chicken"
    if any(word in name for word in ("薯", "玉米", "苹果片", "派", "新地", "麦旋风", "冰淇淋")):
        return "side"
    return "unknown"


def offer_restriction(product, tags=()):
    label = " ".join([product.get("name", ""), product.get("discountType") or "", *tags])
    if product.get("canWithOrder") or product.get("withOrder"):
        return "paid_card_purchase_offer_not_authorized"
    if any(word in label for word in ("麦金卡", "早餐卡", "持卡", "会员专享", "学生专享")):
        return "entitlement_not_verified"
    if any(word in label for word in ("双人", "多人", "亲子", "分享餐", "开心乐园")):
        return "outside_single_adult_meal_scope"
    if category(product.get("name", "")) == "non_food":
        return "non_food"
    return None


def stable_id(components):
    return hashlib.sha256(encode(sorted((c["code"], c["quantity"]) for c in components)).encode()).hexdigest()[:20]


def component(choice):
    return {"code": choice["code"], "name": choice["name"], "quantity": 1,
            "category": category(choice["name"]), "support_modify": bool(choice.get("supportModify"))}


def filter_reason(components, req, nutrition):
    codes = {c["code"] for c in components}
    if not set(req.keep_codes) <= codes:
        return "missing_kept_item"
    if codes & set(req.exclude_codes):
        return "excluded_item"
    if any(word in c["name"] for c in components for word in req.exclude_words):
        return "excluded_word"
    mains = [c for c in components if c["category"] in {"burger", "chicken"}]
    if not mains or (req.main_category != "any" and not any(c["category"] == req.main_category for c in mains)):
        return "main_category_mismatch"
    drinks = [c for c in components if c["category"] == "drink"]
    if req.drink == "none" and drinks:
        return "drink_not_requested"
    if req.drink != "none" and not drinks:
        return "drink_required"
    if req.drink == "no_sugar" and any("无糖" not in c["name"] for c in drinks):
        return "no_explicit_sugar_free_evidence"
    totals = nutrition["totals"]
    if req.min_protein_g is not None or req.max_energy_kcal is not None:
        if totals is None:
            return "nutrition_required_but_unmatched"
        if req.min_protein_g is not None and totals["protein_g"] < req.min_protein_g:
            return "protein_below_minimum"
        if req.max_energy_kcal is not None and totals["energy_kcal"] > req.max_energy_kcal:
            return "energy_above_maximum"
    if stable_id(components) in req.avoid_card_ids:
        return "previously_rejected_card"
    return None


def build_candidates(detail, req, nutrition_index, max_combinations=256):
    """Enumerate small legal single-choice rounds; unsupported detail is rejected."""
    if not detail.get("rounds"):
        item = {"productCode": detail["code"], "quantity": 1}
        mod = default_modification(detail)
        if mod:
            item["modification"] = mod
        possibilities = [([item], [component(detail)])]
    else:
        rounds = detail["rounds"]
        if len(rounds) > 6 or any(r.get("minQuantity") != 1 or r.get("maxQuantity") != 1 for r in rounds):
            raise ValueError("unsupported_round_cardinality")
        options = []
        for slot in rounds:
            choices = [c for c in slot["choices"] if not offer_restriction(c)
                       and c["code"] not in req.exclude_codes
                       and not any(w in c["name"] for w in req.exclude_words)
                       and (category(c["name"]) != "drink" or req.drink != "none")
                       and (category(c["name"]) != "drink" or req.drink != "no_sugar" or "无糖" in c["name"])]
            choices.sort(key=lambda c: hashlib.sha256(f'{req.seed}:{c["code"]}'.encode()).hexdigest())
            options.append(choices)
        possibilities = []
        for choices in itertools.islice(itertools.product(*options), max_combinations):
            selected = {str(slot["id"]): c["code"] for slot, c in zip(rounds, choices)}
            built = build_single_choice_combo(detail, selected)
            possibilities.append((built["items"], [component(c) for c in choices]))
    return [make_candidate(items, components, detail["name"], nutrition_index) for items, components in possibilities]


def choose_detail_drinks(drinks, req, limit=3):
    """Price mode keeps the cheapest drinks. Other goals take one drink per family first."""
    ordered = list(drinks)
    if req.goal == "lower_price":
        return ordered[:limit]
    grouped = defaultdict(list)
    for drink in ordered:
        grouped[drink_family(drink["product"].get("name", ""))].append(drink)
    family_order = sorted(grouped, key=lambda name: hashlib.sha256(f'{req.seed}:{name}'.encode()).hexdigest())
    picked = [grouped[name][0] for name in family_order[:limit]]
    if len(picked) < limit:
        picked.extend(drink for drink in ordered if drink not in picked)
    return picked[:limit]


def main_key(card):
    return tuple(c["code"] for c in card["components"] if c["category"] in {"burger", "chicken"})


def card_drink_family(card):
    names = [c["name"] for c in card["components"] if c["category"] == "drink"]
    return drink_family(" ".join(names)) if names else "none"


def select_cards(ranked, req, limit=3):
    if req.goal == "lower_price":
        return _one_per_main(ranked, limit)
    grouped = defaultdict(list)
    for card in ranked:
        grouped[card_drink_family(card)].append(card)
    family_order = sorted(grouped, key=lambda name: hashlib.sha256(f'{req.seed}:{name}'.encode()).hexdigest())
    chosen, used_mains = [], set()
    while len(chosen) < limit and any(grouped.values()):
        for name in family_order:
            bucket = grouped[name]
            while bucket and main_key(bucket[0]) in used_mains:
                bucket.pop(0)
            if bucket and len(chosen) < limit:
                card = bucket.pop(0)
                chosen.append(card)
                used_mains.add(main_key(card))
    if len(chosen) < limit:
        chosen.extend(card for card in _one_per_main(ranked, limit) if card not in chosen)
    return chosen[:limit]


def _one_per_main(ranked, limit):
    chosen, used_mains = [], set()
    for card in ranked:
        key = main_key(card)
        if key in used_mains:
            continue
        chosen.append(card)
        used_mains.add(key)
        if len(chosen) == limit:
            break
    for card in ranked:
        if len(chosen) == limit:
            break
        if card not in chosen:
            chosen.append(card)
    return chosen[:limit]


def make_candidate(items, components, title, nutrition_index):
    return {"id": stable_id(components), "items": items, "components": components,
            "offer_name": title, "nutrition": summarize_nutrition(components, nutrition_index)}


def applicable_coupons(payload, now):
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("unexpected_store_coupons_format")
    result, rejected = [], 0
    for coupon in data:
        try:
            start, end = coupon["tradeDateTime"].split(" - ")
            start, end = [datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=SHANGHAI) for value in (start, end)]
            if not start <= now <= end:
                raise ValueError("inactive_coupon")
            if not all(isinstance(coupon.get(k), str) and coupon[k] for k in ("couponId", "couponCode", "title")):
                raise ValueError("missing_coupon_identity")
            if not isinstance(coupon.get("products"), list) or not coupon["products"]:
                raise ValueError("missing_product_mapping")
            result.append(coupon)
        except (KeyError, TypeError, ValueError):
            rejected += 1
    return result, rejected


def coupon_variants(candidate, coupons, max_coupons=2):
    variants = [(candidate["items"], None)]
    # One coupon on one matching parent item per quote; never guess stacking rules.
    for coupon in coupons:
        for index, item in enumerate(candidate["items"]):
            if item["productCode"] not in {p.get("productCode") for p in coupon["products"]}:
                continue
            items = copy.deepcopy(candidate["items"])
            items[index].update(couponId=coupon["couponId"], couponCode=coupon["couponCode"])
            variants.append((items, coupon["title"]))
            break
        if len(variants) >= max_coupons + 1:
            break
    return variants
