from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..agents import AgentSpec
from ..schemas import (
    AgentRole,
    ArtifactReference,
    CoordinatorOutput,
    DataInvestigationOutput,
    EnsembleAnalysisOutput,
    EvaluationReview,
    ExperimentProposal,
    MetricBundle,
    SyntheticEngineeringOutput,
    TrainingEngineeringOutput,
)
from ..tools.base import ToolRegistry


class MockProvider:
    """Deterministic offline agents that exercise real tools and handoffs."""

    mode = "mock"

    def __init__(self, tools: ToolRegistry):
        self.tools = tools

    def _call(self, spec: AgentSpec, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.tools.invoke(spec.role, spec.allowed_tools, name, payload)

    async def run(self, spec: AgentSpec, handoff: dict[str, Any]):
        await asyncio.sleep(0)
        handlers = {
            AgentRole.COORDINATOR: self._coordinator,
            AgentRole.DATA_INVESTIGATOR: self._data,
            AgentRole.SYNTHETIC_ENGINEER: self._synthetic,
            AgentRole.RESEARCH_MODELER: self._research,
            AgentRole.TRAINING_ENGINEER: self._training,
            AgentRole.EVALUATOR: self._evaluator,
            AgentRole.ENSEMBLE_ANALYST: self._ensemble,
        }
        return handlers[spec.role](spec, handoff)

    def _coordinator(self, spec: AgentSpec, handoff: dict[str, Any]) -> CoordinatorOutput:
        phase = handoff.get("phase", "intake")
        objective = handoff.get("objective", {})
        if phase == "intake":
            selected = [AgentRole.DATA_INVESTIGATOR.value, AgentRole.RESEARCH_MODELER.value]
            kind = objective.get("task_kind", "analysis")
            text = objective.get("text", "").lower()
            if kind == "synthetic" or "synthetic" in text:
                selected.append(AgentRole.SYNTHETIC_ENGINEER.value)
            if kind == "ensemble" or "ensemble" in text:
                selected.append(AgentRole.ENSEMBLE_ANALYST.value)
            return CoordinatorOutput(
                phase="intake",
                selected_specialists=selected,
                delegated_tasks={role: f"Analyze the objective within the {role} contract." for role in selected},
                decision="delegate",
                summary="Objective decomposed into bounded specialist handoffs.",
            )
        status = handoff.get("status", "complete")
        metrics = handoff.get("metrics")
        metric_text = ""
        if metrics:
            metric_text = f" Toy Combined={metrics.get('combined', 0):.4f}." if "toy" in metrics.get("scorer", "") else f" Combined={metrics.get('combined', 0):.4f}."
        return CoordinatorOutput(
            phase="final",
            decision=status,
            summary=f"Workflow {status} after independent review.{metric_text}",
            unresolved=handoff.get("unresolved", []),
        )

    def _data(self, spec: AgentSpec, handoff: dict[str, Any]) -> DataInvestigationOutput:
        objective = handoff["objective"]
        manifest = objective.get("manifest_path")
        if not manifest:
            return DataInvestigationOutput(False, 0, 0.0, findings=["No manifest was supplied."])
        inspection = self._call(spec, "inspect_manifest", {"manifest_path": manifest})
        integrity = self._call(spec, "validate_source_split", {"manifest_path": manifest})
        return DataInvestigationOutput(
            passed=integrity["passed"],
            item_count=inspection["item_count"],
            duration_hours=inspection["duration_hours"],
            split_counts=inspection["split_counts"],
            category_counts=inspection["category_counts"],
            source_group_intersections={"all_splits": integrity["source_group_intersection_count"]},
            duplicate_hash_intersections={"all_splits": integrity["duplicate_hash_intersection_count"]},
            findings=[
                "Source isolation passed." if integrity["passed"] else "Source isolation failed; execution must stop.",
                f"Evaluation clip leaks: {integrity['eval_clip_leak_count']}.",
            ],
            evidence=[ArtifactReference("manifest", manifest, "jsonl")],
        )

    def _synthetic(self, spec: AgentSpec, handoff: dict[str, Any]) -> SyntheticEngineeringOutput:
        phase = handoff.get("phase")
        if phase == "fixture_prepare":
            result = self._call(spec, "prepare_demo_fixture", {"run_id": handoff["run_id"]})
            return SyntheticEngineeringOutput(
                passed=True,
                generator_policy="deterministic_generated_fixture",
                source_isolation_passed=True,
                sample_accurate_boundaries=True,
                findings=["Generated the fixture and deliberately defective test annotation."],
                evidence=[ArtifactReference("fixture_audio", result["audio_path"], "wav", result["caption"])],
            )
        if phase == "fixture_revision":
            result = self._call(spec, "correct_fixture_annotation", {"run_id": handoff["run_id"]})
            return SyntheticEngineeringOutput(
                passed=True,
                generator_policy="bounded_fixture_reference_revision",
                source_isolation_passed=True,
                sample_accurate_boundaries=True,
                findings=["Revised only the rejected fixture onset and offset."],
                evidence=[ArtifactReference(
                    "corrected_annotation", result["candidate_path"], "json",
                    "Known-reference-guided correction for the explicitly labeled test fixture.",
                )],
            )
        plan = handoff["objective"].get("metadata", {}).get("synthetic_plan", {
            "event_boundary_policy": "sample_accurate_active_interval",
            "source_partition_disjoint": True,
            "eval_exclusion_checked": True,
            "license_checked": True,
            "required_transform_metadata": [
                "crop_origin_sample",
                "local_event_onset_sample",
                "local_event_offset_sample",
                "placement_sample",
            ],
        })
        result = self._call(spec, "validate_synthetic_plan", {"plan": plan})
        return SyntheticEngineeringOutput(
            passed=result["passed"],
            generator_policy=result["generator_policy"],
            source_isolation_passed=result["source_isolation_passed"],
            sample_accurate_boundaries=result["sample_accurate_boundaries"],
            findings=result["errors"] or ["Synthetic plan passed all non-audio preflight checks."],
        )

    def _research(self, spec: AgentSpec, handoff: dict[str, Any]) -> ExperimentProposal:
        objective = handoff["objective"]
        revision = int(handoff.get("revision", 0))
        claims = ["The proposal is a matched comparison; improvement remains a hypothesis."]
        if objective.get("metadata", {}).get("force_revision") and revision == 0:
            claims.append("The candidate is guaranteed to improve the leaderboard.")
        return ExperimentProposal(
            proposal_id=f"mock-proposal-r{revision}",
            title="Matched boundary-supervision check",
            hypothesis="Boundary supervision may improve Event F1 without materially reducing Segment Dice.",
            model_configuration={
                "incumbent": "existing frozen-encoder A1",
                "changed_factor": "proposal-only diagnostic in mock mode",
                "all_other_factors_locked": True,
            },
            data_configuration={"manifest": objective.get("manifest_path"), "source_disjoint_required": True},
            comparison="paired candidate minus incumbent on one fixed held-out population",
            primary_metric="Event F1 + Segment Dice",
            gate={"minimum_combined_delta": 0.01, "maximum_dice_regression": 0.005},
            requires_training=bool(objective.get("execute_training")),
            estimated_gpu_hours=float(objective.get("metadata", {}).get("estimated_gpu_hours", 0.0)),
            evidence_claims=claims,
            revision=revision,
        )

    def _training(self, spec: AgentSpec, handoff: dict[str, Any]) -> TrainingEngineeringOutput:
        result = self._call(spec, "launch_training", handoff["training_request"])
        return TrainingEngineeringOutput(**result)

    def _evaluator(self, spec: AgentSpec, handoff: dict[str, Any]) -> EvaluationReview:
        phase = handoff.get("phase", "proposal_review")
        if phase == "fixture_review":
            result = self._call(spec, "validate_fixture_annotation", {
                "reference_path": handoff["reference_path"],
                "candidate_path": handoff["candidate_path"],
                "tolerance_seconds": handoff.get("tolerance_seconds", 0.005),
            })
            return EvaluationReview(
                decision="approve" if result["passed"] else "revise",
                checks={"known_boundary_match": result["passed"], "deterministic_check": True},
                findings=result["errors"] or ["Candidate matches the explicit known fixture boundaries."],
                required_revisions=[] if result["passed"] else ["Correct only the reported fixture boundary fields."],
                matched_comparison=True,
            )
        if phase == "post_score":
            metrics = MetricBundle(**handoff["metrics"])
            return EvaluationReview(
                decision="approve",
                checks={"scorer_labeled": bool(metrics.scorer), "finite_combined": metrics.combined is not None},
                findings=["Metrics are descriptive for the labeled population only."],
                metrics=metrics,
                matched_comparison=True,
            )
        proposal = handoff["proposal"]
        data = handoff.get("data", {})
        budget = handoff.get("budget", {})
        split_ok = bool(data.get("passed", False))
        claims_ok = not any("guaranteed" in claim.lower() for claim in proposal.get("evidence_claims", []))
        budget_ok = not proposal.get("requires_training") or (
            budget.get("training_authorized", False)
            and budget.get("max_training_runs", 0) >= 1
            and budget.get("max_gpu_hours", 0.0) >= proposal.get("estimated_gpu_hours", 0.0)
        )
        checks = {"source_isolation": split_ok, "claims_supported": claims_ok, "budget_authorized": budget_ok}
        if not split_ok:
            return EvaluationReview("reject", checks, ["Invalid source split blocks the proposal."], matched_comparison=False)
        if not budget_ok:
            return EvaluationReview("reject", checks, ["Training was requested without a sufficient authorized budget."], matched_comparison=False)
        if not claims_ok:
            return EvaluationReview(
                "revise",
                checks,
                ["A guaranteed leaderboard improvement is unsupported."],
                ["Remove the unsupported guarantee and keep the effect as a hypothesis."],
                matched_comparison=True,
            )
        return EvaluationReview("approve", checks, ["Proposal is bounded, matched, and budget-compliant."], matched_comparison=True)

    def _ensemble(self, spec: AgentSpec, handoff: dict[str, Any]) -> EnsembleAnalysisOutput:
        paths = handoff["objective"].get("metadata", {}).get("prediction_paths", [])
        if len(paths) < 2:
            return EnsembleAnalysisOutput(False, [], findings=["Fewer than two saved prediction files were supplied."])
        result = self._call(spec, "compare_saved_predictions", {"prediction_paths": paths})
        return EnsembleAnalysisOutput(
            compatible=result["compatible"],
            candidate_names=result["candidate_names"],
            combinations_evaluated=0,
            findings=[result["finding"]],
        )
