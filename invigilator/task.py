"""Loading and validating task folders.

A task is a directory with this layout:

    my-task/
    ├── task.json           optional settings, e.g. {"allowed_paths": ["/usr/local/bin"]}
    ├── instruction.md      what the agent is told to do
    ├── solution.sh         reference ("oracle") solution, written by a human
    ├── environment/        Docker build context; the agent's world
    │   └── Dockerfile
    └── tests/
        └── run_tests.sh    exit 0 = solved, anything else = not solved

Only environment/ is baked into the image. solution.sh and tests/ are copied
into the container later, so the agent never gets to see them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class TaskError(Exception):
    """Raised when a task folder is missing required files."""


@dataclass(frozen=True)
class Task:
    name: str
    path: Path

    @property
    def instruction_file(self) -> Path:
        return self.path / "instruction.md"

    @property
    def solution_file(self) -> Path:
        return self.path / "solution.sh"

    @property
    def environment_dir(self) -> Path:
        return self.path / "environment"

    @property
    def tests_dir(self) -> Path:
        return self.path / "tests"

    @property
    def instruction(self) -> str:
        return self.instruction_file.read_text()

    @property
    def config(self) -> dict:
        path = self.path / "task.json"
        return json.loads(path.read_text()) if path.exists() else {}

    @property
    def allowed_paths(self) -> tuple[str, ...]:
        """Protected paths this task is allowed to modify (e.g. installing a binary)."""
        return tuple(self.config.get("allowed_paths", []))

    @classmethod
    def load(cls, path: Path) -> Task:
        path = path.resolve()
        task = cls(name=path.name, path=path)
        required = [
            task.instruction_file,
            task.solution_file,
            task.environment_dir / "Dockerfile",
            task.tests_dir / "run_tests.sh",
        ]
        missing = [str(p.relative_to(path)) for p in required if not p.exists()]
        if missing:
            raise TaskError(f"task '{task.name}' is missing: {', '.join(missing)}")
        try:
            task.config
        except json.JSONDecodeError as e:
            raise TaskError(f"task '{task.name}' has invalid task.json: {e}")
        return task


def discover_tasks(root: Path) -> list[Task]:
    """Load a single task folder, or every task folder directly under root."""
    root = Path(root)
    if (root / "instruction.md").exists():
        return [Task.load(root)]
    return [
        Task.load(child)
        for child in sorted(root.iterdir())
        if child.is_dir() and (child / "instruction.md").exists()
    ]
