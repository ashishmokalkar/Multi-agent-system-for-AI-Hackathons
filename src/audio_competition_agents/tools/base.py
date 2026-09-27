from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Callable

from ..schemas import AgentRole


class ToolError(RuntimeError):
    pass


class ToolPermissionError(ToolError):
    pass


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_type: type
    handler: Callable[[Any], Any]
    mutating: bool = False
    source_attribution: str = ""

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            request = self.input_type(**payload)
        except TypeError as error:
            raise ToolError(f"invalid input for {self.name}: {error}") from error
        result = self.handler(request)
        if dataclasses.is_dataclass(result):
            return dataclasses.asdict(result)
        if isinstance(result, dict):
            return result
        raise ToolError(f"{self.name} returned unsupported type {type(result).__name__}")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"duplicate tool: {definition.name}")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as error:
            raise ToolError(f"unknown tool: {name}") from error

    def invoke(self, role: AgentRole, allowed_tools: tuple[str, ...], name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if name not in allowed_tools:
            raise ToolPermissionError(f"{role.value} is not allowed to call {name}")
        return self.get(name).invoke(payload)

    def definitions_for(self, names: tuple[str, ...]) -> list[ToolDefinition]:
        return [self.get(name) for name in names]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))
