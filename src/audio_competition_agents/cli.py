from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .config import Settings
from .providers.mock import MockProvider
from .providers.openai_provider import OpenAIAgentsProvider
from .schemas import RunBudget, UserObjective
from .store import RunStore
from .tools import build_tool_registry
from .workflow import CompetitionWorkflow


def build_runtime(mode: str | None = None):
    settings = Settings.load(mode=mode)
    tools, executor = build_tool_registry(settings)
    provider = MockProvider(tools) if settings.mode == "mock" else OpenAIAgentsProvider(
        settings.model, settings.api_key_env, tools
    )
    store = RunStore(settings.run_root / "runs.sqlite3")
    return settings, tools, executor, store, CompetitionWorkflow(settings, provider, tools, store)


def demo_objective(settings: Settings, scenario: str) -> tuple[UserObjective, RunBudget]:
    fixture = settings.project_root / "examples/toy_data"
    manifest = fixture / ("invalid_manifest.jsonl" if scenario == "invalid-split" else "manifest.jsonl")
    objective = UserObjective(
        text="Inspect toy audio metadata, propose a matched experiment, independently review it, and score saved toy predictions.",
        task_kind="analysis",
        execute_training=scenario == "unauthorized-training",
        manifest_path=str(manifest),
        reference_path=str(fixture / "references.json"),
        prediction_path=str(fixture / "predictions.json"),
        metadata={
            "scorer": "toy",
            "force_revision": scenario in {"happy", "revision"},
            "estimated_gpu_hours": 1.0 if scenario == "unauthorized-training" else 0.0,
        },
    )
    budget = RunBudget(
        training_authorized=False,
        max_gpu_hours=0.0,
        max_training_runs=0,
        max_wall_seconds_per_job=30,
        max_revision_attempts=2,
    )
    return objective, budget


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="audio-agents")
    root.add_argument("--mode", choices=["mock", "real"], default=None)
    commands = root.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Run the CPU-only mock workflow")
    demo.add_argument("--scenario", choices=["happy", "revision", "invalid-split", "unauthorized-training"], default="happy")

    run = commands.add_parser("run", help="Run an objective")
    run.add_argument("--objective", required=True)
    run.add_argument("--task-kind", default="analysis")
    run.add_argument("--manifest")
    run.add_argument("--references")
    run.add_argument("--predictions")
    run.add_argument("--execute-training", action="store_true")
    run.add_argument("--authorize-training", action="store_true")
    run.add_argument("--live-execution", action="store_true", help="Actually launch an authorized allowlisted job")
    run.add_argument("--max-gpu-hours", type=float, default=0.0)
    run.add_argument("--max-training-runs", type=int, default=0)
    run.add_argument("--timeout", type=int, default=1800)

    inspect = commands.add_parser("inspect", help="Inspect a persisted run")
    inspect.add_argument("run_id", nargs="?")
    commands.add_parser("list", help="List persisted runs")
    resume = commands.add_parser("resume", help="Resume a non-terminal persisted run")
    resume.add_argument("run_id")
    cancel = commands.add_parser("cancel", help="Cancel a running managed process")
    cancel.add_argument("run_id")
    serve = commands.add_parser("serve", help="Serve the experiment control-room API and built frontend")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    return root


async def async_main(args: argparse.Namespace) -> int:
    if args.command == "serve":
        from .control_room.server import serve

        serve(args.host, args.port, Settings.load(mode=args.mode or "mock"))
        return 0
    settings, tools, executor, store, workflow = build_runtime(args.mode)
    if args.command == "demo":
        objective, budget = demo_objective(settings, args.scenario)
        result = await workflow.run(objective, budget)
        print(result.to_json())
        expected_block = args.scenario in {"invalid-split", "unauthorized-training"}
        return 0 if (result.status == "blocked") == expected_block else 2
    if args.command == "run":
        objective = UserObjective(
            text=args.objective,
            task_kind=args.task_kind,
            execute_training=args.execute_training,
            manifest_path=args.manifest,
            reference_path=args.references,
            prediction_path=args.predictions,
            metadata={"live_execution": args.live_execution},
        )
        budget = RunBudget(
            training_authorized=args.authorize_training,
            max_gpu_hours=args.max_gpu_hours,
            max_training_runs=args.max_training_runs,
            max_wall_seconds_per_job=args.timeout,
            max_revision_attempts=settings.max_revision_attempts,
        )
        result = await workflow.run(objective, budget)
        print(result.to_json())
        return 0
    if args.command == "inspect":
        if args.run_id:
            print(json.dumps(store.get_run(args.run_id), indent=2, sort_keys=True))
        else:
            print(json.dumps(store.list_runs(), indent=2, sort_keys=True))
        return 0
    if args.command == "list":
        print(json.dumps(store.list_runs(), indent=2, sort_keys=True))
        return 0
    if args.command == "resume":
        saved = store.get_run(args.run_id)
        result = await workflow.run(
            UserObjective(**saved["objective"]),
            RunBudget(**saved["budget"]),
            run_id=args.run_id,
        )
        print(result.to_json())
        return 0
    if args.command == "cancel":
        cancelled = executor.cancel(args.run_id)
        print(json.dumps({"run_id": args.run_id, "cancelled": cancelled}))
        return 0 if cancelled else 1
    return 2


def main() -> None:
    raise SystemExit(asyncio.run(async_main(parser().parse_args())))
