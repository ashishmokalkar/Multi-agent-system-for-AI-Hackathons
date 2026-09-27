from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .legacy import LegacyAdapter
from .paths import PathPolicy
from .synthetic import ValidateSyntheticPlanInput, validate_synthetic_plan


@dataclass(frozen=True)
class GenerateSyntheticClipInput:
    config_path: str
    priors_path: str
    eval_stats_path: str
    beds_manifest_path: str
    stems_manifest_path: str
    output_dir: str
    config_sha256: str
    exclusion_sha256: str
    clip_index: int
    seed: int
    partition: str
    plan: dict[str, Any]
    dry_run: bool = True


class GenerationTools:
    def __init__(self, paths: PathPolicy, legacy: LegacyAdapter | None):
        self.paths = paths
        self.legacy = legacy

    def generate_one(self, request: GenerateSyntheticClipInput) -> dict[str, Any]:
        policy = validate_synthetic_plan(ValidateSyntheticPlanInput(request.plan))
        if not policy["passed"]:
            return {"status": "blocked", "policy": policy}
        inputs = {
            "config": self._json(request.config_path),
            "gold_priors": self._json(request.priors_path),
            "eval_stats": self._json(request.eval_stats_path),
            "beds": self._jsonl(request.beds_manifest_path),
            "stems": self._jsonl(request.stems_manifest_path),
            "output_dir": str(self.paths.writable(Path(request.output_dir) / "placeholder").parent),
            "config_sha256": request.config_sha256,
            "exclusion_sha256": request.exclusion_sha256,
            "clip_index": request.clip_index,
            "seed": request.seed,
            "partition": request.partition,
        }
        if request.dry_run:
            return {
                "status": "dry_run_validated",
                "policy": policy,
                "bed_count": len(inputs["beds"]),
                "stem_count": len(inputs["stems"]),
                "output_dir": inputs["output_dir"],
            }
        if self.legacy is None:
            raise RuntimeError("generation requires AUDIO_AGENTS_ORIGINAL_REPO")
        return {"status": "generated", "policy": policy, "record": self.legacy.call("synthetic_generate_one", inputs)}

    def _json(self, value: str) -> Any:
        return json.loads(self.paths.readable(value).read_text(encoding="utf-8"))

    def _jsonl(self, value: str) -> list[dict[str, Any]]:
        return [
            json.loads(line)
            for line in self.paths.readable(value).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
