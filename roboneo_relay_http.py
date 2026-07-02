"""HTTP relay RoboNeo — chỉ bind localhost, Motion gọi qua VPS nội bộ."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from project_env import get_env, load_project_env
from roboneo_relay import (
    poll_relay_job,
    read_relay_video,
    relay_enabled,
    relay_secret,
    submit_relay_job,
    wire,
)

load_project_env()


class _RelayHandler(BaseHTTPRequestHandler):
    server_version = "RoboNeoRelay/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[relay] {self.address_string()} — {fmt % args}")

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _secret(self, body: dict | None = None) -> str:
        hdr = (self.headers.get("X-Relay-Secret") or "").strip()
        if hdr:
            return hdr
        if body:
            return str(body.get("secret") or "").strip()
        return ""

    def _json(self, code: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/v1/roboneo/submit":
                body = self._read_json()
                body["secret"] = self._secret(body)
                out = submit_relay_job(body)
                self._json(200, out)
                return
            self._json(404, {"ok": False, "error": "not found"})
        except PermissionError as e:
            self._json(403, {"ok": False, "error": str(e)})
        except Exception as e:
            self._json(500, {"ok": False, "error": str(e)})

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        secret = self._secret()
        try:
            parts = [p for p in path.strip("/").split("/") if p]
            # /v1/roboneo/jobs/{id} | /v1/roboneo/jobs/{id}/video
            if len(parts) >= 4 and parts[0] == "v1" and parts[1] == "roboneo" and parts[2] == "jobs":
                relay_id = parts[3]
                if len(parts) >= 5 and parts[4] == "video":
                    data, name = read_relay_video(relay_id, secret=secret)
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Content-Disposition", f'inline; filename="{name}"')
                    self.end_headers()
                    self.wfile.write(data)
                    return
                out = poll_relay_job(relay_id, secret=secret)
                self._json(200, out)
                return
            self._json(404, {"ok": False, "error": "not found"})
        except KeyError as e:
            self._json(404, {"ok": False, "error": str(e)})
        except PermissionError as e:
            self._json(403, {"ok": False, "error": str(e)})
        except FileNotFoundError as e:
            self._json(409, {"ok": False, "error": str(e)})
        except Exception as e:
            self._json(500, {"ok": False, "error": str(e)})


def start_relay_http_server(*, download_file) -> None:
    if not relay_enabled():
        print("ℹ️ RoboNeo relay HTTP tắt (ROBONEO_RELAY_ENABLED=0)")
        return
    if not relay_secret():
        print("⚠️ RoboNeo relay: thiếu ROBONEO_RELAY_SECRET — không start HTTP")
        return
    wire(download_file=download_file)
    host = (get_env("ROBONEO_RELAY_HOST") or "127.0.0.1").strip()
    port = int(get_env("ROBONEO_RELAY_PORT", "18765") or "18765")

    def _run() -> None:
        server = ThreadingHTTPServer((host, port), _RelayHandler)
        print(f"🔌 RoboNeo relay HTTP → http://{host}:{port} (secret đã set)")
        server.serve_forever()

    threading.Thread(target=_run, daemon=True).start()
