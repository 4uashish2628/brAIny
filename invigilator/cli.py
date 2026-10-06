"""Command-line entry point.

    python -m invigilator check tasks/                  check every task's verifier
    python -m invigilator run tasks/ --trials 3         run an LLM agent on every task
    python -m invigilator run tasks/my-task --model X   run one task with a given model
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from .llm import LLMConfig
from .runner import SandboxError, TrialResult, build_image, run_trial
from .task import Task, TaskError, discover_tasks


def verdict(oracle: TrialResult, noop: TrialResult) -> str:
    if oracle.error or noop.error:
        return "ERROR"
    if not oracle.passed:
        return "BROKEN: reference solution fails the tests"
    if noop.passed:
        return "WEAK: tests pass without any changes"
    return "OK"


def _fmt(result: TrialResult) -> str:
    if result.error:
        return "ERROR"
    return "PASS" if result.passed else "FAIL"


def _print_detail(label: str, text: str) -> None:
    indent = "    " + " " * (len(label) + 3)
    print(f"    [{label}] " + text.replace("\n", "\n" + indent))


def _load_tasks(path: str) -> Optional[list[Task]]:
    try:
        tasks = discover_tasks(Path(path))
    except TaskError as e:
        print(f"error: {e}", file=sys.stderr)
        return None
    if not tasks:
        print(f"no tasks found in {path}", file=sys.stderr)
        return None
    return tasks


def cmd_check(args: argparse.Namespace) -> int:
    tasks = _load_tasks(args.path)
    if tasks is None:
        return 2

    width = max(len(t.name) for t in tasks) + 2
    print(f"{'TASK':<{width}}{'ORACLE':<9}{'NO-OP':<9}{'TIME':<8}VERDICT")

    all_ok = True
    for task in tasks:
        oracle = run_trial(task, "oracle")
        noop = run_trial(task, "noop")
        v = verdict(oracle, noop)
        elapsed = f"{oracle.duration + noop.duration:.1f}s"
        print(f"{task.name:<{width}}{_fmt(oracle):<9}{_fmt(noop):<9}{elapsed:<8}{v}")

        if v != "OK":
            all_ok = False
        if v != "OK" or args.verbose:
            for r in (oracle, noop):
                if r.solution_output:
                    _print_detail(f"{r.mode} solution", r.solution_output)
                _print_detail(f"{r.mode} tests", r.error or r.test_output or "(no output)")

    return 0 if all_ok else 1


def cmd_run(args: argparse.Namespace) -> int:
    tasks = _load_tasks(args.path)
    if tasks is None:
        return 2
    llm = LLMConfig.from_env(model=args.model, base_url=args.base_url)

    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", llm.model)
    run_dir = Path(args.out) / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}"
    print(f"model: {llm.model} @ {llm.base_url}")
    print(f"{len(tasks)} task(s) x {args.trials} trial(s), {args.parallel} at a time -> {run_dir}\n", flush=True)

    # Build every image up front so parallel trials don't race to build the same one.
    for task in tasks:
        try:
            build_image(task)
        except SandboxError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2

    jobs = [(task, n) for task in tasks for n in range(1, args.trials + 1)]
    results: dict[str, list[TrialResult]] = defaultdict(list)
    print_lock = threading.Lock()

    def job(task: Task, n: int) -> TrialResult:
        result = run_trial(task, "agent", llm=llm, max_steps=args.max_steps)
        out = run_dir / task.name / f"trial-{n}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"model": llm.model, "instruction": task.instruction, **asdict(result)}, indent=2))
        return result

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {pool.submit(job, task, n): (task, n) for task, n in jobs}
        for future in as_completed(futures):
            task, n = futures[future]
            result = future.result()
            results[task.name].append(result)
            traj = result.trajectory or {}
            status = "ERROR" if result.error else ("PASS" if result.passed else "FAIL")
            detail = result.error or traj.get("error") or traj.get("stop_reason", "")
            with print_lock:
                print(f"  {task.name} #{n}: {status:<5} {len(traj.get('steps', [])):>2} steps  "
                      f"{result.duration:6.1f}s  ({detail})", flush=True)

    width = max(len(t.name) for t in tasks) + 2
    print(f"\n{'TASK':<{width}}{'PASSED':<9}{'RATE':<7}{'STEPS':<7}{'TIME':<8}")
    summary = {}
    for task in tasks:
        rs = results[task.name]
        passed = sum(r.passed for r in rs)
        steps = sum(len((r.trajectory or {}).get("steps", [])) for r in rs) / len(rs)
        secs = sum(r.duration for r in rs) / len(rs)
        print(f"{task.name:<{width}}{f'{passed}/{len(rs)}':<9}{passed / len(rs):<7.0%}{steps:<7.1f}{secs:<8.1f}")
        summary[task.name] = {"trials": len(rs), "passed": passed, "avg_steps": steps, "avg_seconds": secs}

    total = sum(v["passed"] for v in summary.values())
    print(f"\noverall: {total}/{len(jobs)} trials passed ({total / len(jobs):.0%})")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text(json.dumps({"model": llm.model, "tasks": summary}, indent=2))
    print(f"trajectories saved to {run_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="invigilator", description="Sandboxed agent evaluation harness.")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="sanity-check task verifiers (oracle must pass, no-op must fail)")
    check.add_argument("path", help="a task folder, or a folder containing task folders")
    check.add_argument("-v", "--verbose", action="store_true", help="show test output for every trial")
    check.set_defaults(func=cmd_check)

    run = sub.add_parser("run", help="run an LLM agent on tasks and grade it")
    run.add_argument("path", help="a task folder, or a folder containing task folders")
    run.add_argument("--model", help="model name (default: $INVIG_MODEL or qwen2.5-coder:7b)")
    run.add_argument("--base-url", help="OpenAI-compatible API URL (default: $INVIG_BASE_URL or local Ollama)")
    run.add_argument("--trials", type=int, default=1, help="trials per task (default: 1)")
    run.add_argument("--parallel", type=int, default=1, help="trials to run at once (default: 1)")
    run.add_argument("--max-steps", type=int, default=30, help="max model turns per trial (default: 30)")
    run.add_argument("--out", default="runs", help="where to save trajectories (default: runs/)")
    run.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)
