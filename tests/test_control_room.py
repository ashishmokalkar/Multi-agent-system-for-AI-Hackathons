from __future__ import annotations

import asyncio
import dataclasses
import json
import threading
import time
import wave
from pathlib import Path

import pytest

from audio_competition_agents.config import Settings
from audio_competition_agents.control_room.scenario import ControlRoomManager, ControlRoomScenario
from audio_competition_agents.providers.mock import MockProvider
from audio_competition_agents.schemas import AgentRole, RunBudget
from audio_competition_agents.store import RunStore
from audio_competition_agents.tools import build_tool_registry


def control_room(tmp_path: Path):
    project = Path(__file__).resolve().parents[1]
    settings = dataclasses.replace(
        Settings.load(project / "configs/default.toml", mode="mock"),
        run_root=tmp_path / "runs",
    )
    tools, _ = build_tool_registry(settings)
    store = RunStore(settings.run_root / "runs.sqlite3")
    return settings, tools, store, ControlRoomManager(settings, tools, store)


def wait_for_run(store: RunStore, run_id: str, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = store.get_run(run_id)
        if run["status"] in {"complete", "failed", "cancelled"}:
            return run
        time.sleep(0.02)
    raise TimeoutError(run_id)


def test_control_room_handoffs_reject_revise_and_score(tmp_path: Path):
    _, _, store, manager = control_room(tmp_path)
    run_id = manager.start("mock")
    run = wait_for_run(store, run_id)
    assert run["status"] == "complete", run["state"]
    events = run["events"]
    event_types = [event["event_type"] for event in events]
    assert event_types.index("review_rejected") < event_types.index("revision_requested")
    assert event_types.index("revision_requested") < event_types.index("review_accepted")
    assert event_types.index("review_accepted") < event_types.index("metrics_recorded")
    agents = {event["agent"] for event in events if event["agent"]}
    assert {
        "coordinator",
        "data_investigator",
        "synthetic_data_engineer",
        "research_modeling_agent",
        "independent_evaluator",
    } <= agents
    assert "ensemble_analyst" not in agents
    rejection = next(event for event in events if event["event_type"] == "review_rejected")
    assert {change["field"] for change in rejection["payload"]["changes"]} == {"onset", "offset"}
    measured = next(event for event in events if event["event_type"] == "metrics_recorded")["payload"]
    assert "not competition metrics" in measured["label"]
    assert measured["candidate"]["combined"] > measured["baseline"]["combined"]
    for event in events:
        progress = event["payload"].get("progress")
        assert progress is None or progress == "indeterminate"


def test_fixture_audio_and_annotation_are_sample_aligned(tmp_path: Path):
    _, tools, _, _ = control_room(tmp_path)
    prepared = tools.invoke(
        AgentRole.SYNTHETIC_ENGINEER,
        ("prepare_demo_fixture",),
        "prepare_demo_fixture",
        {"run_id": "alignment"},
    )
    with wave.open(prepared["audio_path"], "rb") as handle:
        assert handle.getframerate() == 16_000
        assert handle.getnframes() == 64_000
        assert handle.getnchannels() == 1
    check = tools.invoke(
        AgentRole.EVALUATOR,
        ("validate_fixture_annotation",),
        "validate_fixture_annotation",
        {
            "reference_path": prepared["reference_path"],
            "candidate_path": prepared["candidate_path"],
            "tolerance_seconds": 0.005,
        },
    )
    assert not check["passed"]
    tools.invoke(
        AgentRole.SYNTHETIC_ENGINEER,
        ("correct_fixture_annotation",),
        "correct_fixture_annotation",
        {"run_id": "alignment"},
    )
    check = tools.invoke(
        AgentRole.EVALUATOR,
        ("validate_fixture_annotation",),
        "validate_fixture_annotation",
        {
            "reference_path": prepared["reference_path"],
            "candidate_path": prepared["candidate_path"],
            "tolerance_seconds": 0.005,
        },
    )
    assert check["passed"]


def test_pre_cancelled_scenario_stops_cleanly(tmp_path: Path):
    settings, tools, store, _ = control_room(tmp_path)
    budget = RunBudget(max_revision_attempts=1)
    run_id = store.create_run({"text": "cancel fixture", "task_kind": "synthetic"}, budget.to_dict(), "mock")
    cancel = threading.Event()
    cancel.set()
    scenario = ControlRoomScenario(settings, MockProvider(tools), tools, store, run_id, cancel)
    asyncio.run(scenario.run())
    run = store.get_run(run_id)
    assert run["status"] == "cancelled"
    assert run["events"][-1]["event_type"] == "run_cancelled"


def test_unknown_execution_mode_is_an_error(tmp_path: Path):
    _, _, _, manager = control_room(tmp_path)
    with pytest.raises(ValueError, match="mock or live"):
        manager.start("scripted")
