from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import PathPolicy


FIXTURE_CLIP_ID = "generated_boundary_fixture_01"
REFERENCE_ONSET = 0.750
REFERENCE_OFFSET = 1.250
ORIGINAL_ONSET = 0.700
ORIGINAL_OFFSET = 1.550
SAMPLE_RATE = 16_000
DURATION_SECONDS = 4.0
_RUN_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class PrepareFixtureInput:
    run_id: str


@dataclass(frozen=True)
class ValidateFixtureAnnotationInput:
    reference_path: str
    candidate_path: str
    tolerance_seconds: float = 0.005


@dataclass(frozen=True)
class CorrectFixtureAnnotationInput:
    run_id: str


def _json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _event(onset: float, offset: float, source: str) -> dict[str, Any]:
    return {
        "event_id": "fixture_event_01",
        "category": "generated_test_event",
        "subcategory": "linear_chirp",
        "onset": onset,
        "offset": offset,
        "source": source,
    }


def _write_fixture_audio(path: Path, *, with_event: bool) -> None:
    frames = bytearray()
    total = int(DURATION_SECONDS * SAMPLE_RATE)
    for index in range(total):
        time_s = index / SAMPLE_RATE
        background = 0.045 * math.sin(2 * math.pi * 115 * time_s)
        background += 0.025 * math.sin(2 * math.pi * 230 * time_s)
        event = 0.0
        if with_event and REFERENCE_ONSET <= time_s < REFERENCE_OFFSET:
            local = time_s - REFERENCE_ONSET
            duration = REFERENCE_OFFSET - REFERENCE_ONSET
            envelope = min(1.0, local / 0.025, (duration - local) / 0.025)
            frequency = 760.0 + 720.0 * local / duration
            event = 0.46 * max(0.0, envelope) * math.sin(2 * math.pi * frequency * time_s)
        value = max(-1.0, min(1.0, background + event))
        frames.extend(struct.pack("<h", int(round(value * 32767))))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(frames)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FixtureTools:
    """Deterministic, redistributable fixture generation and boundary checks."""

    def __init__(self, paths: PathPolicy):
        self.paths = paths

    def _directory(self, run_id: str) -> Path:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("run_id contains unsupported characters")
        directory = self.paths.writable(self.paths.write_root / run_id / "control_room_fixture")
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def prepare(self, request: PrepareFixtureInput) -> dict[str, Any]:
        directory = self._directory(request.run_id)
        audio = directory / "fixture.wav"
        context = directory / "context.wav"
        _write_fixture_audio(audio, with_event=True)
        _write_fixture_audio(context, with_event=False)

        reference = {"clip_id": FIXTURE_CLIP_ID, "events": [_event(REFERENCE_ONSET, REFERENCE_OFFSET, "known_fixture_reference")]}
        original = {"clip_id": FIXTURE_CLIP_ID, "events": [_event(ORIGINAL_ONSET, ORIGINAL_OFFSET, "deliberately_defective_test_annotation")]}
        proposed = {"clip_id": FIXTURE_CLIP_ID, "events": [_event(ORIGINAL_ONSET, ORIGINAL_OFFSET, "initial_proposal")], "revision": 0}
        _json(directory / "reference_annotations.json", reference)
        _json(directory / "original_annotations.json", original)
        _json(directory / "proposed_annotations.json", proposed)
        _json(directory / "references.json", {FIXTURE_CLIP_ID: [[REFERENCE_ONSET, REFERENCE_OFFSET]]})
        _json(directory / "baseline_predictions.json", {FIXTURE_CLIP_ID: [[ORIGINAL_ONSET, ORIGINAL_OFFSET]]})

        rows = [
            {
                "clip_id": FIXTURE_CLIP_ID,
                "source_group": "generated_fixture/source_a",
                "audio_sha256": _sha256(audio),
                "split": "train",
                "duration": DURATION_SECONDS,
                "events": [reference["events"][0]],
            },
            {
                "clip_id": "generated_boundary_fixture_context_02",
                "source_group": "generated_fixture/source_b",
                "audio_sha256": _sha256(context),
                "split": "validation",
                "duration": DURATION_SECONDS,
                "events": [],
            },
        ]
        manifest = directory / "manifest.jsonl"
        manifest.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
        return {
            "artifact_id": "fixture_audio",
            "audio_path": str(audio),
            "manifest_path": str(manifest),
            "reference_path": str(directory / "reference_annotations.json"),
            "original_path": str(directory / "original_annotations.json"),
            "candidate_path": str(directory / "proposed_annotations.json"),
            "scoring_reference_path": str(directory / "references.json"),
            "baseline_prediction_path": str(directory / "baseline_predictions.json"),
            "duration_seconds": DURATION_SECONDS,
            "sample_rate": SAMPLE_RATE,
            "caption": "A generated chirp is audible from 0.750 s to 1.250 s over a quiet tonal background.",
            "known_reference": [REFERENCE_ONSET, REFERENCE_OFFSET],
            "original_annotation": [ORIGINAL_ONSET, ORIGINAL_OFFSET],
        }

    def validate(self, request: ValidateFixtureAnnotationInput) -> dict[str, Any]:
        reference_path = self.paths.readable(request.reference_path)
        candidate_path = self.paths.readable(request.candidate_path)
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        errors: list[str] = []
        changes: list[dict[str, Any]] = []
        if reference.get("clip_id") != candidate.get("clip_id"):
            errors.append("clip identity does not match the known fixture")
        ref_events = reference.get("events", [])
        candidate_events = candidate.get("events", [])
        if len(ref_events) != len(candidate_events):
            errors.append(f"event count differs: expected {len(ref_events)}, observed {len(candidate_events)}")
        for index, (expected, observed) in enumerate(zip(ref_events, candidate_events)):
            for field in ("onset", "offset"):
                expected_value = float(expected[field])
                observed_value = float(observed[field])
                if not math.isfinite(observed_value):
                    errors.append(f"event {index + 1} {field} is not finite")
                    continue
                difference = observed_value - expected_value
                if abs(difference) > request.tolerance_seconds:
                    errors.append(
                        f"event {index + 1} {field} differs by {difference:+.3f} s "
                        f"(allowed ±{request.tolerance_seconds:.3f} s)"
                    )
                    changes.append({
                        "event_id": expected.get("event_id", f"event_{index + 1}"),
                        "field": field,
                        "observed": observed_value,
                        "expected": expected_value,
                        "delta_seconds": difference,
                    })
            if observed.get("category") != expected.get("category"):
                errors.append(f"event {index + 1} category does not match")
        return {
            "passed": not errors,
            "check": "deterministic known-boundary comparison; not semantic listening verification",
            "tolerance_seconds": request.tolerance_seconds,
            "errors": errors,
            "changes": changes,
            "reference_event_count": len(ref_events),
            "candidate_event_count": len(candidate_events),
        }

    def correct(self, request: CorrectFixtureAnnotationInput) -> dict[str, Any]:
        directory = self._directory(request.run_id)
        reference_path = self.paths.readable(directory / "reference_annotations.json")
        candidate_path = self.paths.writable(directory / "proposed_annotations.json")
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        corrected = {
            "clip_id": reference["clip_id"],
            "events": [{**reference["events"][0], "source": "fixture_reference_guided_revision"}],
            "revision": 1,
            "revision_reason": "bounded correction after deterministic evaluator rejection",
        }
        _json(candidate_path, corrected)
        scoring_path = directory / "candidate_predictions.json"
        event = corrected["events"][0]
        _json(scoring_path, {corrected["clip_id"]: [[event["onset"], event["offset"]]]})
        return {
            "artifact_id": "corrected_annotation",
            "candidate_path": str(candidate_path),
            "prediction_path": str(scoring_path),
            "revision": 1,
            "proposed_correction": [event["onset"], event["offset"]],
            "changed_fields": ["onset", "offset"],
        }
