#!/usr/bin/env bash
# 公考备考台 · 一键发布到 GitHub Pages（免费方案）
#
# 用法：
#   ./publish.sh --create <仓库名>          # 用钥匙串里的凭据新建公开仓库并发布
#   ./publish.sh <仓库URL>                 # 发布到你已建好的仓库
#
# 只发布纯客户端文件（index.html / app.js / style.css / vendor/ / README），
# 不含 data/、题库、方法库或任何个人数据。
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
CREATE_NAME=""
REPO_URL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --create) CREATE_NAME="$2"; shift 2 ;;
    *) REPO_URL="$1"; shift ;;
  esac
done

if [[ -n "$CREATE_NAME" ]]; then
  TOKEN="$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill | sed -n 's/^password=//p')"
  [[ -n "$TOKEN" ]] || { echo "✘ 钥匙串中没有 GitHub 凭据"; exit 1; }
  echo "→ 创建公开仓库 $CREATE_NAME …"
  HTTP=$(curl -sS -o /tmp/gh_create.json -w '%{http_code}' -X POST \
    -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" \
    https://api.github.com/user/repos \
    -d "{\"name\":\"$CREATE_NAME\",\"private\":false,\"description\":\"公考备考台 · 纯静态网页客户端（自带模型端点，无内置题库）\"}")
  if [[ "$HTTP" == "422" ]]; then
    echo "ℹ 仓库已存在，直接复用"
  elif [[ "$HTTP" != "201" ]]; then
    echo "✘ 创建失败 HTTP $HTTP：$(head -c 300 /tmp/gh_create.json)"; exit 1
  fi
  REPO_URL="https://github.com/fejxc/$CREATE_NAME.git"
fi

[[ -n "$REPO_URL" ]] || { echo "用法: $0 --create <仓库名> | $0 <仓库URL>"; exit 1; }

# —— 组装发布目录（白名单拷贝，杜绝误带数据）——
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cp "$SRC/index.html" "$SRC/app.js" "$SRC/style.css" "$TMP/"
cp -R "$SRC/vendor" "$TMP/vendor"
cat > "$TMP/README.md" <<'EOF'
# 公考备考台 · 网页客户端

纯静态公考行测/申论讲解客户端：讲解由用户自配的 OpenAI 兼容端点生成，
方法库、题库、错题记录全部只存浏览器本地（IndexedDB），本仓库不含任何题库或个人数据。

打开站点后在「设置」填入端点，并在「设置 → 载入资料」导入题库与方法库即可使用。
详见主仓库 webapp/README.md。
EOF

# —— 推送 ——
cd "$TMP"
git init -q -b main
git add -A
git commit -q -m "Publish webapp client"
git remote add origin "$REPO_URL"
echo "→ 推送到 $REPO_URL …"
git push -q -u origin main --force

# —— 尝试自动开启 Pages（失败则给手动提示）——
REPO_PATH="${REPO_URL#*github.com/}"; REPO_PATH="${REPO_PATH%.git}"
TOKEN="$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill | sed -n 's/^password=//p')"
HTTP=$(curl -sS -o /tmp/gh_pages.json -w '%{http_code}' -X POST \
  -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$REPO_PATH/pages" \
  -d '{"source":{"branch":"main","path":"/"}}' || true)
if [[ "${HTTP:-}" == "201" || "${HTTP:-}" == "409" ]]; then
  echo "✔ Pages 已开启"
else
  echo "ℹ 请手动开启 Pages：仓库 Settings → Pages → Source 选 main / root"
fi

echo
echo "✔ 发布完成，稍后访问: https://$(echo "$REPO_PATH" | cut -d/ -f1).github.io/$(echo "$REPO_PATH" | cut -d/ -f2)/"
