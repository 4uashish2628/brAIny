"""Command-line entry point.

    python -m invigilator check tasks/                  check every task's verifier
    python -m invigilator run tasks/ --trials 3         run an LLM agent on every task
    python -m invigilator run tasks/my-task --model X   run one task with a given model
    python -m invigilator cleanup                       remove leftover sandboxes
    python -m invigilator serve                         API + dashboard (needs requirements-server.txt)
    python -m invigilator worker --concurrency 4        run queued trials
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Optional

from .llm import LLMConfig
from .runner import TrialResult, run_trial
from .sandbox import Limits, SandboxError, build_image, remove_containers, safe_parallelism
from .task import Task, TaskError, discover_tasks


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


def _limits(args: argparse.Namespace) -> Limits:
    return Limits(
        memory_mb=args.memory_mb,
        cpus=args.cpus,
        disk_mb=args.disk_mb,
        trial_timeout=args.trial_timeout,
    )


def _prepare(tasks: list[Task], limits: Limits, requested: int) -> Optional[int]:
    """Build images up front (so parallel trials don't race to build the same
    one) and cap parallelism to what Docker can hold. Returns the parallelism."""
    for task in tasks:
        try:
            build_image(task)
        except SandboxError as e:
            print(f"error: {e}", file=sys.stderr)
            return None
    parallel = safe_parallelism(requested, limits)
    if parallel < requested:
        print(f"note: running {parallel} at a time instead of {requested}; more would exceed "
              f"Docker's memory/CPU at {limits.memory_mb} MB and {limits.cpus:g} CPU per sandbox", flush=True)
    return parallel


def _run_jobs(jobs: list, fn: Callable, parallel: int, run_id: str, on_result: Callable) -> None:
    """Run jobs in a thread pool. On Ctrl+C (or SIGTERM), cancel pending jobs,
    remove this run's sandboxes and exit right away instead of leaking containers."""
    pool = ThreadPoolExecutor(max_workers=parallel)
    try:
        futures = {pool.submit(fn, *job): job for job in jobs}
        for future in as_completed(futures):
            on_result(futures[future], future.result())
        pool.shutdown()
    except KeyboardInterrupt:
        print("\ninterrupted - cleaning up sandboxes...", file=sys.stderr, flush=True)
        pool.shutdown(wait=False, cancel_futures=True)
        removed = remove_containers(run_id)
        print(f"removed {removed} container(s)", file=sys.stderr, flush=True)
        os._exit(130)  # don't wait for in-flight model calls to return


def _print_detail(label: str, text: str) -> None:
    indent = "    " + " " * (len(label) + 3)
    print(f"    [{label}] " + text.replace("\n", "\n" + indent))


# -- check --------------------------------------------------------------------

def verdict(oracles: list[TrialResult], noop: TrialResult) -> str:
    everything = [*oracles, noop]
    if any(r.error for r in everything):
        return "ERROR"
    limited = next((r for r in everything if r.violation), None)
    if limited:
        return f"LIMIT: {limited.mode} hit a resource limit ({limited.violation})"
    invasive = next((r for r in oracles if r.tampering), None)
    if invasive:
        return f"INVASIVE: reference solution modifies protected paths ({', '.join(invasive.tampering[:3])})"
    passes = sum(r.tests_passed for r in oracles)
    if passes == 0:
        return "BROKEN: reference solution fails the tests"
    if passes < len(oracles):
        return f"FLAKY: reference solution passed only {passes}/{len(oracles)} times"
    if noop.tests_passed:
        return "WEAK: tests pass without any changes"
    return "OK"


