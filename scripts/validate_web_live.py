"""Read-only live acceptance through the same assistant API as the browser."""
import json
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from maimen.api import create_app

if sys.argv[1:] != ['--live']:
    raise SystemExit('Pass --live to allow real read-only MCP calls.')
logging.disable(logging.CRITICAL)
report = []
with TestClient(create_app('data/web-live-acceptance.sqlite3', live_enabled=True)) as client:
    session = client.post('/api/sessions', json={}).json()
    headers = {'Authorization':'Bearer ' + session['session_token']}
    url = '/api/sessions/' + session['snapshot']['session_id'] + '/assistant'
    for kind in ['campaigns', 'stores', 'menu', 'nutrition', 'coupons']:
        response = client.post(url, headers=headers, json={'request_id':'accept-' + kind, 'mode':'query',
            'query':{'kind':kind, 'keyword':'双层吉士' if kind == 'nutrition' else ''}})
        result = response.json()
        entry = {'kind':kind, 'http_status':response.status_code,
                 'items':len(result.get('facts', [{}])[0].get('items', [])) if response.is_success else None,
                 'error':result.get('error')}
        report.append(entry)
        print(json.dumps(entry, ensure_ascii=False), flush=True)
    response = client.post(url, headers=headers, json={'request_id':'accept-recommend', 'mode':'recommend',
        'preferences':{'budget_cents':3000,'main_category':'burger','drink':'no_sugar'}})
    data = response.json()
    recommendation = data.get('recommendation') or {}
    entry = {'kind':'recommend', 'http_status':response.status_code, 'status':recommendation.get('status'),
             'cards':len(recommendation.get('cards', [])), 'warnings':recommendation.get('warnings', []), 'error':data.get('error')}
    report.append(entry)
    print(json.dumps(entry, ensure_ascii=False), flush=True)
Path('artifacts/local/web-live-acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
if any(r['http_status'] != 200 for r in report):
    raise SystemExit(1)
