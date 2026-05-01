"""
data/plugins/llm-metadata/plugin.py

通过 Ollama 对上传文件的元数据做 LLM 清洗（仅 parse_upload；不参与指纹曲库查询）：
  - 从文件名和/或标签中提取 title、artists、album、track_number
  - 拆分 "feat./ft./&/、" 等分隔符得到有序艺人列表
  - 检测并纠正 title 与 artist 互换的情况
  - 补全文件名含有但标签里缺失的信息

依次尝试原生 Chat、OpenAI 兼容层、Generate（与 https://docs.ollama.com/api/chat 、
https://docs.ollama.com/openai 一致）。对支持 thinking 的模型（如 qwen3 / qwen3.5），默认在请求里传
`think: false`（见 Ollama ChatRequest.think），以关闭显式 thinking 输出、通常可缩短耗时。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

import httpx

from plugins.base import MetadataPlugin, MetadataResult, PluginManifest
from plugins.errors import PluginUpstreamError

_APP_LOGGER = logging.getLogger("uvicorn.error")
_RAW_LOG_MAX = 16_384

# ── 系统提示 ──────────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are a music metadata parser. Given a filename and optional raw tags, \
extract and clean the music metadata.

Rules:
1. Return ONLY valid JSON — no explanation, no markdown.
2. Split multiple artists on: feat. / ft. / & / 、/ ; — each becomes a separate list element.
3. The first element of "artists" is the primary artist.
4. If title and artist appear swapped (e.g. artist looks like a song name), correct them.
5. Strip track numbers, dashes, underscores, brackets from title when they are clearly noise.
6. Remove source/site/watermark/uploader/release-group tokens from all metadata fields,
   including title, artists, and album. If such a token is attached to valid metadata,
   keep the valid music metadata and remove only the source token.
   Examples: "[51ape.com]陶喆" -> "陶喆"; "【example.net】Some Artist" -> "Some Artist".
7. Set a field to null if it genuinely cannot be determined.
8. "track_number" must be an integer (0 if unknown).

Output schema (strict):
{
  "title": "<song title>",
  "artists": ["<primary artist>", "<featured artist>", ...],
  "album": "<album name or null>",
  "track_number": 0
}"""

# 用于从模型输出里提取第一个 JSON 对象（防止模型输出多余文字）
_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)


def _metadata_json_safe(value):
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return None
    if isinstance(value, (list, tuple)):
        cleaned = [_metadata_json_safe(x) for x in value]
        return [x for x in cleaned if x not in (None, "", [], {})]
    if isinstance(value, dict):
        cleaned = {str(k): _metadata_json_safe(v) for k, v in value.items()}
        return {k: v for k, v in cleaned.items() if v not in (None, "", [], {})}
    text = str(value).strip()
    return text or None


def _metadata_for_json(raw_tags: dict) -> dict:
    out: dict = {}
    for key, value in raw_tags.items():
        safe = _metadata_json_safe(value)
        if safe not in (None, "", [], {}):
            out[key] = safe
    return out


def _hint_ollama_model_missing(model: str, http_body: str) -> str:
    """Parse Ollama JSON error body; return extra hint for model-not-found."""
    try:
        data = json.loads(http_body)
    except json.JSONDecodeError:
        return ""
    err = str(data.get("error", "")).lower()
    if "not found" not in err or "model" not in err:
        return ""
    return (
        f" 未安装模型 {model!r}：在运行 Ollama 的主机执行 `ollama pull {model}`。"
        f"标签须与官方库一致（勿写成 qwen35；Qwen3.5 见 https://ollama.com/library/qwen3.5 ）。"
    )


def _build_user_message(filename_stem: str, raw_tags: Optional[dict]) -> str:
    lines = [f'filename: "{filename_stem}"']
    if raw_tags:
        relevant = _metadata_for_json({
            k: raw_tags[k]
            for k in (
                "title",
                "artist",
                "artists",
                "album",
                "album_artist",
                "album_artists",
                "track_number",
                "release_date",
                "lyrics",
                "raw_text_tags",
            )
            if raw_tags.get(k)
        })
        if relevant:
            lines.append(f"tags: {json.dumps(relevant, ensure_ascii=False)}")
    return "\n".join(lines)


def _parse_response(content: str) -> Optional[dict]:
    """Extract and validate the JSON object from model output."""
    content = content.strip()
    # 优先直接解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    # 从输出中提取第一个 {...}
    m = _JSON_RE.search(content)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