def cmd_check(args: argparse.Namespace) -> int:
    tasks = _load_tasks(args.path)
    if tasks is None:
        return 2
    limits = _limits(args)
    parallel = _prepare(tasks, limits, args.parallel)
    if parallel is None:
        return 2

    run_id = uuid.uuid4().hex[:8]
    jobs = [(t, "oracle") for t in tasks for _ in range(args.repeat)] + [(t, "noop") for t in tasks]
    results: dict[str, dict[str, list[TrialResult]]] = defaultdict(lambda: defaultdict(list))

    def job(task: Task, mode: str) -> TrialResult:
        return run_trial(task, mode, limits=limits, run_id=run_id)

    def collect(job_args, result: TrialResult) -> None:
        task, mode = job_args
        results[task.name][mode].append(result)

    print(f"checking {len(tasks)} task(s): oracle x{args.repeat}, no-op x1, {parallel} at a time\n", flush=True)
    _run_jobs(jobs, job, parallel, run_id, collect)

    width = max(len(t.name) for t in tasks) + 2
    print(f"{'TASK':<{width}}{'ORACLE':<9}{'NO-OP':<9}{'TIME':<8}VERDICT")
    all_ok = True
    for task in tasks:
        oracles, noop = results[task.name]["oracle"], results[task.name]["noop"][0]
        v = verdict(oracles, noop)
        passes = sum(r.tests_passed for r in oracles)
        avg = sum(r.duration for r in oracles) / len(oracles)
        noop_status = noop.status if noop.status in ("ERROR", "LIMIT") else ("PASS" if noop.tests_passed else "FAIL")
        print(f"{task.name:<{width}}{f'{passes}/{len(oracles)}':<9}{noop_status:<9}{f'{avg:.1f}s':<8}{v}")

        if v != "OK":
            all_ok = False
        if v != "OK" or args.verbose:
            for r in [*oracles, noop]:
                if r.solution_output:
                    _print_detail(f"{r.mode} solution", r.solution_output)
                _print_detail(f"{r.mode} tests", r.error or r.violation or r.test_output or "(no output)")

    return 0 if all_ok else 1


# -- run ----------------------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> int:
    tasks = _load_tasks(args.path)
    if tasks is None:
        return 2
    limits = _limits(args)
    llm = LLMConfig.from_env(model=args.model, base_url=args.base_url)
    parallel = _prepare(tasks, limits, args.parallel)
    if parallel is None:
        return 2

    run_id = uuid.uuid4().hex[:8]
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", llm.model)
    run_dir = Path(args.out) / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}"
    print(f"model: {llm.model} @ {llm.base_url}")
    print(f"{len(tasks)} task(s) x {args.trials} trial(s), {parallel} at a time -> {run_dir}")
    print(f"limits per trial: {limits.memory_mb} MB RAM, {limits.cpus:g} CPU, {limits.disk_mb} MB disk, "
          f"{limits.pids} processes, {limits.trial_timeout}s\n", flush=True)

    jobs = [(task, n) for task in tasks for n in range(1, args.trials + 1)]
    results: dict[str, list[TrialResult]] = defaultdict(list)
    print_lock = threading.Lock()

    def job(task: Task, n: int) -> TrialResult:
        result = run_trial(task, "agent", limits=limits, llm=llm, max_steps=args.max_steps, run_id=run_id)
        out = run_dir / task.name / f"trial-{n}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(
            {"model": llm.model, "instruction": task.instruction, "status": result.status, **asdict(result)},
            indent=2,
        ))
        return result

    def report(job_args, result: TrialResult) -> None:
        task, n = job_args
        results[task.name].append(result)
        traj = result.trajectory or {}
        if result.tampering:
            detail = "tampered: " + ", ".join(result.tampering[:3])
        else:
            detail = result.error or result.violation or traj.get("error") or traj.get("stop_reason", "")
        with print_lock:
            print(f"  {task.name} #{n}: {result.status:<6} {len(traj.get('steps', [])):>2} steps  "
                  f"{result.duration:6.1f}s  ({detail})", flush=True)

    _run_jobs(jobs, job, parallel, run_id, report)

    width = max(len(t.name) for t in tasks) + 2
    print(f"\n{'TASK':<{width}}{'PASSED':<9}{'RATE':<7}{'STEPS':<7}{'TIME':<8}{'TAMPER':<8}LIMIT")
    summary = {}
    for task in tasks:
        rs = results[task.name]
        passed = sum(r.passed for r in rs)
        tampered = sum(bool(r.tampering) for r in rs)
        limited = sum(bool(r.violation) for r in rs)
        steps = sum(len((r.trajectory or {}).get("steps", [])) for r in rs) / len(rs)
        secs = sum(r.duration for r in rs) / len(rs)
        print(f"{task.name:<{width}}{f'{passed}/{len(rs)}':<9}{passed / len(rs):<7.0%}{steps:<7.1f}"
              f"{secs:<8.1f}{tampered:<8}{limited}")
        summary[task.name] = {"trials": len(rs), "passed": passed, "tampered": tampered,
                              "resource_limited": limited, "avg_steps": steps, "avg_seconds": secs}

    total = sum(v["passed"] for v in summary.values())
    print(f"\noverall: {total}/{len(jobs)} trials passed ({total / len(jobs):.0%})")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text(json.dumps(
        {"model": llm.model, "limits": asdict(limits), "tasks": summary}, indent=2))
    print(f"trajectories saved to {run_dir}")
    return 0


