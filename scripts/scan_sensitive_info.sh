#!/usr/bin/env bash
set -euo pipefail

# 文件级排除：规避依赖、数据库、构建产物和大文件
RG_COMMON_ARGS=(
  --hidden
  -g '!.git'
  -g '!**/.git/**'
  -g '!frontend/node_modules/**'
  -g '!frontend/dist/**'
  -g '!frontend/.vite/**'
  -g '!frontend/.npm/**'
  -g '!frontend/package-lock.json'
  -g '!frontend/.cache/**'
  -g '!backend/.venv/**'
  -g '!backend/venv/**'
  -g '!backend/.pytest_cache/**'
  -g '!backend/uv.lock'
  -g '!data/**'
  -g '!**/__pycache__/**'
  -g '!**/*.png'
  -g '!**/*.jpg'
  -g '!**/*.jpeg'
  -g '!**/*.gif'
  -g '!**/*.svg'
  -g '!**/*.zip'
  -g '!**/*.gz'
)

SCAN_PATHS=(
  backend
  frontend/src
  frontend/index.html
  scripts
  plugins
  docs
  README.md
  AGENTS.md
  .github/workflows/test.yml
)

FOUND=0

has_hits() {
  local label="$1"
  local regex="$2"
  local filter="${3-}"

  local raw
  raw="$(rg -n -P "${regex}" "${RG_COMMON_ARGS[@]}" "${SCAN_PATHS[@]}" || true)"

  if [[ -z "${raw}" ]]; then
    return
  fi

  local hits="$raw"
  if [[ -n "${filter}" ]]; then
    hits="$(printf '%s\n' "$raw" | grep -Ev "${filter}" || true)"
  fi

  if [[ -n "$hits" ]]; then
    printf '\n[!] %s\n' "$label"
    printf '%s\n' "$hits"
    FOUND=1
  fi
}

# 1) 高置信度密钥/凭据格式
has_hits "High confidence API keys / tokens" "\\b(sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|am_[A-Za-z0-9_-]{24,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{20,}\\.[A-Za-z0-9_-]{20,}\\.[A-Za-z0-9_-]{20,})\\b"

# 2) 私钥片段
has_hits "Private key artifacts" "(?m)-----BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE KEY-----"

# 3) 明确的硬编码认证字段赋值（仅抓取带明文字符串的赋值）
has_hits "Hardcoded auth values" "(?im)^[[:space:]]*(?:api[_-]?key|api[_-]?token|access[_-]?token|refresh[_-]?token|x[_-]?api[_-]?key|secret[_-]?key|password)\\s*[:=]\\s*['\"][^'\"]{12,}['\"]" "change-me-in-production|demo|example|placeholder|am_xxx|your|user|xxxx|dummy|test|demo123|secret\"?\\)?\\s*$"

# 4) 真实邮箱（排除示例域和占位符）
has_hits "Potential personal emails" "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}" "example\\.com|example\\.org|example\\.net|localhost|localhost:|test\\.com|your@|user@|demo@|u[0-9]+@"

# 5) 11 位手机号（初步规则）
has_hits "Potential phone numbers" "(?<!\\d)(1[3-9][0-9]{9})(?!\\d)" "10086|110|120|119|10010|10001|114"

if (( FOUND != 0 )); then
  echo
  echo "检测到可能的敏感信息。请先确认并替换为占位值后再提交。"
  exit 1
fi

echo "未发现可疑敏感信息。"
