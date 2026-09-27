from __future__ import annotations

import json
import os
from typing import Any

from ..agents import AgentSpec
from ..schemas import JsonModel
from ..tools.base import ToolRegistry


class OpenAIAgentsProvider:
    """Optional real-provider bridge using the OpenAI Agents SDK."""

    mode = "real"

    def __init__(self, model: str, api_key_env: str, tools: ToolRegistry):
        if not os.getenv(api_key_env):
            raise RuntimeError(f"{api_key_env} is required for real mode")
        try:
            from agents import Agent, Runner, function_tool
        except ImportError as error:
            raise RuntimeError("install the openai extra: pip install -e '.[openai]'") from error
        self.model = model
        self.tools = tools
        self._Agent = Agent
        self._Runner = Runner
        self._function_tool = function_tool
        self._instances: dict[str, Any] = {}

    def _tool(self, spec: AgentSpec, name: str) -> Any:
        definition = self.tools.get(name)

        def invoke(payload_json: str) -> str:
            """Invoke this typed competition tool with a JSON object."""
            payload = json.loads(payload_json)
            result = self.tools.invoke(spec.role, spec.allowed_tools, name, payload)
            return json.dumps(result, sort_keys=True)

        invoke.__name__ = name
        invoke.__doc__ = definition.description + " Input is a JSON object matching the documented typed schema."
        return self._function_tool(invoke)

    def _agent(self, spec: AgentSpec) -> Any:
        if spec.role.value not in self._instances:
            self._instances[spec.role.value] = self._Agent(
                name=spec.display_name,
                instructions=spec.instructions,
                model=self.model,
                tools=[self._tool(spec, name) for name in spec.allowed_tools],
                output_type=spec.output_type,
            )
        return self._instances[spec.role.value]

    async def run(self, spec: AgentSpec, handoff: dict[str, Any]) -> JsonModel:
        result = await self._Runner.run(
            self._agent(spec),
            input=json.dumps(handoff, sort_keys=True),
            max_turns=spec.max_turns,
        )
        output = result.final_output
        if isinstance(output, spec.output_type):
            return output
        if isinstance(output, dict):
            return spec.output_type(**output)
        raise TypeError(f"{spec.display_name} returned {type(output).__name__}, expected {spec.output_type.__name__}")
