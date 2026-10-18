"""Local-only calendar editor and GitHub subscription publisher."""
import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from .models import ValidationError
from .plugins import load_sources
from .workspace import WorkspaceService
from .publishing import PublishError

STATIC = Path(__file__).parent / "static"


def handler_for(service):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body, content_type="application/json; charset=utf-8"):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def local_request(self):
            host = urlsplit('//' + self.headers.get('Host', '')).hostname
            if host not in ('localhost', '127.0.0.1', '::1'):
                self.reply(403, {"error": "仅允许本机访问"})
                return False
            return True

        def do_GET(self):
            if not self.local_request():
                return
            path = urlsplit(self.path).path
            if path == "/api/state":
                project_id = parse_qs(urlsplit(self.path).query).get('project', [None])[0]
                try:
                    return self.reply(200, service.snapshot(project_id))
                except KeyError:
                    return self.reply(404, {"error": "项目不存在"})
            if path in ("/", "/app.js", "/style.css", "/chevron-down.svg", "/check.svg"):
                name = "index.html" if path == "/" else path[1:]
                mime = {"index.html": "text/html", "app.js": "text/javascript", "style.css": "text/css", "chevron-down.svg": "image/svg+xml", "check.svg": "image/svg+xml"}[name]
                return self.reply(200, (STATIC / name).read_bytes(), mime + "; charset=utf-8")
            with service.lock:
                allowed = {f"/subscription/{key}.ics" for key in service.calendars}
                if path in allowed:
                    return self.reply(200, (service.root / path[1:]).read_bytes(), "text/calendar; charset=utf-8")
            self.reply(404, {"error": "页面不存在"})

        def mutate(self):
            if not self.local_request():
                return
            try:
                origin = self.headers.get("Origin")
                if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                    return self.reply(403, {"error": "不允许跨站修改"})
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    return self.reply(415, {"error": "请使用 application/json"})
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 1024 * 1024:
                    return self.reply(413, {"error": "请求内容为空或超过 1 MB"})
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValidationError("请求必须为 JSON 对象")
                parts = urlsplit(self.path).path.strip("/").split("/")
                with service.lock:
                    if parts == ["api", "projects"] and self.command == "POST":
                        return self.reply(201, service.create(payload))
                    if len(parts) >= 3 and parts[:2] == ["api", "projects"]:
                        project_id = parts[2]
                        calendar = service.calendar(project_id)
                        if len(parts) == 3 and self.command == "PUT":
                            return self.reply(200, service.configure(project_id, payload))
                        if parts[3:] == ["publish"] and self.command == "POST":
                            return self.reply(200, service.publish_project(project_id))
                        if parts[3:] == ["events"] and self.command == "POST":
                            return self.reply(201, calendar.save(payload))
                        if len(parts) == 5 and parts[3] == "events":
                            if self.command == "PUT":
                                return self.reply(200, calendar.save(payload, parts[4]))
                            if self.command == "DELETE":
                                calendar.delete(parts[4])
                                return self.reply(200, {"ok": True})
                        if len(parts) == 6 and parts[3] == "sources" and parts[5] == "refresh" and self.command == "POST":
                            calendar.refresh(parts[4], payload)
                            return self.reply(200, {"ok": True})
                self.reply(404, {"error": "接口不存在"})
            except KeyError:
                self.reply(404, {"error": "渠道或事件不存在"})
            except PublishError as exc:
                self.reply(409, {"error": str(exc)})
            except (ValidationError, ValueError, TypeError) as exc:
                self.reply(400, {"error": str(exc)})
            except Exception:
                logging.exception("Calendar operation failed")
                self.reply(500, {"error": "操作失败，原有渠道数据不会因采集失败而清空；请查看服务日志"})

        do_POST = do_PUT = do_DELETE = mutate
    return Handler


def main():
    parser = argparse.ArgumentParser(description="统一日历订阅中心")
    parser.add_argument("--host", choices=["127.0.0.1", "localhost"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="data 和 subscription 的父目录")
    parser.add_argument("--plugin", action="append", default=[], metavar="MODULE:CLASS")
    args = parser.parse_args()
    service = WorkspaceService(args.root, load_sources(args.plugin))
    server = ThreadingHTTPServer((args.host, args.port), handler_for(service))
    print(f"日历中心：http://{args.host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
