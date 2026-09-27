from __future__ import annotations

from typing import Any, Protocol

from ..agents import AgentSpec
from ..schemas import JsonModel


class AgentProvider(Protocol):
    mode: str

    async def run(self, spec: AgentSpec, handoff: dict[str, Any]) -> JsonModel:
        """Run one agent with only the explicitly supplied handoff context."""
        ...
