# 上海总部餐厅：真实菜单与计价首条链路

> **价格争议后续（2026-10-17）：用户已核对并确认存在随心配活动。** 单品22.5与活动组合14.9并不矛盾。下表保留首次接口证据，不能当作永久报价。原菜单该商品currentPrice=14.9、originalPrice=14.9、canWithOrder=false；计价1490/1390为整数分。响应回显父商品，但不逐项回显子选项，这一边界保留。完整推荐及再次计价已另行实现，见 [RECOMMENDATION.md](RECOMMENDATION.md)。
>
> **麦金卡持有状态：未知。** 重新发现35项工具，未发现明确的持卡状态/有效期查询契约。query-my-account为积分账户；query-my-coupons为优惠券资产，都不能证明是否持卡。withOrder、canWithOrder和“随单购麦金卡优惠”代表报价条件/购卡入口，不证明客户已持卡。今后先判断持卡证据及当前餐单权益，再计价；无证据时不得默认为有卡或无卡。更不能把本机Token账户的价格用于其他客户。

验证日期：2026-10-17，北京时间约 16:42—16:44。用户指定“上海、麦当劳总部”；按到店自取查询，不创建订单。

门店搜索首项为麦当劳上海龙腾大道餐厅，`storeCode=1450398`，地址龙腾大道2121号巨无霸魔方1F2F。查询时显示营业中，营业时间07:00—22:00。距离是相对搜索位置，不代表用户当前位置。

## 已验证

- `query-nearby-stores`：city=上海，keyword=麦当劳总部，searchType=2，beType=1。
- `query-meals`：取得120个商品映射条目；其中含非餐食和有优惠条件的商品，不能视为120个普通可推荐套餐。
- `query-meal-detail`：读取“人气经典随心配” `9900013304`，蓝区/粉区各选1项，取得具体选项、数量限制和默认特制键。
- `calculate-price`：按详情中的合法选项，分别计算以下3套。均返回 success=true、code=200。

| 组合 | 返回 price（分） | 折合元 |
| --- | ---: | ---: |
| 双层吉士汉堡 + 无糖可口可乐中杯 | 1490 | 14.90 |
| 麦香鱼 + 无糖可口可乐中杯 | 1490 | 14.90 |
| 麦香鸡 + 无糖可口可乐中杯 | 1390 | 13.90 |

这是当前账户、该门店、查询时刻的计价结果，不是长期有效价格或对所有账户的承诺。请求未使用优惠券或随单购参数，未购买会员或创建订单。营养未匹配，不据此标注“健身餐”。

## 可复现入口

在项目目录、配置已有本机 Token 后：

```powershell
.venv\Scripts\python.exe -X utf8 -m maimen.menu_probe search --report artifacts/local/hq-stores.json
.venv\Scripts\python.exe -X utf8 -m maimen.menu_probe meals --store 1450398 --report artifacts/local/hq-menu.json
.venv\Scripts\python.exe -X utf8 -m maimen.menu_probe detail --store 1450398 --code 9900013304 --report artifacts/local/hq-detail.json
.venv\Scripts\python.exe -X utf8 -m maimen.menu_probe calculate --store 1450398 --items artifacts/local/hq-items-1.json --report artifacts/local/hq-price-1.json
```

最后一条依赖本机已保存的请求文件。其他机器需先读取新详情，用 `menu_candidates.build_single_choice_combo(detail, selections)` 生成 items，不能把旧选项当作永久菜单。

原始报告在忽略目录 artifacts/local。菜单响应可能含“我的常点”等账户相关字段，不能直接公开；本说明只保留门店、选定商品和必要计价结果。

## 代码与边界

`adapters/menu.py` 为独立只读适配器，只开放门店、菜单、详情、计价；未修改 smoke 探针权限，也未让 demo harness 接受真实 ID。`menu_candidates.py` 只支持每轮恰选1项的套餐，保留默认特制，不支持的结构明确拒绝。CLI 为开发联调入口，尚未暴露 live HTTP 推荐接口。

本次验证的是数据可用性与合法组合计价，三套由开发者指定来验证链路，尚不是自动推荐引擎。

下一步优先需求结构与推荐规则：预算、主食偏好、饮料限制、保留项、排除项和待澄清目标 → 有界候选生成 → 真实计价筛选 → 三套差异化结果 → 反馈后再次生成。先支持结构化输入，再接模型解析自由表达。健身目标不自动等同减脂，营养要求无可靠数据时应显示未知或澄清。
