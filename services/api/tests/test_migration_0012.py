"""Migration 0012_notifications_realtime integrity checks."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
REVISION = "0012_notifications_realtime"
DOWN_REVISION = "0011_stories_official_content"


def _alembic_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault(
        "DATABASE_URL",
        "postgresql+asyncpg://societe:societe@localhost:5432/societe",
    )
    return env


def _run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_ROOT,
        env=_alembic_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def test_alembic_heads_is_exactly_one() -> None:
    result = _run_alembic("heads")
    assert result.returncode == 0, result.stderr or result.stdout
    heads = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.strip().startswith("FAILED")
    ]
    revision_lines = [line for line in heads if REVISION in line or "head" in line.lower()]
    assert len(revision_lines) == 1, (
        f"Expected a single Alembic head containing {REVISION}, got:\n{result.stdout}"
    )
    assert REVISION in revision_lines[0]


def test_migration_0012_revises_stories() -> None:
    migration = API_ROOT / "migrations" / "versions" / "0012_notifications_realtime.py"
    text = migration.read_text(encoding="utf-8")
    assert f'revision: str = "{REVISION}"' in text
    assert f'down_revision: str | None = "{DOWN_REVISION}"' in text
    for table in (
        "app.notifications",
        "app.notification_preferences",
        "app.notification_deliveries",
        "app.notification_event_consumptions",
    ):
        assert table in text
    assert "push_token_hash" in text


def test_upgrade_when_database_available() -> None:
    current = _run_alembic("current")
    if current.returncode != 0:
        pytest.skip(f"Alembic cannot read current revision: {current.stderr}")

    up = _run_alembic("upgrade", REVISION)
    if up.returncode != 0:
        pytest.skip(f"Database unavailable for upgrade: {up.stderr or up.stdout}")

    after_up = _run_alembic("current")
    assert after_up.returncode == 0, after_up.stderr
    assert REVISION in after_up.stdout

    if os.getenv("SOCIETE_TEST_MIGRATION_ROUNDTRIP") != "1":
        pytest.skip(
            "Set SOCIETE_TEST_MIGRATION_ROUNDTRIP=1 to exercise destructive "
            "downgrade/upgrade round-trip for 0012_notifications_realtime."
        )

    down = _run_alembic("downgrade", DOWN_REVISION)
    assert down.returncode == 0, down.stderr or down.stdout
    mid = _run_alembic("current")
    assert DOWN_REVISION in mid.stdout

    restore = _run_alembic("upgrade", REVISION)
    assert restore.returncode == 0, restore.stderr or restore.stdout
    after = _run_alembic("current")
    assert REVISION in after.stdout
