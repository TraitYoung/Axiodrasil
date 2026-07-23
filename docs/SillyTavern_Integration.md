# SillyTavern Group Chat 接入 Axiodrasil

后端提供 OpenAI 兼容接口：`http://127.0.0.1:8000/v1`。  
谁说话由**酒馆 Group Chat**调度；后端负责强制人设回复 + 三层记忆（吵架 / 私忆 / 共识）。

## 1. 启动后端

`.env` 至少配置：

```env
AX_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-...
AX_CHAT_MODEL=deepseek-v4-flash
# embedding 仍用千问
QWEN_API_KEY=sk-...
```

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

探活：`GET http://127.0.0.1:8000/api/v1/health`  
应看到 `"llm_provider": "deepseek"`。

## 2. 酒馆 API 连接

1. API 类型选 **Chat Completion** / Custom (OpenAI-compatible)
2. Base URL：`http://127.0.0.1:8000/v1`（不要多一层 `/v1/v1`）
3. Model：先随便选一个，群成员会各自覆盖
4. **Additional Headers** 必加（全群共用同一记忆空间）：

```http
x-session-id: ax-cabinet-main
```

可选：`x-persona: bina`（一般用 model 绑定即可）。

## 3. 导入角色卡并建群

角色卡目录：[`sillytavern/character_card/group/`](../sillytavern/character_card/group/)（12 张）。

1. 在 SillyTavern 导入全部 group 卡
2. 新建 **Group Chat**，把需要的人设拉进群
3. 给每个群成员绑定模型（若 ST 支持 per-member model）：
   - Bina → `axiodrasil-bina`
   - Bit → `axiodrasil-bit`
   - … 其余同理（`GET /v1/models` 可列出）
4. 若无法按成员绑 model：确保每张卡的 `system_prompt` 含 `[AX_PERSONA:id]`（导出卡已内置）

旧单卡「内阁」已移至 [`sillytavern/character_card/legacy/`](../sillytavern/character_card/legacy/)。  
扩展 `persona-avatar-switch` 仅服务旧单卡，Group Chat **不需要**。

## 4. 三层记忆怎么玩

| 层 | 行为 |
|----|------|
| M1 吵架层 | Group 强制人设发言时自动写入；全员下一轮可见 |
| M2 人设私忆 | 异步提取，仅该人设注入 |
| M3 共识层 | 散会后写入，全员长期可见 |

**散会口令**（用户或台词命中即可）：`散会` / `达成共识` / `先这样` / `记下结论`  

或调用：

```http
POST /api/v1/cabinet/consensus
x-session-id: ax-cabinet-main
```

散会后吵架缓冲清空，只留压缩共识。

## 5. 安全熔断

即使用 `axiodrasil-bit` 点名 Bit，若 parser 判定 `pain_level > 6`，仍强制 **Bina** 医疗熔断。

## 6. 回退 Qwen 聊天

```env
AX_LLM_PROVIDER=qwen
AX_CHAT_MODEL=qwen-plus
QWEN_API_KEY=...
```
