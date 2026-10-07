"""Running one trial of a task.

Every trial is: fresh sandbox -> something works on the task -> integrity
checks -> tests run. The "something" depends on the mode:

    oracle  the reference solution.sh   (verifier check: should PASS)
    noop    nothing at all              (verifier check: should FAIL)
    agent   an LLM running shell commands
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from .agent import ChatFn, Step, run_agent
from .llm import LLMConfig, chat
from .sandbox import Limits, Sandbox, SandboxError, build_image
from .task import Task

# Tests run as root inside the same container the agent controlled, using the
# container's own tools (sh, python3, wget...). An agent that can't solve a task
# could instead replace those tools with fakes that print the expected answer.
# Any change under these paths is treated as tampering and fails the trial,
# unless the task explicitly allows it in task.json.
PROTECTED_PATHS = (
    "/bin", "/sbin", "/usr/bin", "/usr/sbin", "/usr/local/bin", "/usr/libexec",
    "/lib", "/lib64", "/usr/lib", "/usr/local/lib",
    "/etc/ld.so.preload", "/etc/ld.so.conf", "/etc/ld.so.conf.d",
)
MAX_CHANGES_RECORDED = 200
HARNESS_FILES = "/tmp/.invig_"  # process-group markers written by Sandbox.exec


@dataclass
class TrialResult:
    task: str
    mode: str
    passed: bool                 # tests passed AND no tampering AND no limit hit
    tests_passed: bool
    test_output: str
    duration: float
    error: Optional[str] = None
    violation: Optional[str] = None       # resource limit that ended the trial
    tampering: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    peak_disk_mb: float = 0.0
    solution_output: str = ""
    trajectory: Optional[dict] = None

    @property
    def status(self) -> str:
        if self.error:
            return "ERROR"
        if self.violation:
            return "LIMIT"
        if self.tampering:
            return "TAMPER"
        return "PASS" if self.passed else "FAIL"


def _under(path: str, prefix: str) -> bool:
    prefix = prefix.rstrip("/")
    return path == prefix or path.startswith(prefix + "/")


def leaf_changes(changes: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Drop the harness's own marker files, and "C /dir" entries that only mean
    something inside the directory changed, leaving the files themselves."""
    paths = [p for _, p in changes]
    leaves = [(k, p) for k, p in changes
              if not (k == "C" and any(q.startswith(p.rstrip("/") + "/") for q in paths))]
    return [(k, p) for k, p in leaves if not p.startswith(HARNESS_FILES)]


def find_tampering(changes: list[tuple[str, str]], allowed: tuple[str, ...] = ()) -> list[str]:
    """Return the changes that touch protected paths, as 'KIND path' strings."""
    flagged = []
    for kind, path in leaf_changes(changes):
        if "__pycache__" in path or path.endswith(".pyc"):
            continue  # Python writes bytecode caches next to modules it imports
        if not any(_under(path, p) for p in PROTECTED_PATHS):
            continue
        if any(_under(path, a) for a in allowed):
            continue
        flagged.append(f"{kind} {path}")
    return flagged


def run_trial(
    task: Task,
    mode: str,
    limits: Optional[Limits] = None,
    llm: Optional[LLMConfig] = None,
    max_steps: int = 30,
    run_id: str = "",
    chat_fn: ChatFn = chat,
    on_step: Optional[Callable[[Step], None]] = None,
    owner: str = "",
) -> TrialResult:
    if mode not in ("oracle", "noop", "agent"):
        raise ValueError(f"unknown mode: {mode}")
    if mode == "agent" and llm is None:
        raise ValueError("agent mode needs an LLMConfig")
    limits = limits or Limits()
    start = time.monotonic()

    def failed(error: str) -> TrialResult:
        return TrialResult(task.name, mode, False, False, "", time.monotonic() - start, error=error)

    # A fresh random path per trial, so an agent can't plant fake tests where
    # the real ones are about to be copied.
    tests_path = f"/tmp/invig_tests_{uuid.uuid4().hex}"
    solution_output, trajectory = "", None
    tests_passed, test_output = False, ""

    try:
        image = build_image(task)
        with Sandbox(image, limits, run_id, owner=owner) as sandbox:
            if mode == "oracle":
                # A non-zero exit here isn't fatal on its own: the tests decide pass/fail.
                sandbox.copy_in(task.solution_file, "/tmp/invig_solution.sh")
                _, solution_output = sandbox.exec(["sh", "/tmp/invig_solution.sh"], limits.step_timeout)
            elif mode == "agent":
                # Graded even if the agent errored or ran out of steps: it may
                # have solved the task without calling finish.
                trajectory = run_agent(
                    sandbox, task.instruction, llm,
                    max_steps=max_steps, command_timeout=limits.command_timeout,
                    chat_fn=chat_fn, on_step=on_step,
                ).to_dict()

            # Integrity check before the tests touch anything.
            changes = [] if sandbox.violation else sandbox.diff()
            tampering = find_tampering(changes, task.allowed_paths)
            changed = [f"{k} {p}" for k, p in leaf_changes(changes)][:MAX_CHANGES_RECORDED]

            if not sandbox.violation:
                sandbox.copy_in(task.tests_dir, tests_path)
                code, test_output = sandbox.exec(["sh", f"{tests_path}/run_tests.sh"], limits.step_timeout)
                tests_passed = code == 0
            violation, peak_disk = sandbox.violation, sandbox.peak_disk_mb
    except SandboxError as e:
        return failed(str(e))

    return TrialResult(
        task=task.name,
        mode=mode,
        passed=tests_passed and not tampering and not violation,
        tests_passed=tests_passed,
        test_output=test_output.strip(),
        duration=time.monotonic() - start,
        violation=violation,
        tampering=tampering,
        changed_files=changed,
        peak_disk_mb=round(peak_disk, 1),
        solution_output=solution_output.strip(),
        trajectory=trajectory,
    )
