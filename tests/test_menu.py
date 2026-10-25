import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from maimen.adapters.menu import PickupMenu
from maimen.menu_candidates import build_single_choice_combo, default_modification


class MenuTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = SimpleNamespace(call_tool=AsyncMock(return_value=SimpleNamespace(
            is_error=False, structured_content={"success": True, "code": 200, "data": []})))
        tools = [SimpleNamespace(name=n, input_schema={"type": "object"}) for n in
                 ["query-nearby-stores", "query-meals", "query-meal-detail", "calculate-price"]]
        self.menu = PickupMenu(self.client, tools)

    async def test_search_uses_explicit_location_and_pickup(self):
        await self.menu.search("上海", "麦当劳总部")
        self.client.call_tool.assert_awaited_once_with("query-nearby-stores", {
            "beType": 1, "searchType": 2, "city": "上海", "keyword": "麦当劳总部"})

    async def test_business_failure_is_not_success(self):
        self.client.call_tool.return_value.structured_content = {"success": False, "code": 200}
        with self.assertRaisesRegex(ValueError, "not_successful"):
            await self.menu.meals("123")

    async def test_rejects_mutating_tools_and_demo_ids(self):
        with self.assertRaises(ValueError):
            await self.menu._call("create-order", {})
        with self.assertRaises(ValueError):
            await self.menu.meals("demo-store-a")
        with self.assertRaises(ValueError):
            await self.menu.calculate("123", [{"productCode": "demo-zero", "quantity": 1}])
        self.client.call_tool.assert_not_awaited()

    async def test_pickup_has_no_be_code_and_quantity_is_required(self):
        with self.assertRaises(ValueError):
            await self.menu.calculate("123", [{"productCode": "456"}])
        await self.menu.calculate("123", [{"productCode": "456", "quantity": 1}])
        args = self.client.call_tool.call_args.args[1]
        self.assertNotIn("beCode", args)
        self.assertEqual((1, 1), (args["beType"], args["orderType"]))


class ComboTests(unittest.TestCase):
    def setUp(self):
        self.detail = {"code": "combo", "rounds": [
            {"id": 1, "minQuantity": 1, "maxQuantity": 1, "choices": [
                {"code": "burger", "name": "测试汉堡", "maxQuantity": -1}]},
            {"id": 2, "minQuantity": 1, "maxQuantity": 1, "choices": [
                {"code": "drink", "name": "测试饮料", "maxQuantity": -1}]}]}

    def test_builds_exact_slot_codes_without_mutating_detail(self):
        before = copy.deepcopy(self.detail)
        result = build_single_choice_combo(self.detail, {"1": "burger", "2": "drink"})
        self.assertEqual(self.detail, before)
        self.assertEqual("2", result["items"][0]["roundList"][1]["round"])
        self.assertEqual("unmatched", result["nutrition_status"])

    def test_rejects_unknown_missing_and_wrong_slot_selections(self):
        for selection in [{"1": "burger"}, {"1": "drink", "2": "burger"}, {"1": "invented", "2": "drink"}]:
            with self.assertRaises(ValueError):
                build_single_choice_combo(self.detail, selection)

    def test_rejects_unimplemented_slot_cardinality(self):
        self.detail["rounds"][0]["maxQuantity"] = 2
        with self.assertRaisesRegex(ValueError, "unsupported_round"):
            build_single_choice_combo(self.detail, {"1": "burger", "2": "drink"})

    def test_preserves_unselected_modification_keys(self):
        choice = {"modification": {"items": [{"minValues": 0, "maxValues": 1, "values": [
            {"code": "sauce", "minQuantity": 0, "maxQuantity": 1, "selectedQuantity": 0,
             "selectedKey": "0-1", "unselectedKey": "0-0"}]}]}}
        self.assertEqual({"values": [{"code": "sauce", "key": "0-0", "quantity": 0}]}, default_modification(choice))
