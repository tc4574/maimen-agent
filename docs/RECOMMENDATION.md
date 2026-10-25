# 真实 MCP 推荐后端 v1

2026-10-17。已实现结构化需求 → 门店核验 → 菜单/营养/券 → 合法候选 → 官方计价 → 至多三套 → 保留条件再次推荐。

首版范围是**本机 MCP 账号、单人、立即到店自取**。默认联调上海麦当劳总部所在的龙腾大道餐厅1450398。无需模型 Key；自由语言解析、角色页面和语音仍未实现。模型未来只负责将表达转成相同的结构化请求，不能自行填写价格或会员权益。

## 已实现的数据与规则

| 数据 | 来源 | 实际用途与限制 |
| --- | --- | --- |
| 门店与营业状态 | query-nearby-stores | 按城市/地点核对指定 storeCode，暂停营业时停止即时推荐，不推断用户坐标 |
| 菜单、品类、标签 | query-meals | 排除周边、多人餐、儿童餐和未核实权益商品；保留官方分类。餐品名称规则辅助识别主食/饮料，不用于过敏原判断 |
| 套餐槽位和特制 | query-meal-detail | 只选该槽位允许项；保留默认特制。支持单品及每轮恰选1项的套餐，复杂数量结构拒绝并统计 |
| 菜单标价 | query-meals | 仅用于搜索排序，不直接筛掉高标价商品，不作为最终价格 |
| 最终报价 | calculate-price | 按完整组合及适用券计价；整数分、父商品与数量、商品小计/费用类型校验；预算用返回price判断 |
| 当前门店可用券 | query-store-coupons | 核对期限、couponId/couponCode与适用productCode；支持普通菜单外的券商品。单次计价最多使用一张券，不自行计算折扣或猜叠券规则 |
| 营养 | list-nutrition-foods | 校验表头、列数、160等返回声明数量及非负数值；只做名称/规格精确匹配，允许空白和全半角规范化，不模糊猜规格 |
| 麦金卡等权益 | 当前无明确持卡契约 | 状态保持unknown；用户自述单独记录。随单购卡入口不等于已持卡，相关商品全部排除 |
| 团餐促销 | query-promotions | 仅beType=6有效，本版beType=1不调用，不能将团餐满减用于自取 |

不调用自动领券、购卡、积分兑换、抽奖、创建/取消订单。原demo harness不接收live商品；新增推荐结果独立存储。

## 输入条件

完整例子见 `examples/recommendation.json`。主要字段：

- `budget_cents`：硬预算，整数分；`main_category`：burger/chicken/any。
- `drink`：any/no_sugar/none；no_sugar要求饮料名称明确含“无糖”，不推断咖啡或茶的糖量，也不表示整餐无糖。
- `goal`：balanced/lower_price/higher_protein/lower_energy。fitness含义不明时返回clarification_required，要求明确目标。
- `min_protein_g`、`max_energy_kcal`：硬营养门槛，缺少匹配数据的候选不可通过。输出同时保留脂肪、碳水和钠数据。
- `keep_codes`：最终组成中必须包含的实际商品code；`exclude_codes`、`exclude_words`：排除商品或名称关键词。关键词排除不等于医学避敏。
- `avoid_card_ids`：不再推荐的组成；`seed`：有限候选采样顺序，固定输入、数据和规则版本时可复现。
- `use_coupons`：是否查询并尝试已拥有且当前门店可用的券。
- `reported_gold_card`：unknown/yes/no，只有自述意义，不能绕过权益校验。
- `allergies`：目前返回数据能力不足的澄清，不生成承诺避敏的推荐。

当前请求只接受people=1、order_type=1、be_type=1，不支持配送/预约/多人用餐。

## 搜索、排序和准确性

默认最多读取18个餐品详情，每个详情最多枚举256种合法组合；生成候选后按硬条件筛选。保留主食的多样性，优先对可能符合预算的候选计价，最多12个候选、30次计价，总工具调用上限80、单次30秒、整轮180秒。

先考虑优惠券映射，再用菜单估计值排序，但不把估计值当硬预算筛选依据。每个候选比较无券与最多两张匹配券分别计算的结果，取成功计价中较低的金额；不把未计价的券面金额写为已节省。券专用商品必须携带匹配券，多个券专用商品组合若不能在单券规则下覆盖全部则跳过。

最终按目标排序、优先不同主食、再补组成不同的候选；等价组成跨套餐编码去重，保留本轮较低实时报价。不足三套返回partial/no_candidates和排除原因，不放宽硬条件。搜索范围有上限，**不是全菜单全组合最优解**。

