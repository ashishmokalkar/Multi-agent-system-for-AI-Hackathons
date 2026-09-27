from __future__ import annotations

import json
from pathlib import Path

import pytest

from audio_competition_agents.schemas import AgentRole, RunBudget
from audio_competition_agents.tools.base import ToolPermissionError
from audio_competition_agents.tools.data import validate_source_isolation
from audio_competition_agents.tools.execution import (
    AuthorizationError,
    ExecutionCatalog,
    GuardedExecutor,
    LaunchTrainingInput,
)
from audio_competition_agents.tools.scoring import toy_metrics
from audio_competition_agents.tools.synthetic import ValidateSyntheticPlanInput, validate_synthetic_plan


def test_invalid_source_group_split_fails_closed():
    rows = [
        {"clip_id": "a", "source_group": "same", "audio_sha256": "h1", "split": "train"},
        {"clip_id": "b", "source_group": "same", "audio_sha256": "h2", "split": "validation"},
    ]
    result = validate_source_isolation(rows)
    assert not result["passed"]
    assert result["source_group_intersection_count"] == 1


def test_missing_source_identity_fails_closed():
    result = validate_source_isolation([
        {"clip_id": "a", "split": "train"},
        {"clip_id": "b", "source_group": "g2", "audio_sha256": "h2", "split": "validation"},
    ])
    assert not result["passed"]
    assert result["missing_identity_row_count"] == 1


def test_evaluation_source_group_overlap_fails_closed():
    records = [{"clip_id": "a", "source_group": "shared", "audio_sha256": "h1", "split": "train"}]
    evaluation = [{"clip_id": "eval-a", "source_group": "shared", "audio_sha256": "eh1"}]
    result = validate_source_isolation(records, evaluation)
    assert not result["passed"]
    assert result["eval_source_group_leak_count"] == 1


def test_known_defective_synthetic_policy_is_blocked():
    result = validate_synthetic_plan(ValidateSyntheticPlanInput({
        "event_boundary_policy": "center_crop_whole_annotation",
        "source_partition_disjoint": True,
        "eval_exclusion_checked": True,
        "license_checked": True,
        "required_transform_metadata": [],
    }))
    assert not result["passed"]
    assert any("whole-crop" in error for error in result["errors"])


def test_toy_scorer_is_explicitly_not_official():
    result = toy_metrics({"x": [(0.1, 0.2)]}, {"x": [(0.1, 0.2)]})
    assert result["combined"] == pytest.approx(2.0)
    assert "not the official" in result["scorer"]


def test_unauthorized_training_is_blocked(project_root: Path, tmp_path: Path):
    catalog = ExecutionCatalog(project_root / "configs/training_allowlist.toml")
    executor = GuardedExecutor(None, project_root, tmp_path, catalog)
    with pytest.raises(AuthorizationError):
        executor.launch_training(LaunchTrainingInput(
            config_id="beats_a1_synthetic_40h_local",
            run_id="test",
            dry_run=False,
            estimated_gpu_hours=0.0,
            timeout_seconds=10,
            budget=RunBudget(
                training_authorized=False,
                max_gpu_hours=0,
                max_training_runs=0,
                max_wall_seconds_per_job=10,
            ).to_dict(),
        ))


def test_training_dry_run_never_launches(project_root: Path, tmp_path: Path):
    catalog = ExecutionCatalog(project_root / "configs/training_allowlist.toml")
    executor = GuardedExecutor(None, project_root, tmp_path, catalog)
    result = executor.launch_training(LaunchTrainingInput(
        config_id="beats_a1_synthetic_40h_local",
        run_id="test",
        dry_run=True,
        timeout_seconds=10,
        budget=RunBudget(max_wall_seconds_per_job=10).to_dict(),
    ))
    assert result.status == "dry_run_validated"
    assert not (tmp_path / "test").exists()


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]
