from __future__ import annotations

from audio_competition_agents.agents import build_agent_specs
from audio_competition_agents.schemas import AgentRole


def test_seven_agents_have_separate_prompts_schemas_and_tools():
    specs = build_agent_specs()
    assert set(specs) == set(AgentRole)
    assert len({spec.instructions for spec in specs.values()}) == 7
    assert len({spec.output_type for spec in specs.values()}) == 7
    assert "launch_training" in specs[AgentRole.TRAINING_ENGINEER].allowed_tools
    assert "launch_training" not in specs[AgentRole.RESEARCH_MODELER].allowed_tools
    assert "generate_synthetic_clip" in specs[AgentRole.SYNTHETIC_ENGINEER].allowed_tools
    assert "score_predictions" in specs[AgentRole.EVALUATOR].allowed_tools
