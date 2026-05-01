"""插件抛出的业务异常，供路由层映射为 HTTP 状态码。"""


class PluginUpstreamError(Exception):
    """上游服务异常（网络、HTTP 非预期、业务错误码等）→ 通常映射为 502。"""


class PluginParseError(Exception):
    """响应体解析或结构不符合预期 → 通常映射为 500；日志级别见 docs/logging-and-errors.md。"""
