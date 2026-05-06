# 批量导入指南

本文档介绍如何使用 `scripts/bulk_import.py` 在导入前完成格式转换与元数据清洗，并将清洗后的元数据随上传请求提交给服务端。

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
| `python scripts/bulk_import.py upload` | 按后端上传协议直接上传音频文件，或导入 `.m3u/.m3u8` 播放列表 | 处理后目录批量上传；从播放列表创建歌单 |

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

`upload` 会在本地先计算与服务端一致的 `audio_hash`，调用 `GET /rest/x-banana/tracks/exists-by-hash?audio_hash=...` 查询是否重复；命中时返回已有 `track_id/title` 并跳过上传。未命中时才执行 Ollama 清洗，清洗成功后上传并创建曲目。这样重复文件不会消耗 LLM 推理。

默认遇到重复内容时不会修改服务器已有曲目。若明确传 `--overwrite-duplicates`，脚本会在查重命中后**不重新上传音频**，而是用本地 LLM 清洗结果（失败时退回文件内嵌标签）调用管理员接口覆盖已有曲目的标题、主艺人、专辑和音轨号。该参数需要管理员账号或管理员 API Key。

`upload` 也支持 `.m3u` / `.m3u8` 播放列表文件：脚本会解析其中的本地音频路径（支持相对路径、绝对路径和 `file://` URI）以及 `http/https` 远程音频 URL。远程音频会先下载到临时目录，再逐首执行上传/查重，并创建 Banana Music 歌单，按 M3U 顺序添加曲目。若同名歌单已存在，只有空歌单会被复用；非空同名歌单会保留不动，脚本自动创建带编号的新歌单。缺失文件会记录 warning 并跳过。

```bash
# 使用环境变量
BANANA_API_KEY=am_xxx python scripts/bulk_import.py upload ./processed/*.flac

# 或显式传参
python scripts/bulk_import.py upload ./processed/*.flac \
  --base-url http://localhost:8000 \
  --api-key am_xxx \
  --job-timeout 180

# 导入 m3u8，上传引用歌曲并创建同名歌单
BANANA_API_KEY=am_xxx python scripts/bulk_import.py upload ./playlists/favorites.m3u8 \
  --base-url http://localhost:8000
```

认证参数支持：

- `--api-key` 或环境变量 `BANANA_API_KEY`
- `--token` 或环境变量 `BANANA_TOKEN`，优先于 API Key
- `--base-url` 或环境变量 `BANANA_BASE_URL`，默认 `http://localhost:8000`

---

## 3. 服务端不再排队清洗上传标签

Banana Music 服务端不再在入库后创建 `parse_upload_tasks` 队列任务。上传请求必须在调用 `create` 时提交已经解析/清洗后的 `metadata`；前端通过 `/rest/x-banana/plugins/llm-metadata/parse-metadata` 同步调用 LLM，批量脚本则继续在本地预处理阶段完成清洗。

---

## 4. 批量导入推荐工作流

```
本地音乐文件
      │
      ▼
scripts/bulk_import.py process  ← 格式转换；若不直接上传，则 LLM 清洗并写入副本标签
      │
      ▼
processed/ 目录            ← 标签整洁、格式统一的 FLAC / MP3
      │
      ▼
scripts/bulk_import.py upload
或 process --upload
      │
      ▼
脚本先按 audio_hash 查询服务端；非重复再清洗、上传并入库
```

**具体步骤**：

1. **预处理**：在本地用 `bulk_import.py process` 处理所有文件

   ```bash
   python scripts/bulk_import.py process /music/inbox/*.ape /music/inbox/*.mp3 \
     --output-dir /music/processed/ \
     --level 8 \
     --ollama-url http://localhost:11434
   ```

2. **批量上传**：将 `processed/` 中的文件上传至服务

   ```bash
   BANANA_API_KEY=am_xxx python scripts/bulk_import.py upload /music/processed/*.flac \
     --base-url http://localhost:8000
   ```

   也可以在第 1 步直接加 `--upload`，预处理完成后立即上传最终文件。

## 5. 重复处理与上传参数

`bulk_import.py upload` 和 `bulk_import.py process --upload` 都支持同一组上传参数：

| 参数 | 传给后端的值 | 行为 |
|------|--------------|------|
| `--overwrite-duplicates` | 不上传重复音频；额外调用管理员更新接口 | 内容重复时，用本地元数据覆盖服务器已有曲目的标题、主艺人、专辑和音轨号；默认关闭。 |

推荐批量导入命令：

```bash
BANANA_API_KEY=am_xxx python scripts/bulk_import.py process /music/inbox/*.ape \
  --upload \
  --base-url http://localhost:8000 \
  --ollama-url http://localhost:11434
```