# -- cleanup ------------------------------------------------------------------

def cmd_cleanup(args: argparse.Namespace) -> int:
    print(f"removed {remove_containers()} invigilator container(s)")
    return 0


# -- server -------------------------------------------------------------------

def _server_deps_missing(e: ImportError) -> int:
    print(f"error: {e.name} is not installed. The server needs: pip install -r requirements-server.txt",
          file=sys.stderr)
    return 2


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        from .server.api import serve
    except ImportError as e:
        return _server_deps_missing(e)
    serve(args.host, args.port)
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    try:
        from .server.worker import run_worker
    except ImportError as e:
        return _server_deps_missing(e)
    run_worker(args.concurrency)
    return 0


def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGTERM, _raise_interrupt)  # `kill` cleans up like Ctrl+C does

    parser = argparse.ArgumentParser(prog="invigilator", description="Sandboxed agent evaluation harness.")
    sub = parser.add_subparsers(dest="command", required=True)

    limits = argparse.ArgumentParser(add_help=False)
    group = limits.add_argument_group("per-trial resource limits")
    group.add_argument("--memory-mb", type=int, default=Limits.memory_mb, help="RAM, no swap (default: %(default)s)")
    group.add_argument("--cpus", type=float, default=Limits.cpus, help="CPU cores (default: %(default)s)")
    group.add_argument("--disk-mb", type=int, default=Limits.disk_mb, help="disk writes (default: %(default)s)")
    group.add_argument("--trial-timeout", type=int, default=Limits.trial_timeout,
                       help="seconds per trial, wall clock (default: %(default)s)")
    group.add_argument("--parallel", type=int, default=1,
                       help="trials at once, capped to what Docker can hold (default: 1)")

    check = sub.add_parser("check", parents=[limits],
                           help="sanity-check task verifiers: oracle must pass every time, no-op must fail")
    check.add_argument("path", help="a task folder, or a folder containing task folders")
    check.add_argument("--repeat", type=int, default=3, help="oracle runs per task, to catch flaky tests (default: 3)")
    check.add_argument("-v", "--verbose", action="store_true", help="show test output for every trial")
    check.set_defaults(func=cmd_check)

    run = sub.add_parser("run", parents=[limits], help="run an LLM agent on tasks and grade it")
    run.add_argument("path", help="a task folder, or a folder containing task folders")
    run.add_argument("--model", help="model name (default: $INVIG_MODEL or qwen2.5-coder:7b)")
    run.add_argument("--base-url", help="OpenAI-compatible API URL (default: $INVIG_BASE_URL or local Ollama)")
    run.add_argument("--trials", type=int, default=1, help="trials per task (default: 1)")
    run.add_argument("--max-steps", type=int, default=30, help="max commands per trial (default: 30)")
    run.add_argument("--out", default="runs", help="where to save trajectories (default: runs/)")
    run.set_defaults(func=cmd_run)

    cleanup = sub.add_parser("cleanup", help="remove sandboxes left behind by crashed runs")
    cleanup.set_defaults(func=cmd_cleanup)

    serve = sub.add_parser("serve", help="start the API and dashboard")
    serve.add_argument("--host", default="127.0.0.1", help="default: 127.0.0.1 (there is no auth; keep it local)")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=cmd_serve)

    worker = sub.add_parser("worker", help="run queued trials from the API")
    worker.add_argument("--concurrency", type=int, default=1, help="trials at once, capped to what Docker can hold")
    worker.set_defaults(func=cmd_worker)

    args = parser.parse_args(argv)
    return args.func(args)
