from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import threading
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..schemas import RunBudget, TrainingEngineeringOutput


class AuthorizationError(RuntimeError):
    pass


class ComputeLimitError(RuntimeError):
    pass


@dataclass(frozen=True)
class LaunchTrainingInput:
    config_id: str
    run_id: str
    device: str = "cuda"
    dry_run: bool = True
    estimated_gpu_hours: float = 0.0
    timeout_seconds: int = 1800
    budget: dict[str, Any] | None = None


@dataclass(frozen=True)
class RunInferenceInput:
    config_id: str
    run_id: str
    device: str = "cuda"
    execute: bool = False
    timeout_seconds: int = 1800


class ExecutionCatalog:
    def __init__(self, path: Path):
        with path.open("rb") as handle:
            self.jobs = tomllib.load(handle)["jobs"]

    def resolve(self, config_id: str) -> dict[str, Any]:
        try:
            return dict(self.jobs[config_id])
        except KeyError as error:
            raise ValueError(f"configuration is not allowlisted: {config_id}") from error


class GuardedExecutor:
    """Runs only catalogued Python entry points; shell input is never accepted."""

    def __init__(self, original_repo: Path | None, project_root: Path, run_root: Path, catalog: ExecutionCatalog):
        self.original_repo = original_repo.resolve() if original_repo else None
        self.project_root = project_root.resolve()
        self.run_root = run_root.resolve()
        self.catalog = catalog
        self.run_root.mkdir(parents=True, exist_ok=True)
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.RLock()

    def preview(self, config_id: str, device: str) -> tuple[list[str], dict[str, Any]]:
        job = self.catalog.resolve(config_id)
        if device not in job["allowed_devices"]:
            raise ComputeLimitError(f"device {device} is not allowed for {config_id}")
        if self.original_repo is None:
            script = Path("$AUDIO_AGENTS_ORIGINAL_REPO") / job["script"]
        else:
            script = (self.original_repo / job["script"]).resolve()
            try:
                script.relative_to(self.original_repo)
            except ValueError as error:
                raise ComputeLimitError("entry point escapes original repository") from error
            if not script.is_file():
                raise FileNotFoundError(script)
        command = [sys.executable, str(script), "--device", device, *job.get("fixed_args", [])]
        return command, job

    def launch_training(self, request: LaunchTrainingInput) -> TrainingEngineeringOutput:
        command, job = self.preview(request.config_id, request.device)
        budget = RunBudget(**(request.budget or {}))
        if request.timeout_seconds > min(int(job["max_wall_seconds"]), budget.max_wall_seconds_per_job):
            raise ComputeLimitError("requested timeout exceeds the authorized/catalogued limit")
        if request.estimated_gpu_hours > budget.max_gpu_hours:
            raise ComputeLimitError("estimated GPU hours exceed the authorized budget")
        if not request.dry_run:
            if not budget.training_authorized or budget.max_training_runs < 1:
                raise AuthorizationError("training requires an explicit authorized run budget")
            if self.original_repo is None:
                raise RuntimeError("AUDIO_AGENTS_ORIGINAL_REPO is required for execution")
        if request.dry_run:
            return TrainingEngineeringOutput(
                status="dry_run_validated",
                config_id=request.config_id,
                dry_run=True,
                command_preview=command,
                message="allowlisted configuration validated; no process launched",
            )
        return self._run(request.run_id, request.config_id, command, request.timeout_seconds)

    def run_inference(self, request: RunInferenceInput) -> TrainingEngineeringOutput:
        command, job = self.preview(request.config_id, request.device)
        if int(job["max_epochs"]) != 0:
            raise ComputeLimitError("run_inference accepts evaluation-only catalog entries")
        if request.timeout_seconds > int(job["max_wall_seconds"]):
            raise ComputeLimitError("requested timeout exceeds catalogued limit")
        if not request.execute:
            return TrainingEngineeringOutput(
                status="dry_run_validated",
                config_id=request.config_id,
                dry_run=True,
                command_preview=command,
                message="inference entry point validated; no process launched",
            )
        if self.original_repo is None:
            raise RuntimeError("AUDIO_AGENTS_ORIGINAL_REPO is required for execution")
        return self._run(request.run_id, request.config_id, command, request.timeout_seconds)

    def _run(self, run_id: str, config_id: str, command: list[str], timeout_seconds: int) -> TrainingEngineeringOutput:
        job_dir = (self.run_root / run_id).resolve()
        job_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.run_root / ".gpu-training.lock"
        started = time.monotonic()
        with lock_path.open("a+") as gpu_lock:
            try:
                fcntl.flock(gpu_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ComputeLimitError("another GPU job is already running") from error
            environment = os.environ.copy()
            source = str(self.project_root / "src")
            environment["PYTHONPATH"] = source + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
            process = subprocess.Popen(
                command,
                cwd=self.project_root,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            with self._lock:
                self._processes[run_id] = process
            try:
                output, _ = process.communicate(timeout=timeout_seconds)
                (job_dir / f"{config_id}.log").write_text(output, encoding="utf-8")
            except subprocess.TimeoutExpired as error:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise TimeoutError(f"{config_id} exceeded {timeout_seconds} seconds") from error
            finally:
                with self._lock:
                    self._processes.pop(run_id, None)
                fcntl.flock(gpu_lock.fileno(), fcntl.LOCK_UN)
        return TrainingEngineeringOutput(
            status="completed" if process.returncode == 0 else "failed",
            config_id=config_id,
            dry_run=False,
            command_preview=command,
            elapsed_seconds=time.monotonic() - started,
            return_code=process.returncode,
            message="process completed under the catalogued timeout and single-GPU lock",
        )

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            process = self._processes.get(run_id)
            if process is None or process.poll() is not None:
                return False
            process.terminate()
            return True
