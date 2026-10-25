import copy
import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from maimen.nutrition import FIELDS, parse_nutrition, summarize_nutrition
from maimen.recommendation_contracts import RecommendationRequest
from maimen.recommendation_rules import applicable_coupons, coupon_variants
from maimen.recommender import Recommender, RecommendationError

NOW = datetime(2026, 10, 17, 8, tzinfo=timezone.utc).timestamp()


def nutrition_text(rows):
    return f'[{len(rows)}]{{{",".join(FIELDS)}}}:\n' + '\n'.join(','.join(map(str, r)) for r in rows)


def envelope(data):
    return {"success": True, "code": 200, "datetime": "2026-10-17 16:00:00", "data": data}


class Provider:
    def __init__(self):
        self.quotes = []
        self.detail_calls = []
        self.store_open = True
        self.price = 1800
        self.coupons_data = []
        self.coupon_failure = False
        self.quote_failure = False
        self.wrong_parent = False
        self.nutrition_rows = [
            ["测试牛肉汉堡", "null", 1600, 400, 25, 10, 30, 500, 20],
            ["测试鸡肉汉堡", "null", 1400, 350, 22, 8, 35, 450, 20],
            ["测试鱼肉汉堡", "null", 1300, 310, 18, 7, 30, 400, 20],
            ["无糖可乐中杯", "null", 0, 0, 0, 0, 0, 0, 0],
        ]
        self.products = {"combo": {"name": "测试随心配", "currentPrice": "18", "canWithOrder": False},
                         "paid": {"name": "麦金卡四件套", "currentPrice": "1", "canWithOrder": True,
                                  "withOrder": {"membershipCode": "card"}}}
        self.details = {"code": "combo", "name": "测试随心配", "rounds": [
            {"id": 1, "minQuantity": 1, "maxQuantity": 1, "choices": [
                {"code": "beef", "name": "测试牛肉汉堡", "maxQuantity": -1},
                {"code": "chicken", "name": "测试鸡肉汉堡", "maxQuantity": -1},
                {"code": "fish", "name": "测试鱼肉汉堡", "maxQuantity": -1}]},
            {"id": 2, "minQuantity": 1, "maxQuantity": 1, "choices": [
                {"code": "zero", "name": "无糖可乐中杯", "maxQuantity": -1},
                {"code": "sugar", "name": "可乐中杯", "maxQuantity": -1}]}]}

    async def search(self, city, location):
        return envelope([{"storeCode": "1450398", "storeName": "测试门店", "businessStatus": self.store_open}])

    async def meals(self, store):
        return envelope({"meals": self.products, "categories": []})

    async def coupons(self, store):
        if self.coupon_failure:
            raise ValueError("unavailable")
        return envelope(self.coupons_data)

    async def nutrition(self):
        return envelope(nutrition_text(self.nutrition_rows))

    async def detail(self, store, code):
        self.detail_calls.append(code)
        if code == "combo":
            return envelope(self.details)
        raise ValueError("unknown_product")

    async def calculate(self, store, items):
        self.quotes.append(copy.deepcopy(items))
        if self.quote_failure or (self.coupon_failure and any(i.get("couponId") for i in items)):
            raise ValueError("quote_failed")
        price = 1200 if any(i.get("couponId") for i in items) else self.price
        return envelope({"price": price, "productPrice": price, "discount": 0,
                         "productList": [{"productCode": "wrong" if self.wrong_parent else items[0]["productCode"],
                                          "quantity": 1, "subtotal": price}]})


def coupon(**changes):
    return {"couponId": "private-id", "couponCode": "private-code", "title": "测试优惠券",
            "tradeDateTime": "2026-10-17 00:00:00 - 2026-10-18 23:59:59",
            "products": [{"productCode": "combo", "productName": "测试随心配"}], **changes}


