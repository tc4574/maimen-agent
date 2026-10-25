"""Read-only pickup menu integration, isolated from the demo harness."""
from jsonschema import validate


class PickupMenu:
    def __init__(self, client, tools):
        self.client = client
        self.schemas = {tool.name: tool.input_schema for tool in tools}

    async def _call(self, name, arguments):
        if name not in {"query-nearby-stores", "query-meals", "query-meal-detail", "calculate-price",
                        "query-store-coupons", "list-nutrition-foods"}:
            raise ValueError("read_only_menu_scope")
        validate(arguments, self.schemas[name])
        result = await self.client.call_tool(name, arguments)
        if result.is_error:
            raise ValueError("menu_tool_error")
        payload = result.structured_content
        if not isinstance(payload, dict) or payload.get("success") is not True or payload.get("code") != 200:
            raise ValueError("menu_business_response_not_successful")
        return payload

    async def search(self, city, keyword):
        if not city.strip() or not keyword.strip():
            raise ValueError("city_and_keyword_required")
        return await self._call("query-nearby-stores", {"beType": 1, "searchType": 2, "city": city, "keyword": keyword})

    @staticmethod
    def context(store_code):
        if not isinstance(store_code, str) or not store_code.strip() or store_code.startswith("demo-"):
            raise ValueError("real_store_code_required")
        return {"storeCode": store_code, "orderType": 1, "beType": 1}

    async def meals(self, store_code):
        return await self._call("query-meals", self.context(store_code))

    async def coupons(self, store_code):
        return await self._call("query-store-coupons", self.context(store_code))

    async def nutrition(self):
        return await self._call("list-nutrition-foods", {})

    async def detail(self, store_code, code):
        if not code or code.startswith("demo-"):
            raise ValueError("real_product_code_required")
        return await self._call("query-meal-detail", {**self.context(store_code), "code": code})

    async def calculate(self, store_code, items):
        if not isinstance(items, list) or not 1 <= len(items) <= 12:
            raise ValueError("invalid_items")
        for item in items:
            if not isinstance(item.get("productCode"), str) or not item["productCode"] or item["productCode"].startswith("demo-"):
                raise ValueError("real_product_code_required")
            if type(item.get("quantity")) is not int or not 1 <= item["quantity"] <= 10:
                raise ValueError("invalid_quantity")
        return await self._call("calculate-price", {**self.context(store_code), "items": items})
