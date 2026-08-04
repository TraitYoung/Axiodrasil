# AGENTS.md

This file provides guidance to Lingma (lingma.aliyun.com) when working with code in this repository.

## Project Overview

Axiodrasil is a **multi-agent routing + memory kernel** system for high-pressure study/project scenarios. It uses LangGraph + DeepSeek（默认）/ Qwen  to route user inputs to specialized agents ("内阁/cabinet"), backed by an L3 memory matrix (SQLite + FTS5 + vector embeddings) and Hybrid RAG retrieval. Primary interactive front-end is the **Next.js Bina 单聊**（`/` → `/solo`）；群聊 `/group` 与旧 `/lab` 已软归档（见 `docs/archive_ui.md`）。SillyTavern Group Chat 仍可通过 `/v1` 接入。

### Host + 接口矩阵（模块化）

工程按「主体 Host + 统一接口矩阵 + 功能模块」组织（增量迁移中）：

| 路径 | 职责 |
|------|------|
| `app/matrix/` | Port 契约：`HealthPort` / `SessionPort` / `ChatPort` / `PersonaPort` / `CabinetPort` / `TracePort` |
| `app/registry.py` | 模块注册表；`bootstrap_registry()` 装配默认适配器 |
| `infra/` | 薄封装 → `infrastructure.container`（LLM / DB / Redis） |
| `observability/` | 轻量 `obs()` stub（proactive 等）；完整 JSONL 管线可选 |
| `modules/personas/` | 角色卡 catalog（`GET /api/v1/personas`） |
| `modules/chat_api/` | Chat / Health / Trace 适配外壳 |
| `modules/cabinet_memory/` | 散会共识适配 |
| `frontend/src/host` + `matrix` + `modules/*` | 前端壳与 Bina 单聊（主入口）/群聊软归档/角色卡模块 |
| `launcher/` | Windows 桌面启动器（CustomTkinter → PyInstaller exe），调用 `scripts/dev_stack.ps1` |

新能力应经矩阵 Port 接入，避免在 Host 内堆业务。旧演示台移至 `frontend/app/lab`。

The system persona is an "imperial cabinet" (BIOS V17.0) with 11 named characters + 1 functional role (Jean), organized in tiers:
- **Tier 1 (Core)**: Bina (emotion), Bit (tech), Taki (logic audit), Chizheng (strategy)
- **Tier 2 (Specialists)**: Tianji (shopping/intel), Fukucho (discipline/late-night), Vinci (art/design)
- **Tier 3 (Think Tank)**: Planck (math), Jiafa (politics), Qianjin (health), Boming (unconventional strategy)
- **Functional**: Jean (document/RAG retrieval, not a BIOS persona)

## Build & Run Commands

### Prerequisites
- Python 3.10+ (developed on 3.13)
- Node.js (for Next.js frontend)
- Redis (optional, for session hot cache)

### Environment Setup
```powershell
# Create .env in project root (see .env.example) with:
# AX_LLM_PROVIDER=deepseek
# DEEPSEEK_API_KEY=<your key>
# AX_CHAT_MODEL=deepseek-v4-flash
# QWEN_API_KEY=<for embeddings>
# QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
# REDIS_URL=redis://localhost:6379/0
# Optional: JINA_API_KEY, RERANK_PROVIDER, RERANK_MODEL, RERANK_API_URL, RERANK_DISABLED
# Optional: AX_DEEPSEEK_THINKING=0|1
# Recommended: AX_DB_PATH=%USERPROFILE%\.axiodrasil\axiodrasil_core.db

pip install -r requirements.txt
cd frontend; npm install; cd ..
```

**SQLite 路径**：`AX_DB_PATH` 统一聊天历史 / mood / enrichment / hybrid。启动器与 `scripts/dev_stack.ps1` 默认指向 `%USERPROFILE%\.axiodrasil\axiodrasil_core.db`；勿在 WSL UNC 上跑默认 `data/`（易锁死）。

SillyTavern Group Chat：见 `docs/SillyTavern_Integration.md`；角色卡在 `sillytavern/character_card/group/`。

