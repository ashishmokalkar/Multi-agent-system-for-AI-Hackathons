from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path


ALLOWLIST = {
    "official_score": ("e1_beats.official_scorer", "official_metrics", None),
    "split_integrity": ("e1_beats.data", "assert_split_integrity", None),
    "synthetic_preflight": (
        "generator",
        "assert_generation_ready",
        "artifacts/vaani_synthetic_generator_v1/src",
    ),
    "synthetic_generate_one": (
        "generator",
        "SyntheticGenerator",
        "artifacts/vaani_synthetic_generator_v1/src",
    ),
}


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ALLOWLIST:
        raise SystemExit("unknown or missing allowlisted legacy tool")
    repo_text = os.getenv("AUDIO_AGENTS_LEGACY_REPO", "")
    if not repo_text:
        raise SystemExit("AUDIO_AGENTS_LEGACY_REPO is required")
    repo = Path(repo_text).resolve()
    module_name, function_name, extra_root = ALLOWLIST[sys.argv[1]]
    sys.path.insert(0, str(repo / extra_root) if extra_root else str(repo))
    payload = json.load(sys.stdin)
    function = getattr(importlib.import_module(module_name), function_name)
    if sys.argv[1] == "official_score":
        result = function(payload["ref_data"], payload["pred_data"])
    elif sys.argv[1] == "split_integrity":
        function(payload["records"], payload.get("eval_records", []))
        result = {"passed": True}
    elif sys.argv[1] == "synthetic_preflight":
        payload["exclusion_file"] = Path(payload["exclusion_file"])
        result = function(**payload)
    else:
        output_dir = Path(payload.pop("output_dir"))
        clip_index = int(payload.pop("clip_index"))
        seed = int(payload.pop("seed"))
        partition = str(payload.pop("partition"))
        generator = function(**payload)
        audio, row = generator.generate_one(clip_index, seed, partition)
        module = importlib.import_module("generator")
        result = module.write_generated_clip(audio, row, output_dir)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
