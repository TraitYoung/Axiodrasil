# 历史实现清理

当前页面入口为 Bina 单聊 `/solo`。旧群聊、演示台、角色选择抽屉及其专用接口已删除。消息列表组件归入 `frontend/src/modules/solo-chat/`。

其他人物设定与历史系统提示词保存在 `docs/characters/`。多人物路由、内阁记忆、开发流水线、日志清洗工具及其专用测试已删除。

长期记忆统一使用 Hindsight。本地 `storage/chat_history.py` 仅保存原始聊天记录，沿用已有 `chat_turns` 表。旧 L3、FTS5、向量检索、Redis 缓存与滚动摘要实现已删除。
