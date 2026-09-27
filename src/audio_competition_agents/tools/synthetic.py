from __future__ import annotations

from dataclasses import dataclass
from typing import Any


FORBIDDEN_POLICIES = {
    "center_crop_whole_annotation",
    "whole_crop_annotation",
    "center_crop_full_duration_label",
}


@dataclass(frozen=True)
class ValidateSyntheticPlanInput:
    plan: dict[str, Any]


def validate_synthetic_plan(request: ValidateSyntheticPlanInput) -> dict[str, Any]:
    plan = request.plan
    policy = str(plan.get("event_boundary_policy", ""))
    errors: list[str] = []
    if policy in FORBIDDEN_POLICIES or "whole_crop" in policy:
        errors.append("defective whole-crop annotation policy is forbidden")
    if policy != "sample_accurate_active_interval":
        errors.append("event_boundary_policy must be sample_accurate_active_interval")
    if not plan.get("source_partition_disjoint", False):
        errors.append("source partitions are not proven disjoint")
    if not plan.get("eval_exclusion_checked", False):
        errors.append("evaluation exclusion has not been checked")
    if not plan.get("license_checked", False):
        errors.append("source licensing has not been checked")
    transforms = set(plan.get("required_transform_metadata", []))
    required = {"crop_origin_sample", "local_event_onset_sample", "local_event_offset_sample", "placement_sample"}
    missing = sorted(required - transforms)
    if missing:
        errors.append("missing transform metadata: " + ", ".join(missing))
    return {
        "passed": not errors,
        "errors": errors,
        "generator_policy": policy,
        "source_isolation_passed": bool(plan.get("source_partition_disjoint")) and bool(plan.get("eval_exclusion_checked")),
        "sample_accurate_boundaries": policy == "sample_accurate_active_interval" and not missing,
    }
