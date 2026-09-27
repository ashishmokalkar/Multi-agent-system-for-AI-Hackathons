from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path

from audio_competition_agents.config import Settings
from audio_competition_agents.providers.mock import MockProvider
from audio_competition_agents.schemas import RunBudget, UserObjective
from audio_competition_agents.store import RunStore
from audio_competition_agents.tools import build_tool_registry
from audio_competition_agents.workflow import CompetitionWorkflow


def runtime(tmp_path: Path):
    project = Path(__file__).resolve().parents[1]
    settings = dataclasses.replace(
        Settings.load(project / "configs/default.toml", mode="mock"),
        run_root=tmp_path / "runs",
    )
    tools, _ = build_tool_registry(settings)
    store = RunStore(settings.run_root / "runs.sqlite3")
    workflow = CompetitionWorkflow(settings, MockProvider(tools), tools, store)
    return project, workflow, store


def objective(project: Path, *, manifest: str = "manifest.jsonl", train: bool = False, revise: bool = True):
    toy = project / "examples/toy_data"
    return UserObjective(
        text="Bounded toy experiment",
        execute_training=train,
        manifest_path=str(toy / manifest),
        reference_path=str(toy / "references.json"),
        prediction_path=str(toy / "predictions.json"),
        metadata={"scorer": "toy", "force_revision": revise, "estimated_gpu_hours": 1.0 if train else 0.0},
    )


def test_complete_mock_workflow_has_revision_handoffs_and_metrics(tmp_path: Path):
    project, workflow, store = runtime(tmp_path)
    result = asyncio.run(workflow.run(objective(project), RunBudget(max_revision_attempts=2)))
    assert result.status == "complete"
    assert result.revision_attempts == 1
    assert result.metrics is not None and result.metrics.combined > 1.9
    persisted = store.get_run(result.run_id)
    senders = {message["sender"] for message in persisted["messages"]}
    assert {"coordinator", "data_investigator", "research_modeling_agent", "independent_evaluator"} <= senders
    assert len(persisted["messages"]) >= 12
    resumed = asyncio.run(workflow.run(objective(project), run_id=result.run_id))
    assert resumed.run_id == result.run_id
    assert resumed.status == "complete"


def test_invalid_split_is_blocked_before_proposal(tmp_path: Path):
    project, workflow, store = runtime(tmp_path)
    result = asyncio.run(workflow.run(objective(project, manifest="invalid_manifest.jsonl", revise=False)))
    assert result.status == "blocked"
    persisted = store.get_run(result.run_id)
    assert "proposal" not in persisted["state"]


def test_unauthorized_training_request_is_rejected(tmp_path: Path):
    project, workflow, _ = runtime(tmp_path)
    result = asyncio.run(workflow.run(
        objective(project, train=True, revise=False),
        RunBudget(training_authorized=False, max_gpu_hours=0, max_training_runs=0),
    ))
    assert result.status == "blocked"
    assert result.review is not None
    assert not result.review.checks["budget_authorized"]
