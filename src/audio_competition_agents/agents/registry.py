from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files

from ..schemas import AgentRole, JsonModel, OUTPUT_TYPES


@dataclass(frozen=True)
class AgentSpec:
    role: AgentRole
    display_name: str
    instructions: str
    allowed_tools: tuple[str, ...]
    output_type: type[JsonModel]
    max_turns: int = 8


def _prompt(name: str) -> str:
    return files("audio_competition_agents.agents.prompts").joinpath(name).read_text(encoding="utf-8")


def build_agent_specs() -> dict[AgentRole, AgentSpec]:
    definitions = {
        AgentRole.COORDINATOR: (
            "Coordinator",
            "coordinator.md",
            (),
        ),
        AgentRole.DATA_INVESTIGATOR: (
            "Data investigator",
            "data_investigator.md",
            ("inspect_manifest", "validate_source_split"),
        ),
        AgentRole.SYNTHETIC_ENGINEER: (
            "Synthetic-data engineer",
            "synthetic_engineer.md",
            (
                "validate_synthetic_plan",
                "generate_synthetic_clip",
                "prepare_demo_fixture",
                "correct_fixture_annotation",
            ),
        ),
        AgentRole.RESEARCH_MODELER: (
            "Research/modeling agent",
            "research_modeler.md",
            ("inspect_manifest",),
        ),
        AgentRole.TRAINING_ENGINEER: (
            "Training engineer",
            "training_engineer.md",
            ("launch_training", "run_inference"),
        ),
        AgentRole.EVALUATOR: (
            "Independent evaluator",
            "evaluator.md",
            ("validate_source_split", "validate_fixture_annotation", "score_predictions"),
        ),
        AgentRole.ENSEMBLE_ANALYST: (
            "Ensemble analyst",
            "ensemble_analyst.md",
            ("compare_saved_predictions", "score_predictions"),
        ),
    }
    return {
        role: AgentSpec(role, name, _prompt(prompt), tools, OUTPUT_TYPES[role])
        for role, (name, prompt, tools) in definitions.items()
    }
