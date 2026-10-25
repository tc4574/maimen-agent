# 交付状态与参赛对应

核对日期：2026-10-25。依据[官方 README](https://github.com/M-China/mcd-developer-innovation-challenge)及[完整活动规则](https://github.com/M-China/mcd-developer-innovation-challenge/blob/main/activityGuidelines.md)。此表只记录本地材料状态，不代表主办方审核结论。

| 项目 | 当前状态 |
| --- | --- |
| `README.md`：介绍、安装、示例、目标用户 | 已按当前本地网页和真实推荐改写 |
| `CONTEST_DECLARATION.md` | 保持官方原文，未改写 |
| `MCP_INTEGRATION.md`：Server、Tool、流程、业务价值 | 已按实际调用改写；不把未使用的下单工具写成产品功能 |
| `mcp-config.example.json` | 只有 `${MCD_MCP_TOKEN}` 占位符 |
| 可运行源码 | 本地网页、FastAPI 和真实只读推荐已在仓库中 |
| 真实使用麦当劳 MCP | 推荐与查询调用官方 Server；凭据只在本机 `.env` |
| `workbuddy.md` | 不适用。未使用 WorkBuddy，不提交空文件 |
| 公开 GitHub 仓库 | 尚未发布。报名还需要公开仓库地址 |
| 标准格式报名 Issue | 尚未提交 |

公开仓库前确认 `.env`、`.env.deepseek`、`data/` 和 `artifacts/local/` 不被提交。报名 Issue 使用纯文本，仓库地址不要写成 Markdown 链接：

```text
【参赛申请】
项目名称：麦门战争
项目地址：https://github.com/账号/仓库
项目简介：说出预算和喜好，按当前门店菜单和官方报价推荐到店自取套餐，不下单、不支付。
```
