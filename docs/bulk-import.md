# 批量导入指南

本文档介绍如何使用 `scripts/bulk_import.py` 在导入前完成格式转换与元数据清洗，以及大量导入时如何通过上传参数控制服务端的 `parse_upload` 清洗。

---

## 目录

1. [预处理脚本概览](#1-预处理脚本概览)
2. [脚本详解](#2-脚本详解)
3. [为什么批量导入时建议跳过服务端清洗](#3-为什么批量导入时建议跳过服务端清洗)
4. [批量导入推荐工作流](#4-批量导入推荐工作流)
5. [如何通过参数控制服务端清洗](#5-如何通过参数控制服务端清洗)

---

## 1. 预处理脚本概览

| 命令 | 功能 | 典型用途 |
|------|------|----------|
| `python scripts/bulk_import.py convert` | 无损音频转 FLAC，保留完整元数据 | 单独进行格式标准化 |
| `python scripts/bulk_import.py clean` | 通过 Ollama LLM 清洗文件名/标签 | 单独进行元数据修复 |
| `python scripts/bulk_import.py process` | 上述两步的流水线（转码 → LLM 清洗） | 批量导入前的完整预处理 |
| `python scripts/bulk_import.py upload` | 按后端上传协议直接上传音频文件 | 处理后或已有目录的批量上传 |

该脚本不依赖 Banana Music 服务进程，可在服务器启动前或离线环境中使用。

Python 依赖单独列在：

```bash
pip install -r scripts/requirements-bulk-import.txt
```

---

## 2. 脚本详解

### 2.1 `bulk_import.py convert` — 格式转换

将 APE / WAV / WMA-lossless 转码为 FLAC，并解决 ffmpeg 转码后标签丢失的问题。`convert` 必须显式指定 `--output-dir`；即使输出到当前目录，也请使用 `--output-dir .`。

**核心机制**：转码前用 Mutagen 读取源文件标签，转码后将合并结果写入输出 FLAC，确保标题 / 艺人 / 专辑 / 封面 / 歌词不丢失。同时在输出 FLAC 文件中写入 `COMPRESSION_LEVEL` Vorbis 标签，供下次处理时判断是否需要重编码。

```bash
# 单文件转码（默认 level 5）
python scripts/bulk_import.py convert song.ape --output-dir ./flac/

# 批量转码到指定目录，指定压缩级别
python scripts/bulk_import.py convert *.ape --output-dir ./flac/ --level 8

# 跳过 ReplayGain 分析（加快速度）
python scripts/bulk_import.py convert *.ape --output-dir ./flac/ --no-replaygain

# 仅补写已有 FLAC 的缺失标签，不重新编码；写入的是输出目录中的副本
python scripts/bulk_import.py convert *.flac --output-dir ./flac/ --tags-only
```

**压缩级别说明**（`--level 0-12`，默认 5）：

| 级别 | 速度 | 文件大小 | 建议场景 |
|------|------|----------|----------|
| 0–2  | 最快 | 最大 | 临时转换、低性能设备 |
| 5    | 平衡 | 中等 | **默认，日常使用** |
| 8    | 较慢 | 较小 | 长期存档 |
| 12   | 极慢 | 最小 | 极限压缩，收益边际递减 |

**FLAC 输入的处理规则**：已是 FLAC 时，与目标级别比较——高级别不降级（复制到输出目录），低级别重编码提升压缩率。源文件始终只读，不会被改写。

### 2.2 `bulk_import.py clean` — LLM 元数据清洗

通过 Ollama 对文件名和嵌入标签做智能清洗，输出 JSON 结果（不修改原文件，便于审查）。

```bash
# 单文件清洗，查看结果
python scripts/bulk_import.py clean "01 - 林俊杰 - 圣所.mp3" \
  --ollama-url http://localhost:11434 --model qwen3.5:latest

# 批量清洗，结果写入文件
python scripts/bulk_import.py clean *.mp3 --output results.json
```

输出示例：

```json
{
  "file": "01 - 林俊杰 - 圣所.mp3",
  "raw_tags": { "title": null, "artist": null },
  "result": {
    "title": "圣所",
    "artists": ["林俊杰"],
    "album": null,
    "track_number": 1,
    "confidence": 0.9
  }
}
```

### 2.3 `bulk_import.py process` — 完整预处理流水线

将格式转换和 LLM 清洗串联为单一命令，标签只写入输出目录或临时目录中的副本（支持 FLAC / MP3 / M4A / OGG），源文件始终只读。加 `--upload` 后会将最终文件直接上传到后端。

`process` 不带 `--upload` 时必须显式指定 `--output-dir`；如果带 `--upload` 且未指定 `--output-dir`，脚本会使用系统临时目录处理并在结束后清理，不在当前目录留下转换文件。若希望保留处理后的音频，显式指定 `--output-dir`。

```bash
# 完整流水线：无损转 FLAC + LLM 清洗写入副本标签
python scripts/bulk_import.py process *.ape *.mp3 \
  --output-dir ./processed/ \
  --ollama-url http://localhost:11434

# 完整流水线并直接上传到后端
BANANA_API_KEY=am_xxx python scripts/bulk_import.py process *.ape *.mp3 \
  --output-dir ./processed/ \
  --ollama-url http://localhost:11434 \
  --base-url http://localhost:8000 \
  --upload

# 完整流水线并直接上传，不保留本地处理产物
BANANA_API_KEY=am_xxx python scripts/bulk_import.py process *.ape *.mp3 \
  --ollama-url http://localhost:11434 \
  --base-url http://localhost:8000 \
  --upload

# 仅转码，跳过 LLM（标签已整理好的场景）
python scripts/bulk_import.py process *.ape --output-dir ./processed/ --skip-llm --level 8

# 仅 LLM 清洗，不转码（文件格式已符合要求）；写入的是输出目录中的副本
python scripts/bulk_import.py process *.mp3 --output-dir ./processed/ --skip-convert

# 完整选项示例
python scripts/bulk_import.py process *.ape *.mp3 \
  --output-dir ./processed/ \
  --level 8 --no-replaygain \
  --ollama-url http://172.19.0.1:11434 --model qwen3.5:latest --timeout 60 \
  --overwrite
```

### 2.4 `bulk_import.py upload` — 直接上传

对已有音频文件执行与前端一致的上传协议：

```
POST /rest/x-banana/tracks/upload-file
→ GET /rest/x-banana/tracks/upload-status/{job_id} 轮询
→ POST /rest/x-banana/tracks/create
```

默认上传写库后会让服务端继续执行 `parse_upload` 元数据清洗；如只想使用脚本已写入的标签，可加 `--no-parse-metadata`，脚本会在 `POST /rest/x-banana/tracks/create` 中传 `parse_metadata: false`。不需要禁用插件或重启后端。

```bash
# 使用环境变量
BANANA_API_KEY=am_xxx python scripts/bulk_import.py upload ./processed/*.flac

# 或显式传参
python scripts/bulk_import.py upload ./processed/*.flac \
  --base-url http://localhost:8000 \
  --api-key am_xxx \
  --job-timeout 180 \
  --no-parse-metadata
```

认证参数支持：

- `--api-key` 或环境变量 `BANANA_API_KEY`
- `--token` 或环境变量 `BANANA_TOKEN`，优先于 API Key
- `--base-url` 或环境变量 `BANANA_BASE_URL`，默认 `http://localhost:8000`

---

## 3. 为什么批量导入时建议跳过服务端清洗

Banana Music 服务端默认会在每首曲目入库后将 LLM 清洗任务写入 `parse_upload_tasks` 表，由 `parse_upload_worker` 异步消费。这在日常少量上传时运转良好，但**批量导入时建议用 `--no-parse-metadata` 跳过这一步**，原因如下：

**队列积压与超时**
: `parse_upload_worker` 默认限制单并发（`max_concurrent: 1`），因为 Ollama 等本地 LLM 通常为单路排队处理。批量上传数百首时，队列深度超过 Ollama 的 `timeout_sec`（默认 120 秒），导致大量任务超时失败并被反复重试。

**与预处理脚本重复**
: 若已通过 `bulk_import.py process` 完成了 LLM 清洗并写入待上传副本，服务端再次调用 Ollama 清洗完全是冗余工作——既浪费 LLM 资源，又可能用质量相近的结果覆盖已经整理好的标签。

**影响服务响应**
: 大量 LLM 任务并发时会占满 Ollama 的推理资源，导致其他功能（如指纹查询、搜索建议）响应变慢。

---

## 4. 批量导入推荐工作流

```
本地音乐文件
      │
      ▼
scripts/bulk_import.py process  ← 格式转换 + LLM 清洗，结果写入副本标签
      │
      ▼
processed/ 目录            ← 标签整洁、格式统一的 FLAC / MP3
      │
      ▼
scripts/bulk_import.py upload --no-parse-metadata
或 process --upload --no-parse-metadata
      │
      ▼
服务端按文件标签直接入库，不入队 parse_upload
```

**具体步骤**：

1. **预处理**：在本地用 `bulk_import.py process` 处理所有文件

   ```bash
   python scripts/bulk_import.py process /music/inbox/*.ape /music/inbox/*.mp3 \
     --output-dir /music/processed/ \
     --level 8 \
     --ollama-url http://localhost:11434
   ```

2. **批量上传**：将 `processed/` 中的文件上传至服务，并通过 `--no-parse-metadata` 跳过服务端清洗

   ```bash
   BANANA_API_KEY=am_xxx python scripts/bulk_import.py upload /music/processed/*.flac \
     --base-url http://localhost:8000 \
     --no-parse-metadata
   ```

   也可以在第 1 步直接加 `--upload`，预处理完成后立即上传最终文件。

## 5. 如何通过参数控制服务端清洗

`bulk_import.py upload` 和 `bulk_import.py process --upload` 都支持同一组上传参数：

| 参数 | 传给后端的值 | 行为 |
|------|--------------|------|
| `--parse-metadata` | `parse_metadata: true` | 入库后继续入队服务端 `parse_upload` 清洗，适合少量日常上传。 |
| `--no-parse-metadata` | `parse_metadata: false` | 只使用文件标签入库，不入队服务端 `parse_upload`，适合已由脚本预处理的批量导入。 |

推荐批量导入命令：

```bash
BANANA_API_KEY=am_xxx python scripts/bulk_import.py process /music/inbox/*.ape \
  --upload \
  --no-parse-metadata \
  --base-url http://localhost:8000 \
  --ollama-url http://localhost:11434
```

这个参数是逐次请求生效的，不需要禁用 `llm-metadata` 插件，也不需要重启服务端。日常前端上传仍按默认行为继续执行服务端清洗。
