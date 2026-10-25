import unittest
from fastapi.testclient import TestClient
from maimen.api import create_app


class Model:
    async def complete(self, messages, tools):
        return {'role':'assistant','content':'你好，我是 McBot。'}


class AssistantAPITests(unittest.TestCase):
    def test_auth_receipt_and_real_query_dispatch(self):
        calls=[]
        async def query(q):
            calls.append(q.kind)
            return {'kind':q.kind,'items':[],'warnings':[],'source':'test'}
        with TestClient(create_app(':memory:',live_enabled=True,query_runner=query,model=Model())) as c:
            session=c.post('/api/sessions',json={}).json()
            url='/api/sessions/'+session['snapshot']['session_id']+'/assistant'
            headers={'Authorization':'Bearer '+session['session_token']}
            body={'request_id':'test-query','mode':'query','query':{'kind':'campaigns'}}
            self.assertEqual(c.post(url,json=body).status_code,401)
            self.assertEqual(c.post(url,json=body,headers=headers).status_code,200)
            self.assertEqual(c.post(url,json=body,headers=headers).status_code,200)
            self.assertEqual(calls,['campaigns'])
            altered={**body,'text':'different'}
            self.assertEqual(c.post(url,json=altered,headers=headers).status_code,409)
            chat=c.post(url,json={'request_id':'chat','text':'你好'},headers=headers)
            self.assertEqual(chat.json()['reply'],'你好，我是 McBot。')
            self.assertEqual(c.post(url+'/clear',headers=headers).status_code,200)

    def test_cancellation_before_arrival_and_disabled_query(self):
        with TestClient(create_app(':memory:',live_enabled=False)) as c:
            session=c.post('/api/sessions',json={}).json()
            url='/api/sessions/'+session['snapshot']['session_id']+'/assistant'
            headers={'Authorization':'Bearer '+session['session_token']}
            c.post(url+'/cancel',json={'request_id':'cancelled'},headers=headers)
            self.assertEqual(c.post(url,json={'request_id':'cancelled','text':'hi'},headers=headers).status_code,409)
            result=c.post(url,json={'request_id':'query','mode':'query','query':{'kind':'campaigns'}},headers=headers)
            self.assertEqual(result.status_code,503)
