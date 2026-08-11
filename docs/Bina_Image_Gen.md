# Bina 定妆出图（ComfyUI + LoRA）

参考邻舍.EXE：角色卡挂 **LoRA** → ComfyUI 工作流注入 `LoraLoader` → 聊天里要自拍时真的出图。

## 视觉真相源（SSOT）

**唯一外貌真相源：** [`config/persona_visual/bina.json`](../config/persona_visual/bina.json)

| 字段 | 职责 |
|------|------|
| `canon` | 人读设定（发色/发型/眼睛/常服/禁忌）；BIOS 与角色卡只引用摘要 |
| `appearance_prompt` 等 | 出图用英文底词，必须与 `canon` 一致 |
| BIOS / SillyTavern 卡 | **不是**外貌真相源；冲突时以本 JSON 为准 |

## 前置

1. 本机安装并启动 [ComfyUI](https://github.com/comfyanonymous/ComfyUI)，默认 `http://127.0.0.1:8188`
2. 准备好 **Bina 专用 LoRA**（你自己训练或购买），放入：
   `ComfyUI/models/loras/bina.safetensors`（文件名可改）
3. 准备底模 checkpoint（默认配置为 SDXL 名，可按本机文件改）

## 定妆配置

编辑 [`config/persona_visual/bina.json`](../config/persona_visual/bina.json)：

| 字段 | 含义 |
|------|------|
| `canon` | 中文定妆正文（SSOT） |
| `loras[].path` | 相对 `models/loras/` 的文件名 |
| `loras[].weight` | 强度，常见 0.6–0.9 |
| `loras[].trigger_word` | 训练时的触发词（必填才锁得住脸） |
| `appearance_prompt` | 外貌底词（须对齐 `canon`） |
| `selfie_prompt` | 自拍构图标签 |
| `negative_prompt` | 负向 |

也可用环境变量覆盖单个 LoRA：

```bash
AX_IMAGE_GEN_ENABLED=1
AX_COMFYUI_URL=http://127.0.0.1:8188
AX_COMFYUI_CKPT=你的底模.safetensors
AX_BINA_LORA=bina.safetensors
AX_BINA_LORA_TRIGGER=bina_char
AX_BINA_LORA_WEIGHT=0.85
```

## 使用

1. Linux 栈：`./start.sh`（后端 :8000）
2. ComfyUI 保持运行
3. Solo 对 Bina 说：「发一张自拍给我」
4. 回复文案后会附 `![Bina selfie](/api/v1/images/file/...)` ，前端直接显示图

手动调试：

```bash
curl -s http://127.0.0.1:8000/api/v1/images/persona/bina
curl -s -X POST http://127.0.0.1:8000/api/v1/images/generate \
  -H 'Content-Type: application/json' \
  -d '{"persona_id":"bina","mode":"selfie"}'
```

## 说明

- 一致性主要靠 **LoRA + trigger**；只改提示词不够。
- 当前工作流是 CheckpointLoaderSimple + LoraLoader（SDXL 系）；若你用 Anima/UNET 工作流，可后续再加自定义 workflow JSON。
- 生成文件落在 `data/generated/`（或 `AX_IMAGE_OUT_DIR`）。