def _text_from_native_chat(body: dict) -> Optional[str]:
    msg = body.get("message")
    if isinstance(msg, dict):
        c = msg.get("content")
        if c is not None and str(c).strip():
            return str(c)
    return None


def _text_from_openai_compat(body: dict) -> Optional[str]:
    choices = body.get("choices")
    if not choices or not isinstance(choices, list):
        return None
    ch0 = choices[0]
    if not isinstance(ch0, dict):
        return None
    msg = ch0.get("message")
    if isinstance(msg, dict):
        c = msg.get("content")
        if c is not None and str(c).strip():
            return str(c)
    return None


def _text_from_generate(body: dict) -> Optional[str]:
    c = body.get("response")
    if c is not None and str(c).strip():
        return str(c)
    return None


async def _ollama_infer_json(
    client: httpx.AsyncClient,
    base_url: str,
    model: str,
    user_msg: str,
    *,
    think: bool = False,
) -> str:
    """Return model text content (expected JSON). Tries chat, OpenAI compat, then generate."""
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    chat_payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "think": think,
        "options": {"temperature": 0},
    }
    last_err: Optional[str] = None

    r = await client.post(f"{base_url}/api/chat", json=chat_payload)
    if 200 <= r.status_code < 300:
        try:
            t = _text_from_native_chat(r.json())
            if t is not None:
                return t
        except json.JSONDecodeError:
            pass
    else:
        last_err = f"/api/chat HTTP {r.status_code}"

    openai_base = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "stream": False,
    }
    r = await client.post(
        f"{base_url}/v1/chat/completions",
        json={**openai_base, "response_format": {"type": "json_object"}},
    )
    if r.status_code == 400:
        r = await client.post(f"{base_url}/v1/chat/completions", json=openai_base)
    if 200 <= r.status_code < 300:
        try:
            t = _text_from_openai_compat(r.json())
            if t is not None:
                return t
        except json.JSONDecodeError:
            pass
    else:
        last_err = f"/v1/chat/completions HTTP {r.status_code}"

    gen_payload = {
        "model": model,
        "system": _SYSTEM_PROMPT,
        "prompt": user_msg,
        "format": "json",
        "stream": False,
        "think": think,
        "options": {"temperature": 0},
    }
    r = await client.post(f"{base_url}/api/generate", json=gen_payload)
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as exc:
        tail = (r.text or "")[:400]
        miss = _hint_ollama_model_missing(model, r.text or "")
        openai_note = ""
        if last_err and "v1/chat/completions" in last_err and "404" in last_err:
            openai_note = "（/v1/chat/completions 404 时升级 Ollama 可启用 OpenAI 兼容层，见 https://docs.ollama.com/openai ）"
        raise PluginUpstreamError(
            f"Ollama 推理均失败（{last_err or 'chat/openai 无有效正文'}；"
            f"最后 /api/generate HTTP {r.status_code} {tail!r}）{miss}{openai_note}"
        ) from exc
    try:
        body = r.json()
    except json.JSONDecodeError as exc:
        raise PluginUpstreamError(f"Ollama /api/generate 返回非 JSON: {(r.text or '')[:200]!r}") from exc
    t = _text_from_generate(body)
    if t is None:
        raise PluginUpstreamError(f"Ollama /api/generate 响应无 response 文本: {body!r}")
    return t


def _coerce_result(data: dict) -> Optional[MetadataResult]:
    title = data.get("title")
    if isinstance(title, str):
        title = title.strip() or None

    raw_artists = data.get("artists") or []
    if isinstance(raw_artists, str):
        raw_artists = [raw_artists]
    artists = [a.strip() for a in raw_artists if isinstance(a, str) and a.strip()]

    album = data.get("album")
    if isinstance(album, str):
        album = album.strip() or None

    try:
        track_number = int(data.get("track_number") or 0)
    except (TypeError, ValueError):
        track_number = 0

    if not title and not artists:
        return None

    return MetadataResult(
        title=title,
        artists=artists,
        album=album,
        track_number=track_number or None,
        confidence=0.9,
    )


