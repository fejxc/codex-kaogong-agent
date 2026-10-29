#!/usr/bin/env python3
"""公考备考台 · 本地运行器

只做两件事（无业务逻辑、仅监听本机）：
1. 以 webapp/ 为根提供静态站点；
2. 只读挂载两个本地数据源，供页面"一键载入"：
   /bank.jsonl   <- data/复盘引擎/题库/exam-research-pool.jsonl（存在时）
   /methods.json <- .agents/skills/xingce-review-pro/references 下的 .md（排除 exam-research 挂载）

用法：python3 webapp/serve.py [端口]   （默认 8901）
"""
import json
import sys
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEBAPP = ROOT / "webapp"
BANK = ROOT / "data" / "复盘引擎" / "题库" / "exam-research-pool.jsonl"
METHODS_DIR = ROOT / ".agents" / "skills" / "xingce-review-pro" / "references"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEBAPP), **kwargs)

    def end_headers(self):
        # 本地开发避免 app.js 改动后被缓存
        if self.path.endswith((".html", ".js", ".css")):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path == "/bank.jsonl":
            return self._send_file(BANK, "application/x-ndjson")
        if self.path == "/methods.json":
            return self._send_methods()
        return super().do_GET()

    def do_POST(self):
        # /llm/* 同源反向代理：浏览器同源请求不触发 CORS，转发到请求头 X-Target-Base 指定的端点。
        # 仅用于自建 OpenAI 兼容端点未开跨域的场景；本服务只监听 127.0.0.1。
        if not self.path.startswith("/llm/"):
            self.send_error(404)
            return
        target_base = self.headers.get("X-Target-Base", "").rstrip("/")
        subpath = self.path[4:]  # 去掉 /llm
        if not (target_base.startswith("http://") or target_base.startswith("https://")):
            self.send_error(400, "missing or invalid X-Target-Base")
            return
        url = target_base + subpath
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", self.headers.get("Content-Type", "application/json"))
        if self.headers.get("Authorization"):
            req.add_header("Authorization", self.headers["Authorization"])
        try:
            resp = urllib.request.urlopen(req, timeout=300)
        except urllib.error.HTTPError as e:
            resp = e
        except Exception as e:  # noqa: BLE001 — 上游不可达时给页面一个可读错误
            payload = json.dumps({"error": {"message": f"代理无法连到 {url}: {e}"}}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(resp.status if hasattr(resp, "status") else resp.code)
        self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
        self.end_headers()
        try:
            while chunk := resp.read(8192):
                self.wfile.write(chunk)
        finally:
            resp.close()

    def _send_file(self, path, ctype):
        if not path.is_file():
            self.send_error(404, "local mount not found: %s" % path.relative_to(ROOT))
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()
        with path.open("rb") as f:
            while chunk := f.read(1 << 16):
                self.wfile.write(chunk)

    def _send_methods(self):
        files = []
        if METHODS_DIR.is_dir():
            for p in sorted(METHODS_DIR.rglob("*.md")):
                if "exam-research" in p.parts or p.is_symlink() or p.stat().st_size > 400_000:
                    continue
                files.append({"path": str(p.relative_to(METHODS_DIR)), "text": p.read_text(encoding="utf-8", errors="ignore")})
        body = json.dumps(files, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("[serve] %s\n" % (fmt % args))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8901
    bank_note = "✔ 题库已挂载 /bank.jsonl" if BANK.is_file() else "✘ 未找到题库（/bank.jsonl 将 404）"
    print(f"公考备考台  http://127.0.0.1:{port}")
    print(bank_note)
    print(f"方法库挂载  /methods.json（{METHODS_DIR.relative_to(ROOT)}）")
    ThreadingHTTPServer(("127.0.0.1", port), partial(Handler)).serve_forever()


if __name__ == "__main__":
    main()
