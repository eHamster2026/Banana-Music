#!/usr/bin/env bash
# 本地开发：不经过 Docker / act。日常最快用法是「后端 + Vite 双终端」，无需每次 production build。
# 首次后端请执行：cd backend && UV_PROJECT_ENVIRONMENT=venv uv sync --extra dev
# 首次前端请：cd frontend && npm install（或 npm ci）

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export UV_PROJECT_ENVIRONMENT="${ROOT}/backend/venv"
# 本地 stack/backend/serve：指纹成功后自动调用元数据插件（覆盖 config / .env 默认 false）
export UPLOAD_AUTO_METADATA_AFTER_FINGERPRINT=true

usage() {
  cat <<'EOF'
本地开发：不经过 Docker / act。日常最快：两个终端分别 backend + frontend（Vite 热更新，无需每次 build）。

首次后端依赖: cd backend && UV_PROJECT_ENVIRONMENT=venv uv sync --extra dev
首次前端依赖: cd frontend && npm install

子命令:
  backend   启动 uvicorn（--reload），监听 0.0.0.0:8000
  frontend  启动 Vite 开发服务器（默认 http://localhost:5173，API 已配置代理到 :8000）
  stack     同一终端：后台 uvicorn + 前台 Vite（Ctrl+C 会结束两者）
  build     仅执行前端 production 构建（写入 frontend/dist，供后端静态托管）
  serve     假设 frontend/dist 已存在，仅启动 uvicorn（接近生产静态资源方式）

示例（推荐）:
  终端1: bash scripts/dev-local.sh backend
  终端2: bash scripts/dev-local.sh frontend
EOF
}

cmd="${1:-}"
case "$cmd" in
  backend)
    cd "${ROOT}/backend"
    exec uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000 --log-level debug
    ;;
  frontend)
    cd "${ROOT}/frontend"
    exec npm run dev
    ;;
  stack)
    cleanup() {
      if [[ -n "${_UV_PID:-}" ]] && kill -0 "${_UV_PID}" 2>/dev/null; then
        kill "${_UV_PID}" 2>/dev/null || true
        wait "${_UV_PID}" 2>/dev/null || true
      fi
    }
    trap cleanup EXIT INT TERM
    cd "${ROOT}/backend"
    uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000 --log-level debug &
    _UV_PID=$!
    cd "${ROOT}/frontend"
    npm run dev
    ;;
  build)
    cd "${ROOT}/frontend"
    exec npm run build
    ;;
  serve)
    cd "${ROOT}/backend"
    exec uv run uvicorn main:app --host 0.0.0.0 --port 8000
    ;;
  ""|-h|--help|help)
    usage
    ;;
  *)
    echo "未知子命令: $cmd" >&2
    usage >&2
    exit 1
    ;;
esac
