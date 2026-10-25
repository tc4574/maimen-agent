import test from 'node:test';
import assert from 'node:assert/strict';
import {conversationStore} from '../web/conversations.mjs';
import {formatMessage, speechText} from '../web/message-format.mjs';

test('28 query items survive voice/text follow-ups, reload and a separate conversation',()=>{
  const values=new Map();const storage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)};
  let id=0;const store=conversationStore(storage,()=>String(++id));
  const first=store.current();first.session={session_token:'test',snapshot:{session_id:'session-a'}};
  first.messages.push({role:'bot',text:'28条',facts:[{items:Array.from({length:28},(_,i)=>({title:String(i)}))}]});
  first.messages.push({role:'user',text:'语音追问'}, {role:'bot',text:'回答'});store.save(first);
  assert.equal(store.current().messages[0].facts[0].items.length,28);
  const second=store.create();assert.equal(second.messages.length,0);assert.equal(second.session,null);
  assert.equal(store.load(first.id).session.snapshot.session_id,'session-a');
  assert.equal(store.load(first.id).messages[0].facts[0].items.length,28);
});
test('legacy history is migrated without truncating it',()=>{
  const values=new Map([['mcbot.messages',JSON.stringify(Array.from({length:100},()=>({role:'user',text:'旧记录'})))]]);
  const storage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)};
  assert.equal(conversationStore(storage,()=> 'first').current().messages.length,100);
});
test('formatting renders emphasis and lists without permitting HTML or scripts',()=>{
  const html=formatMessage('## 新品\n**汉堡**\n* 一份\n<img src=x onerror=alert(1)>\n[跳转](javascript:alert(1))');
  assert.ok(html.includes('<strong>汉堡</strong>'));assert.ok(html.includes('message-bullet'));
  assert.ok(!html.includes('<img'));assert.ok(!html.includes('<a'));
  assert.equal(speechText('**汉堡**，*好吃*，`套餐`'),'汉堡，好吃，套餐');
  assert.ok(formatMessage('2 * 3 = 6').includes('2 * 3 = 6'));
});
