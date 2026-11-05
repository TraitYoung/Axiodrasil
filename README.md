# Axiodrasil · Bina 虚拟具身实验

Axiodrasil 是一个虚拟具身实验项目。当前唯一运行人物是 Bina，开发集中于她的虚拟形象、与用户的互动，以及支撑持续互动的记忆系统。

最终目标是让 Bina 在虚拟形象中获得持续的存在感，能够访问用户授权的摄像头，感知用户与环境，并结合对话和记忆与用户互动。

## 当前范围

- Bina 是唯一运行人物，所有聊天请求统一交给 Bina。
- 其他人物退化为文档设定，保存在 `docs/characters/`，旧 BIOS 和内阁设计属于历史资料。
- 当前攻坚虚拟形象的一致性、自然互动、主动互动，以及会话与长期记忆的连续性。
- 摄像头访问、视觉理解、视觉事件与记忆联动属于待实现目标。目前的自拍出图功能用于生成 Bina 的图片。

## 已有基础

| 方向 | 当前实现 |
|---|---|
| 聊天 | Bina 单聊界面、流式接口、单聊快速路径 |
| 输入 | 文字、附件、浏览器听写和服务端语音转写 |
| 虚拟形象 | Bina 统一外貌配置、ComfyUI 与 LoRA 定妆出图 |
| 互动状态 | 情绪状态、用户在场状态、主动消息机制 |
| 记忆 | SQLite 原始聊天记录；Hindsight 长期事实、偏好、更正与共同经历 |

摄像头实时采集、视觉理解和虚拟形象动作驱动尚未实现。已有模块的实际运行需要对应模型服务和本地配置。

## 技术与目录

后端使用 Python、FastAPI、LangGraph 和 Pydantic，前端使用 Next.js、React 和 TypeScript。SQLite 保存原始聊天记录和互动状态，Hindsight 保存长期记忆。聊天模型可通过环境变量选择 DeepSeek 或 Qwen。

| 路径 | 职责 |
|---|---|
| `main.py` | HTTP、流式聊天、附件和语音等接口 |
| `agents/` | Bina 对话图、快速路径和主动互动 |
| `frontend/src/modules/solo-chat/` | Bina 交互界面 |
| `modules/` | 聊天服务、角色目录、附件、语音与出图 |
| `memory/` | Hindsight 长期记忆适配和上下文拼装 |
| `storage/` | 本地原始聊天记录 |
| `state/` | 情绪状态 |
| `config/persona_visual/bina.json` | Bina 外貌配置真相源 |
| `test_suite/` | 脚本化回归检查，部分历史测试属于旧内阁阶段 |
| `docs/characters/` | 已退役人物的文档设定 |

旧群聊、演示台和内阁记忆实现已删除。OpenAI 兼容模型目录仅发布 `axiodrasil-bina`。旧角色参数统一收敛为 Bina，开发流水线返回已归档状态。

## Hindsight 本机部署

复制 `.env.example` 为 `.env`，填写 `DEEPSEEK_API_KEY`。本机 Compose 使用 Hindsight 1.2.0，复用该密钥，向量与重排使用本地多语言模型。

```bash
docker compose up -d
```

Bina 后端为 `http://127.0.0.1:8000`，Hindsight API 为 `http://127.0.0.1:8888`，记忆管理界面为 `http://127.0.0.1:9999`。第一次启动需要下载镜像、模型及 Python 依赖，可查看启动状态。

```bash
docker compose ps
docker compose logs -f api
```

记忆和模型缓存使用 `hindsight-data`、`hindsight-models` 命名卷。常规 `docker compose down` 保留数据，`down -v` 会删除这些卷。

### 记忆身份与写入时序

浏览器沿用已有稳定的 `x-memory-thread`，新建聊天仅改变 `x-session-id`。直接调用 API 时，缺省使用 `.env` 的 `AX_MEMORY_USER_ID`，适用于当前本地单用户模式。不同记忆身份使用独立的 Hindsight bank。

每轮回复前，Hindsight 的 `reflect` 内部召回并解析当前事实、旧事实与经历，再把结果交给 Bina。原始聊天记录写入轻量 SQLite 聊天记录表。回复完成后同步调用 `retain`，等待事实提取结束才返回成功或 SSE `done`，保证紧接着新建会话时可以读取刚写入的记忆。这样会增加每轮请求的等待时间与模型调用量。

长期记忆服务不可用时返回明确的错误，写入失败时本地仍保留聊天记录。旧的 L3、向量、FTS5、内阁记忆、Redis 缓存和滚动摘要代码已移除。SQLite 聊天记录继续兼容已有 `chat_turns` 表。

### 真实验收

以下脚本通过真实聊天接口调用 Bina 和 Hindsight，逐项检查跨会话偏好、事实更正、共同经历。每个请求都使用新的会话 ID，整轮测试使用独立记忆身份。测试记忆保留在独立 bank 中供管理界面检查。

```bash
docker compose exec api python scripts/check_hindsight_memory.py
```

## 本地开发

需要 Python 3.13、Node.js。先填写 `.env` 并启动记忆服务。

```bash
docker compose up -d hindsight
```

单独运行后端时使用 `AX_HINDSIGHT_URL=http://127.0.0.1:8888`，已部署远程服务可设置 `AX_HINDSIGHT_API_KEY`。安装并启动后端。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

在另一个终端启动前端。

```bash
cd frontend
npm ci
npm run dev
```

打开 `http://127.0.0.1:3000/solo`。Linux/WSL 也可在启动 Hindsight 后使用 `bash start.sh` 与 `bash stop.sh` 启停前后端。出图配置见 `docs/Bina_Image_Gen.md`。

## 检查

离线回归使用官方客户端类型及模拟响应，不调用外部模型。真实语义验收使用上面的脚本。

```bash
python -m unittest discover -s test_suite -v
PYTHONPATH=. python test_suite/test_solo_fast.py
PYTHONPATH=. python test_suite/test_bina_first.py
```

使用 Docker 时可以通过 `docker compose exec api` 执行上述 Python 命令。

```bash
cd frontend
npm run lint
npm run build
```

Python 依赖见 `requirements.txt`，前端依赖与锁文件位于 `frontend/`。前端已配置 ESLint，后端尚未统一配置格式化和 lint。

## 文档约定

当前开发计划见 `TODO.md`。历史多 Agent 介绍见 `docs/历史项目说明.md`，旧内阁、软件工程流水线和角色扩展文档用于追溯。新功能与设计以 Bina 的虚拟具身、互动和记忆目标为准。