### Starting the Dev Stack
**推荐（Linux / WSL Ubuntu 全栈，勿跨 Windows）**：
```bash
# 首次配置依赖
cd ~/Axiodrasil
./scripts/setup_linux_env.sh

# 日常
./start.sh          # redis + backend:8000 + frontend:3000
./stop.sh
./scripts/dev_stack.sh status
```
浏览器打开 http://127.0.0.1:3000/solo（WSL2 与 Windows 共享 localhost）。

> 根目录 `一键启动.cmd` / `一键停止.cmd` 仅作提示，日常请在 Ubuntu 终端用 `./start.sh`。

遗留 Windows 编排（不推荐）：`scripts/dev_stack.ps1`、`python -m launcher`。

Or manually in 3 terminals:
```powershell
# Terminal 1 - Redis
redis-server --port 6379

# Terminal 2 - Backend (FastAPI)
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 3 - Frontend (Next.js)
cd frontend; npm run dev
```

### Running Tests
Tests are manual regression scripts (not pytest), run individually:
```powershell
python test_suite/test.py              # Router end-to-end flow test
python test_suite/test_memory.py       # L3 memory matrix regression
python test_suite/test_rag.py          # Hybrid RAG pressure test
python test_suite/test_system_prompts.py  # Prompt node regression
```

### Utility Scripts
```powershell
python scripts/migration.py            # Q2 cold-start vectorization (idempotent)
python scripts/inspect_q2.py           # View Q2 memory contents
python scripts/insert_career_nuke.py   # Insert sample strategic memory
python scripts/clear_Q1.py             # Clear specific thread memories
python tools/logs_to_sft.py            # Log cleaning -> SFT jsonl pipeline
```

### Frontend
```powershell
cd frontend
npm run dev      # Dev server on :3000
npm run build    # Production build
npm run lint     # ESLint
```

## Architecture

### Request Flow
```
User Input → FastAPI (main.py) → SessionCache (Redis, 5-turn sliding window)
  → LangGraph Router (agents/router.py)
    → node_parser: LLM structured output → TaskIntent (Pydantic)
    → _resolve_route: deterministic persona selection (keyword triggers, summon protocol, diversity patch)
    → route_by_intent: conditional edge lookup (no randomness)
    → Agent node (emotion/jean/bit/chizheng/taki/tianji/...) → END
  → Response with [persona]: prefix → Redis write-back + async enrichment
```

### Key Architectural Decisions

**Routing is two-phase**: `node_parser` calls `_resolve_route()` once to compute `(persona, route_key)` deterministically (except diversity patch which uses randomness — called exactly once, result stored in `resolved_route_key`). `route_by_intent()` only does table lookup. This prevents inconsistent results when tracing replays the route function.

**Safety invariant**: `pain_level > 6` triggers medical hard circuit-breaker to Bina's emotion node. This CANNOT be overridden by summon protocol or any other mechanism. Check `agents/router.py` `_resolve_route()` step 0.

**Persona resolution priority** (in `_resolve_route`):
1. Medical hard break (pain_level > 6) → bina
2. Forced persona (SillyTavern Group Chat: `x-persona` / model / `[AX_PERSONA:]`)
3. Summon protocol (`传 [Name]` regex) → mapped persona
4. Cleaning keywords → bit
5. Debate detection (indulgence + conflict keywords) → debate_agent
6. Late-night + work keywords → fukucho
7. Fatigue keywords → qianjin
8. Shopping/Art/Math/Taki/Boming/Politics keyword tables
9. Domain defaults via `DOMAIN_DEFAULT_PERSONA`
10. Diversity patch (Q3/Q4 only, 15% probability) → random low-frequency persona

