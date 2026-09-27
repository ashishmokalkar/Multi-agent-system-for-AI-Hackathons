from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


class LegacyAdapter:
    """Invoke allowlisted original-project functions without changing cwd."""

    def __init__(self, original_repo: Path, project_root: Path, timeout_seconds: int = 300):
        self.original_repo = original_repo.resolve()
        self.project_root = project_root.resolve()
        self.timeout_seconds = timeout_seconds
        if not self.original_repo.is_dir():
            raise FileNotFoundError(self.original_repo)

    def call(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        environment = os.environ.copy()
        source_root = self.project_root / "src"
        existing = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = str(source_root) + (os.pathsep + existing if existing else "")
        environment["AUDIO_AGENTS_LEGACY_REPO"] = str(self.original_repo)
        completed = subprocess.run(
            [sys.executable, "-m", "audio_competition_agents.tools.legacy_worker", tool_name],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            cwd=self.project_root,
            env=environment,
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"legacy tool {tool_name} failed: {detail}")
        return json.loads(completed.stdout)
