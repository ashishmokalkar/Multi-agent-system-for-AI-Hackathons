from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class AgentRole(StrEnum):
    COORDINATOR = "coordinator"
    DATA_INVESTIGATOR = "data_investigator"
    SYNTHETIC_ENGINEER = "synthetic_data_engineer"
    RESEARCH_MODELER = "research_modeling_agent"
    TRAINING_ENGINEER = "training_engineer"
    EVALUATOR = "independent_evaluator"
    ENSEMBLE_ANALYST = "ensemble_analyst"


class RunStatus(StrEnum):
    CREATED = "created"
    ANALYZING = "analyzing"
    REVISION = "revision"
    APPROVED = "approved"
    EXECUTING = "executing"
    SCORING = "scoring"
    COMPLETE = "complete"
    BLOCKED = "blocked"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"


class ExecutionMode(StrEnum):
    MOCK = "mock"
    REAL = "real"


@dataclass
class JsonModel:
    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


@dataclass
class ArtifactReference(JsonModel):
    name: str
    uri: str
    kind: str
    description: str = ""


@dataclass
class MetricBundle(JsonModel):
    event_precision: float | None = None
    event_recall: float | None = None
    event_f1: float | None = None
    segment_dice: float | None = None
    combined: float | None = None
    population: str = ""
    scorer: str = ""


@dataclass
class RunBudget(JsonModel):
    training_authorized: bool = False
    max_gpu_hours: float = 0.0
    max_training_runs: int = 0
    max_wall_seconds_per_job: int = 1800
    max_revision_attempts: int = 2


@dataclass
class UserObjective(JsonModel):
    text: str
    task_kind: str = "analysis"
    requested_specialists: list[str] = field(default_factory=list)
    execute_training: bool = False
    prediction_path: str | None = None
    reference_path: str | None = None
    manifest_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CoordinatorOutput(JsonModel):
    phase: str
    selected_specialists: list[str] = field(default_factory=list)
    delegated_tasks: dict[str, str] = field(default_factory=dict)
    decision: str = ""
    summary: str = ""
    unresolved: list[str] = field(default_factory=list)


@dataclass
class DataInvestigationOutput(JsonModel):
    passed: bool
    item_count: int
    duration_hours: float
    split_counts: dict[str, int] = field(default_factory=dict)
    category_counts: dict[str, int] = field(default_factory=dict)
    source_group_intersections: dict[str, int] = field(default_factory=dict)
    duplicate_hash_intersections: dict[str, int] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    evidence: list[ArtifactReference] = field(default_factory=list)


@dataclass
class SyntheticEngineeringOutput(JsonModel):
    passed: bool
    generator_policy: str
    source_isolation_passed: bool
    sample_accurate_boundaries: bool
    findings: list[str] = field(default_factory=list)
    evidence: list[ArtifactReference] = field(default_factory=list)


@dataclass
class ExperimentProposal(JsonModel):
    proposal_id: str
    title: str
    hypothesis: str
    model_configuration: dict[str, Any]
    data_configuration: dict[str, Any]
    comparison: str
    primary_metric: str
    gate: dict[str, Any]
    requires_training: bool
    estimated_gpu_hours: float
    evidence_claims: list[str] = field(default_factory=list)
    revision: int = 0


@dataclass
class TrainingEngineeringOutput(JsonModel):
    status: str
    config_id: str
    dry_run: bool
    command_preview: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    return_code: int | None = None
    artifact_references: list[ArtifactReference] = field(default_factory=list)
    message: str = ""


@dataclass
class EvaluationReview(JsonModel):
    decision: str
    checks: dict[str, bool]
    findings: list[str]
    required_revisions: list[str] = field(default_factory=list)
    metrics: MetricBundle | None = None
    matched_comparison: bool = False


@dataclass
class EnsembleAnalysisOutput(JsonModel):
    compatible: bool
    candidate_names: list[str]
    event_counts: dict[str, int] = field(default_factory=dict)
    combinations_evaluated: int = 0
    best_descriptive_combination: str | None = None
    findings: list[str] = field(default_factory=list)


@dataclass
class WorkflowResult(JsonModel):
    run_id: str
    status: str
    mode: str
    revision_attempts: int
    coordinator_summary: str
    proposal: ExperimentProposal | None = None
    review: EvaluationReview | None = None
    metrics: MetricBundle | None = None
    artifacts: list[ArtifactReference] = field(default_factory=list)


OUTPUT_TYPES: dict[AgentRole, type[JsonModel]] = {
    AgentRole.COORDINATOR: CoordinatorOutput,
    AgentRole.DATA_INVESTIGATOR: DataInvestigationOutput,
    AgentRole.SYNTHETIC_ENGINEER: SyntheticEngineeringOutput,
    AgentRole.RESEARCH_MODELER: ExperimentProposal,
    AgentRole.TRAINING_ENGINEER: TrainingEngineeringOutput,
    AgentRole.EVALUATOR: EvaluationReview,
    AgentRole.ENSEMBLE_ANALYST: EnsembleAnalysisOutput,
}
