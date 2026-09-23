import os
from pathlib import Path
import subprocess
import sys
import sqlite3
import pytest


def test_migration_builds_schema_without_drift(tmp_path):
    env = dict(os.environ, DATABASE_URL="sqlite+aiosqlite:///" + (tmp_path / "migration.db").as_posix())
    backend = Path(__file__).resolve().parents[2]
    for arguments in (["upgrade", "head"], ["upgrade", "head"], ["check"]):
        result = subprocess.run([sys.executable, "-m", "alembic", *arguments],
                                cwd=backend, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr

    # Verify the migrated schema, not only create_all's equivalent guards.
    with sqlite3.connect(tmp_path / "migration.db") as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0003_instrument_catalog"
        db.execute("INSERT INTO research_families VALUES (?, ?, ?, ?, ?, ?)",
                   ("a" * 32, "retained", "hypothesis", '["a"]', "2026-09-23", "operator"))
        db.commit()
        for statement in ("UPDATE research_families SET name='changed'", "DELETE FROM research_families"):
            with pytest.raises(sqlite3.DatabaseError, match="append-only"):
                db.execute(statement)
            db.rollback()
        assert db.execute("SELECT name FROM research_families").fetchone()[0] == "retained"
        db.execute("INSERT INTO instrument_revisions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   ("b" * 64, "TEST", "TEST", "TEST", "v1", "{}", "2026-09-23", "admin"))
        db.commit()
        for statement in ("UPDATE instrument_revisions SET revision='changed'", "DELETE FROM instrument_revisions"):
            with pytest.raises(sqlite3.DatabaseError, match="append-only"):
                db.execute(statement)
            db.rollback()
        assert db.execute("SELECT revision FROM instrument_revisions").fetchone()[0] == "v1"
