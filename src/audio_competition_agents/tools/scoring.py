from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import PathPolicy


@dataclass(frozen=True)
class ScoreFilesInput:
    reference_path: str
    prediction_path: str
    scorer: str = "toy"


def _load_intervals(path: Path) -> dict[str, list[tuple[float, float]]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, list[tuple[float, float]]] = {}
    for clip_id, events in raw.items():
        parsed = []
        for item in events:
            onset, offset = float(item[0]), float(item[1])
            if not math.isfinite(onset) or not math.isfinite(offset) or not 0 <= onset < offset:
                raise ValueError(f"invalid interval for {clip_id}: {item}")
            parsed.append((onset, offset))
        result[str(clip_id)] = parsed
    return result


def toy_metrics(
    references: dict[str, list[tuple[float, float]]],
    predictions: dict[str, list[tuple[float, float]]],
) -> dict[str, Any]:
    """Deterministic demo scorer; it is deliberately not labeled official."""
    tp = fp = fn = 0
    dice_values = []
    for clip_id, refs in references.items():
        preds = predictions.get(clip_id, [])
        candidates = []
        for ri, (ron, roff) in enumerate(refs):
            tolerance = max(0.05, 0.2 * (roff - ron))
            for pi, (pon, poff) in enumerate(preds):
                if abs(pon - ron) <= tolerance and abs(poff - roff) <= tolerance:
                    candidates.append((abs(pon - ron) + abs(poff - roff), ri, pi))
        used_r: set[int] = set()
        used_p: set[int] = set()
        for _, ri, pi in sorted(candidates):
            if ri not in used_r and pi not in used_p:
                used_r.add(ri)
                used_p.add(pi)
        tp += len(used_r)
        fp += len(preds) - len(used_p)
        fn += len(refs) - len(used_r)
        dice_values.append(_interval_dice(refs, preds))
    for clip_id, events in predictions.items():
        if clip_id not in references:
            fp += len(events)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    dice = sum(dice_values) / len(dice_values) if dice_values else 0.0
    return {
        "event_precision": precision,
        "event_recall": recall,
        "event_f1": f1,
        "segment_dice": dice,
        "combined": f1 + dice,
        "population": "bundled toy data",
        "scorer": "toy deterministic scorer; not the official evaluator",
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def _interval_dice(refs: list[tuple[float, float]], preds: list[tuple[float, float]]) -> float:
    if not refs and not preds:
        return 1.0
    boundaries = sorted({value for interval in refs + preds for value in interval})
    if len(boundaries) < 2:
        return 0.0
    ref_time = pred_time = overlap = 0.0
    for left, right in zip(boundaries, boundaries[1:]):
        midpoint = (left + right) / 2
        span = right - left
        in_ref = any(on <= midpoint < off for on, off in refs)
        in_pred = any(on <= midpoint < off for on, off in preds)
        ref_time += span * in_ref
        pred_time += span * in_pred
        overlap += span * in_ref * in_pred
    return 2 * overlap / (ref_time + pred_time) if ref_time + pred_time else 1.0


class ScoringTools:
    def __init__(self, paths: PathPolicy, legacy_adapter: Any | None = None):
        self.paths = paths
        self.legacy = legacy_adapter

    def score_files(self, request: ScoreFilesInput) -> dict[str, Any]:
        references = _load_intervals(self.paths.readable(request.reference_path))
        predictions = _load_intervals(self.paths.readable(request.prediction_path))
        if request.scorer == "toy":
            return toy_metrics(references, predictions)
        if request.scorer == "official":
            if self.legacy is None:
                raise RuntimeError("official scorer requires AUDIO_AGENTS_ORIGINAL_REPO")
            raw = self.legacy.call("official_score", {
                "ref_data": {key: [list(x) for x in value] for key, value in references.items()},
                "pred_data": {key: [list(x) for x in value] for key, value in predictions.items()},
            })
            event = raw["event"]
            return {
                "event_precision": event["precision"],
                "event_recall": event["recall"],
                "event_f1": event["f1"],
                "segment_dice": raw["segment_dice_macro"],
                "combined": raw["combined_sum"],
                "population": "configured references",
                "scorer": "existing project official_metrics adapter",
            }
        raise ValueError(f"unknown scorer: {request.scorer}")
