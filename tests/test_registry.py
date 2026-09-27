from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from audio_competition_agents.config import Settings
from audio_competition_agents.schemas import AgentRole
from audio_competition_agents.tools import build_tool_registry
from audio_competition_agents.tools.base import ToolPermissionError


def settings_for(project_root: Path, run_root: Path) -> Settings:
    return dataclasses.replace(Settings.load(project_root / "configs/default.toml"), run_root=run_root)


def test_tool_access_is_role_restricted(tmp_path: Path):
    project = Path(__file__).resolve().parents[1]
    registry, _ = build_tool_registry(settings_for(project, tmp_path))
    with pytest.raises(ToolPermissionError):
        registry.invoke(
            AgentRole.RESEARCH_MODELER,
            ("inspect_manifest",),
            "launch_training",
            {},
        )


def test_manifest_adapter_runs_from_unrelated_working_directory(tmp_path: Path, monkeypatch):
    project = Path(__file__).resolve().parents[1]
    registry, _ = build_tool_registry(settings_for(project, tmp_path / "runs"))
    monkeypatch.chdir(tmp_path)
    result = registry.invoke(
        AgentRole.DATA_INVESTIGATOR,
        ("inspect_manifest",),
        "inspect_manifest",
        {"manifest_path": str(project / "examples/toy_data/manifest.jsonl")},
    )
    assert result["item_count"] == 4
    assert result["unique_source_groups"] == 4