class LLMMetadataPlugin(MetadataPlugin):
    manifest = PluginManifest(
        id="llm-metadata",
        name="LLM Metadata Parser",
        version="1.0.0",
        capabilities=["metadata"],
    )

    def setup(self, ctx) -> None:
        super().setup(ctx)
        base_url = ctx.config.get("ollama_base_url", "http://172.19.240.1:11434").rstrip("/")
        model    = ctx.config.get("model", "qwen3.5:latest")

        # ── 连通性探测 ────────────────────────────────────────
        self.ctx.log("info", f"探测 Ollama 连通性: {base_url}/api/tags")
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{base_url}/api/tags")
        except httpx.RequestError as exc:
            raise PluginUpstreamError(f"Ollama 不可达 ({base_url}): {exc}") from exc

        if resp.status_code < 200 or resp.status_code >= 300:
            raise PluginUpstreamError(
                f"Ollama /api/tags 返回 HTTP {resp.status_code}，请确认 ollama_base_url "
                f"（当前 {base_url}）指向本机或局域网的 Ollama（默认 http://<host>:11434）。"
            )

        try:
            tags_data = resp.json()
        except json.JSONDecodeError as exc:
            raise PluginUpstreamError(
                f"Ollama /api/tags 返回非 JSON，请确认 {base_url} 是否为 Ollama 服务。"
            ) from exc

        if not isinstance(tags_data, dict) or "models" not in tags_data:
            raise PluginUpstreamError(
                f"Ollama /api/tags 响应缺少 models 字段，{base_url} 可能不是 Ollama。"
            )

        # ── 检查目标模型是否已拉取（须与 ollama.com/library 标签一致）────────────────
        available = [
            m["name"]
            for m in tags_data.get("models", [])
            if isinstance(m, dict) and m.get("name")
        ]

        if not available:
            raise PluginUpstreamError(
                f"Ollama 未报告任何本地模型。请在 Ollama 主机执行 `ollama pull {model}` "
                f"（名称须与 ollama list 一致，Qwen3.5 常见为 qwen3.5:latest 或 qwen3.5:9b）。"
            )

        base_name = model.split(":", 1)[0]
        if not any(
            m == model or m.startswith(base_name + ":")
            for m in available
        ):
            raise PluginUpstreamError(
                f"Ollama 中未找到模型 {model!r}（已安装示例: {available[:12]}）。"
                f"请执行 `ollama pull {model}`，并确认配置里写的是官方标签（Qwen3.5："
                f"https://ollama.com/library/qwen3.5 ）。"
            )

        self.ctx.log(
            "info",
            f"Ollama 已连接: {base_url}  模型: {model}"
            + (f"  可用模型数: {len(available)}" if available else ""),
        )

        # 自检通过后注册流水线回调
        ctx.register_for_stage("parse_upload", self.parse_upload)

    async def parse_upload(
        self,
        filename_stem: str,
        raw_tags: Optional[dict] = None,
    ) -> Optional[MetadataResult]:
        base_url: str = self.ctx.config.get("ollama_base_url", "http://172.19.240.1:11434").rstrip("/")
        model: str    = self.ctx.config.get("model", "qwen3.5:latest")
        timeout: float = float(self.ctx.config.get("timeout_sec", 120))
        think: bool   = bool(self.ctx.config.get("ollama_think", False))

        user_msg = _build_user_message(filename_stem, raw_tags)
        self.ctx.log(
            "info",
            "parse_upload 输入 model=%r stem=%r ollama_user_text=%r"
            % (model, filename_stem, user_msg),
        )

        async with httpx.AsyncClient(timeout=timeout) as client:
            content = await _ollama_infer_json(
                client, base_url, model, user_msg, think=think
            )

        if _APP_LOGGER.isEnabledFor(logging.DEBUG):
            raw_out = content if len(content) <= _RAW_LOG_MAX else (
                content[: _RAW_LOG_MAX // 2]
                + "\n...[truncated]...\n"
                + content[-(_RAW_LOG_MAX // 2) :]
            )
            self.ctx.log("debug", f"parse_upload 模型原始输出 ({len(content)} chars): {raw_out!r}")

        data = _parse_response(content)
        if data is None:
            self.ctx.log(
                "warning",
                "parse_upload 解析失败：无法从模型输出得到 JSON（info 已记录输入；"
                f"原始片段 preview={content[:240]!r}）",
            )
            return None

        self.ctx.log(
            "info",
            "parse_upload 解析 JSON: %s"
            % (json.dumps(data, ensure_ascii=False),),
        )

        result = _coerce_result(data)
        if result is None:
            self.ctx.log(
                "warning",
                "parse_upload 无有效 MetadataResult（title 与 artists 均为空） data=%s"
                % (json.dumps(data, ensure_ascii=False),),
            )
        else:
            self.ctx.log(
                "info",
                "parse_upload 结果 title=%r artists=%r album=%r track_number=%s confidence=%s"
                % (
                    result.title,
                    result.artists,
                    result.album,
                    result.track_number,
                    result.confidence,
                ),
            )
        return result


plugin = LLMMetadataPlugin()
