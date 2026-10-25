const PREFERENCE_FIELDS = ['city', 'location', 'store_code', 'budget_cents', 'main_category', 'drink', 'goal', 'reported_gold_card', 'max_energy_kcal', 'min_protein_g', 'exclude_codes', 'exclude_words', 'allergies'];

const NUTRITION_LABELS = {
  energy_kcal: '能量 / kcal', protein_g: '蛋白质 / g', fat_g: '脂肪 / g',
  carbohydrate_g: '碳水 / g', carbs_g: '碳水 / g', sodium_mg: '钠 / mg',
  energyKcal: '能量 / kcal', energyKj: '能量 / kJ', protein: '蛋白质 / g',
  fat: '脂肪 / g', carbohydrate: '碳水 / g', sodium: '钠 / mg', calcium: '钙 / mg',
};

const PRICE_LABELS = {
  productPrice: '商品金额', discount: '优惠', packingPrice: '打包费',
  deliveryPrice: '配送费', tablewarePrice: '餐具费',
};

const COUPON_STATUS = { CAN_GET: '可领取', AVAILABLE: '可用' };

const FACT_TITLES = {
  campaigns: '活动与上新线索', nutrition: '标准营养', menu: '门店菜单',
  coupons: '麦麦省优惠列表', stores: '门店查询',
};

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[character]));
}

const money = cents => `¥${(Number(cents) / 100).toFixed(2)}`;

export function nutritionLabel(key) {
  return NUTRITION_LABELS[key] || key;
}

export function mergePreference(current, incoming = {}) {
  const next = {};
  for (const key of PREFERENCE_FIELDS) {
    if (incoming[key] !== undefined) next[key] = incoming[key];
    else if (current?.[key] !== undefined) next[key] = current[key];
  }
  next.use_coupons = false;
  return next;
}

export function requestPreferences(current, extra = {}) {
  return {
    ...mergePreference(current, extra),
    keep_codes: extra.keep_codes ?? [],
    avoid_card_ids: extra.avoid_card_ids ?? [],
  };
}

export function rerollAvoidIds(skipped, cards) {
  const ids = [...(skipped || []), ...(cards || []).map(card => card?.id).filter(Boolean)];
  return [...new Set(ids)].slice(-30);
}

export function rememberedStore(previous, store) {
  const code = String(store?.storeCode || store?.store_code || '');
  const title = store?.storeName || store?.title || '';
  if (!/^\d{1,20}$/.test(code) || !title) return previous || {};
  const prior = previous?.[code] || {};
  return {...(previous || {}), [code]: {
    title,
    address: store.address || store.body || prior.address || '',
    opens: store.businessStartTime || store.opens || prior.opens || '',
    closes: store.businessEndTime || store.closes || prior.closes || '',
  }};
}

export function locationText(preferences, stores = {}) {
  const code = preferences?.store_code;
  const known = stores[code];
  const name = known?.title || (code === '1450398' ? '龙腾大道餐厅' : `门店 ${code}`);
  const hours = known?.opens && known?.closes ? ` · ${known.opens}–${known.closes}` : '';
  return `${preferences?.city || ''} · ${name}${hours}`;
}

export function metricMarkup(nutrition) {
  if (nutrition?.totals) {
    return `<span>${escapeHtml(nutrition.totals.energy_kcal)} kcal</span><span>蛋白质 ${escapeHtml(nutrition.totals.protein_g)} g</span>`;
  }
  const names = (nutrition?.unmatched || []).filter(Boolean);
  const text = names.length ? `营养未匹配：${names.join('、')}` : '营养数据未完整匹配';
  return `<span class="metrics-missing">${escapeHtml(text)}</span>`;
}

export function reasonMarkup(reasons) {
  const line = (reasons || []).find(Boolean);
  return line ? `<p class="meal-reason">${escapeHtml(line)}</p>` : '';
}

export function breakdownMarkup(fees) {
  const rows = Object.entries(fees || {}).filter(([, value]) => Number.isFinite(value));
  if (!rows.length) return '';
  return `<h3>费用组成</h3><ul class="detail-list">${rows.map(([key, value]) => `<li><span>${escapeHtml(PRICE_LABELS[key] || key)}</span><strong>${money(value)}</strong></li>`).join('')}</ul><p class="note">分项来自本次官方计价，不是节省金额的宣传。</p>`;
}

export function nutritionDetail(nutrition) {
  const unmatched = (nutrition?.unmatched || []).filter(Boolean);
  if (!nutrition?.totals) {
    const text = unmatched.length ? `未匹配：${unmatched.join('、')}` : '标准营养未完整匹配';
    return `<ul class="detail-list"><li>${escapeHtml(text)}</li></ul>`;
  }
  const rows = Object.entries(nutrition.totals).map(([key, value]) => `<li><span>${escapeHtml(nutritionLabel(key))}</span><strong>${escapeHtml(value)}</strong></li>`).join('');
  const pending = unmatched.length ? `<p class="note">未计入合计：${escapeHtml(unmatched.join('、'))}</p>` : '';
  return `<ul class="detail-list">${rows}</ul>${pending}`;
}

function factTitle(fact) {
  if (fact.kind === 'coupons' && !fact.scope) return '旧版门店券查询';
  return FACT_TITLES[fact.kind] || '查询结果';
}

function valueLine(values) {
  return Object.entries(values).map(([key, value]) => `${escapeHtml(nutritionLabel(key))} ${escapeHtml(value)}`).join(' · ');
}

function itemBody(fact, item) {
  if (fact.kind === 'campaigns') {
    const badge = item.new_product_evidence ? '上新线索' : '活动';
    return `<h3><span class="fact-badge">${badge}</span>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.date || '')} ${escapeHtml(item.body || '')}</p><p class="note">文案中的价格不是当前门店应付价。</p>`;
  }
  if (fact.kind === 'nutrition') {
    return `<h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.body || '')}</p>${item.values ? `<p>${valueLine(item.values)}</p>` : ''}`;
  }
  if (fact.kind === 'stores') {
    const hours = item.opens && item.closes ? `${item.opens}–${item.closes}` : '';
    const open = item.open === true ? '当前营业' : item.open === false ? '当前未显示营业' : '';
    return `<h3>${escapeHtml(item.title)}</h3><p>${[item.body, hours, open].filter(Boolean).map(escapeHtml).join(' · ')}</p>`;
  }
  if (fact.kind === 'menu') {
    return `<h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.body || '')}${item.code ? ` · 商品编码 ${escapeHtml(item.code)}` : ''}</p>`;
  }
  const status = COUPON_STATUS[item.status] || '';
  const statusText = status && !(item.body || '').includes(status) ? ` · ${status}` : '';
  return `<h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.body || '')}${escapeHtml(statusText)}</p>`;
}

export function factMarkup(fact) {
  const items = fact.items || [];
  const body = items.map(item => `<article class="saved-item">${itemBody(fact, item)}</article>`).join('') || '<p class="note">暂无匹配结果</p>';
  const warnings = (fact.warnings || []).map(warning => `<p class="notice">${escapeHtml(warning)}</p>`).join('');
  const when = fact.checked_at ? new Date(fact.checked_at).toLocaleString('zh-CN') : '';
  return `<details class="message-attachment"><summary>${escapeHtml(factTitle(fact))} · ${items.length} 条（展开查看）</summary><p class="note">${escapeHtml(fact.source || '')} · ${escapeHtml(when)} · 历史查询快照</p>${warnings}${body}</details>`;
}
