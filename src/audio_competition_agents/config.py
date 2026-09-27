from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    project_root: Path
    config_path: Path
    mode: str
    model: str
    api_key_env: str
    original_repo: Path | None
    run_root: Path
    max_revision_attempts: int
    default_timeout_seconds: int
    max_parallel_specialists: int
    gpu_slots: int
    default_dry_run: bool
    allow_submission: bool
    allow_publish: bool
    allow_git_push: bool

    @classmethod
    def load(cls, config_path: str | Path | None = None, *, mode: str | None = None) -> "Settings":
        requested = config_path or os.getenv("AUDIO_AGENTS_CONFIG") or PROJECT_ROOT / "configs/default.toml"
        path = Path(requested).expanduser().resolve()
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        runtime = raw["runtime"]
        provider = raw["provider"]
        paths = raw["paths"]
        safety = raw["safety"]
        original_text = os.getenv(paths["original_repo_env"], "").strip()
        original_repo = Path(original_text).expanduser().resolve() if original_text else None
        run_text = os.getenv(paths["run_root_env"], paths["default_run_root"])
        run_root = Path(run_text).expanduser()
        if not run_root.is_absolute():
            run_root = (PROJECT_ROOT / run_root).resolve()
        model = os.getenv(provider["model_env"], provider["default_model"])
        return cls(
            project_root=PROJECT_ROOT,
            config_path=path,
            mode=mode or runtime["mode"],
            model=model,
            api_key_env=provider["api_key_env"],
            original_repo=original_repo,
            run_root=run_root,
            max_revision_attempts=int(runtime["max_revision_attempts"]),
            default_timeout_seconds=int(runtime["default_timeout_seconds"]),
            max_parallel_specialists=int(runtime["max_parallel_specialists"]),
            gpu_slots=int(runtime["gpu_slots"]),
            default_dry_run=bool(safety["default_dry_run"]),
            allow_submission=bool(safety["allow_submission"]),
            allow_publish=bool(safety["allow_publish"]),
            allow_git_push=bool(safety["allow_git_push"]),
        )
