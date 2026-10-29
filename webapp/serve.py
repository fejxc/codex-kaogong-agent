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
