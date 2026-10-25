# 真实接口接入（2026-10-24）

打开项目根目录 `.env.deepseek`，只需填写第二行 `DEEPSEEK_API_KEY=`。默认接口 https://api.deepseek.com，模型 deepseek-flash。文件已被Git忽略；配置按请求读取，保存后无需重启。不要将Key放进网页或聊天。

启动：`./scripts/start-web.ps1`，默认开启真实只读MCP；`-Offline`关闭。访问 http://127.0.0.1:8000 。当前本机预览服务已按live启动。

网页统一调用 `POST /api/sessions/{id}/assistant`，支持chat、query、recommend；会话凭据隔离、请求回执去重、取消接口、历史清理已接通。DeepSeek最多4轮调用，每轮输出最多1800tokens、45秒超时；每次会话请求最多4次工具、1轮推荐、240秒总超时。模型工具只允许query、recommend、choose_card，没有下单、兑换、领券接口。

真实MCP验收全部HTTP200：活动28条、门店5家、菜单展示40项、双层吉士营养1项、可用券0张；真实推荐返回3套。报告 `artifacts/local/web-live-acceptance.json`。沙箱网络不通，已在获准的沙箱外执行只读验收。73项Python测试通过；JS语法检查通过。

DeepSeek请求适配、工具调用编排和网页调用已实现，但没有Key，尚未完成真实DeepSeek服务验收；对话接口测试使用明确的模型测试替身，不将其称为真实回答。填Key后如认证失败/余额不足/限流，网页显示对应错误。

活动日历不代表全部新品，菜单不代表最终价格；营养须核对规格，麦金卡仍未知。当前仅本机账号、单人到店自取；产品不提供下单功能。
