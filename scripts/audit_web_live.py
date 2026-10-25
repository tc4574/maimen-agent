"""Read-only API acceptance; isolated DB, no account/wallet/order/claim calls."""
import json
import logging
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from maimen.api import create_app

if sys.argv[1:] != ['--live']:
    raise SystemExit('Use --live to authorize read-only MCP and model acceptance.')
sys.stdout.reconfigure(encoding='utf-8')
logging.disable(logging.CRITICAL)
report = []
with TestClient(create_app('data/audit-live.sqlite3', live_enabled=True)) as c:
    session = c.post('/api/sessions', json={}).json()
    headers = {'Authorization': 'Bearer '+session['session_token']}
    url = '/api/sessions/'+session['snapshot']['session_id']+'/assistant'
    def run(name, body, check):
        start = time.monotonic()
        response = c.post(url, headers=headers, json={'request_id': name, **body})
        data = response.json()
        facts = data.get('facts', [])
        rec = data.get('recommendation') or {}
        passed = response.status_code == 200 and check(data)
        entry = {'case': name, 'status': response.status_code, 'passed': passed,
                 'seconds': round(time.monotonic()-start, 2),
                 'facts': [{'kind': f['kind'], 'count': len(f['items']), 'scope': f.get('scope')} for f in facts],
                 'cards': len(rec.get('cards', [])), 'store': rec.get('store', {}).get('storeName'),
                 'coupon_mode': rec.get('coupon_status')}
        report.append(entry)
        print(json.dumps(entry, ensure_ascii=False), flush=True)
        Path('artifacts/local/website-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        return data
    for kind in ['campaigns', 'stores', 'menu', 'nutrition', 'coupons']:
        run(kind, {'mode': 'query', 'query': {'kind': kind, 'keyword': '双层吉士' if kind == 'nutrition' else ''}},
            lambda d: bool(d['facts'][0]['items']))
    run('chat-offers', {'text': '查询最近有哪些麦麦省优惠券，只看优惠列表，不查个人卡包。'},
        lambda d: any(f['kind']=='coupons' and f.get('scope')=='offer_browsing_not_personal_wallet' and f['items'] for f in d['facts']))
    run('chat-nutrition', {'text': '请实时查双层吉士汉堡的标准营养，包括热量和蛋白质。'},
        lambda d: any(f['kind']=='nutrition' and f['items'] for f in d['facts']))
    first = run('recommend', {'mode': 'recommend', 'preferences': {'budget_cents': 3000, 'drink': 'any', 'main_category': 'any', 'use_coupons': True}},
        lambda d: len(d['recommendation']['cards'])==3 and not d['recommendation']['request']['use_coupons'])
    rec = first.get('recommendation') or {}
    if rec.get('cards'):
        run('choose-second', {'text': '选择当前推荐的第二套', 'run_id': rec['run_id']},
            lambda d: (d.get('action') or {}).get('card_id')==rec['cards'][1]['id'])
        old = {card['id'] for card in rec['cards']}
        run('reroll', {'mode': 'recommend', 'reroll': True, 'run_id': rec['run_id'], 'preferences': rec['request']},
            lambda d: bool(d['recommendation']['cards']) and not old.intersection(card['id'] for card in d['recommendation']['cards']))
    run('fitness-clarification', {'mode': 'recommend', 'preferences': {'goal': 'fitness'}},
        lambda d: d['recommendation']['status']=='clarification_required')
    run('allergy-boundary', {'mode': 'recommend', 'preferences': {'allergies': ['花生']}},
        lambda d: d['recommendation']['status']=='clarification_required')
if not all(e['passed'] for e in report):
    raise SystemExit(1)
