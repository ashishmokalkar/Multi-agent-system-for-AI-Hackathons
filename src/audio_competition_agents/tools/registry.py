from __future__ import annotations

from pathlib import Path

from ..config import Settings
from .base import ToolDefinition, ToolRegistry
from .data import DataTools, InspectManifestInput, ValidateSplitInput
from .ensemble import ComparePredictionsInput, EnsembleTools
from .execution import ExecutionCatalog, GuardedExecutor, LaunchTrainingInput, RunInferenceInput
from .fixture import (
    CorrectFixtureAnnotationInput,
    FixtureTools,
    PrepareFixtureInput,
    ValidateFixtureAnnotationInput,
)
from .generation import GenerateSyntheticClipInput, GenerationTools
from .legacy import LegacyAdapter
from .paths import PathPolicy
from .scoring import ScoreFilesInput, ScoringTools
from .synthetic import ValidateSyntheticPlanInput, validate_synthetic_plan


def build_tool_registry(settings: Settings) -> tuple[ToolRegistry, GuardedExecutor]:
    settings.run_root.mkdir(parents=True, exist_ok=True)
    read_roots = [settings.project_root, settings.run_root]
    if settings.original_repo:
        read_roots.append(settings.original_repo)
    paths = PathPolicy(tuple(read_roots), settings.run_root)
    legacy = LegacyAdapter(settings.original_repo, settings.project_root) if settings.original_repo else None
    data = DataTools(paths)
    scoring = ScoringTools(paths, legacy)
    ensemble = EnsembleTools(paths)
    generation = GenerationTools(paths, legacy)
    fixture = FixtureTools(paths)
    catalog = ExecutionCatalog(settings.project_root / "configs/training_allowlist.toml")
    executor = GuardedExecutor(settings.original_repo, settings.project_root, settings.run_root, catalog)

    registry = ToolRegistry()
    registry.register(ToolDefinition(
        "inspect_manifest",
        "Inspect a JSONL audio manifest and report counts, hours, splits, categories, and source groups.",
        InspectManifestInput,
        data.inspect_manifest,
        source_attribution="generic adapter; field conventions follow the existing Vaani manifests",
    ))
    registry.register(ToolDefinition(
        "validate_source_split",
        "Fail closed on source-group, duplicate-hash, clip-ID, or audio-hash leakage.",
        ValidateSplitInput,
        data.validate_split,
        source_attribution="mirrors e1_beats.data.assert_split_integrity",
    ))
    registry.register(ToolDefinition(
        "validate_synthetic_plan",
        "Reject unsafe source isolation or whole-crop event annotation behavior.",
        ValidateSyntheticPlanInput,
        validate_synthetic_plan,
        source_attribution="guards the sample-accurate v1 generator contract",
    ))
    registry.register(ToolDefinition(
        "generate_synthetic_clip",
        "Validate a generation plan and optionally invoke the existing SyntheticGenerator for one clip.",
        GenerateSyntheticClipInput,
        generation.generate_one,
        mutating=True,
        source_attribution="artifacts/vaani_synthetic_generator_v1/src/generator.py",
    ))
    registry.register(ToolDefinition(
        "prepare_demo_fixture",
        "Generate the redistributable demo WAV, manifest, known reference, and deliberately defective annotation.",
        PrepareFixtureInput,
        fixture.prepare,
        mutating=True,
        source_attribution="new deterministic control-room fixture generator",
    ))
    registry.register(ToolDefinition(
        "validate_fixture_annotation",
        "Compare a candidate fixture annotation against its explicit known-boundary reference.",
        ValidateFixtureAnnotationInput,
        fixture.validate,
        source_attribution="new deterministic known-boundary fixture check",
    ))
    registry.register(ToolDefinition(
        "correct_fixture_annotation",
        "Apply the bounded known-reference correction after evaluator rejection.",
        CorrectFixtureAnnotationInput,
        fixture.correct,
        mutating=True,
        source_attribution="new bounded fixture-only correction adapter",
    ))
    registry.register(ToolDefinition(
        "score_predictions",
        "Score saved interval predictions with the toy scorer or configured existing official scorer.",
        ScoreFilesInput,
        scoring.score_files,
        source_attribution="e1_beats.official_scorer.official_metrics for scorer=official",
    ))
    registry.register(ToolDefinition(
        "compare_saved_predictions",
        "Check saved frame-prediction candidates for compatible clip and frame identities.",
        ComparePredictionsInput,
        ensemble.compare,
        source_attribution="compatibility contract from beats_a1_short_long_ensemble_v1",
    ))
    registry.register(ToolDefinition(
        "launch_training",
        "Dry-run or launch one exact allowlisted training entry point under a budget and GPU lock.",
        LaunchTrainingInput,
        executor.launch_training,
        mutating=True,
        source_attribution="validated existing training entry points",
    ))
    registry.register(ToolDefinition(
        "run_inference",
        "Dry-run or execute an evaluation-only allowlisted inference entry point.",
        RunInferenceInput,
        executor.run_inference,
        mutating=True,
        source_attribution="validated existing evaluation entry points",
    ))
    return registry, executor
