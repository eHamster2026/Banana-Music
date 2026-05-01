"""
应用日志：使用 Uvicorn 默认配置的 `uvicorn.error` logger，
与 FastAPI / Starlette 应用层输出一致，确保在 Docker 控制台可见。
"""
import logging

logger = logging.getLogger("uvicorn.error")
