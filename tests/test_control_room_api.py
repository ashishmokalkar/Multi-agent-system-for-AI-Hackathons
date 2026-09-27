from __future__ import annotations

import dataclasses
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from audio_competition_agents.config import Settings
from audio_competition_agents.control_room.server import ControlRoomApplication, Handler


def request(url: str, value=None):
    body = json.dumps(value).encode() if value is not None else None
    call = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(call, timeout=10) as response:
        return response.status, response.headers.get_content_type(), response.read()


def test_control_room_http_health_fixture_and_error(tmp_path: Path):
    project = Path(__file__).resolve().parents[1]
    settings = dataclasses.replace(
        Settings.load(project / "configs/default.toml", mode="mock"),
        run_root=tmp_path / "runs",
    )
    app = ControlRoomApplication(settings)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.app = app  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, kind, body = request(base + "/api/health")
        assert status == 200 and kind == "application/json"
        assert json.loads(body)["modes"]["mock"].startswith("offline")
        status, kind, body = request(base + "/api/demo/audio.wav")
        assert status == 200 and kind == "audio/wav" and body[:4] == b"RIFF"
        try:
            request(base + "/api/runs", {"mode": "scripted"})
        except urllib.error.HTTPError as error:
            assert error.code == 400
            assert "mock or live" in error.read().decode()
        else:
            raise AssertionError("invalid mode was not rejected")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
