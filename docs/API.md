# 本地 demo API

独立的真实推荐API已增加，协议与启用方式见 [RECOMMENDATION.md](RECOMMENDATION.md)。`/recommendations`与`/recommendations/feedback`不会修改下述demo卡片/草稿。数据库003迁移持久化真实推荐需求和结果。

2026-10-17：H01 最小服务边界已实现，前端 H02 尚未开始。只启动单个 Uvicorn worker，绑定 127.0.0.1；SQLite 连接在 ASGI lifespan 所属事件循环创建与使用。事务不跨越模型或报价的 await。

## 请求流程

1. `POST /api/sessions`，JSON `{}`。返回 `session_token` 与 `snapshot`。保存 token 和 session_id，刷新或服务重启时复用。Token 不写进 URL，数据库只存 SHA-256 摘要。
2. 后续所有会话路径携带 `Authorization: Bearer <session_token>`。`GET /api/sessions/{id}` 读取快照。
3. `POST /api/sessions/{id}/turns`，提交页面看到的 `scene_revision` 和 `plan_revision`，得到 `turn_id`。
4. `POST /api/sessions/{id}/commands`，例如：

```json
{
  "command_id": "client-generated-unique-id",
  "turn_id": "turn-id-from-step-3",
  "scene_revision": 1,
  "plan_revision": 0,
  "action": {"type": "text", "text": "选第二张"}
}
```

响应包含 command_id 和执行时的 snapshot。相同 command_id 与相同请求返回原成功回执；同 ID 换内容返回 `command_id_reused`。重试回执可能早于当前状态，客户端应按 revision 忽略更旧快照，必要时 GET 同步。错误请求不占用成功回执；处理冲突后用新轮次、新 ID 再提交。

允许 action：`select_card`（ordinal 1—3）、`replace_item`（from_sku、to_sku）、`undo`、`collect`（name）、`text`（text）。文字严格支持“选第二张”“饮料换无糖”“撤回上一步”；不支持的文本返回 `unsupported_demo_text`。确认与真实下单不属于此 API。

5. `POST /api/sessions/{id}/quotes`，提交两项当前版本，返回 accepted 与 snapshot。结果迟到时 accepted=false。报价是独立可重试计算，重复请求不保证返回同一 ticket；最新有效请求优先。金额为虚构整数分。
6. `POST /api/sessions/{id}/interrupt` 使旧提案/报价无法生效，不等于取消购买。正在执行的 provider 最迟在服务超时（默认 10 秒）退出；该接口当前不主动取消 provider task。请求任务取消时会释放报价 ticket。
7. `GET /api/sessions/{id}/events?after=N` 返回 revision 大于 N 的持久事件，首次 after=-1。sequence 是会话内版本；event_id 可去重。重连先 GET 快照，再从其 revision 拉取新事件；不重播旧动画。

## 错误与边界

错误形如 `{"error":{"code":"stale_client_versions"}}`。422 是请求结构无效，401 是凭据无效，403 是 Origin 不允许，409 是业务拒绝或版本冲突。Provider 内部异常不会原样输出。

仅接受同源浏览器请求，不开放任意 CORS。H02 的 Vite 需使用同源 `/api` 代理并保留/正确处理 Origin；若采用直连，需另行添加明确的开发来源白名单。当前 `/docs` 可检查协议，正式卡牌页面尚未提供。

数据库按版本增加 002 迁移，不改写既有会话。命令业务变更、事件和成功回执在同一事务中保存。旧 CLI 会话没有网页凭据，应通过 API 新建网页会话。收藏仍在所属会话内；跨会话收藏、事件分页/保留策略和多进程高并发尚未实现。

重启遗留的报价在下次 request_quote 时按 60 秒时效清理；当前没有后台定时清理器。客户端仍须根据 expires_at 判断报价显示是否过期。