`recommendation_eligible=true`仅指通过本轮推荐规则与官方计价，不能当作购买授权或永久价格。计价响应回显父套餐、不回显每个子项，因此证据中明确记录这一限制；子项合法性依据detail。选定购买前必须再计价，且本版没有下单入口。

营养是官方数据中的标准配方值之和，不是实际餐品检测或个性化健康建议。不完整时totals=null，不能将部分营养值伪装成整餐总值。

## 运行

在项目根目录，已有 `.env` 中的 MCP Token 和 `requirements-dev.lock.txt` 依赖：

```powershell
.venv\Scripts\python.exe -X utf8 -m maimen.recommend --request examples/recommendation.json --report artifacts/local/recommendation.json
```

API 默认关闭live调用；启用后仍仅绑定本机：

```powershell
$env:MAIMEN_ENABLE_LIVE_RECOMMENDATIONS='1'
.venv\Scripts\python.exe -m uvicorn maimen.api:app --host 127.0.0.1 --port 8000
```

此开关读取**进程环境**，不自动加载`.env`；只有MCD_MCP_TOKEN由现有load_token读取`.env`。

先 `POST /api/sessions {}` 获取本机会话凭据，后续携带Bearer session_token。这个凭据只是本地接口的访问凭据，所有live查询仍属于本机配置的同一个MCP账号，**不是多客户授权系统**，不能公开部署后让其他客户共用账号权益。

`POST /api/sessions/{id}/recommendations`：提交完整需求，返回cards、run_id、request、store、membership、coupon_status、coverage、warnings、tool_calls。

`POST /api/sessions/{id}/recommendations/feedback`：保留上一轮未改条件，例如：

```json
{
  "run_id": "上一轮返回的run_id",
  "changes": {"keep_codes": ["1120"]},
  "reject_card_ids": []
}
```

changes可修改预算、主食品类、饮料、目标、营养门槛、保留/排除项、用券开关、自述持卡和种子；未指定seed时自动加1。reject_card_ids仅能引用上一轮实际返回的卡，累计排除旧卡。changes中的数组替换对应条件，未给出的其他条件保留。

每次推荐重新查询和计价，不复用上轮价格。SQLite迁移003持久化需求与结果；重启后可凭原run_id继续，但旧报价不能直接购买。run归属按本地session校验。一次只执行一轮live推荐，忙时返回409。demo状态和真实推荐结果分开存储，推荐不修改demo草稿。

未启用503、无凭据401、无归属run404、非法条件422、运行中409、provider失败502、整轮超时504。券/营养/个别详情失败可降级为明确标注的部分结果，门店/菜单等必要查询失败则整体失败，不返回虚构数据。

## 实测与验证

2026-10-17 17:09（北京时间），上海龙腾大道餐厅，测试需求：3000分、汉堡、无糖饮料、蛋白质至少20g、能量至多650kcal，目标higher_protein。

| 返回组成 | 官方计价 | 标准能量 | 标准蛋白质 |
| --- | ---: | ---: | ---: |
| 双层吉士汉堡 + 中杯无糖可乐（随心配） | 14.90元 | 429kcal | 27g |
| 吉士汉堡包 + 中薯条 + 中杯无糖可乐 | 26.00元 | 583kcal | 20g |
| 吉士汉堡包 + 大杯玉米杯 + 中杯无糖可乐 | 27.50元 | 381kcal | 20g |

首次查询菜单118个商品映射、读取18个详情、生成241个结构候选、12次计价；以上是该账号该时刻的返回，不是永久价。第二轮指定保留双层吉士汉堡，其他条件保留，得到1套，状态partial。没有为了凑三套放宽条件。

本机报告：`artifacts/local/recommendation-api-first.json` 和 `recommendation-api-feedback.json`。复验命令（会发起真实只读调用）：

```powershell
.venv\Scripts\python.exe -X utf8 scripts/validate_live_recommendation.py --live
.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
```

真实账号可用券为0，因此真实优惠券查询已验证，“有券更便宜/过期/映射不符”由模拟服务测试验证，尚无非空真实券的端到端证据。70项自动测试覆盖核心、API、规则、营养、优惠、失败和反馈持久化；不是线上覆盖率或真实模型准确率。

后续优先：非空真实券样本联调、更复杂套餐数量结构、准确持卡契约/每客户授权、自由语言转结构化请求、前端卡片与动态角色。过期历史推荐与本地记录保留/删除策略仍待补齐。