**Memory architecture is 4-tier storage + cabinet M1/M2/M3**:
- **L1**: Redis session cache — 5-turn sliding window, 1h TTL (`memory/session_cache.py`); SQLite `chat_turns` cold history for history/export and Redis fallback (`main.py` `_persist_turn`)
- **L2**: Rolling summaries — mid-term, generated every 20 turns by async task; **injected** into parser + persona prompts via `memory/context_inject.py`
- **L3**: Memory matrix — SQLite with FTS5 + 1536-dim vector BLOBs + entity tables (`memory/database.py`); online `embed_and_store_memory` after Q1/Q2 save
- **Cabinet M1/M2/M3** (`memory/cabinet_layers.py`): shared debate buffer / persona-private fragments / consensus after `散会` or `POST /api/v1/cabinet/consensus`
- **Enrichment pipeline**: Q1/Q2 memories trigger async `extract_and_store` → fragments (fact/preference/emotion) + entity registration; preference/fact fragments injected on emotion/闲聊 paths (Bina/Tianji/Fukucho/Qianjin)
- **Interaction hooks**: MoodEngine `arm_interaction_hook` before `tick` — reunion (>2h) / daily-first greetings (`AX_INTERACTION_HOOKS_ENABLED`)
- **Proactive contact（托盘常驻）**: 后端 lifespan 心跳调用 `tick_idle` + `check_triggers`；阈值触达时以 Bina 写入最近活跃会话（`POST /api/v1/presence`），托盘轮询 `GET /api/v1/proactive/pending` 弹 Windows 通知（`AX_PROACTIVE_*`）
- **LLM**: default DeepSeek `deepseek-v4-flash` (`AX_LLM_PROVIDER=deepseek`); embeddings still DashScope via `QWEN_API_KEY`
- **SillyTavern Group Chat**: force persona via `x-persona` / `axiodrasil-<id>` model / `[AX_PERSONA:id]`; see `docs/SillyTavern_Integration.md`

**Hybrid RAG** (`hybrid_engine.py`): 3-way recall (FTS5 BM25 + cosine vector + entity string match) → RRF fusion → optional external rerank (Jina/SiliconFlow). Used primarily by Jean node for Q2 document retrieval.

**Mood engine** (`state/mood_engine.py`): 5-axis numerical drift (connection, pride, valence, arousal, immersion) persisted per `thread_id` in SQLite. User turns call `tick` + `reset_connection`; idle heartbeat uses `tick_idle` / `check_triggers` (`agents/proactive.py`). Translated to natural language via `get_prompt_context()` / `get_style_guidance()` and injected into every persona's system prompt.

**Style steering**（正/负向提示，`prompts/steering.py`）：在人格 system prompt 末尾注入「尽量做到 / 坚决避免」。默认读 `prompts/steering/{persona}.json`，可用 `AX_{PERSONA}_POSITIVE_PROMPT` / `AX_{PERSONA}_NEGATIVE_PROMPT` 覆盖。经 `_persona_prompt` 对所有节点生效。

**Workflow mode** (`agents/workflow_pipelines.py`): Alternative to cabinet routing — 4-step agile SE pipeline (discovery → sprint design → code sketch → delivery review), each step uses structured output and only passes JSON summary to next step to control token budget. Invoked when `workflow_mode="dev_pipeline"`.

### API Endpoints (main.py)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/chat` | Synchronous chat, returns full response |
| POST | `/api/v1/chat/stream` | SSE **pseudo-streaming**（整轮完成后再切块；期间发 heartbeat） |
| POST | `/api/v1/chat/export` | Export session to `output/chats/*.jsonl` |
| GET | `/api/v1/chat/history` | Get recent turns for session |
| GET | `/api/v1/health` | Health probe (no LLM call；Redis 熔断) |
| GET | `/api/v1/personas` | Persona / character-card catalog |
| GET | `/api/v1/personas/{id}` | Single persona card |
| POST | `/api/v1/presence` | Solo 上报活跃会话（主动开口落点） |
| GET | `/api/v1/proactive/pending` | 托盘拉取未读主动消息 |
| POST | `/api/v1/attachments/ingest` | Solo 附件消化：文本抽取 / 图片 VL 描述 → 文本 |
| POST | `/api/v1/stt` | 服务端语音转写（Web Speech 回退；需 `QWEN_API_KEY`） |
| POST | `/api/v1/images/generate` | ComfyUI + 定妆 LoRA 出图（Bina 自拍等） |
| GET | `/api/v1/images/file/{name}` | 读取已生成图片 |
| GET | `/api/v1/images/persona/{id}` | 查看人格定妆配置摘要 |
| POST | `/api/v1/cabinet/consensus` | Compress M1 debate → M3 consensus |
| GET | `/v1/models` | OpenAI-compat model list (cabinet + 12 personas) |
| POST | `/v1/chat/completions` | OpenAI-compat chat (SillyTavern Group Chat) |

Session identity: `x-session-id` header (primary), or derived from auth key / user field.

