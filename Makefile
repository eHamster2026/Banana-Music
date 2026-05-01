.PHONY: help install run clean build test docker-build up down logs restart pull-model

# ── 默认目标 ──────────────────────────────────────────────────────────────────
help:
	@echo "常用目标："
	@echo "  make install      安装后端（含 dev 依赖）与前端依赖"
	@echo "  make run          启动本地开发栈（后端 :8000 + 前端 :5173）"
	@echo "  make clean        清理本地开发依赖与构建产物"
	@echo "  make build        编译前端到 frontend/dist/"
	@echo "  make test         运行后端 pytest + 前端 Vitest"
	@echo "  make docker-build 编译前端并构建 banana-music Docker 镜像"
	@echo "  make up           启动全部服务（banana-music + solara + ollama）"
	@echo "  make down         停止全部服务"
	@echo "  make logs         跟踪主应用日志"
	@echo "  make restart      重启主应用（插件配置改动后使用）"
	@echo "  make pull-model   拉取默认 LLM 模型（首次启动 ollama 后）"

# ── 开发环境 ──────────────────────────────────────────────────────────────────
install:
	cd backend && UV_PROJECT_ENVIRONMENT=venv uv sync --extra dev
	cd frontend && npm install

run:
	bash scripts/dev-local.sh stack

clean:
	rm -rf backend/venv
	rm -rf frontend/node_modules frontend/dist frontend/.vite
	rm -rf backend/.pytest_cache backend/.ruff_cache

# ── 前端编译 ─────────────────────────────────────────────────────────────────
build:
	cd frontend && npm ci && npm run build

# ── 测试 ──────────────────────────────────────────────────────────────────────
test:
	UV_PROJECT_ENVIRONMENT="$(shell pwd)/backend/venv" \
	  uv run --directory backend pytest tests/ -v --tb=short
	cd frontend && npm run test

# ── Docker 打包 ───────────────────────────────────────────────────────────────
docker-build: build
	docker build --target production -t banana-music:latest .

# ── Compose 操作 ──────────────────────────────────────────────────────────────
up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f banana-music

restart:
	docker compose restart banana-music

pull-model:
	docker compose exec ollama ollama pull qwen3.5:latest

# ── 一键部署（打包 + 启动）───────────────────────────────────────────────────
deploy: docker-build up
