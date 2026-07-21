# AGENTS.md

This file provides guidance to Lingma (lingma.aliyun.com) when working with code in this repository.

## Project Overview

Axiodrasil is a **multi-agent routing + memory kernel** system for high-pressure study/project scenarios. It uses LangGraph + Qwen (千问) to route user inputs to specialized agents ("内阁/cabinet"), backed by an L3 memory matrix (SQLite + FTS5 + vector embeddings) and Hybrid RAG retrieval. The frontend is a Next.js chat UI with SSE streaming.

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
# Create .env in project root with:
# QWEN_API_KEY=<your key>
# QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
# REDIS_URL=redis://localhost:6379/0
# Optional: JINA_API_KEY, RERANK_PROVIDER, RERANK_MODEL, RERANK_API_URL, RERANK_DISABLED

pip install -r requirements.txt
cd frontend; npm install; cd ..
```

### Starting the Dev Stack
Use the PowerShell orchestrator (recommended):
```powershell
.\scripts\dev_stack.ps1 -Action start -All -OpenBrowser
.\scripts\dev_stack.ps1 -Action stop -All
.\scripts\dev_stack.ps1 -Action status -All
```

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
2. Summon protocol (`传 [Name]` regex) → mapped persona
3. Cleaning keywords → bit
4. Debate detection (indulgence + conflict keywords) → debate_agent
5. Late-night + work keywords → fukucho
6. Fatigue keywords → qianjin
7. Shopping/Art/Math/Taki/Boming/Politics keyword tables
8. Domain defaults via `DOMAIN_DEFAULT_PERSONA`
9. Diversity patch (Q3/Q4 only, 15% probability) → random low-frequency persona

**Memory architecture is 4-tier**:
- **L1**: Redis session cache — 5-turn sliding window, 1h TTL (`memory/session_cache.py`)
- **L2**: Rolling summaries — mid-term, generated every 20 turns by async task (`memory/enrichment.py`)
- **L3**: Memory matrix — SQLite with FTS5 + 1536-dim vector BLOBs + entity tables (`memory/database.py`)
- **Enrichment pipeline**: Q1/Q2 memories trigger async `extract_and_store` → fragments (fact/preference/emotion) + entity registration

**Hybrid RAG** (`hybrid_engine.py`): 3-way recall (FTS5 BM25 + cosine vector + entity string match) → RRF fusion → optional external rerank (Jina/SiliconFlow). Used primarily by Jean node for Q2 document retrieval.

**Mood engine** (`state/mood_engine.py`): 5-axis numerical drift (connection, pride, valence, arousal, immersion) persisted per `thread_id` in SQLite. Ticked once per `node_parser` call. Translated to natural language via `get_prompt_context()` / `get_style_guidance()` and injected into every persona's system prompt.

**Workflow mode** (`agents/workflow_pipelines.py`): Alternative to cabinet routing — 4-step agile SE pipeline (discovery → sprint design → code sketch → delivery review), each step uses structured output and only passes JSON summary to next step to control token budget. Invoked when `workflow_mode="dev_pipeline"`.

### API Endpoints (main.py)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/chat` | Synchronous chat, returns full response |
| POST | `/api/v1/chat/stream` | SSE streaming chat (pseudo-streaming) |
| POST | `/api/v1/chat/export` | Export session to `output/chats/*.jsonl` |
| GET | `/api/v1/chat/history` | Get recent turns for session |
| GET | `/api/v1/health` | Health probe (no LLM call) |
| GET | `/v1/models` | OpenAI-compat model list (for SillyTavern) |
| POST | `/v1/chat/completions` | OpenAI-compat chat (for SillyTavern) |

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

### Tracing

`tracing/router_run.py` wraps LangGraph `stream_mode="updates"` to collect per-node state deltas and insert a synthetic `__router__` step after `parser`. Every API call returns trace steps with timing, keys written, and summaries.

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
