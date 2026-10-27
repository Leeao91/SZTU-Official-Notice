# -*- coding: utf-8 -*-
"""
公文通 · 手机版服务端
=====================
把 reports/ 下的日报（.json）通过一个小型 HTTP 服务提供给手机浏览器，
手机连同一个校园网/WiFi 即可打开，支持「添加到主屏幕」当 App 用。

用法：
    python serve.py               # 默认 8080 端口
    python serve.py --port 9000
    python serve.py --open        # 启动后自动打开浏览器

仅依赖 Python 3 标准库。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .core import DATA_DIR, ROOT

WEB_DIR = Path(__file__).resolve().parent / "web"
REPORTS_DIR = DATA_DIR / "reports"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def lan_ips() -> list[str]:
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))          # 不真正发包，只为拿到出口网卡地址
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    return ips or ["127.0.0.1"]


def load_days(limit: int) -> tuple[list[dict], dict]:
    """读最近 limit 天的 JSON，返回 (days 摘要, {date: 完整日报})。"""
    files = [f for f in sorted(REPORTS_DIR.glob("*.json"), reverse=True) if f.name != "latest.json"]
    days, reports = [], {}
    for f in files[:limit]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        date = data.get("date", f.stem)
        reports[date] = data
        days.append({
            "date": date,
            "count": data.get("count", len(data.get("items", []))),
            "by_category": data.get("by_category", {}),
            "generated_at": data.get("generated_at", ""),
            "baseline": bool(data.get("baseline")),
        })
    return days, reports


def build_offline_html(limit: int = 14) -> str:
    """把前端资源 + 数据内联成一个可以直接发到手机上打开的单文件 HTML。"""
    days, reports = load_days(limit)
    index = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    css = (WEB_DIR / "style.css").read_text(encoding="utf-8")
    js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    payload = json.dumps({"days": days, "reports": reports}, ensure_ascii=False).replace("</", "<\\/")

    html = index
    html = re.sub(r'<link rel="stylesheet" href="/style.css">', f"<style>\n{css}\n</style>", html)
    html = re.sub(r'<link rel="manifest"[^>]*>', "", html)
    html = re.sub(r'<link rel="icon"[^>]*>', "", html)
    html = re.sub(r'<link rel="apple-touch-icon"[^>]*>', "", html)
    html = html.replace('<script src="/app.js"></script>',
                        f"<script>window.__NBW_DATA__ = {payload};</script>\n"
                        f"<script>\n{js}\n</script>")
    return html


class Handler(BaseHTTPRequestHandler):
    server_version = "NBWDigest/1.0"
    protocol_version = "HTTP/1.0"

    # ---------- 工具 ----------
    def _send(self, body: bytes, ctype: str, status: int = 200, cache: str = "no-store"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, status: int = 200):
        self._send(json.dumps(obj, ensure_ascii=False), MIME[".json"], status)

    def _file(self, path: Path, cache: str = "no-store"):
        if not path.is_file():
            return self._json({"error": "not found", "path": str(path.name)}, 404)
        self._send(path.read_bytes(), MIME.get(path.suffix.lower(), "application/octet-stream"), 200, cache)

    # ---------- 路由 ----------
    def do_GET(self):
        path = unquote(urlparse(self.path).path)

        if path in ("/", "/index.html"):
            return self._file(WEB_DIR / "index.html", "no-cache")

        if path == "/api/days":
            return self._api_days()
        if path == "/api/latest":
            return self._file(REPORTS_DIR / "latest.json")
        if path == "/export":
            return self._export()
        if path.startswith("/api/day/"):
            day = path[len("/api/day/"):].strip("/")
            if not day.replace("-", "").isdigit():
                return self._json({"error": "bad date"}, 400)
            return self._file(REPORTS_DIR / f"{day}.json")

        # 静态资源：web/ 目录
        rel = path.lstrip("/")
        if rel and ".." not in rel:
            candidate = WEB_DIR / rel
            if candidate.is_file():
                return self._file(candidate)
            # 兼容旧的日报文件：/reports/xxx.md|html|json
            if rel.startswith("reports/"):
                legacy = ROOT / rel
                if legacy.is_file():
                    return self._file(legacy)

        return self._json({"error": "not found"}, 404)

    def _export(self):
        """生成离线单文件版（把最近 N 天数据内联进 HTML），方便发到手机上直接打开。"""
        qs = parse_qs(urlparse(self.path).query)
        n = int(qs.get("days", ["14"])[0] or 14)
        html = build_offline_html(n)
        self._send(html, MIME[".html"], 200, "no-store")

    def _api_days(self):
        days = []
        for f in sorted(REPORTS_DIR.glob("*.json"), reverse=True):
            if f.name == "latest.json":
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            days.append({
                "date": data.get("date", f.stem),
                "count": data.get("count", len(data.get("items", []))),
                "by_category": data.get("by_category", {}),
                "generated_at": data.get("generated_at", ""),
                "baseline": bool(data.get("baseline")),
            })
        self._json({"days": days})

    def log_message(self, fmt, *args):   # 安静一点，只记错误
        if args and isinstance(args[1], str) and args[1].startswith(("4", "5")):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main() -> int:
    ap = argparse.ArgumentParser(description="公文通手机版服务")
    ap.add_argument("--port", type=int, default=int(os.environ.get("NBW_PORT", "8080")))
    ap.add_argument("--open", action="store_true", help="启动后自动打开本机浏览器")
    ap.add_argument("--export", metavar="FILE", nargs="?", const=str(REPORTS_DIR / "手机版-离线.html"),
                    help="生成离线单文件 HTML（内联最近 14 天数据）后退出，可直接发到手机打开")
    ap.add_argument("--days", type=int, default=14, help="离线版包含最近几天，默认 14")
    args = ap.parse_args()

    if not WEB_DIR.is_dir():
        print(f"[fatal] 找不到前端目录：{WEB_DIR}")
        return 1
    if not (REPORTS_DIR / "latest.json").exists():
        print("[warn] reports/latest.json 还不存在，先运行一次 nbw_digest.py")

    if args.export:
        out = Path(args.export)
        html = build_offline_html(args.days)
        out.write_text(html, encoding="utf-8")
        print(f"已生成离线版：{out}（{len(html.encode('utf-8'))/1024:.0f} KB，含最近 {args.days} 天）")
        print("把这个文件发到手机（微信/QQ/网盘），用浏览器打开即可，无需电脑和网络。")
        return 0

    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    except OSError as exc:
        print(f"[fatal] 端口 {args.port} 无法监听：{exc}")
        return 1

    local = f"http://127.0.0.1:{args.port}"
    print("公文通 · 手机版已启动", flush=True)
    print(f"  本机访问：{local}", flush=True)
    for ip in lan_ips():
        print(f"  手机访问：http://{ip}:{args.port}   ← 手机连同一个 WiFi/校园网后打开", flush=True)
    print("  手机浏览器里点「添加到主屏幕」，即可当作 App 使用", flush=True)
    print("  按 Ctrl+C 停止\n", flush=True)

    if args.open:
        webbrowser.open(local)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