### Key Schemas

- `TaskIntent` (`schemas/protocols.py`): Core routing protocol with `task_type`, `persona`, `urgency_level` (1-5), `pain_level` (1-10), `quadrant` (Q1-Q4), `raw_input`
- `GraphState` (`agents/router.py`): LangGraph state dict — `current_input`, `thread_id`, `recent_history`, `intent`, `final_response`, `active_task_type`, `active_persona`, `resolved_route_key`
- `MemoryExtraction` (`schemas/memory.py`): Structured output for async enrichment (facts, preferences, emotion_snapshot, entities)
- Workflow schemas (`schemas/workflows.py`): `DevTaskSpec`, `DevOutline`, `DevCodeSketch`, `DevTestsChangelog`

### Configuration

Token/context budgets are centralized in `config/context_budget.py`, overridable via env vars (`AX_PARSER_HISTORY_MAX_CHARS`, `AX_JEAN_MATERIALS_MAX_CHARS`, etc.).

Diversity patch toggles: `AX_DIVERSITY_PATCH_ENABLED` (default "1"), `AX_DIVERSITY_PATCH_PROB` (default "0.15").

Rolling summary frequency: `AX_SUMMARY_EVERY_N_TURNS` (default "20").

Enrichment model: `AX_ENRICHMENT_MODEL` (default "qwen-turbo", cheaper than main "qwen-plus").

Solo 附件/语音：图片描述 `AX_VL_MODEL`（默认 `qwen-vl-plus`）、服务端 STT `AX_STT_MODEL`（默认 `qwen2-audio-instruct`），均复用 `QWEN_API_KEY`。前端优先浏览器 Web Speech，失败再走 `/api/v1/stt`；附件经 ingest 后拼进 `chat` 的 `text`（不改 L1 schema）。

Bina 定妆出图：本地 ComfyUI（`AX_COMFYUI_URL`）+ `config/persona_visual/bina.json` 的 LoRA；要自拍时 `node_bina` 调用出图并拼 markdown。详见 `docs/Bina_Image_Gen.md`。

### Tracing

`tracing/router_run.py` wraps LangGraph `stream_mode="updates"` to collect per-node state deltas and insert a synthetic `__router__` step after `parser`. Every API call returns trace steps with timing, keys written, and summaries.

### Reliability notes（已知边界）

- **Solo 减负**：`forced_persona=bina` + `group_mode=false` 走 `solo_fast`（跳过全量 parser LLM，规则估痛感）；主入口为同步 `POST /api/v1/chat`（Next rewrite），伪 SSE 仅兼容。
- **无真 token 流式**：`/api/v1/chat/stream` 仍为伪切块 + heartbeat；不存在 `agents/stream_turn.py`。
- **前端本机收口**：`npm run dev` 绑 `127.0.0.1`；`/api/v1/*` rewrite 到 FastAPI。
- **单聊主入口**：`/solo`；多会话 UI / 群聊为软归档或未接线，勿假设已实现。
- **请求路径日志**：勿在 Windows GBK 控制台 `print` emoji，否则可把可恢复错误打成 500。
- **回合入口**：`modules/chat_api/service.py` `TurnService`（ChatAdapter 不得再 import main）。

### Optional Encryption

`memory/crypto.py` provides optional field-level encryption for `memory_matrix.content` and `memory_fragments.content`. Enabled by setting `AX_MEMORY_ENC_KEY`. **Known limitation**: encryption breaks FTS5 keyword recall (triggers sync ciphertext to FTS index); hybrid search degrades to vector + entity paths only.

### Adding a New Persona

1. Add persona name to `PersonaName` Literal in `schemas/protocols.py`
2. Add entry to `PERSONA_META`, `SUMMON_ALIASES`, `PERSONA_TO_ROUTE` in `agents/router.py`
3. Add route key → node name mapping in `ROUTE_TO_NODE`
4. Add conditional edge mapping in the `workflow.add_conditional_edges` call
5. Add the node to the END edge loop
6. Create a system prompt in `prompts/system_prompts.py`
7. Implement `node_xxx()` function — use `_simple_agent_reply()` for simple nodes, or custom logic for nodes with retrieval/tools
8. Add keyword trigger list and detection logic in `_resolve_route()`
