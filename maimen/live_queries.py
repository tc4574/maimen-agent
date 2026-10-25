"""Bounded read-only queries; no coupon codes, user addresses or executable HTML."""
import asyncio
import json
import re
from datetime import datetime, timezone
from html import unescape
from typing import Literal
from pydantic import Field
from jsonschema import validate
from .contracts import DTO
from .adapters.mcd import connect, discover, load_token
from .adapters.menu import PickupMenu
from .nutrition import parse_nutrition, normalized_name


class Query(DTO):
    kind: Literal['campaigns', 'stores', 'menu', 'nutrition', 'coupons']
    keyword: str = Field(default='', max_length=100)
    city: str = Field(default='上海', min_length=1, max_length=60)
    location: str = Field(default='麦当劳总部', min_length=1, max_length=100)
    store_code: str = Field(default='1450398', pattern=r'^\d{1,20}$')


def clean(value, limit=1200):
    if not isinstance(value, str):
        return ''
    return unescape(re.sub(r'<[^>]*>', '', value))[:limit].strip()


NEW_PRODUCT_CUES = ('新品', '上新', '来袭')
CAMPAIGN_WARNING = '日历日期不等于活动有效期。只有文案出现上新说法才标为上新线索。文案中的价格不是当前门店应付价，是否在售要另查菜单。'
MENU_EMPTY_WARNING = '当前门店菜单没有匹配到这个名称。活动文案中的价格不能当作本店应付价。'
MENU_CAP_WARNING = '菜单查询最多展示40个匹配商品；不是全部组合或报价。'


def has_new_product_cue(text):
    return any(cue in text for cue in NEW_PRODUCT_CUES)


def menu_warnings(count):
    return [MENU_EMPTY_WARNING if count == 0 else MENU_CAP_WARNING]


def normalize_campaigns(payload):
    data = payload.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('dailyList'), list):
        raise ValueError('unexpected_campaign_format')
    items = []
    for day in data['dailyList']:
        for event in day.get('events', []):
            article = event.get('articleDto') or {}
            title = clean(event.get('activityTitle') or article.get('title'), 160)
            body = clean(event.get('activitySubTitle'))
            content = clean(article.get('content'))
            if title:
                items.append({'title': title, 'body': '\n'.join(x for x in (body, content) if x),
                              'date': clean(day.get('date'), 20), 'kind': 'activity',
                              'new_product_evidence': has_new_product_cue(title + body + content)})
    # A calendar date is not an availability range, and an activity is not automatically a new product.
    return items[:60], len(items)



def normalize_available_coupons(payload):
    if payload.get('code') != 200 or payload.get('success') is False or not isinstance(payload.get('data'), list):
        raise ValueError('unexpected_available_coupons_format')
    return [{'title': clean(c.get('couponName'), 160),
             'body': clean(c.get('label')), 'status': clean(c.get('couponStatus'), 80)}
            for c in payload['data'] if isinstance(c, dict) and clean(c.get('couponName'))][:60]

async def live_query(query):
    async with asyncio.timeout(60):
        async with connect(load_token()) as client:
            tools = await discover(client)
            menu = PickupMenu(client, tools)
            result = {'kind': query.kind, 'source': '麦当劳 MCP',
                      'checked_at': datetime.now(timezone.utc).isoformat(), 'items': [], 'warnings': []}
            if query.kind in {'campaigns', 'coupons'}:
                name = 'available-coupons' if query.kind == 'coupons' else 'campaign-calendar'
                tool = next((t for t in tools if t.name == name), None)
                if tool is None:
                    raise ValueError('campaign_tool_unavailable')
                validate({}, tool.input_schema)
                response = await client.call_tool(name, {})
                if response.is_error:
                    raise ValueError('campaign_tool_failed')
                payload = response.structured_content
                if not isinstance(payload, dict):
                    payload = json.loads(next(c.text for c in response.content if getattr(c, 'type', '') == 'text'))
                if payload.get('code') != 200 or payload.get('success') is False:
                    raise ValueError('campaign_business_failure')
                if query.kind == 'coupons':
                    result['items'] = normalize_available_coupons(payload)
                    result['source'] = '麦当劳 MCP · 麦麦省优惠列表'
                    result['scope'] = 'offer_browsing_not_personal_wallet'
                    result['warnings'] = ['仅浏览优惠，不读取访客卡包、不领券。领取资格、有效期、适用门店与最终价格请在官方渠道核实；不把这些券自动计入推荐价格。']
                    return result
                result['items'], result['total'] = normalize_campaigns(payload)
                result['warnings'] = [CAMPAIGN_WARNING]
            elif query.kind == 'stores':
                payload = await menu.search(query.city, query.location)
                result['items'] = [{'title': clean(s.get('storeName'), 160), 'body': clean(s.get('address')),
                                    'store_code': s.get('storeCode'), 'open': s.get('businessStatus') is True,
                                    'opens': clean(s.get('businessStartTime'), 20),
                                    'closes': clean(s.get('businessEndTime'), 20)}
                                   for s in payload['data'][:30]]
            elif query.kind == 'menu':
                payload = await menu.meals(query.store_code)
                products = payload['data']['meals']
                result['items'] = [{'title': clean(p.get('name'), 160), 'code': code,
                                    'body': '当前门店菜单商品；具体组合和价格以官方计价为准。'}
                                   for code, p in products.items() if query.keyword in p.get('name', '')][:40]
                result['warnings'] = menu_warnings(len(result['items']))
            elif query.kind == 'nutrition':
                payload = await menu.nutrition()
                index = parse_nutrition(payload['data'])
                keyword = normalized_name(query.keyword)
                result['items'] = [{'title': name, 'values': value, 'body': '官方标准配方；请核对完整名称和规格。'}
                                   for name, value in index.items() if keyword in name and value is not None][:30]
                result['warnings'] = ['展示匹配的独立规格，不把相似名称自动当成同一商品；最多30项。']
            if query.kind == 'menu':
                result['store_code'] = query.store_code
            return result
