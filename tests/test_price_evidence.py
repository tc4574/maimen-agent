import unittest
from maimen.price_evidence import inspect_calculation, inspect_menu_offer


class PriceEvidenceTests(unittest.TestCase):
    def test_card_purchase_offer_does_not_prove_ownership(self):
        evidence = inspect_menu_offer({"currentPrice": "28", "canWithOrder": True,
            "withOrder": {"membershipCode": "106"}, "discountType": "随单购麦金卡优惠"})
        self.assertEqual("unknown", evidence["card_status"])
        self.assertTrue(evidence["requires_offer_review"])
        self.assertFalse(evidence["menu_price_is_payable_price"])

    def test_no_card_offer_does_not_prove_no_card(self):
        self.assertEqual("unknown", inspect_menu_offer({"canWithOrder": False})["card_status"])

    def test_successful_quote_is_not_complete_verification(self):
        result = inspect_calculation({"success": True, "code": 200, "data": {
            "price": 1490, "productList": [{"productCode": "combo", "quantity": 1}]}},
            [{"productCode": "combo", "quantity": 1}])
        self.assertEqual(1490, result["reported_amount_cents"])
        self.assertFalse(result["recommendation_eligible"])
        self.assertFalse(result["child_selections_verified"])

    def test_wrong_product_and_invalid_currency_types_rejected(self):
        items = [{"productCode": "combo", "quantity": 1}]
        for amount, code in [(14.9, "combo"), (True, "combo"), (1490, "different")]:
            with self.assertRaises(ValueError):
                inspect_calculation({"success": True, "code": 200, "data": {
                    "price": amount, "productList": [{"productCode": code, "quantity": 1}]}}, items)
