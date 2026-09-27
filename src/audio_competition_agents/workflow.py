from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from .agents import AgentSpec, build_agent_specs
from .config import Settings
from .providers.base import AgentProvider
from .schemas import (
    AgentRole,
    EvaluationReview,
    ExperimentProposal,
    MetricBundle,
    ReviewDecision,
    RunBudget,
    RunStatus,
    UserObjective,
    WorkflowResult,
)
from .store import RunStore
from .tools.base import ToolRegistry


class CompetitionWorkflow:
    def __init__(
        self,
        settings: Settings,
        provider: AgentProvider,
        tools: ToolRegistry,
        store: RunStore,
    ):
        self.settings = settings
        self.provider = provider
        self.tools = tools
        self.store = store
        self.specs = build_agent_specs()

    async def run(
        self,
        objective: UserObjective,
        budget: RunBudget | None = None,
        *,
        run_id: str | None = None,
    ) -> WorkflowResult:
        budget = budget or RunBudget(max_revision_attempts=self.settings.max_revision_attempts)
        if run_id is None:
            run_id = self.store.create_run(objective.to_dict(), budget.to_dict(), self.provider.mode)
            state: dict[str, Any] = {"phase": "created", "revision_attempts": 0}
        else:
            saved = self.store.get_run(run_id)
            state = saved["state"]
            objective = UserObjective(**saved["objective"])
            budget = RunBudget(**saved["budget"])
            if saved["status"] in {
                RunStatus.COMPLETE.value,
                RunStatus.BLOCKED.value,
                RunStatus.BUDGET_EXHAUSTED.value,
                RunStatus.CANCELLED.value,
            }:
                return self._result(run_id, saved["status"], state)

        if "coordination" not in state:
            state["phase"] = "coordinator_intake"
            self._checkpoint(run_id, RunStatus.ANALYZING, state)
            coordination = await self._invoke(
                run_id,
                AgentRole.COORDINATOR,
                "user",
                {"phase": "intake", "objective": objective.to_dict(), "budget": budget.to_dict()},
            )
            state["coordination"] = coordination.to_dict()
            self._checkpoint(run_id, RunStatus.ANALYZING, state)

        if "specialist_outputs" not in state:
            selected = {
                AgentRole(value)
                for value in state["coordination"]["selected_specialists"]
                if value not in {AgentRole.RESEARCH_MODELER.value, AgentRole.TRAINING_ENGINEER.value}
            }
            semaphore = asyncio.Semaphore(self.settings.max_parallel_specialists)

            async def invoke_specialist(role: AgentRole):
                async with semaphore:
                    return role, await self._invoke(
                        run_id,
                        role,
                        AgentRole.COORDINATOR.value,
                        {"phase": "specialist_analysis", "objective": objective.to_dict()},
                    )

            outputs = await asyncio.gather(*(invoke_specialist(role) for role in sorted(selected, key=str)))
            state["specialist_outputs"] = {role.value: output.to_dict() for role, output in outputs}
            self._checkpoint(run_id, RunStatus.ANALYZING, state)

        data = state["specialist_outputs"].get(AgentRole.DATA_INVESTIGATOR.value, {})
        if not data.get("passed", False):
            return await self._finish(
                run_id,
                state,
                RunStatus.BLOCKED,
                "Data integrity failed before proposal review.",
                ["Source-disjointness or manifest availability was not established."],
            )

        max_revisions = min(self.settings.max_revision_attempts, budget.max_revision_attempts)
        while True:
            if "proposal" not in state or state.get("review", {}).get("decision") == ReviewDecision.REVISE.value:
                revision = int(state.get("revision_attempts", 0))
                proposal = await self._invoke(
                    run_id,
                    AgentRole.RESEARCH_MODELER,
                    AgentRole.COORDINATOR.value,
                    {
                        "phase": "proposal",
                        "objective": objective.to_dict(),
                        "specialist_outputs": state["specialist_outputs"],
                        "revision": revision,
                        "revision_feedback": state.get("review", {}).get("required_revisions", []),
                    },
                )
                state["proposal"] = proposal.to_dict()
                self.store.add_configuration(run_id, "experiment_proposal", state["proposal"])
                state.pop("review", None)
                self._checkpoint(run_id, RunStatus.ANALYZING, state)

            review = await self._invoke(
                run_id,
                AgentRole.EVALUATOR,
                AgentRole.COORDINATOR.value,
                {
                    "phase": "proposal_review",
                    "proposal": state["proposal"],
                    "data": data,
                    "specialist_outputs": state["specialist_outputs"],
                    "budget": budget.to_dict(),
                },
            )
            state["review"] = review.to_dict()
            self._checkpoint(run_id, RunStatus.ANALYZING, state)

            if review.decision == ReviewDecision.APPROVE.value:
                break
            if review.decision == ReviewDecision.REJECT.value:
                return await self._finish(
                    run_id,
                    state,
                    RunStatus.BLOCKED,
                    "Independent evaluator rejected the proposal.",
                    review.findings,
                )
            state["revision_attempts"] = int(state.get("revision_attempts", 0)) + 1
            if state["revision_attempts"] > max_revisions:
                return await self._finish(
                    run_id,
                    state,
                    RunStatus.BUDGET_EXHAUSTED,
                    "Proposal revision budget was exhausted.",
                    review.required_revisions,
                )
            self._checkpoint(run_id, RunStatus.REVISION, state)

        self._checkpoint(run_id, RunStatus.APPROVED, state)
        proposal = ExperimentProposal(**state["proposal"])
        if proposal.requires_training and "execution" not in state:
            training_request = {
                "config_id": objective.metadata.get("training_config_id", "beats_a1_synthetic_40h_local"),
                "run_id": run_id,
                "device": objective.metadata.get("device", "cuda"),
                "dry_run": self.provider.mode == "mock" or not bool(objective.metadata.get("live_execution", False)),
                "estimated_gpu_hours": proposal.estimated_gpu_hours,
                "timeout_seconds": min(
                    int(objective.metadata.get("timeout_seconds", budget.max_wall_seconds_per_job)),
                    budget.max_wall_seconds_per_job,
                ),
                "budget": budget.to_dict(),
            }
            self._checkpoint(run_id, RunStatus.EXECUTING, state)
            execution = await self._invoke(
                run_id,
                AgentRole.TRAINING_ENGINEER,
                AgentRole.COORDINATOR.value,
                {"phase": "execution", "training_request": training_request},
            )
            state["execution"] = execution.to_dict()
            self._checkpoint(run_id, RunStatus.EXECUTING, state)
            if execution.status == "failed":
                return await self._finish(run_id, state, RunStatus.FAILED, execution.message, [])

        if objective.reference_path and objective.prediction_path and "metrics" not in state:
            self._checkpoint(run_id, RunStatus.SCORING, state)
            score = self.tools.invoke(
                AgentRole.EVALUATOR,
                self.specs[AgentRole.EVALUATOR].allowed_tools,
                "score_predictions",
                {
                    "reference_path": objective.reference_path,
                    "prediction_path": objective.prediction_path,
                    "scorer": objective.metadata.get("scorer", "toy"),
                },
            )
            metrics = MetricBundle(
                event_precision=score.get("event_precision"),
                event_recall=score.get("event_recall"),
                event_f1=score.get("event_f1"),
                segment_dice=score.get("segment_dice"),
                combined=score.get("combined"),
                population=score.get("population", ""),
                scorer=score.get("scorer", ""),
            )
            state["metrics"] = metrics.to_dict()
            self.store.add_metrics(run_id, metrics.population, metrics.to_dict())
            post_review = await self._invoke(
                run_id,
                AgentRole.EVALUATOR,
                AgentRole.COORDINATOR.value,
                {"phase": "post_score", "metrics": metrics.to_dict(), "proposal": state["proposal"]},
            )
            state["post_score_review"] = post_review.to_dict()
            self._checkpoint(run_id, RunStatus.SCORING, state)

        return await self._finish(run_id, state, RunStatus.COMPLETE, "Workflow completed.", [])

    async def _invoke(
        self,
        run_id: str,
        role: AgentRole,
        sender: str,
        handoff: dict[str, Any],
    ):
        spec = self.specs[role]
        self.store.append_message(run_id, sender, role.value, "handoff", handoff)
        output = await self.provider.run(spec, handoff)
        if not isinstance(output, spec.output_type):
            raise TypeError(f"{role.value} returned {type(output).__name__}; expected {spec.output_type.__name__}")
        self.store.append_message(run_id, role.value, AgentRole.COORDINATOR.value, "structured_output", output.to_dict())
        return output

    async def _finish(
        self,
        run_id: str,
        state: dict[str, Any],
        status: RunStatus,
        reason: str,
        unresolved: list[str],
    ) -> WorkflowResult:
        summary = await self._invoke(
            run_id,
            AgentRole.COORDINATOR,
            "workflow",
            {
                "phase": "final",
                "status": status.value,
                "reason": reason,
                "metrics": state.get("metrics"),
                "review": state.get("review"),
                "unresolved": unresolved,
            },
        )
        state["final_summary"] = summary.to_dict()
        state["phase"] = "finished"
        self._checkpoint(run_id, status, state)
        return self._result(run_id, status.value, state)

    def _checkpoint(self, run_id: str, status: RunStatus, state: dict[str, Any]) -> None:
        self.store.update_run(run_id, status.value, state)

    def _result(self, run_id: str, status: str, state: dict[str, Any]) -> WorkflowResult:
        proposal = ExperimentProposal(**state["proposal"]) if state.get("proposal") else None
        review = None
        if state.get("review"):
            raw = dict(state["review"])
            if raw.get("metrics"):
                raw["metrics"] = MetricBundle(**raw["metrics"])
            review = EvaluationReview(**raw)
        metrics = MetricBundle(**state["metrics"]) if state.get("metrics") else None
        summary = state.get("final_summary", {}).get("summary", status)
        return WorkflowResult(
            run_id=run_id,
            status=status,
            mode=self.provider.mode,
            revision_attempts=int(state.get("revision_attempts", 0)),
            coordinator_summary=summary,
            proposal=proposal,
            review=review,
            metrics=metrics,
        )
