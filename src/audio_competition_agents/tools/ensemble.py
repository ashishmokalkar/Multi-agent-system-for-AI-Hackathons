from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import PathPolicy


@dataclass(frozen=True)
class ComparePredictionsInput:
    prediction_paths: list[str]


class EnsembleTools:
    def __init__(self, paths: PathPolicy):
        self.paths = paths

    def compare(self, request: ComparePredictionsInput) -> dict[str, Any]:
        if len(request.prediction_paths) < 2:
            raise ValueError("at least two saved prediction files are required")
        loaded = [self._load(self.paths.readable(path)) for path in request.prediction_paths]
        clip_sets = [set(value) for value in loaded]
        compatible = all(current == clip_sets[0] for current in clip_sets[1:])
        length_mismatches = 0
        if compatible:
            for clip_id in clip_sets[0]:
                lengths = {len(value[clip_id]) for value in loaded}
                length_mismatches += len(lengths) != 1
        return {
            "compatible": compatible and length_mismatches == 0,
            "candidate_names": [Path(path).stem for path in request.prediction_paths],
            "clip_counts": [len(value) for value in loaded],
            "frame_length_mismatch_clips": length_mismatches,
            "combinations_evaluated": 0,
            "finding": "compatibility only; no weights selected",
        }

    @staticmethod
    def _load(path: Path) -> dict[str, list[float]]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        result = {}
        for clip_id, values in raw.items():
            floats = [float(value) for value in values]
            if not all(math.isfinite(value) for value in floats):
                raise ValueError(f"non-finite probability in {clip_id}")
            result[str(clip_id)] = floats
        return result
