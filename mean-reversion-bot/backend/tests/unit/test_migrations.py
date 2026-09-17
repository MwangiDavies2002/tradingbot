import os
from pathlib import Path
import subprocess
import sys


def test_migration_builds_schema_without_drift(tmp_path):
    env = dict(os.environ, DATABASE_URL="sqlite+aiosqlite:///" + (tmp_path / "migration.db").as_posix())
    backend = Path(__file__).resolve().parents[2]
    for arguments in (["upgrade", "head"], ["upgrade", "head"], ["check"]):
        result = subprocess.run([sys.executable, "-m", "alembic", *arguments],
                                cwd=backend, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
