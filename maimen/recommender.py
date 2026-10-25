"""Read-only, account-scoped pickup recommender. No language model or order creation."""
import copy
import hashlib
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

from .nutrition import parse_nutrition
from .price_evidence import inspect_calculation
from .recommendation_rules import (RULE_VERSION, applicable_coupons, budget_distance, build_candidates,
    category, choose_detail_drinks, coupon_variants, filter_reason, make_candidate, menu_cents,
    offer_restriction, select_cards)
from .store import encode


class RecommendationError(ValueError):
    pass


class Recommender:
    def __init__(self, provider, *, detail_limit=18, candidate_limit=12, quote_limit=30,
                 clock=time.time, progress=None):
        self.provider = provider
        self.detail_limit = detail_limit
        self.candidate_limit = candidate_limit
        self.quote_limit = quote_limit
        self.clock = clock
        self.progress = progress or (lambda message: None)

    async def recommend(self, req):
        started = self.clock()
        result = {
            "source": "live_mcp", "rule_version": RULE_VERSION, "request": req.model_dump(),
            "account_scope": "current_local_token_only", "checked_at": datetime.fromtimestamp(started, timezone.utc).isoformat(),
            "membership": {"gold_card": "unknown", "reported_by_user": req.reported_gold_card,
                           "evidence": "MCP未提供明确持卡有效期字段；自述不作为已核实权益"},
            "status": "no_candidates", "cards": [], "warnings": [], "clarifications": [],
            "coverage": {"scope": "bounded_search_not_global_optimum", "detail_limit": self.detail_limit,
                         "candidate_limit": self.candidate_limit, "quote_limit": self.quote_limit},
        }
        if req.goal == "fitness":
            result["clarifications"].append("健身目标是提高蛋白质、控制能量，还是仅作为场景？请明确后再筛选。")
        if req.allergies:
            result["clarifications"].append("当前MCP数据不足以核实过敏原和交叉接触，不能承诺避敏餐单。")
        if result["clarifications"]:
            result["status"] = "clarification_required"
            return result

        skipped = Counter()
        self.progress("核对门店与营业状态")
        stores = (await self.provider.search(req.city, req.location))["data"]
        store = next((s for s in stores if s.get("storeCode") == req.store_code), None)
        if store is None:
            raise RecommendationError("selected_store_not_found_for_location")
        result["store"] = {key: store.get(key) for key in ("storeCode", "storeName", "address", "businessStartTime", "businessEndTime")}
        if store.get("businessStatus") is not True:
            result.update(status="store_unavailable")
            result["warnings"].append("当前门店未营业；本版仅支持立即到店自取，不自动改预约时间。")
            return result

        self.progress("读取菜单、门店可用券与营养")
        menu_payload = await self.provider.meals(req.store_code)
        menu = menu_payload["data"]
        if not isinstance(menu, dict) or not isinstance(menu.get("meals"), dict):
            raise RecommendationError("unexpected_menu_format")
        coupons, coupon_count = [], 0
        result["coupon_status"] = "disabled"
        if req.use_coupons:
            try:
                coupons_payload = await self.provider.coupons(req.store_code)
                coupons, invalid = applicable_coupons(coupons_payload, datetime.fromtimestamp(self.clock(), timezone.utc))
                coupon_count = len(coupons_payload["data"])
                skipped["unverified_or_inactive_coupon"] += invalid
                result["coupon_status"] = "available" if coupons else "none_verified"
            except Exception:
                result["coupon_status"] = "unavailable"
                result["warnings"].append("优惠券查询失败或格式无法验证，本次不使用券；不会静默假定已享优惠。")
        try:
            nutrition_payload = await self.provider.nutrition()
            nutrition_index = parse_nutrition(nutrition_payload["data"])
            result["nutrition_source_time"] = nutrition_payload.get("datetime")
        except Exception:
            nutrition_index = {}
            result["warnings"].append("营养信息暂不可用；有硬性营养要求的组合将被排除。")

        tags, categories = defaultdict(set), defaultdict(set)
        for group in menu.get("categories", []):
            for meal in group.get("meals", []):
                tags[meal["code"]].update(meal.get("tags", []))
                categories[meal["code"]].add(group.get("name", ""))
        products = copy.deepcopy(menu["meals"])
        # Coupons can reference dedicated products absent from the ordinary menu.
        coupon_codes = set()
        for coupon in coupons:
            for p in coupon["products"]:
                code = p.get("productCode")
                if isinstance(code, str) and code and isinstance(p.get("productName"), str):
                    coupon_codes.add(code)
                    products.setdefault(code, {"name": p["productName"], "coupon_only": True})

        eligible = []
        for code, product in products.items():
            restriction = offer_restriction(product, tags[code])
            if code in req.exclude_codes:
                restriction = "excluded_parent_product"
            if restriction:
                skipped[restriction] += 1
                continue
            name = product.get("name", "")
            kind = category(name)
            is_combo = any(word in name for word in ("套餐", "件套", "随心配", "随心选", "单品精选"))
            if not is_combo and kind not in {"burger", "chicken", "drink"}:
                skipped["outside_candidate_categories"] += 1
                continue
            # No prefilter by list price: coupon price can be lower, combo choices may differ.
            estimated = menu_cents(product.get("currentPrice"))
            eligible.append({"code": code, "product": product, "kind": kind, "combo": is_combo,
                             "estimate": estimated if estimated is not None else 10**8,
                             "categories": sorted(categories[code])})

        # Reserve detail budget for independent main/drink pairs as well as combo offers.
        def priority(p):
            # Drinks stay cheap-first so a drink priced near the whole budget is not treated as a meal.
            # Only the explicit low-price goal fills the search with the cheapest meals.
            listed = p["estimate"]
            if req.goal != "lower_price" and p["kind"] != "drink":
                listed = budget_distance(listed, req.budget_cents)
            return (0 if p["code"] in req.keep_codes else 1,
                    0 if p["code"] in coupon_codes else 1,
                    0 if p["combo"] or p["kind"] == req.main_category else 1,
                    0 if req.drink == "no_sugar" and "可乐" in p["product"].get("name", "") else 1,
                    listed, p["code"])
        combos = sorted([p for p in eligible if p["combo"]], key=priority)
        mains = sorted([p for p in eligible if not p["combo"] and p["kind"] in {"burger", "chicken"}], key=priority)
        drinks = sorted([p for p in eligible if not p["combo"] and p["kind"] == "drink"], key=priority)
        chosen = (combos[:max(1, self.detail_limit - 8)] + mains[:5] + choose_detail_drinks(drinks, req))[:self.detail_limit]
        result["coverage"].update(menu_products=len(products), eligible_products=len(eligible),
                                  selected_details=len(chosen), coupons_returned=coupon_count,
                                  coupons_verified=len(coupons), menu_timestamp=menu_payload.get("datetime"),
                                  detail_search_truncated=len(eligible) > len(chosen),
                                  combinations_per_detail_limit=256)
        pool, single_mains, single_drinks = [], [], []
        for product in chosen:
            self.progress("读取餐品详情 " + product["code"])
            try:
                detail = (await self.provider.detail(req.store_code, product["code"]))["data"]
                if detail.get("code") != product["code"]:
                    raise ValueError("detail_product_mismatch")
                if offer_restriction(detail):
                    raise ValueError("restricted_detail_offer")
                generated = build_candidates(detail, req, nutrition_index)
                # Keep coupon-only items strictly tied to a matching coupon variant later.
                for candidate in generated:
                    candidate["coupon_only"] = bool(product["product"].get("coupon_only"))
                    candidate["coupon_required_codes"] = [product["code"]] if candidate["coupon_only"] else []
                    candidate["menu_categories"] = product["categories"]
                    candidate["discount_description"] = product["product"].get("discountType") or None
                    pool.append(candidate)
                    if len(candidate["components"]) == 1:
                        kind = candidate["components"][0]["category"]
                        if kind in {"burger", "chicken"}:
                            single_mains.append(candidate)
                        elif kind == "drink":
                            single_drinks.append(candidate)
            except (ValueError, KeyError, TypeError):
                skipped["detail_or_structure_unverified"] += 1
            except Exception:
                skipped["detail_query_failed"] += 1
        for main in single_mains:
            for drink in single_drinks:
                pair = make_candidate(main["items"] + drink["items"], main["components"] + drink["components"],
                                      "单品搭配", nutrition_index)
                pair["coupon_only"] = main["coupon_only"] or drink["coupon_only"]
                pair["coupon_required_codes"] = main["coupon_required_codes"] + drink["coupon_required_codes"]
                pair["menu_categories"] = sorted(set(main["menu_categories"] + drink["menu_categories"]))
                pool.append(pair)

        filtered, seen = [], set()
        for candidate in pool:
            reason = filter_reason(candidate["components"], req, candidate["nutrition"])
            if reason:
                skipped[reason] += 1
                continue
            key = encode(candidate["items"])
            if key in seen:
                continue
            seen.add(key)
            filtered.append(candidate)

        def rank(candidate):
            totals = candidate["nutrition"]["totals"]
            if req.goal == "higher_protein":
                goal = -totals["protein_g"] if totals else float("inf")
            elif req.goal == "lower_energy":
                goal = totals["energy_kcal"] if totals else float("inf")
            else:
                goal = 0
            estimate = sum(menu_cents(products.get(i["productCode"], {}).get("currentPrice")) or 10**6 for i in candidate["items"])
            # Use seeded order within the limited shortlist; final ranking uses real quotes.
            tie = hashlib.sha256(f'{req.seed}:{candidate["id"]}'.encode()).hexdigest()
            has_coupon = any(i["productCode"] in coupon_codes for i in candidate["items"])
            # This is ordering only; never reject a candidate using display/list prices.
            likely_affordable = has_coupon or estimate <= req.budget_cents
            if req.goal == "lower_price":
                return (0 if likely_affordable else 1, goal, estimate, tie)
            return (0 if likely_affordable else 1, budget_distance(estimate, req.budget_cents), goal, tie)

        filtered.sort(key=rank)

        def _closer_quote(new_amount, old_amount):
            if req.goal == "lower_price":
                return new_amount < old_amount
            return budget_distance(new_amount, req.budget_cents) < budget_distance(old_amount, req.budget_cents)
        # Round robin by main item stops a single burger with many drink variants consuming the budget.
        buckets = defaultdict(list)
        for candidate in filtered:
            main_key = tuple(c["code"] for c in candidate["components"] if c["category"] in {"burger", "chicken"})
            buckets[main_key].append(candidate)
        shortlisted = []
        while len(shortlisted) < self.candidate_limit and any(buckets.values()):
            for bucket in buckets.values():
                if bucket and len(shortlisted) < self.candidate_limit:
                    shortlisted.append(bucket.pop(0))

        result["coverage"].update(generated=len(pool), passes_nonprice_conditions=len(filtered),
                                  candidates_to_quote=len(shortlisted), truncated=len(filtered) > len(shortlisted))
        quoted = []
        quote_calls = 0
        for candidate in shortlisted:
            best = None
            for items, coupon_title in coupon_variants(candidate, coupons):
                if any(not any(i["productCode"] == code and i.get("couponId") for i in items)
                       for code in candidate.get("coupon_required_codes", [])):
                    continue
                if quote_calls >= self.quote_limit:
                    break
                quote_calls += 1
                self.progress(f"真实计价 {quote_calls}/{self.quote_limit}")
                try:
                    quote = await self.provider.calculate(req.store_code, items)
                    evidence = inspect_calculation(quote, items)
                    amount = evidence["reported_amount_cents"]
                    if amount > req.budget_cents:
                        skipped["over_budget_after_real_quote"] += 1
                        continue
                    data = quote["data"]
                    subtotals = [p.get("subtotal") for p in data["productList"]]
                    if any(type(v) is not int or v < 0 for v in subtotals):
                        raise ValueError("invalid_product_subtotals")
                    if "productPrice" in data and data["productPrice"] != sum(subtotals):
                        raise ValueError("inconsistent_product_total")
                    # No client-side savings claims: display server totals/fees verbatim by field.
                    fees = {k: data[k] for k in ("productPrice", "discount", "packingPrice", "deliveryPrice", "tablewarePrice") if k in data}
                    if any(type(v) is not int or v < 0 for v in fees.values()):
                        raise ValueError("invalid_quote_breakdown")
                    card = {
                        "id": candidate["id"], "offer_name": candidate["offer_name"],
                        "components": candidate["components"], "menu_categories": candidate["menu_categories"],
                        "nutrition": candidate["nutrition"], "amount_cents": amount,
                        "price_source": "calculate-price", "quoted_at": self.clock(),
                        "valid_until": self.clock() + 60, "validity_basis": "本地60秒展示期限，非官方价格保证",
                        "coupon": {"used_in_calculation": coupon_title is not None, "title": coupon_title},
                        "price_breakdown_cents": fees, "gold_card_required_by_observed_offer": False,
                        "gold_card_status": "unknown", "recommendation_eligible": True,
                        "evidence": {"request_sha256": hashlib.sha256(encode(items).encode()).hexdigest(),
                            "parent_products_match": True, "selection_basis": "query-meal-detail允许项及默认特制",
                            "child_selections_echoed_by_quote": False, "server_timestamp": quote.get("datetime"),
                            "level": "official_tool_quote_for_current_account_not_purchase_guarantee"},
                    }
                    if best is None or _closer_quote(card["amount_cents"], best["amount_cents"]):
                        best = card
                except Exception:
                    skipped["quote_failed_or_unverified"] += 1
            if best:
                quoted.append(best)

        # Drop expired quotes. Same composition keeps the quote that matches the active price goal.
        unique = {}
        for card in quoted:
            if self.clock() >= card["valid_until"]:
                skipped["quote_expired_during_run"] += 1
                continue
            current = unique.get(card["id"])
            if current is None or _closer_quote(card["amount_cents"], current["amount_cents"]):
                unique[card["id"]] = card
        def final_rank(card):
            totals = card["nutrition"]["totals"]
            value = 0
            if req.goal == "higher_protein":
                value = -totals["protein_g"] if totals else float("inf")
            elif req.goal == "lower_energy":
                value = totals["energy_kcal"] if totals else float("inf")
            tie = hashlib.sha256(f'{req.seed}:{card["id"]}'.encode()).hexdigest()
            if req.goal == "lower_price":
                return (value, card["amount_cents"], tie)
            return (budget_distance(card["amount_cents"], req.budget_cents), value, tie)
        ranked = sorted(unique.values(), key=final_rank)
        selected = select_cards(ranked, req)
        for card in selected:
            card["reasons"] = [f'本次官方计价 ¥{card["amount_cents"] / 100:.2f}，不超过预算',
                               "组成来自该门店餐品详情，未添加购卡或叠券"]
            if req.goal == "lower_price":
                card["reasons"].insert(0, "按更低价格优先，便宜饮料会排在前面")
            else:
                card["reasons"].insert(0, "在不超过预算的报价里，优先接近你的预算")
                if req.goal == "balanced":
                    card["reasons"].append("均衡搭配会错开饮料种类")
            if req.drink == "no_sugar":
                card["reasons"].append("饮料名称明确标注无糖；不代表整餐无糖")
            if card["nutrition"]["totals"]:
                card["reasons"].append("标准配方营养已精确匹配，可比较能量与蛋白质")
            if card["coupon"]["used_in_calculation"]:
                card["reasons"].append("已将当前门店可用券提交官方计价")
        result.update(cards=selected, status="ready" if len(selected) == 3 else "partial" if selected else "no_candidates")
        result["coverage"].update(quote_calls=quote_calls, verified_compositions=len(unique),
                                  skipped=dict(skipped), elapsed_ms=round((self.clock() - started) * 1000))
        result["warnings"].extend([
            "麦金卡及其他未核实权益商品已排除，不能把本账号报价用于其他客户。",
            "仅当前门店、当前账号、立即到店自取；价格会变，选定后应重新计价。",
            "未实现企业团餐满减、外送费优化、付费购卡、领取新券或真实下单。",
        ])
        if len(selected) < 3:
            result["warnings"].append("本次有界搜索不足三套，未放宽预算或其他硬条件；可调整条件或扩大搜索。")
        if req.goal in {"higher_protein", "lower_energy"}:
            result["warnings"].append("营养目标仅在已精确匹配的候选中排序，不等同个性化健康建议。")
        return result
