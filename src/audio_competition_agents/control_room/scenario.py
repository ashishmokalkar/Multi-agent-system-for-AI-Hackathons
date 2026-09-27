from __future__ import annotations

import asyncio
import importlib.util
import os
import threading
from dataclasses import dataclass
from typing import Any

from ..agents import build_agent_specs
from ..config import Settings
from ..providers.base import AgentProvider
from ..providers.mock import MockProvider
from ..providers.openai_provider import OpenAIAgentsProvider
from ..schemas import AgentRole, RunBudget, RunStatus, UserObjective
from ..store import RunStore
from ..tools.base import ToolRegistry


class ScenarioCancelled(RuntimeError):
    pass


@dataclass
class RunControl:
    cancel: threading.Event
    thread: threading.Thread | None = None


class ControlRoomScenario:
    def __init__(
        self,
        settings: Settings,
        provider: AgentProvider,
        tools: ToolRegistry,
        store: RunStore,
        run_id: str,
        cancel: threading.Event,
    ):
        self.settings = settings
        self.provider = provider
        self.tools = tools
        self.store = store
        self.run_id = run_id
        self.cancel = cancel
        self.specs = build_agent_specs()

    def emit(
        self,
        event_type: str,
        summary: str,
        *,
        agent: AgentRole | str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        role = agent.value if isinstance(agent, AgentRole) else agent
        return self.store.append_event(self.run_id, event_type, summary, agent=role, payload=payload)

    def check_cancelled(self) -> None:
        if self.cancel.is_set():
            raise ScenarioCancelled("run cancelled by user")

    async def invoke(self, role: AgentRole, handoff: dict[str, Any], task: str):
        self.check_cancelled()
        spec = self.specs[role]
        self.emit("agent_started", task, agent=role, payload={"status": "running"})
        self.store.append_message(self.run_id, "coordinator", role.value, "control_room_handoff", handoff)
        output = await self.provider.run(spec, handoff)
        if not isinstance(output, spec.output_type):
            raise TypeError(f"{role.value} returned {type(output).__name__}; expected {spec.output_type.__name__}")
        self.store.append_message(self.run_id, role.value, "coordinator", "structured_output", output.to_dict())
        self.emit("agent_completed", task, agent=role, payload={"status": "completed", "output": output.to_dict()})
        return output

    async def run(self) -> None:
        budget = RunBudget(max_revision_attempts=1)
        fixture_dir = self.settings.run_root / self.run_id / "control_room_fixture"
        objective = UserObjective(
            text=(
                "Inspect a generated audio fixture, propose a bounded annotation experiment, "
                "prepare a candidate, independently verify its known boundaries, revise once if needed, and score it."
            ),
            task_kind="synthetic",
            manifest_path=str(fixture_dir / "manifest.jsonl"),
            reference_path=str(fixture_dir / "references.json"),
            prediction_path=str(fixture_dir / "candidate_predictions.json"),
            metadata={"scorer": "toy", "control_room_demo": True},
        )
        state: dict[str, Any] = {"phase": "control_room", "mode": self.provider.mode}
        try:
            self.store.update_run(self.run_id, RunStatus.ANALYZING.value, state)
            self.emit(
                "task_assigned",
                "Boundary-quality demo assigned",
                agent=AgentRole.COORDINATOR,
                payload={"objective": objective.text, "mode": self.provider.mode},
            )
            coordination = await self.invoke(
                AgentRole.COORDINATOR,
                {"phase": "intake", "objective": objective.to_dict(), "budget": budget.to_dict()},
                "Delegating the bounded audio experiment",
            )
            state["coordination"] = coordination.to_dict()

            self.check_cancelled()
            self.emit("tool_started", "Generating redistributable fixture", agent=AgentRole.SYNTHETIC_ENGINEER, payload={"progress": "indeterminate"})
            fixture = self.tools.invoke(
                AgentRole.SYNTHETIC_ENGINEER,
                self.specs[AgentRole.SYNTHETIC_ENGINEER].allowed_tools,
                "prepare_demo_fixture",
                {"run_id": self.run_id},
            )
            self.emit("tool_completed", "Generated 4-second fixture with explicit known boundaries", agent=AgentRole.SYNTHETIC_ENGINEER, payload={"result": {"duration_seconds": fixture["duration_seconds"], "sample_rate": fixture["sample_rate"]}})
            self.store.add_artifact(self.run_id, "fixture_audio", "control-room://fixture/audio", "wav", {"caption": fixture["caption"]})
            self.emit("artifact_created", "Audio fixture and reference annotation available", agent=AgentRole.SYNTHETIC_ENGINEER, payload={"artifact_id": "fixture_audio", "caption": fixture["caption"], "fixture": {"duration_seconds": fixture["duration_seconds"], "original_annotation": fixture["original_annotation"], "known_reference": fixture["known_reference"]}})

            data = await self.invoke(
                AgentRole.DATA_INVESTIGATOR,
                {"phase": "specialist_analysis", "objective": objective.to_dict()},
                "Inspecting fixture manifest and source isolation",
            )
            if not data.passed:
                raise RuntimeError("generated fixture failed source-isolation checks")
            state["data"] = data.to_dict()

            proposal = await self.invoke(
                AgentRole.RESEARCH_MODELER,
                {"phase": "proposal", "objective": objective.to_dict(), "specialist_outputs": {"data": data.to_dict()}, "revision": 0},
                "Drafting one bounded annotation-quality comparison",
            )
            state["proposal"] = proposal.to_dict()
            self.store.add_configuration(self.run_id, "control_room_proposal", proposal.to_dict())

            self.emit("tool_started", "Preparing initial candidate annotation", agent=AgentRole.SYNTHETIC_ENGINEER, payload={"progress": "indeterminate"})
            synthetic = await self.invoke(
                AgentRole.SYNTHETIC_ENGINEER,
                {"phase": "fixture_prepare", "run_id": self.run_id, "objective": objective.to_dict()},
                "Preparing the initial candidate artifact",
            )
            self.emit("tool_completed", "Initial candidate preserves the deliberately defective test boundary", agent=AgentRole.SYNTHETIC_ENGINEER, payload={"artifact_id": "initial_annotation"})
            state["synthetic"] = synthetic.to_dict()

            self.emit("tool_started", "Checking candidate against explicit fixture boundaries", agent=AgentRole.EVALUATOR, payload={"progress": "indeterminate"})
            first_review = await self.invoke(
                AgentRole.EVALUATOR,
                {
                    "phase": "fixture_review",
                    "reference_path": fixture["reference_path"],
                    "candidate_path": fixture["candidate_path"],
                    "tolerance_seconds": 0.005,
                },
                "Independently checking the candidate boundary",
            )
            first_check = self.tools.invoke(
                AgentRole.EVALUATOR,
                self.specs[AgentRole.EVALUATOR].allowed_tools,
                "validate_fixture_annotation",
                {"reference_path": fixture["reference_path"], "candidate_path": fixture["candidate_path"], "tolerance_seconds": 0.005},
            )
            self.emit("tool_completed", "Boundary check returned measured deltas", agent=AgentRole.EVALUATOR, payload={"result": first_check})
            if first_review.decision != "revise" or first_check["passed"]:
                raise RuntimeError("deliberately defective fixture was not rejected")
            self.emit("review_rejected", "Evaluator rejected the initial annotation", agent=AgentRole.EVALUATOR, payload={"findings": first_review.findings, "changes": first_check["changes"], "artifact_id": "initial_annotation"})
            self.emit("revision_requested", "One bounded boundary correction requested", agent=AgentRole.SYNTHETIC_ENGINEER, payload={"attempt": 1, "limit": budget.max_revision_attempts, "target": "synthetic_data_engineer"})

            self.emit("tool_started", "Applying fixture-only boundary correction", agent=AgentRole.SYNTHETIC_ENGINEER, payload={"progress": "indeterminate"})
            revised = await self.invoke(
                AgentRole.SYNTHETIC_ENGINEER,
                {"phase": "fixture_revision", "run_id": self.run_id, "objective": objective.to_dict(), "review": first_review.to_dict()},
                "Revising the rejected candidate artifact",
            )
            corrected = self.tools.invoke(
                AgentRole.SYNTHETIC_ENGINEER,
                self.specs[AgentRole.SYNTHETIC_ENGINEER].allowed_tools,
                "correct_fixture_annotation",
                {"run_id": self.run_id},
            )
            self.store.add_artifact(self.run_id, "corrected_annotation", "control-room://fixture/corrected", "json", {"revision": 1})
            self.emit("artifact_created", "Corrected annotation saved as revision 1", agent=AgentRole.SYNTHETIC_ENGINEER, payload={"artifact_id": "corrected_annotation", "proposed_correction": corrected["proposed_correction"], "changed_fields": corrected["changed_fields"]})
            self.emit("tool_completed", "Bounded correction completed", agent=AgentRole.SYNTHETIC_ENGINEER, payload={"revision": 1})
            state["revision"] = revised.to_dict()

            self.emit("tool_started", "Rerunning the deterministic boundary check", agent=AgentRole.EVALUATOR, payload={"progress": "indeterminate"})
            final_review = await self.invoke(
                AgentRole.EVALUATOR,
                {"phase": "fixture_review", "reference_path": fixture["reference_path"], "candidate_path": corrected["candidate_path"], "tolerance_seconds": 0.005},
                "Rechecking corrected boundaries",
            )
            final_check = self.tools.invoke(
                AgentRole.EVALUATOR,
                self.specs[AgentRole.EVALUATOR].allowed_tools,
                "validate_fixture_annotation",
                {"reference_path": fixture["reference_path"], "candidate_path": corrected["candidate_path"], "tolerance_seconds": 0.005},
            )
            self.emit("tool_completed", "Corrected candidate passed the known-boundary check", agent=AgentRole.EVALUATOR, payload={"result": final_check})
            if final_review.decision != "approve" or not final_check["passed"]:
                raise RuntimeError("corrected fixture did not pass evaluator recheck")
            self.emit("review_accepted", "Evaluator accepted revision 1", agent=AgentRole.EVALUATOR, payload={"findings": final_review.findings, "revision": 1})

            self.check_cancelled()
            self.emit("job_progress", "CPU scoring is running", agent=AgentRole.EVALUATOR, payload={"progress": "indeterminate", "job": "validation_and_scoring"})
            baseline_metrics = self.tools.invoke(
                AgentRole.EVALUATOR,
                self.specs[AgentRole.EVALUATOR].allowed_tools,
                "score_predictions",
                {"reference_path": fixture["scoring_reference_path"], "prediction_path": fixture["baseline_prediction_path"], "scorer": "toy"},
            )
            candidate_metrics = self.tools.invoke(
                AgentRole.EVALUATOR,
                self.specs[AgentRole.EVALUATOR].allowed_tools,
                "score_predictions",
                {"reference_path": fixture["scoring_reference_path"], "prediction_path": corrected["prediction_path"], "scorer": "toy"},
            )
            metrics = {"baseline": baseline_metrics, "candidate": candidate_metrics, "label": "Generated fixture only — toy scorer, not competition metrics"}
            self.store.add_metrics(self.run_id, "generated control-room fixture", metrics)
            self.emit("metrics_recorded", "Measured fixture scores recorded", agent=AgentRole.EVALUATOR, payload=metrics)
            state["metrics"] = metrics

            summary = await self.invoke(
                AgentRole.COORDINATOR,
                {"phase": "final", "status": "complete", "reason": "Fixture correction passed deterministic review and CPU scoring.", "metrics": candidate_metrics, "review": final_review.to_dict(), "unresolved": []},
                "Summarizing the observed fixture outcome",
            )
            state["summary"] = summary.to_dict()
            state["phase"] = "finished"
            self.emit("run_completed", "Demo completed with one measured rejection and correction", agent=AgentRole.COORDINATOR, payload={"status": "complete", "summary": summary.summary})
            self.store.update_run(self.run_id, RunStatus.COMPLETE.value, state)
        except ScenarioCancelled as error:
            state["phase"] = "cancelled"
            self.emit("run_cancelled", str(error), agent=AgentRole.COORDINATOR, payload={"status": "cancelled"})
            self.store.update_run(self.run_id, RunStatus.CANCELLED.value, state)
        except Exception as error:
            state["phase"] = "failed"
            state["error"] = str(error)
            self.emit("run_failed", "Control-room run failed", agent=AgentRole.COORDINATOR, payload={"status": "failed", "error": str(error)})
            self.store.update_run(self.run_id, RunStatus.FAILED.value, state)


class ControlRoomManager:
    def __init__(self, settings: Settings, tools: ToolRegistry, store: RunStore):
        self.settings = settings
        self.tools = tools
        self.store = store
        self._controls: dict[str, RunControl] = {}
        self._lock = threading.RLock()

    def _provider(self, mode: str) -> AgentProvider:
        if mode == "mock":
            return MockProvider(self.tools)
        if mode == "live":
            return OpenAIAgentsProvider(self.settings.model, self.settings.api_key_env, self.tools)
        raise ValueError("mode must be mock or live")

    def start(self, mode: str = "mock") -> str:
        provider = self._provider(mode)
        objective = {"text": "Control-room generated fixture demonstration", "task_kind": "synthetic"}
        budget = RunBudget(max_revision_attempts=1).to_dict()
        run_id = self.store.create_run(objective, budget, provider.mode)
        cancel = threading.Event()
        scenario = ControlRoomScenario(self.settings, provider, self.tools, self.store, run_id, cancel)
        thread = threading.Thread(target=lambda: asyncio.run(scenario.run()), name=f"control-room-{run_id}", daemon=True)
        control = RunControl(cancel=cancel, thread=thread)
        with self._lock:
            self._controls[run_id] = control
        thread.start()
        return run_id

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            control = self._controls.get(run_id)
            if control is None or control.thread is None or not control.thread.is_alive():
                return False
            control.cancel.set()
            return True

    def active(self, run_id: str) -> bool:
        with self._lock:
            control = self._controls.get(run_id)
            return bool(control and control.thread and control.thread.is_alive())

    def live_available(self) -> bool:
        return bool(os.getenv(self.settings.api_key_env)) and importlib.util.find_spec("agents") is not None
