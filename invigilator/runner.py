"""Running tasks inside isolated Docker sandboxes.

Every trial is: fresh container -> something works on the task -> tests run.
The "something" depends on the mode:

    oracle  the reference solution.sh   (verifier check: should PASS)
    noop    nothing at all              (verifier check: should FAIL)
    agent   an LLM running shell commands
"""

from __future__ import annotations

import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .agent import run_agent
from .llm import LLMConfig
from .task import Task

IMAGE_PREFIX = "invigilator-task"

# Where things get copied inside the container. Tests are copied only after
# the solution/agent has finished, so they can't be read or tampered with early.
SOLUTION_PATH = "/tmp/invig_solution.sh"
TESTS_PATH = "/tmp/invig_tests"


class SandboxError(Exception):
    """Raised when Docker itself fails (as opposed to a task failing)."""


@dataclass
class Limits:
    memory: str = "512m"
    cpus: str = "1"
    pids: int = 256
    step_timeout: int = 120  # seconds, per solution/test run
    network: bool = False


@dataclass
class TrialResult:
    task: str
    mode: str
    passed: bool
    test_output: str
    duration: float
    error: Optional[str] = None
    solution_output: str = ""
    trajectory: Optional[dict] = None


def _docker(args: list[str], timeout: Optional[int] = None, merge_stderr: bool = False) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["docker", *args],
            stdout=subprocess.PIPE,
            # Merging keeps stdout and stderr interleaved in their real order.
            stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        raise SandboxError("docker CLI not found - is Docker installed?")


def build_image(task: Task) -> str:
    """Build the task's environment image and return its tag. Docker caches layers."""
    tag = f"{IMAGE_PREFIX}-{task.name}"
    proc = _docker(["build", "-q", "-t", tag, str(task.environment_dir)], timeout=900)
    if proc.returncode != 0:
        raise SandboxError(f"failed to build image for '{task.name}':\n{proc.stderr.strip()}")
    return tag


class Sandbox:
    """A throwaway container with resource limits and (by default) no network.

    Use as a context manager; the container is always removed on exit.
    The image's own CMD must keep the container alive (e.g. `sleep infinity`).
    """

    def __init__(self, image: str, limits: Limits):
        self.image = image
        self.limits = limits
        self.name = f"invig-{uuid.uuid4().hex[:10]}"

    def __enter__(self) -> Sandbox:
        args = [
            "run", "-d",
            "--name", self.name,
            "--init",
            "--memory", self.limits.memory,
            "--cpus", self.limits.cpus,
            "--pids-limit", str(self.limits.pids),
        ]
        if not self.limits.network:
            args += ["--network", "none"]
        proc = _docker([*args, self.image], timeout=60)
        if proc.returncode != 0:
            raise SandboxError(f"failed to start container:\n{proc.stderr.strip()}")
        time.sleep(0.5)  # let the image's startup processes come up
        return self

    def __exit__(self, *exc) -> None:
        _docker(["rm", "-f", self.name], timeout=60)

    def copy_in(self, src: Path, dest: str) -> None:
        proc = _docker(["cp", str(src), f"{self.name}:{dest}"], timeout=60)
        if proc.returncode != 0:
            raise SandboxError(f"failed to copy {src} into sandbox:\n{proc.stderr.strip()}")

    def exec(self, command: list[str], timeout: int) -> tuple[int, str]:
        """Run a command in the sandbox. Returns (exit_code, combined output)."""
        try:
            proc = _docker(["exec", self.name, *command], timeout=timeout, merge_stderr=True)
        except subprocess.TimeoutExpired:
            return 124, f"[invigilator] command timed out after {timeout}s"
        return proc.returncode, proc.stdout


def run_trial(
    task: Task,
    mode: str,
    limits: Optional[Limits] = None,
    llm: Optional[LLMConfig] = None,
    max_steps: int = 30,
) -> TrialResult:
    if mode not in ("oracle", "noop", "agent"):
        raise ValueError(f"unknown mode: {mode}")
    if mode == "agent" and llm is None:
        raise ValueError("agent mode needs an LLMConfig")
    limits = limits or Limits()
    start = time.monotonic()

    solution_output = ""
    trajectory = None
    try:
        image = build_image(task)
        with Sandbox(image, limits) as sandbox:
            if mode == "oracle":
                # A non-zero exit here isn't fatal on its own: the tests decide pass/fail.
                sandbox.copy_in(task.solution_file, SOLUTION_PATH)
                _, solution_output = sandbox.exec(["sh", SOLUTION_PATH], timeout=limits.step_timeout)
            elif mode == "agent":
                # Tests are graded even if the agent errored or ran out of steps:
                # it may have solved the task without calling finish.
                trajectory = run_agent(sandbox, task.instruction, llm, max_steps=max_steps).to_dict()

            sandbox.copy_in(task.tests_dir, TESTS_PATH)
            code, test_output = sandbox.exec(["sh", f"{TESTS_PATH}/run_tests.sh"], timeout=limits.step_timeout)
    except SandboxError as e:
        return TrialResult(task.name, mode, False, "", time.monotonic() - start, error=str(e))

    return TrialResult(
        task=task.name,
        mode=mode,
        passed=code == 0,
        test_output=test_output.strip(),
        duration=time.monotonic() - start,
        solution_output=solution_output.strip(),
        trajectory=trajectory,
    )