class RecommendationTests(unittest.IsolatedAsyncioTestCase):
    async def run_engine(self, provider=None, **kwargs):
        self.provider = provider or Provider()
        return await Recommender(self.provider, clock=lambda: NOW).recommend(RecommendationRequest(**kwargs))

    async def test_end_to_end_three_distinct_mains_real_quote_and_exact_nutrition(self):
        result = await self.run_engine()
        self.assertEqual("ready", result["status"])
        self.assertEqual(3, len({c["id"] for c in result["cards"]}))
        self.assertTrue(all(c["amount_cents"] == 1800 for c in result["cards"]))
        self.assertTrue(all(c["nutrition"]["totals"] for c in result["cards"]))
        self.assertNotIn("paid", self.provider.detail_calls)
        self.assertEqual("unknown", result["membership"]["gold_card"])
        self.assertFalse(any("sugar" == c["code"] for card in result["cards"] for c in card["components"]))

    async def test_final_price_controls_budget_not_menu_price(self):
        provider = Provider()
        provider.price = 3100
        result = await self.run_engine(provider)
        self.assertEqual([], result["cards"])
        self.assertGreater(result["coverage"]["skipped"]["over_budget_after_real_quote"], 0)

    async def test_coupon_can_make_overbudget_base_affordable(self):
        provider = Provider()
        provider.price = 3100
        provider.coupons_data = [coupon()]
        result = await self.run_engine(provider, budget_cents=1500)
        self.assertEqual(3, len(result["cards"]))
        self.assertTrue(all(c["coupon"]["used_in_calculation"] for c in result["cards"]))
        self.assertNotIn("private-code", str(result))
        self.assertNotIn("private-id", str(result))
        self.assertTrue(any(i.get("couponCode") == "private-code" for q in provider.quotes for i in q))

    async def test_expired_or_unmapped_coupon_never_sent(self):
        provider = Provider()
        provider.coupons_data = [coupon(tradeDateTime="2020-01-01 00:00:00 - 2020-01-02 00:00:00"),
                                 coupon(products=[{"productCode": "other", "productName": "另一个商品"}])]
        result = await self.run_engine(provider)
        self.assertTrue(all(not c["coupon"]["used_in_calculation"] for c in result["cards"]))
        self.assertFalse(any(i.get("couponCode") for q in provider.quotes for i in q))

    async def test_coupon_endpoint_failure_is_explicit(self):
        provider = Provider()
        provider.coupon_failure = True
        result = await self.run_engine(provider)
        self.assertEqual("unavailable", result["coupon_status"])
        self.assertEqual(3, len(result["cards"]))

    async def test_no_success_when_quote_failed_or_wrong_parent(self):
        for attr in ("quote_failure", "wrong_parent"):
            provider = Provider()
            setattr(provider, attr, True)
            result = await self.run_engine(provider)
            self.assertEqual([], result["cards"])

    async def test_keep_exclude_and_rejected_cards_are_hard_constraints(self):
        result = await self.run_engine(keep_codes=["beef"])
        self.assertEqual(1, len(result["cards"]))
        self.assertEqual("beef", result["cards"][0]["components"][0]["code"])
        rejected = result["cards"][0]["id"]
        result = await self.run_engine(avoid_card_ids=[rejected], exclude_codes=["fish"])
        self.assertEqual(1, len(result["cards"]))
        self.assertEqual("chicken", result["cards"][0]["components"][0]["code"])

    async def test_nutrition_constraints_and_unknown_values(self):
        result = await self.run_engine(min_protein_g=24, max_energy_kcal=450)
        self.assertEqual(1, len(result["cards"]))
        provider = Provider()
        provider.nutrition_rows = []
        result = await self.run_engine(provider, min_protein_g=20)
        self.assertEqual([], result["cards"])
        result = await self.run_engine(provider)
        self.assertTrue(all(c["nutrition"]["totals"] is None for c in result["cards"]))

    async def test_fitness_or_allergy_requires_clarification_before_calls(self):
        for args in ({"goal": "fitness"}, {"allergies": ["牛奶"]}):
            result = await self.run_engine(**args)
            self.assertEqual("clarification_required", result["status"])
            self.assertEqual([], self.provider.detail_calls)

    async def test_closed_or_wrong_store_never_quotes(self):
        provider = Provider()
        provider.store_open = False
        result = await self.run_engine(provider)
        self.assertEqual("store_unavailable", result["status"])
        self.assertEqual([], provider.quotes)
        with self.assertRaises(RecommendationError):
            await self.run_engine(store_code="0000")

    async def test_self_report_does_not_unlock_paid_card_purchase(self):
        result = await self.run_engine(reported_gold_card="yes")
        self.assertEqual("unknown", result["membership"]["gold_card"])
        self.assertNotIn("paid", self.provider.detail_calls)

    async def test_seeded_results_and_bounded_quotes(self):
        first, second = await self.run_engine(seed=42), await self.run_engine(seed=42)
        self.assertEqual(first["cards"], second["cards"])
        provider = Provider()
        result = await Recommender(provider, candidate_limit=1, quote_limit=1, clock=lambda: NOW).recommend(RecommendationRequest())
        self.assertLessEqual(len(provider.quotes), 1)
        self.assertEqual("partial", result["status"])

    async def test_balanced_goal_quotes_meals_close_to_the_budget(self):
        class Menu(Provider):
            def __init__(self):
                super().__init__()
                self.products = {}
                self.details_by_code = {}
                self.prices = {}
                for index in range(10):
                    self._add(f"cheap{index}", 21)
                for yuan in (55, 56, 58, 70):
                    self._add(f"near{yuan}", yuan)

            def _add(self, code, yuan):
                burger = f"测试牛肉{code}汉堡"
                self.products[code] = {"name": f"{burger}套餐", "currentPrice": str(yuan)}
                self.prices[code] = yuan * 100
                self.details_by_code[code] = {"code": code, "name": f"{burger}套餐", "rounds": [
                    {"id": 1, "minQuantity": 1, "maxQuantity": 1, "choices": [
                        {"code": f"main-{code}", "name": burger, "maxQuantity": -1}]},
                    {"id": 2, "minQuantity": 1, "maxQuantity": 1, "choices": [
                        {"code": f"cola-{code}", "name": "可乐中杯", "maxQuantity": -1}]}]}

            async def detail(self, store, code):
                self.detail_calls.append(code)
                return envelope(self.details_by_code[code])

            async def calculate(self, store, items):
                self.quotes.append(copy.deepcopy(items))
                price = self.prices[items[0]["productCode"]]
                rows = [{"productCode": item["productCode"], "quantity": item["quantity"], "subtotal": price} for item in items]
                return envelope({"price": price, "productPrice": price, "discount": 0, "productList": rows})

        balanced = await self.run_engine(Menu(), drink="any", goal="balanced", budget_cents=6000)
        self.assertEqual([5500, 5600, 5800], sorted(card["amount_cents"] for card in balanced["cards"]))
        self.assertTrue({"near55", "near56", "near58"} <= set(self.provider.detail_calls))
        protein = await self.run_engine(Menu(), drink="any", goal="higher_protein", budget_cents=6000)
        self.assertEqual([5500, 5600, 5800], sorted(card["amount_cents"] for card in protein["cards"]))
        cheap = await self.run_engine(Menu(), drink="any", goal="lower_price", budget_cents=6000)
        self.assertTrue(all(card["amount_cents"] == 2100 for card in cheap["cards"]))
        self.assertFalse({"near55", "near56", "near58"} & set(self.provider.detail_calls))

    async def test_balanced_goal_does_not_fill_every_card_with_the_cheapest_water(self):
        class Menu(Provider):
            def __init__(self):
                super().__init__()
                self.products = {
                    "beef": {"name": "测试牛肉汉堡", "currentPrice": "15"},
                    "chicken": {"name": "测试鸡肉汉堡", "currentPrice": "16"},
                    "fish": {"name": "测试鱼肉汉堡", "currentPrice": "17"},
                    "water": {"name": "纯悦", "currentPrice": "2"},
                    "water2": {"name": "纯悦大瓶", "currentPrice": "3"},
                    "spark": {"name": "纯悦气泡", "currentPrice": "4"},
                    "cola": {"name": "可乐中杯", "currentPrice": "9"},
                    "tea": {"name": "锡兰红茶", "currentPrice": "8"},
                }
                self.prices = {code: int(float(item["currentPrice"]) * 100) for code, item in self.products.items()}

            async def detail(self, store, code):
                self.detail_calls.append(code)
                return envelope({"code": code, "name": self.products[code]["name"]})

            async def calculate(self, store, items):
                self.quotes.append(copy.deepcopy(items))
                rows = [{"productCode": item["productCode"], "quantity": item["quantity"], "subtotal": self.prices[item["productCode"]]} for item in items]
                price = sum(row["subtotal"] for row in rows)
                return envelope({"price": price, "productPrice": price, "discount": 0, "productList": rows})

        balanced = await self.run_engine(Menu(), drink="any", goal="balanced", main_category="burger")
        water_cards = [card for card in balanced["cards"] if any("纯悦" in part["name"] for part in card["components"])]
        self.assertEqual(3, len(balanced["cards"]))
        self.assertLess(len(water_cards), 3)
        self.assertIn("cola", balanced and self.provider.detail_calls)
        cheap = await self.run_engine(Menu(), drink="any", goal="lower_price", main_category="burger")
        self.assertTrue(all(any("纯悦" in part["name"] for part in card["components"]) for card in cheap["cards"]))
        self.assertNotIn("cola", self.provider.detail_calls)

    async def test_low_budget_shortlist_does_not_starve_affordable_offer(self):
        class Mixed(Provider):
            async def detail(self, store, code):
                detail = copy.deepcopy(self.details)
                detail["code"] = code
                if code == "expensive":
                    detail["rounds"][0]["choices"] = [{"code": "beef", "name": "测试牛肉汉堡", "maxQuantity": -1}]
                else:
                    detail["rounds"][0]["choices"] = [{"code": "fish", "name": "测试鱼肉汉堡", "maxQuantity": -1}]
                return envelope(detail)
        provider = Mixed()
        provider.products["expensive"] = {"name": "豪华汉堡套餐", "currentPrice": "80"}
        result = await Recommender(provider, clock=lambda: NOW, candidate_limit=1).recommend(
            RecommendationRequest(goal="higher_protein"))
        self.assertEqual("combo", provider.quotes[0][0]["productCode"])
        self.assertEqual(1, len(result["cards"]))


