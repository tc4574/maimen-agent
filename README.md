# 麦门战争

## 项目介绍

麦门战争是一个本地麦当劳选餐助手。用户说出预算、主食和饮料偏好后，程序读取当前门店菜单，查询套餐详情和官方报价，给出不超过三套到店自取搭配。

报价、活动和菜单都来自麦当劳 MCP。对话由本机配置的 DeepSeek 组织，模型不能自行编造价格或下单。默认目标会在不超过预算的真实报价里优先接近预算；只有用户选择「价格低一点」时才优先更低价格。

本项目由参赛者独立开发，非麦当劳官方产品。输出仅供参考，不构成营养或医疗建议。餐品、价格和供应以麦当劳官方渠道的实时结果为准。

## 目标用户

面向想自己决定吃什么、又不想在长菜单里逐项比较的学生和上班族。适合单人、立即到店自取，并希望先看到接近预算的几套选择。

## 安装方法

需要 Windows、Python 3.12 和本机麦当劳 MCP Token。在项目根目录执行：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.lock.txt
.venv\Scripts\python.exe -X utf8 -m maimen.configure
```

`configure` 会隐藏输入，并把 Token 写入已被 Git 忽略的 `.env`。公开仓库只保留 `mcp-config.example.json` 里的 `${MCD_MCP_TOKEN}` 占位符。

对话还需要 DeepSeek Key。在根目录新建同样被忽略的 `.env.deepseek`，只写占位后的真实值，不要提交：

```text
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
```

启动本地页面。脚本默认开启真实只读 MCP；`-Offline` 关闭外部查询：

```powershell
./scripts/start-web.ps1
```

浏览器打开 http://127.0.0.1:8000 。语音识别需要系统 Chrome；凭据只留在本机后端，不进入网页。

## 使用示例

页面里可以直接说：

```text
我现在预算60，想吃汉堡，有什么推荐？
```

助手会按当前门店返回最多三张餐卡。每张卡包含官方计价、组成和推荐理由。也可以先查活动、门店、菜单、营养或麦麦省优惠列表，再决定要不要推荐。

命令行可以单独跑一次真实推荐，结果写入本地报告，不进入公开仓库：

```powershell
.venv\Scripts\python.exe -X utf8 -m maimen.recommend --request examples/recommendation.json --report artifacts/local/recommendation.json
```

不连接 MCP 的离线演示：

```powershell
python -X utf8 -m maimen.demo --db data/demo.sqlite3 --report artifacts/local/demo.json
```

离线餐品和价格都是虚构数据，脚本结尾会说明没有创建真实订单。

## 当前边界

- 只做单人、立即到店自取的查询、推荐、收藏和对话。
- 不提供下单、支付、领券、兑换、积分、商城或外送。
- 麦麦省优惠只供浏览，不计入推荐价格。
- 麦金卡身份保持未知，不把购卡商品当成已拥有权益。
- 本地报价展示约 60 秒，不是官方锁价。

## 参赛材料

规定文件都在仓库根目录，名称未改：

- [CONTEST_DECLARATION.md](CONTEST_DECLARATION.md) 使用官方原文。
- [MCP_INTEGRATION.md](MCP_INTEGRATION.md) 说明实际 Server、Tool、调用流程和业务价值。
- [mcp-config.example.json](mcp-config.example.json) 只含环境变量占位符。

活动规则见 [activityGuidelines.md](https://github.com/M-China/mcd-developer-innovation-challenge/blob/main/activityGuidelines.md)。本项目未使用 WorkBuddy，因此没有 `workbuddy.md`。
