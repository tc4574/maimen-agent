import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient
from maimen.api import create_app
from maimen.live_queries import Query, live_query, menu_warnings, normalize_available_coupons, normalize_campaigns


class OfferTests(unittest.IsolatedAsyncioTestCase):
    async def test_offer_query_never_reads_wallet_or_store_coupons(self):
        calls = []
        class Client:
            async def call_tool(self, name, args):
                calls.append((name, args))
                return SimpleNamespace(is_error=False, structured_content={
                    'code': 200, 'data': [{'couponName': '<b>测试优惠</b>', 'label': '限时',
                    'couponStatus': 'AVAILABLE', 'couponCode': 'private', 'couponId': 'private'}]})
        @asynccontextmanager
        async def connect(token):
            yield Client()
        async def discover(client):
            return [SimpleNamespace(name='available-coupons', input_schema={'type': 'object'})]
        with patch('maimen.live_queries.connect', connect), patch('maimen.live_queries.discover', discover), patch('maimen.live_queries.load_token', return_value='test'):
            result = await live_query(Query(kind='coupons'))
        self.assertEqual(calls, [('available-coupons', {})])
        self.assertEqual(result['items'][0]['title'], '测试优惠')
        self.assertNotIn('private', str(result))
        self.assertNotIn('store_code', result)

    def test_campaign_cue_and_empty_menu_warning_stay_separate(self):
        items, total = normalize_campaigns({'data': {'dailyList': [{'date': '2026-10-24', 'events': [
            {'activityTitle': '龙焰鸡腿堡来袭', 'activitySubTitle': '26.9元起', 'articleDto': {}},
            {'activityTitle': '周末派对', 'activitySubTitle': '到店活动', 'articleDto': {}},
        ]}]}})
        self.assertEqual(total, 2)
        self.assertTrue(items[0]['new_product_evidence'])
        self.assertFalse(items[1]['new_product_evidence'])
        self.assertIn('不能当作本店应付价', menu_warnings(0)[0])
        self.assertIn('40', menu_warnings(4)[0])

    def test_empty_success_and_business_failure_are_distinct(self):
        self.assertEqual(normalize_available_coupons({'code': 200, 'data': []}), [])
        with self.assertRaises(ValueError):
            normalize_available_coupons({'code': 500, 'data': []})
        with self.assertRaises(ValueError):
            normalize_available_coupons({'code': 200, 'data': None})

    def test_website_forces_personal_coupon_opt_out(self):
        seen = []
        async def runner(req):
            seen.append(req.use_coupons)
            return {'cards': [], 'request': req.model_dump()}
        with TestClient(create_app(':memory:', live_enabled=True, recommendation_runner=runner)) as c:
            session = c.post('/api/sessions', json={}).json()
            url = '/api/sessions/' + session['snapshot']['session_id']
            headers = {'Authorization': 'Bearer ' + session['session_token']}
            direct = c.post(url+'/recommendations', headers=headers, json={'use_coupons': True})
            chat = c.post(url+'/assistant', headers=headers, json={'request_id': 'offer-test', 'mode': 'recommend', 'preferences': {'use_coupons': True}})
            self.assertEqual(direct.status_code, 200)
            self.assertEqual(chat.status_code, 200)
            self.assertEqual(seen, [False, False])