class NutritionTests(unittest.TestCase):
    def test_count_header_columns_and_negative_values_are_validated(self):
        for text in ("[1]{wrong}:\n", nutrition_text([]).replace("[0]", "[1]"),
                     nutrition_text([["test", "null", 0, -1, 0, 0, 0, 0, 0]])):
            with self.assertRaises(ValueError):
                parse_nutrition(text)

    def test_does_not_guess_size_or_ambiguous_name(self):
        row = ["测试饮料中杯", "null", 0, 10, 0, 0, 0, 0, 0]
        index = parse_nutrition(nutrition_text([row]))
        self.assertIsNone(summarize_nutrition([{"name": "测试饮料大杯", "quantity": 1}], index)["totals"])
        index = parse_nutrition(nutrition_text([row, row]))
        self.assertIsNone(summarize_nutrition([{"name": "测试饮料中杯", "quantity": 1}], index)["totals"])

    def test_typography_normalization_preserves_specification(self):
        index = parse_nutrition(nutrition_text([["牛奶（盒装）", "null", 100, 20, 3, 2, 1, 0, 0]]))
        self.assertEqual(40, summarize_nutrition([{"name": "牛奶(盒装)", "quantity": 2}], index)["totals"]["energy_kcal"])


class InputTests(unittest.TestCase):
    def test_conflicting_constraints_and_unsupported_channels(self):
        for args in ({"keep_codes": ["a"], "exclude_codes": ["a"]}, {"budget_cents": True},
                     {"be_type": 6}, {"exclude_words": [""]}, {"min_protein_g": float("nan")}):
            with self.assertRaises(ValidationError):
                RecommendationRequest(**args)
