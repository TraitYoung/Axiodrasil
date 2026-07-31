# UI 软归档说明（Bina 单聊优先）

当前产品入口收敛为 **Bina 单人聊天**（`/` → `/solo`）。

## 已软归档、仍保留代码

| 路径 | 说明 | 恢复方式 |
|------|------|----------|
| `frontend/app/group/` + `frontend/src/modules/group-chat/` | 内阁群聊 UI | 导航加回 `/group`；注意 `MessageList` 仍被 Solo 复用，**勿整目录删除** |
| `frontend/app/lab/` | 旧演示台（清洗 / 工程流水线） | 直接访问 `/lab`；独占 `frontend/app/api/cleaning/files` |
| 非 Bina 角色卡 JSON（`sillytavern/character_card/group/*.json`） | 仍保留；公开 `GET /api/v1/personas` 只列 Bina | `PersonaCatalog.list_cards` 去掉公开过滤即可 |

## 后端未删

- `agents/persona_meta.py` 全量路由表与人格 ID
- `agents/router.py` 各人格节点
- `prompts/system_prompts.py` 各人格 prompt
- `/v1/models` / SillyTavern 强制人格协议

历史会话、M2 私忆与 `axiodrasil-<id>` 模型 ID 仍依赖这些注册项。Bina 单聊稳定后，可按 Solo 壳复制其他人设。
