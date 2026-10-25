# 麦当劳 MCP 接入说明

更新：2026-10-25。本文只记录本项目实际调用的官方能力。

## 使用的 Server

- 官方指南：[M-China/mcd-mcp-server](https://github.com/M-China/mcd-mcp-server)
- 服务地址：`https://mcp.mcd.cn`
- 传输：Streamable HTTP
- 客户端：官方 Python SDK `mcp==2.3.0`，协议版本 `2025-06-18`
- 授权：后端读取本机 `.env` 的 `MCD_MCP_TOKEN`，以 `Authorization: Bearer` 发送
- 公开配置：[mcp-config.example.json](mcp-config.example.json)，其中只有 `${MCD_MCP_TOKEN}` 占位符

工具发现可以看到 35 个工具。产品代码只调用下面列出的工具，不因为发现了下单或支付工具就启用它们。

## 实际调用的 Tool

| 工具 | 使用位置 | 作用 |
| --- | --- | --- |
| `query-nearby-stores` | 推荐、门店查询 | 按城市和地点查找营业门店，确认用户选择的门店仍在结果中 |
| `query-meals` | 推荐、菜单查询 | 读取该门店当前菜单和标价，作为候选来源 |
| `query-meal-detail` | 推荐 | 读取套餐槽位和允许的单品，只组合详情里存在的选择 |
| `calculate-price` | 推荐 | 对候选组合做当前账号、当前门店的官方计价，超预算的结果不展示 |
| `list-nutrition-foods` | 推荐、营养查询 | 解析标准配方营养；名称和规格不能精确匹配时标为未匹配 |
| `campaign-calendar` | 活动查询 | 展示活动文案。文案价格不是当前门店应付价 |
| `available-coupons` | 优惠浏览 | 只展示麦麦省优惠列表，不读取个人卡包，不领券，也不把券抵进推荐价 |
| `now-time-info` | 连接探针 | `python -m maimen.mcp_probe --smoke` 用来检查连接，不参与选餐 |

到店查询固定使用 `beType=1`、`orderType=1`。菜单和计价还需要 `storeCode`；详情再加商品 `code`。价格字段按分处理。

推荐引擎里保留了 `query-store-coupons` 的代码路径，但网页提交推荐时强制 `use_coupons=false`，因此当前产品不会把门店券送去计价。

## 调用流程

1. 用户在本地页面确认城市、地点、门店、预算、主食、饮料和目标。
2. `query-nearby-stores` 核对门店仍可到店自取。
3. `query-meals` 取出菜单。除「价格低一点」外，搜索优先选择标价接近预算的套餐，而不是最便宜的一批。
4. 对入围套餐调用 `query-meal-detail`，只保留详情允许的单人组合。
5. `list-nutrition-foods` 为能精确对上名称的组成补充营养。
6. `calculate-price` 取得官方应付价。超过预算的组合丢弃。
7. 页面展示最多三套。默认目标按接近预算排序，并错开同类饮料。
8. 用户另外询问时，再调用活动、菜单、营养或优惠列表。这些查询不改变已经展示的报价。

网页通过本机 FastAPI 间接调用 MCP。浏览器不保存 MCP Token。

## 业务价值

用户不用自己翻完整菜单，就能按预算看到当前门店真实可计价的几套搭配。活动文案、菜单名称和官方报价分开呈现，避免把宣传价说成现在应付的价格。优惠只作浏览，避免把未领取的券算进总价。

## 明确不调用的能力

不调用下单、支付、领券、兑换、积分、地址、抽奖、商城、外送或团餐促销工具。发现这些工具不等于产品具备对应功能。购卡商品和未核实的麦金卡权益不进入推荐。

连接检查报告、真实报价和数据库都在被 Git 忽略的 `artifacts/local/` 与 `data/`，不放入公开仓库。
