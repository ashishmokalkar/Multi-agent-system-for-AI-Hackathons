from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .paths import PathPolicy


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise ValueError(f"{path}:{line_number}: {error}") from error
    return rows


@dataclass(frozen=True)
class InspectManifestInput:
    manifest_path: str


@dataclass(frozen=True)
class ValidateSplitInput:
    manifest_path: str
    eval_manifest_path: str | None = None


class DataTools:
    def __init__(self, paths: PathPolicy):
        self.paths = paths

    def inspect_manifest(self, request: InspectManifestInput) -> dict[str, Any]:
        path = self.paths.readable(request.manifest_path)
        rows = read_jsonl(path)
        split_counts = Counter(str(row.get("split", "unspecified")) for row in rows)
        categories = Counter()
        duration_seconds = 0.0
        for row in rows:
            duration_seconds += float(row.get("duration", row.get("duration_seconds", 0.0)) or 0.0)
            for event in row.get("events", []):
                category = event.get("category", event.get("label"))
                if category:
                    categories[str(category)] += 1
        return {
            "manifest_path": str(path),
            "item_count": len(rows),
            "duration_hours": duration_seconds / 3600,
            "split_counts": dict(sorted(split_counts.items())),
            "category_counts": dict(sorted(categories.items())),
            "unique_clip_ids": len({str(row.get("clip_id", row.get("id", ""))) for row in rows}),
            "unique_source_groups": len({str(row.get("source_group", "")) for row in rows if row.get("source_group")}),
        }

    def validate_split(self, request: ValidateSplitInput) -> dict[str, Any]:
        path = self.paths.readable(request.manifest_path)
        rows = read_jsonl(path)
        eval_rows = read_jsonl(self.paths.readable(request.eval_manifest_path)) if request.eval_manifest_path else []
        return validate_source_isolation(rows, eval_rows)


def validate_source_isolation(
    rows: Iterable[dict[str, Any]],
    eval_rows: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    records = list(rows)
    evaluation = list(eval_rows)
    required = ("clip_id", "source_group", "audio_sha256", "split")
    missing_identity_fields = [
        {"row_index": index, "fields": [field for field in required if not row.get(field)]}
        for index, row in enumerate(records)
        if any(not row.get(field) for field in required)
    ]
    eval_required = ("clip_id", "source_group", "audio_sha256")
    missing_eval_identity_fields = [
        {"row_index": index, "fields": [field for field in eval_required if not row.get(field)]}
        for index, row in enumerate(evaluation)
        if any(not row.get(field) for field in eval_required)
    ]
    group_splits: dict[str, set[str]] = defaultdict(set)
    hash_splits: dict[str, set[str]] = defaultdict(set)
    for row in records:
        split = str(row.get("split", "unspecified"))
        group = row.get("source_group")
        digest = row.get("audio_sha256")
        if group:
            group_splits[str(group)].add(split)
        if digest:
            hash_splits[str(digest)].add(split)
    crossing_groups = {key: sorted(value) for key, value in group_splits.items() if len(value) > 1}
    crossing_hashes = {key: sorted(value) for key, value in hash_splits.items() if len(value) > 1}
    clip_counts = Counter(str(row.get("clip_id")) for row in records if row.get("clip_id"))
    duplicate_clip_ids = sorted(clip_id for clip_id, count in clip_counts.items() if count > 1)
    train_rows = [row for row in records if row.get("split") == "train"]
    train_ids = {str(row.get("clip_id")) for row in train_rows}
    train_hashes = {str(row.get("audio_sha256")) for row in train_rows if row.get("audio_sha256")}
    train_groups = {str(row.get("source_group")) for row in train_rows if row.get("source_group")}
    eval_ids = {str(row.get("clip_id")) for row in evaluation}
    eval_hashes = {str(row.get("audio_sha256")) for row in evaluation if row.get("audio_sha256")}
    eval_groups = {str(row.get("source_group")) for row in evaluation if row.get("source_group")}
    leaked_ids = sorted(train_ids & eval_ids)
    leaked_hashes = sorted(train_hashes & eval_hashes)
    leaked_groups = sorted(train_groups & eval_groups)
    passed = not any((
        missing_identity_fields,
        missing_eval_identity_fields,
        duplicate_clip_ids,
        crossing_groups,
        crossing_hashes,
        leaked_ids,
        leaked_hashes,
        leaked_groups,
    ))
    return {
        "passed": passed,
        "item_count": len(records),
        "missing_identity_row_count": len(missing_identity_fields),
        "missing_eval_identity_row_count": len(missing_eval_identity_fields),
        "duplicate_clip_id_count": len(duplicate_clip_ids),
        "source_group_intersection_count": len(crossing_groups),
        "duplicate_hash_intersection_count": len(crossing_hashes),
        "eval_clip_leak_count": len(leaked_ids),
        "eval_hash_leak_count": len(leaked_hashes),
        "eval_source_group_leak_count": len(leaked_groups),
        "representative_missing_identity_rows": missing_identity_fields[:5],
        "representative_missing_eval_identity_rows": missing_eval_identity_fields[:5],
        "representative_duplicate_clip_ids": duplicate_clip_ids[:5],
        "representative_crossing_groups": list(crossing_groups.items())[:5],
        "representative_crossing_hashes": list(crossing_hashes.items())[:5],
        "representative_eval_clip_leaks": leaked_ids[:5],
        "representative_eval_hash_leaks": leaked_hashes[:5],
        "representative_eval_source_group_leaks": leaked_groups[:5],
    }
