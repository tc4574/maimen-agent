import { conversationStore } from './conversations.mjs';
import { formatMessage, speechText } from './message-format.mjs';
import { createAnimationController } from './animation.mjs';
import { breakdownMarkup, factMarkup, locationText, mergePreference, metricMarkup, nutritionDetail, reasonMarkup, rememberedStore, requestPreferences, rerollAvoidIds } from './present.mjs';
const $ = (s) => document.querySelector(s);
const paths = {
 chat:'M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5 4v-4H3V6a2 2 0 0 1 2-2Z M7 9h10M7 13h6',
 heart:'M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z',
 clock:'M12 8v5l3 2 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
 settings:'M4 7h16M4 17h16 M9 4v6M16 14v6',
 pin:'M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 0 1 16 0Z M15 10a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
 mic:'M9 5a3 3 0 0 1 6 0v7a3 3 0 0 1-6 0ZM5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8',
 arrow:'M12 19V5M5 12l7-7 7 7',
 burger:'M3 9c0-8 18-8 18 0ZM2 13h20M3 17h18v2a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2ZM8 5h.1M15 6h.1M7 13l5 3 5-3',
 ticket:'M3 5h18v5a2 2 0 0 0 0 4v5H3v-5a2 2 0 0 0 0-4ZM15 5v2M15 10v4M15 17v2M6 9h5M6 14h3',
 spark:'m12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3ZM20 2v4M18 4h4',
 drink:'M5 8h14l-2 14H7ZM13 8l2-6h5M4 8h16',
 leaf:'M20 3C6 1 1 8 6 16s17 3 14-13ZM5 21 16 9',
};
const icon = (name) => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.burger}"/></svg>`;
document.querySelectorAll('[data-icon]').forEach(el => el.innerHTML = icon(el.dataset.icon));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = (n) => `¥${(n / 100).toFixed(2)}`;
const read = (key, fallback) => { try { return JSON.parse(localStorage.getItem(`mcbot.${key}`)) ?? fallback; } catch { return fallback; } };
const save = (key, value) => { try { localStorage.setItem(`mcbot.${key}`, JSON.stringify(value)); } catch { toast('本机存储不可用，本次内容仅在当前页面保留。'); } };
const threads=conversationStore(localStorage);
let activeThread=threads.current();
const defaults = {city:'上海',location:'麦当劳总部',store_code:'1450398',budget_cents:3000,main_category:'any',drink:'any',goal:'balanced',reported_gold_card:'unknown',use_coupons:false};
const state = {preferences:mergePreference(defaults, read('preferences',{})), favorites:read('favorites',[]), messages:activeThread.messages, cards:activeThread.cards||[], run:activeThread.run||null, selected:activeThread.selected||null, previous:null, session:activeThread.session||null, busy:false, generation:0, capabilities:{}, locks:activeThread.locks||[], skippedCardIds:activeThread.skippedCardIds||[], voice:false};
let ball, controller, recognition, toastTimer, opener;
try { ball = GrokBall.create('#bot', {emotion:'02',color:'#FFC72C',eyeColor:'#24211D',label:'McBot'}); } catch { $('#bot').textContent = 'McBot'; }
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
const animation = createAnimationController(mode => {
  $('#bot').dataset.state = mode;
  ball?.setActive(mode !== 'paused' && !reducedMotion);
  if (mode !== 'paused') ball?.setEmotion(({idle:'02',listening:'03',thinking:'30',speaking:'10',success:'33',error:'03'})[mode]);
});
function emotion(code) { if(code==='33'||code==='10')animation.flash('success');else if(code==='03')animation.flash('error'); }
window.addEventListener('pointermove', e => { if (e.pointerType !== 'mouse' || reducedMotion) return; const r = $('#bot').getBoundingClientRect(); ball?.setGaze((e.clientX-r.left-r.width/2)/(r.width/2),(e.clientY-r.top-r.height/2)/(r.height/2)); });
function toast(text) { $('#toast').textContent = text; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').hidden = true, 3500); }
function setStatus(text, code='02') { $('#status').textContent = text; if(code==='10'||code==='03')emotion(code); }
let speechGeneration = 0;
function cancelSpeech() {
  speechGeneration++;
  window.speechSynthesis?.cancel();
  animation.set({speaking:false});
  $('#stop-speech').hidden=true;
}
function say(text) {
  if (!state.voice || !('speechSynthesis' in window)) return;
  recognition?.abort(); cancelSpeech(); const generation=speechGeneration;
  const utterance = new SpeechSynthesisUtterance(speechText(text)); utterance.lang='zh-CN'; utterance.rate=1;
  utterance.onstart=()=>{if(generation===speechGeneration){animation.set({speaking:true,listening:false});$('#stop-speech').hidden=false;}};
  utterance.onend=utterance.onerror=() => { if(generation!==speechGeneration)return;animation.set({speaking:false});$('#stop-speech').hidden=true; if(state.voice) listen(); };
  speechSynthesis.speak(utterance);
}
function persistThread(){
  activeThread={...activeThread,messages:state.messages,cards:state.cards,run:state.run,selected:state.selected,locks:state.locks,skippedCardIds:state.skippedCardIds,session:state.session};
  if(activeThread.title==='新对话')activeThread.title=state.messages.find(m=>m.role==='user')?.text.slice(0,24)||'新对话';
  try{threads.save(activeThread);}catch{toast('本机存储空间不足，当前内容尚未全部保存，请勿关闭页面。');}
}
function addMessage(text, role='bot', attachments={}) {
  state.messages.push({id:crypto.randomUUID(),text,role,time:Date.now(),...attachments});
  persistThread();renderMessages();if(role==='bot')say(text);
}
function renderMessages(){
  const opened=new Set([...document.querySelectorAll('#conversation details[open]')].map(el=>el.dataset.key));
  $('#conversation').hidden=!state.messages.length;$('#main').classList.toggle('has-chat',!!state.messages.length);
  $('#conversation').innerHTML=state.messages.map((m,index)=>`<article class="message ${m.role==='user'?'user':'bot'}"><div class="message-text">${m.role==='user'?esc(m.text):formatMessage(m.text)}</div>${(m.facts||[]).map(factMarkup).join('')}${m.recommendation?`<details class="message-attachment"><summary>本轮推荐 · ${m.recommendation.cards?.length||0} 套</summary><p class="note">当时餐厅：${esc(m.recommendation.store?.storeName || m.recommendation.request?.store_code || '未记录')}</p>${(m.recommendation.cards||[]).map(c=>`<p>${esc(c.offer_name)}：${esc(components(c))} · 历史报价 ${money(c.amount_cents)}</p>`).join('')}<button class="secondary" data-restore-turn="${index}">查看这轮餐单</button></details>`:''}</article>`).join('');
  document.querySelectorAll('#conversation .message').forEach((el,index)=>el.querySelectorAll('details').forEach((details,j)=>{details.dataset.key=(state.messages[index].id||index)+':'+j;details.open=opened.has(details.dataset.key);}));
}
function switchThread(id){
  if(state.busy)return toast('请先取消当前查询，再切换对话。');
  persistThread();stopVoice();
  activeThread=id?threads.load(id):threads.create();if(!activeThread)return;
  Object.assign(state,{messages:activeThread.messages,cards:activeThread.cards||[],run:activeThread.run||null,selected:activeThread.selected||null,session:activeThread.session||null,locks:activeThread.locks||[],skippedCardIds:activeThread.skippedCardIds||[],previous:null});
  persistThread();closeDrawer();renderMessages();renderCards();renderSelection();setStatus('今日你“麦”了吗？');
}
function openDrawer(title, html) { opener=document.activeElement; $('#drawer-title').textContent=title; $('#drawer-body').innerHTML=html; if(!$('#drawer').open) $('#drawer').showModal(); document.body.classList.add('modal-open'); }
function closeDrawer() { $('#drawer').close(); }
$('#drawer').addEventListener('close',()=>{document.body.classList.remove('modal-open');opener?.focus();});
$('#close-drawer').onclick=closeDrawer;
$('#drawer').addEventListener('click',e=>{if(e.target===$('#drawer')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientY<r.top)closeDrawer();}});
const options = (values,current) => Object.entries(values).map(([v,t])=>`<option value="${v}" ${v===current?'selected':''}>${t}</option>`).join('');
function locationLabel(){ return locationText(state.preferences, read('stores',{})); }
function remember(store){ save('stores', rememberedStore(read('stores',{}), store)); }
function skippedNote(){
  if(!state.skippedCardIds.length) return '';
  return `<p class="note skipped-note">换一批会避开已看过的 ${state.skippedCardIds.length} 套。普通推荐仍会包含它们。<button type="button" class="text-button" data-action="show-skipped">清除避开记录</button></p>`;
}
function renderLocation(){ $('.location-label').textContent=locationLabel(); }
function settings(recommend=false) {
  if(state.busy)return toast('请先结束当前查询，再修改用餐条件。');
  const p=state.preferences;
  openDrawer(recommend?'今天想怎么吃？':'我的用餐偏好',`<p class="note">${recommend?'确认这些条件，我就去查门店菜单和实际价格。':'偏好保存在这台设备。每次推荐都可以修改。'}</p>${skippedNote()}<form id="preferences"><div class="field">用餐门店<strong>${esc(locationLabel())}</strong><button type="button" class="secondary" id="change-store">更换餐厅</button><small>到店自取 · 单人用餐</small></div><div class="form-row"><label class="field">这次预算（元）<input name="budget" type="number" min="0.01" max="1000" step="0.01" required value="${p.budget_cents/100}"></label><label class="field">主食品类<select name="main_category">${options({any:'都可以',burger:'汉堡',chicken:'鸡肉'},p.main_category)}</select></label></div><div class="form-row"><label class="field">饮料偏好<select name="drink">${options({any:'都可以',no_sugar:'无糖饮料',none:'不需要饮料'},p.drink)}</select></label><label class="field">更在意什么<select name="goal">${options({balanced:'均衡搭配',lower_price:'价格低一点',higher_protein:'蛋白质多一点',lower_energy:'热量低一点'},p.goal)}</select></label></div><label class="field">你有麦金卡吗？<select name="reported_gold_card">${options({unknown:'不确定',yes:'我有麦金卡',no:'没有'},p.reported_gold_card)}</select><small>这是你的自述。当前无法自动核验持卡权益，推荐不会套用未核实的会员价。</small></label><p class="notice">仅浏览优惠，不关联你的麦当劳账号、不读取个人卡包。推荐不自动使用个人券；价格以本次查询为参考。</p><button class="primary full" type="submit">${recommend?'确认条件，给我推荐':'保存偏好'}</button></form>`);
  $('#change-store').onclick=()=>storePicker(recommend,new FormData($('#preferences')));
  $('#preferences').onsubmit=e=>{e.preventDefault();const f=new FormData(e.target);state.preferences=mergePreference(p,{budget_cents:Math.round(Number(f.get('budget'))*100),main_category:f.get('main_category'),drink:f.get('drink'),goal:f.get('goal'),reported_gold_card:f.get('reported_gold_card')});save('preferences',state.preferences);closeDrawer();if(recommend) recommendMeals();else toast('偏好已保存，下次推荐时生效');};
}
function storePicker(recommend, draft){
  const p=state.preferences;
  openDrawer('选择用餐餐厅',`<form id="store-search"><label class="field">城市<input name="city" required maxlength="60" value="${esc(p.city)}"></label><label class="field">地址或地标<input name="location" required maxlength="100" value="${esc(p.location)}"></label><button class="primary full">搜索附近餐厅</button></form><p id="store-status" class="note" role="status">搜索后选择一家餐厅，保存即生效。</p><div id="store-results"></div><button id="back-preferences" class="secondary">返回用餐偏好</button>`);
  const form=$('#store-search'), results=$('#store-results'), status=$('#store-status');
  const back=()=>{if(state.busy)return toast('门店查询中，请稍候');settings(recommend);if(draft)for(const [key,value] of draft){const input=$('#preferences').elements.namedItem(key);if(input){if(input.type==='checkbox')input.checked=true;else input.value=value;}}};
  $('#back-preferences').onclick=back;
  form.onsubmit=async e=>{
    e.preventDefault();if(state.busy)return toast('请先结束当前查询');
    const data=new FormData(form), city=data.get('city').trim(), location=data.get('location').trim();
    if(!city||!location)return;
    state.busy=true;const button=form.querySelector('button');button.disabled=true;results.innerHTML='';status.textContent='正在查询真实门店…';
    try{
      const sid=await getSession();
      const response=await api(`/api/sessions/${sid}/assistant`,{request_id:crypto.randomUUID(),mode:'query',query:{kind:'stores',city,location},preferences:state.preferences});
      if(!form.isConnected)return;
      const stores=(response.facts||[]).flatMap(f=>f.kind==='stores'?f.items:[]).filter(s=>/^\d{1,20}$/.test(String(s.store_code)));
      status.textContent=stores.length?`找到 ${stores.length} 家餐厅，请选择。`:'没有找到餐厅，请换一个地址或地标。';
      results.innerHTML=stores.map((s,i)=>`<article class="saved-item"><h3>${esc(s.title)}</h3><p>${esc(s.body)}</p><p class="note">${s.open?'当前营业':'当前未显示营业，推荐时需核实供应'}</p><button class="secondary" data-store-index="${i}">选择这家</button></article>`).join('');
      results.onclick=e=>{
        const b=e.target.closest('[data-store-index]');if(!b)return;if(state.busy)return;
        const store=stores[+b.dataset.storeIndex], code=String(store.store_code);
        const changed=code!==state.preferences.store_code;
        state.preferences=mergePreference(state.preferences,{city,location,store_code:code});
        if(changed){state.cards=[];state.run=null;state.selected=null;state.previous=null;state.locks=[];state.skippedCardIds=[];}
        remember({store_code:code,title:store.title,address:store.body,opens:store.opens,closes:store.closes});save('preferences',state.preferences);
        persistThread();renderLocation();renderCards();renderSelection();back();toast('餐厅已切换，后续查询按新餐厅进行');
      };
    }catch{if(form.isConnected)status.textContent='门店查询失败，请重试。当前餐厅未改变。';}
    finally{state.busy=false;button.disabled=false;}
  };
}
async function api(path, body, signal) {
  const headers={};if(body!==undefined)headers['Content-Type']='application/json';if(state.session)headers.Authorization=`Bearer ${state.session.session_token}`;
  const response=await fetch(path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body),signal});
  const data=await response.json();if(!response.ok)throw new Error(data.error?.code||'network_error');return data;
}
async function getSession(signal) { if(!state.session){const created=await api('/api/sessions',{},signal);state.session={session_token:created.session_token,snapshot:{session_id:created.snapshot.session_id}};persistThread();} return state.session.snapshot.session_id; }
const errors={live_recommendations_disabled:'真实推荐尚未启用。请在本机服务启用后再试；我不会拿演示价格来凑数。',recommendation_in_progress:'上一轮查询还在处理中，请稍后再试。',recommendation_timeout:'这次查询超时了。可以保留条件再试一次。',recommendation_provider_failed:'门店数据暂时没有查询成功，请稍后重试。',invalid_session_credentials:'本机会话已失效，请再试一次。',invalid_request:'这些条件暂时无法提交，请重新确认。'};
async function recommendMeals(feedback=false, keep=state.locks) {
  if(state.busy)return toast('请等待当前查询完成');
  addMessage(feedback?'按当前条件再换一批搭配。':`请按已确认的用餐条件推荐：${locationLabel()}，预算 ${money(state.preferences.budget_cents)}。`,'user');
  const avoid=feedback?rerollAvoidIds(state.skippedCardIds,state.cards):[];
  return requestAssistant({mode:'recommend',reroll:feedback,preferences:requestPreferences(state.preferences,{keep_codes:keep,avoid_card_ids:avoid})});
}
async function requestAssistant(payload) {
  if(state.busy)return toast('上一轮正在处理，请先取消或稍后再试。');
  state.busy=true;const generation=++state.generation;
  const requestId=crypto.randomUUID();state.activeRequest=requestId;
  controller=new AbortController();animation.set({querying:true,feedback:null});
  setStatus('正在查询和整理回答…');
  $('#connection').innerHTML='正在处理 <button class="text-button" data-action="cancel">取消</button>';
  try {
    const sid=await getSession(controller.signal);
    const result=await api(`/api/sessions/${sid}/assistant`,{
      request_id:requestId,preferences:requestPreferences(state.preferences,{keep_codes:state.locks}),
      run_id:state.run,selected_id:state.run?state.selected?.id||null:null,...payload
    },controller.signal);
    if(generation!==state.generation)return;
    if(result.recommendation){const r=result.recommendation;if(payload.reroll)state.skippedCardIds=rerollAvoidIds(state.skippedCardIds,state.cards);state.previous={cards:state.cards,selected:state.selected,run:state.run};if(r.store)remember(r.store);state.cards=r.cards||[];state.run=r.run_id;state.selected=null;state.preferences=mergePreference(state.preferences,r.request);save('preferences',state.preferences);renderLocation();renderCards();renderSelection();}
    if(result.action?.type==='select'){const i=state.cards.findIndex(c=>c.id===result.action.card_id);if(i>=0)selectCard(i);}
    addMessage(result.reply,'bot',{facts:result.facts||[],recommendation:result.recommendation||null});setStatus('今日你“麦”了吗？','10');
  } catch(e){if(e.name!=='AbortError'&&generation===state.generation){const messages={model_not_configured:'请在项目 .env.deepseek 文件中填写 DEEPSEEK_API_KEY，保存后即可开始自由对话。推荐和活动查询不需要模型 Key。',model_auth_failed:'DeepSeek Key 无效，请检查本机配置。',model_insufficient_balance:'DeepSeek 账户余额不足。',model_rate_limited:'模型请求较多，请稍后再试。',assistant_cancelled:'本轮已取消。',assistant_query_failed:'MCP 查询暂未成功，请检查连接或稍后重试。',assistant_timeout:'本轮查询超时，请重试。'};addMessage(messages[e.message]||errors[e.message]||'服务暂时不可用，请稍后再试。');setStatus('这次没有完成，可以重试。','03');}}
  finally{if(generation===state.generation){state.busy=false;state.activeRequest=null;animation.set({querying:false});connectionLabel();if(state.voice)setTimeout(listen,400);}}
}
function connectionLabel(){ $('#connection').textContent=(state.capabilities.recommendations?'MCP 实时查询已启用':'实时查询未启用')+' · '+(state.capabilities.conversation?'DeepSeek 已配置':'请填写 DeepSeek Key 开启自由对话'); }
const components = c => c.components.map(x=>`${x.name}${x.quantity>1?` ×${x.quantity}`:''}`).join(' + ');
function renderCards(){
  const target=$('#results');
  target.hidden=!state.cards.length;
  target.innerHTML=`<div class="section-heading"><h2>这次的美味灵感</h2><div class="heading-actions"><button class="text-button" data-action="reroll">换一批 ↻</button></div></div>${skippedNote()}<div class="cards">${state.cards.map((c,i)=>`<article class="meal-card"><span class="card-number">${i+1}</span><div class="meal-art">${icon('burger')}${icon('drink')}</div><div class="meal-content"><h3>${esc(c.offer_name)}</h3><p>${esc(components(c))}</p><div class="price">${money(c.amount_cents)}</div><span class="quote-state" data-expiry="${c.valid_until}"></span>${reasonMarkup(c.reasons)}<div class="metrics">${metricMarkup(c.nutrition)}</div><div class="card-actions"><button class="primary" data-select="${i}">就选这套</button><button class="secondary" data-detail="${i}">看详情</button></div></div></article>`).join('')}</div>`;
  updateExpiry();
}
function updateExpiry(){document.querySelectorAll('[data-expiry]').forEach(el=>el.textContent=Date.now()/1000>=Number(el.dataset.expiry)?'历史报价 · 需重新查询':'本次官方计价 · 非保价承诺');}
setInterval(updateExpiry,1000);
function selectCard(i){const c=state.cards[i];if(!c)return;state.previous={cards:state.cards,selected:state.selected,run:state.run};state.selected=c;renderSelection();persistThread();toast('已选中，可以查看详情或收藏');emotion('33');}
function renderSelection(){const el=$('#selection');el.hidden=!state.selected;el.innerHTML=state.selected?`<span>已选：${esc(state.selected.offer_name)}</span><button data-action="undo">撤回</button><button class="primary" data-action="save">收藏搭配</button>`:'';}
function details(i){
  const c=state.cards[i];if(!c)return;
  const reasons=(c.reasons||[]).map(line=>`<li>${esc(line)}</li>`).join('');
  openDrawer(c.offer_name,`<p class="notice">${money(c.amount_cents)} · ${Date.now()/1000>=c.valid_until?'历史报价，需要重新查询':'本次官方计价'}<br>报价时间：${new Date(c.quoted_at*1000).toLocaleString('zh-CN')}<br>本地展示期限不代表官方保价。</p>${reasons?`<h3>推荐理由</h3><ul class="detail-list">${reasons}</ul>`:''}${breakdownMarkup(c.price_breakdown_cents)}<h3>这套有什么</h3><ul class="detail-list">${c.components.map(x=>`<li><span>${esc(x.name)} ×${esc(x.quantity||1)}</span><button class="secondary" data-lock="${esc(x.code)}">${state.locks.includes(x.code)?'取消保留':'下轮保留'}</button></li>`).join('')}</ul><p class="note">保留表示下轮搭配包含这个商品；当前还不能直接修改套餐槽位。</p><h3>营养与优惠</h3>${nutritionDetail(c.nutrition)}<p class="note">${c.coupon?.used_in_calculation?`已使用：${esc(c.coupon.title)}`:'本次未使用优惠券'}<br>麦金卡权益：尚未核实</p><button class="primary full" data-select="${i}">选这套搭配</button>`);
}
function saveFavorite(){if(!state.selected)return;openDrawer('把好吃的记下来',`<form id="save-form"><label class="field">给这套搭配起个名字<input name="name" maxlength="40" required value="${esc(state.selected.offer_name)}"></label><p class="note">保存餐品组成，下次使用会重新查询供应和价格。</p><button class="primary full">保存收藏</button></form>`);$('#save-form').onsubmit=e=>{e.preventDefault();state.favorites.unshift({id:crypto.randomUUID(),name:new FormData(e.target).get('name'),card:state.selected,time:Date.now()});save('favorites',state.favorites);closeDrawer();toast('已收进你的小口袋');};}
function favorites(){openDrawer('我的美味收藏',state.favorites.length?state.favorites.map((f,i)=>`<article class="saved-item"><h3>${esc(f.name)}</h3><p>${esc(components(f.card))}</p><p>收藏于 ${new Date(f.time).toLocaleDateString('zh-CN')} · 价格需重新查询</p><button class="primary" data-reuse="${i}">按这套重新找</button> <button class="text-button" data-delete="${i}">删除</button></article>`).join(''):`<div class="empty">${icon('heart')}<h3>给喜欢的味道留个位</h3><p>选中推荐餐单后，点击「收藏搭配」。<br>下一次不用再从头想。</p><button class="primary" data-action="recommend">找一套喜欢的</button></div>`);}
function history(){openDrawer('我的对话',`<button class="primary full" data-action="new-chat">＋ 新建对话</button><p class="note">文字、语音和查询结果一起保存在各自对话中。切换语音不会新建或清空对话。</p>${threads.list().map(t=>`<article class="saved-item"><button class="thread-choice" data-thread="${esc(t.id)}"><strong>${esc(t.title)}</strong><small>${t.id===activeThread.id?'当前对话 · ':''}${new Date(t.updated).toLocaleString('zh-CN')}</small></button></article>`).join('')}<button class="text-button" data-action="clear-history">清空当前对话</button>`);}
function handleText(text){text=text.trim();if(!text)return;if(state.busy)return toast('请先取消当前查询，再发送新消息。');addMessage(text,'user');$('#message').value='';cancelSpeech();requestAssistant({mode:'chat',text});}
function directQuery(kind){if(state.busy)return toast('请等待当前查询完成');addMessage(kind==='campaigns'?'最近有什么活动和上新？':'最近有哪些麦麦省优惠？','user');requestAssistant({mode:'query',query:{kind,city:state.preferences.city||'上海',location:state.preferences.location||'麦当劳总部',store_code:state.preferences.store_code||'1450398'}});}
const actions={'new-chat':()=>switchThread(null),greet:()=>{emotion('10');toast('我在呢，今天想吃点什么？');},home:()=>{closeDrawer();window.scrollTo({top:0,behavior:reducedMotion?'instant':'smooth'});},settings:()=>settings(),recommend:()=>settings(true),favorites,history,new:()=>directQuery('campaigns'),deals:()=>directQuery('coupons'),reroll:()=>recommendMeals(true),'show-skipped':()=>{state.skippedCardIds=[];persistThread();renderCards();document.querySelectorAll('.skipped-note').forEach(el=>el.remove());toast('已清除避开记录，之后换一批可以再看到这些搭配');},save:saveFavorite,undo:()=>{if(!state.previous)return toast('还没有可以撤回的选择');state.cards=state.previous.cards;state.selected=state.previous.selected;state.run=state.previous.run;state.previous=null;renderCards();renderSelection();persistThread();toast('已恢复上一步；历史价格以重新查询为准');},cancel:()=>{if(state.session&&state.activeRequest)api(`/api/sessions/${state.session.snapshot.session_id}/assistant/cancel`,{request_id:state.activeRequest}).catch(()=>{});controller?.abort();state.generation++;state.busy=false;animation.set({querying:false,feedback:null});connectionLabel();setStatus('已停止等待。');toast('已停止等待并发送取消请求。');},'clear-history':async()=>{if(state.busy)return toast('请先结束当前查询');if(state.session){try{await api(`/api/sessions/${state.session.snapshot.session_id}/assistant/clear`,{});}catch{return toast('清理服务端上下文失败，请重试');}}state.messages=[];state.cards=[];state.run=null;state.selected=null;state.locks=[];state.skippedCardIds=[];state.previous=null;activeThread.title='新对话';persistThread();renderMessages();renderCards();renderSelection();history();}};
document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;const d=b.dataset;if(d.thread){switchThread(d.thread);return;}if(d.restoreTurn!==undefined){if(state.busy)return toast('请先结束本轮查询');const r=state.messages[+d.restoreTurn]?.recommendation;if(r){state.cards=r.cards||[];state.run=r.run_id;state.selected=null;persistThread();renderCards();renderSelection();$('#results').scrollIntoView({behavior:'smooth'});}return;}if(d.action){actions[d.action]?.();return;}if(d.select!==undefined){selectCard(+d.select);if($('#drawer').open)closeDrawer();}if(d.detail!==undefined)details(+d.detail);if(d.lock){const j=state.locks.indexOf(d.lock);if(j<0){if(state.locks.length>=6)return toast('最多保留六个商品');state.locks.push(d.lock);}else state.locks.splice(j,1);b.textContent=j<0?'取消保留':'下轮保留';persistThread();}if(d.delete!==undefined){state.favorites.splice(+d.delete,1);save('favorites',state.favorites);favorites();}if(d.reuse!==undefined){const f=state.favorites[+d.reuse];state.locks=[...new Set(f.card.components.map(x=>x.code))].slice(0,6);closeDrawer();addMessage('我会按收藏中的商品重新查找搭配；当前门店不一定仍有相同规格或套餐。');settings(true);}});
$('#composer').onsubmit=e=>{e.preventDefault();handleText($('#message').value);};
function stopVoice(){state.voice=false;recognition?.abort();cancelSpeech();animation.set({listening:false});$('#voice').classList.remove('on');$('#voice').setAttribute('aria-label','开始语音对话');$('#stop-speech').hidden=true;$('#voice-hint').textContent='打字或说话，按你的节奏来';setStatus('语音已结束，可以继续打字。');}
function listen(){if(!state.voice||state.busy||document.hidden||window.speechSynthesis?.speaking||window.speechSynthesis?.pending)return;try{recognition.start();setStatus('我在听，说吧…','03');}catch{}}
const SpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition;
if(SpeechRecognition){recognition=new SpeechRecognition();recognition.lang='zh-CN';recognition.interimResults=true;recognition.continuous=false;recognition.onstart=()=>animation.set({listening:true});recognition.onresult=e=>{let final='',interim='';for(let i=e.resultIndex;i<e.results.length;i++){if(e.results[i].isFinal)final+=e.results[i][0].transcript;else interim+=e.results[i][0].transcript;}if(interim)$('#voice-hint').textContent=interim;if(final){recognition.abort();handleText(final);}};recognition.onerror=e=>{if(e.error==='aborted')return;stopVoice();toast(e.error==='not-allowed'?'麦克风权限未开启，可以继续打字。':'语音识别暂时不可用，请重试或打字。');};recognition.onend=()=>{animation.set({listening:false});if(state.voice&&!window.speechSynthesis?.speaking)setTimeout(listen,400);};}
$('#voice').onclick=()=>{if(!SpeechRecognition)return toast('此浏览器暂不支持语音识别，请使用文字输入。');if(state.voice)return stopVoice();state.voice=true;$('#voice').classList.add('on');$('#voice').setAttribute('aria-label','结束语音对话');$('#voice-hint').textContent='语音已开启 · 再点麦克风退出';listen();};
$('#stop-speech').onclick=()=>{cancelSpeech();listen();};
document.addEventListener('visibilitychange',()=>{if(document.hidden&&state.voice)stopVoice();animation.set({hidden:document.hidden});});
window.visualViewport?.addEventListener('resize',()=>{document.body.classList.toggle('keyboard-open',innerHeight-window.visualViewport.height>140);});
renderLocation();renderMessages();renderCards();renderSelection();api('/api/capabilities').then(c=>{state.capabilities=c;connectionLabel();}).catch(()=>{$('#connection').textContent='本机服务未连接 · 请通过启动脚本打开网页';});

