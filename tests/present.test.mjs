import test from 'node:test';
import assert from 'node:assert/strict';
import { breakdownMarkup, factMarkup, locationText, mergePreference, metricMarkup, nutritionDetail, rememberedStore, requestPreferences, rerollAvoidIds } from '../web/present.mjs';

test('ordinary preferences do not keep reroll exclusions', () => {
  const stored = mergePreference(
    {city:'上海', store_code:'1', budget_cents:3000, avoid_card_ids:['old']},
    {budget_cents:4000, avoid_card_ids:['shown'], use_coupons:true, seed:3},
  );
  assert.equal(stored.budget_cents, 4000);
  assert.equal(stored.use_coupons, false);
  assert.equal('avoid_card_ids' in stored, false);
  const request = requestPreferences(stored, {keep_codes:['1450'], avoid_card_ids:[]});
  assert.deepEqual(request.avoid_card_ids, []);
  assert.deepEqual(request.keep_codes, ['1450']);
  assert.deepEqual(rerollAvoidIds(['a'], [{id:'b'}, {id:'a'}]), ['a', 'b']);
});

test('returned store name and hours replace a bare store code', () => {
  const stores = rememberedStore({}, {storeCode:'3330001', storeName:'西岸传媒港餐厅', businessStartTime:'07:00', businessEndTime:'22:00'});
  assert.equal(locationText({city:'上海', store_code:'3330001'}, stores), '上海 · 西岸传媒港餐厅 · 07:00–22:00');
});

test('cards and facts show returned fields in Chinese', () => {
  const metrics = metricMarkup({status:'incomplete', unmatched:['高达吉士双牛堡'], totals:null});
  assert.match(metrics, /高达吉士双牛堡/);
  const detail = nutritionDetail({totals:{carbohydrate_g:39, energy_kcal:371}});
  assert.match(detail, /碳水/);
  assert.equal(detail.includes('carbohydrate_g'), false);
  const fees = breakdownMarkup({productPrice:1390, discount:200});
  assert.match(fees, /商品金额/);
  assert.match(fees, /¥2\.00/);
  const facts = factMarkup({kind:'campaigns', source:'麦当劳 MCP', checked_at:'2026-10-24T00:00:00Z', warnings:['文案价格'], items:[
    {title:'龙焰鸡腿堡', new_product_evidence:true, body:'26.9元起'},
    {title:'周末派对', new_product_evidence:false, body:'到店'},
  ]});
  assert.match(facts, /上新线索/);
  assert.match(facts, /<span class="fact-badge">活动<\/span>/);
  assert.match(facts, /不是当前门店应付价/);
  assert.equal(facts.includes('<script'), false);
});
