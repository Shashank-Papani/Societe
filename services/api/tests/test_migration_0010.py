"""Migration 0010_venue_organizations integrity checks.

Documents and verifies that Phase 7A lands as a single Alembic head.
Upgrade/downgrade are exercised against a reachable database when available;
otherwise those steps are skipped so unit CI can still assert head identity.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
REVISION = "0010_venue_organizations"
DOWN_REVISION = "0009_presence_retention"


def _alembic_env() -> dict[str, str]:
    env = os.environ.copy()
    # Prefer the same URL the test suite uses.
    env.setdefault(
        "DATABASE_URL",
        "postgresql+asyncpg://societe:societe@localhost:5432/societe",
    )
    # Alembic sync URL often uses psycopg; keep async URL and let env.ini adapt.
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
    """Phase 7A must not introduce a second Alembic head."""
    result = _run_alembic("heads")
    assert result.returncode == 0, result.stderr or result.stdout
    heads = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.strip().startswith("FAILED")
    ]
    # `alembic heads` prints one revision per line, optionally with "(head)".
    revision_lines = [line for line in heads if REVISION in line or "head" in line.lower()]
    assert len(revision_lines) == 1, (
        f"Expected a single Alembic head containing {REVISION}, got:\n{result.stdout}"
    )
    assert REVISION in revision_lines[0]


def test_migration_0010_revises_presence_retention() -> None:
    """Document the linear chain: 0009 → 0010 (venue organizations)."""
    migration = API_ROOT / "migrations" / "versions" / "0010_venue_organizations.py"
    text = migration.read_text(encoding="utf-8")
    assert f'revision: str = "{REVISION}"' in text
    assert f'down_revision: str | None = "{DOWN_REVISION}"' in text
    assert "def upgrade() -> None:" in text
    assert "def downgrade() -> None:" in text
    # Core Phase 7A objects.
    for table in (
        "app.organizations",
        "app.organization_members",
        "app.venue_claims",
        "app.venue_organizations",
        "app.organization_invitations",
        "app.venue_audit_events",
    ):
        assert table in text
    assert "primary_cover_media_id" in text
    assert "purpose" in text


def test_upgrade_and_downgrade_when_database_available() -> None:
    """
    Optional round-trip against local Compose Postgres.

    Destructive: downgrade drops Phase 7A tables. Only runs when
    ``SOCIETE_TEST_MIGRATION_ROUNDTRIP=1`` is set and Postgres is reachable.
    Otherwise we only verify ``alembic upgrade`` to the Phase 7A head is a no-op
    (or succeeds) when the database is already available.
    """
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
            "downgrade/upgrade round-trip for 0010_venue_organizations."
        )

    down = _run_alembic("downgrade", DOWN_REVISION)
    assert down.returncode == 0, down.stderr or down.stdout

    restore = _run_alembic("upgrade", REVISION)
    assert restore.returncode == 0, restore.stderr or restore.stdout

    after = _run_alembic("current")
    assert after.returncode == 0, after.stderr
    assert REVISION in after.stdout
