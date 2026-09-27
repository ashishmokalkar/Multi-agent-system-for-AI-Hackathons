from __future__ import annotations

import argparse
import json
import mimetypes
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..config import Settings
from ..schemas import AgentRole
from ..store import RunStore
from ..tools import build_tool_registry
from .scenario import ControlRoomManager


TERMINAL = {"complete", "blocked", "cancelled", "failed", "budget_exhausted"}


class ControlRoomApplication:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.tools, _ = build_tool_registry(settings)
        self.store = RunStore(settings.run_root / "runs.sqlite3")
        self.manager = ControlRoomManager(settings, self.tools, self.store)
        self.frontend = settings.project_root / "frontend" / "dist"
        self.recording = settings.project_root / "examples" / "control_room_recording.json"
        self.preview = self.tools.invoke(
            AgentRole.SYNTHETIC_ENGINEER,
            ("prepare_demo_fixture",),
            "prepare_demo_fixture",
            {"run_id": "control-room-preview"},
        )

    def latest_control_room_run(self) -> dict[str, Any] | None:
        for row in self.store.list_runs():
            try:
                run = self.store.get_run(row["run_id"])
            except KeyError:
                continue
            if run["objective"].get("task_kind") == "synthetic" and run.get("events"):
                return run
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "AudioCompetitionControlRoom/1.0"

    @property
    def app(self) -> ControlRoomApplication:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        print(f"control-room: {format % args}")

    def _headers(self, status: int, content_type: str, length: int | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5173")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def _json(self, value: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(value, sort_keys=True).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_OPTIONS(self) -> None:
        self._headers(HTTPStatus.NO_CONTENT, "text/plain", 0)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/runs":
                mode = str(self._body().get("mode", "mock"))
                run_id = self.app.manager.start(mode)
                self._json({"run_id": run_id, "mode": mode}, HTTPStatus.ACCEPTED)
                return
            if parsed.path.endswith("/cancel") and parsed.path.startswith("/api/runs/"):
                run_id = parsed.path.split("/")[3]
                cancelled = self.app.manager.cancel(run_id)
                self._json({"run_id": run_id, "cancelled": cancelled}, HTTPStatus.OK if cancelled else HTTPStatus.CONFLICT)
                return
            if parsed.path == "/api/reset":
                self._json({"reset": True, "note": "UI state reset; persisted run records were preserved."})
                return
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except (ValueError, RuntimeError) as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception as error:
            self._json({"error": f"backend error: {error}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                self._json({
                    "status": "ok",
                    "live_available": self.app.manager.live_available(),
                    "modes": {
                        "live": "actual OpenAI Agents SDK calls and real tools",
                        "mock": "offline deterministic agents and real local tools",
                        "replay": "captured mock trace unless source_mode says live",
                    },
                })
                return
            if parsed.path == "/api/demo/fixture":
                self._json({
                    "duration_seconds": self.app.preview["duration_seconds"],
                    "sample_rate": self.app.preview["sample_rate"],
                    "caption": self.app.preview["caption"],
                    "known_reference": self.app.preview["known_reference"],
                    "original_annotation": self.app.preview["original_annotation"],
                    "audio_url": "/api/demo/audio.wav",
                })
                return
            if parsed.path == "/api/demo/audio.wav":
                self._file(Path(self.app.preview["audio_path"]), "audio/wav")
                return
            if parsed.path == "/api/recordings/default":
                if self.app.recording.is_file():
                    self._file(self.app.recording, "application/json; charset=utf-8")
                    return
                run = self.app.latest_control_room_run()
                if run:
                    self._json({"source_mode": run["mode"], "run_id": run["run_id"], "events": run["events"]})
                    return
                self._json({"error": "no captured recording is available"}, HTTPStatus.NOT_FOUND)
                return
            if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/stream"):
                run_id = parsed.path.split("/")[3]
                after = int(parse_qs(parsed.query).get("after", ["0"])[0])
                self._stream(run_id, after)
                return
            if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/events"):
                run_id = parsed.path.split("/")[3]
                after = int(parse_qs(parsed.query).get("after", ["0"])[0])
                self._json({"run_id": run_id, "events": self.app.store.list_events(run_id, after)})
                return
            if parsed.path.startswith("/api/runs/"):
                run_id = parsed.path.split("/")[3]
                self._json(self.app.store.get_run(run_id))
                return
            self._static(parsed.path)
        except KeyError as error:
            self._json({"error": str(error)}, HTTPStatus.NOT_FOUND)
        except Exception as error:
            self._json({"error": f"backend error: {error}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _stream(self, run_id: str, after: int) -> None:
        self._headers(HTTPStatus.OK, "text/event-stream; charset=utf-8")
        sequence = after
        try:
            while True:
                events = self.app.store.list_events(run_id, sequence)
                for event in events:
                    sequence = int(event["sequence"])
                    packet = json.dumps(event, separators=(",", ":"))
                    self.wfile.write(f"id: {sequence}\nevent: control_room\ndata: {packet}\n\n".encode("utf-8"))
                self.wfile.flush()
                run = self.app.store.get_run(run_id)
                if run["status"] in TERMINAL and not events:
                    break
                if not events:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                time.sleep(0.20)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _file(self, path: Path, content_type: str | None = None) -> None:
        data = path.read_bytes()
        self._headers(HTTPStatus.OK, content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream", len(data))
        self.wfile.write(data)

    def _static(self, request_path: str) -> None:
        if not self.app.frontend.is_dir():
            self._json({"error": "frontend is not built; run npm install and npm run build in frontend"}, HTTPStatus.NOT_FOUND)
            return
        relative = request_path.lstrip("/") or "index.html"
        candidate = (self.app.frontend / relative).resolve()
        try:
            candidate.relative_to(self.app.frontend.resolve())
        except ValueError:
            self._json({"error": "invalid static path"}, HTTPStatus.BAD_REQUEST)
            return
        if not candidate.is_file():
            candidate = self.app.frontend / "index.html"
        self._file(candidate)


def serve(host: str = "127.0.0.1", port: int = 8765, settings: Settings | None = None) -> None:
    app = ControlRoomApplication(settings or Settings.load(mode="mock"))
    server = ThreadingHTTPServer((host, port), Handler)
    server.app = app  # type: ignore[attr-defined]
    print(f"Control room available at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
