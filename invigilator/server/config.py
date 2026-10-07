"""Server settings, from environment variables."""

import os
from pathlib import Path

DATABASE_URL = os.environ.get("INVIG_DATABASE_URL", "postgresql://invig:invig@localhost:5432/invigilator")
REDIS_URL = os.environ.get("INVIG_REDIS_URL", "redis://localhost:6379/0")
TASKS_DIR = Path(os.environ.get("INVIG_TASKS_DIR", "tasks")).resolve()
DASHBOARD_DIR = Path(__file__).resolve().parents[2] / "dashboard" / "dist"
