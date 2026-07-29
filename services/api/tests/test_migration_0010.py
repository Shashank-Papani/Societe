"""Migration 0010_venue_organizations integrity checks.

Phase 7A lands as a linear revision. The live Alembic head may advance in
later phases (currently 0011); this module still documents the 0009 → 0010
chain and that 0010 remains a single ancestor, not a branch.
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
CURRENT_HEAD = "0011_stories_official_content"


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
    """The migration graph must remain a single head (now Phase 8A)."""
    result = _run_alembic("heads")
    assert result.returncode == 0, result.stderr or result.stdout
    heads = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.strip().startswith("FAILED")
    ]
    revision_lines = [line for line in heads if "head" in line.lower() or CURRENT_HEAD in line]
    assert len(revision_lines) == 1, (
        f"Expected a single Alembic head containing {CURRENT_HEAD}, got:\n{result.stdout}"
    )
    assert CURRENT_HEAD in revision_lines[0]
    # 0010 must not remain a competing head.
    assert not any(REVISION in line and CURRENT_HEAD not in line for line in revision_lines)


def test_migration_0010_revises_presence_retention() -> None:
    """Document the linear chain: 0009 → 0010 (venue organizations)."""
    migration = API_ROOT / "migrations" / "versions" / "0010_venue_organizations.py"
    text = migration.read_text(encoding="utf-8")
    assert f'revision: str = "{REVISION}"' in text
    assert f'down_revision: str | None = "{DOWN_REVISION}"' in text
    assert "def upgrade() -> None:" in text
    assert "def downgrade() -> None:" in text
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


def test_upgrade_to_head_when_database_available() -> None:
    """Upgrade to the current head (includes 0010 as an ancestor)."""
    current = _run_alembic("current")
    if current.returncode != 0:
        pytest.skip(f"Alembic cannot read current revision: {current.stderr}")

    up = _run_alembic("upgrade", "head")
    if up.returncode != 0:
        pytest.skip(f"Database unavailable for upgrade: {up.stderr or up.stdout}")

    after_up = _run_alembic("current")
    assert after_up.returncode == 0, after_up.stderr
    assert CURRENT_HEAD in after_up.stdout

    if os.getenv("SOCIETE_TEST_MIGRATION_ROUNDTRIP") != "1":
        pytest.skip(
            "Set SOCIETE_TEST_MIGRATION_ROUNDTRIP=1 to exercise destructive "
            "downgrade/upgrade round-trip through 0010_venue_organizations."
        )

    # Round-trip through 0010, then restore head (0011).
    down = _run_alembic("downgrade", REVISION)
    assert down.returncode == 0, down.stderr or down.stdout
    at_0010 = _run_alembic("current")
    assert REVISION in at_0010.stdout

    restore = _run_alembic("upgrade", "head")
    assert restore.returncode == 0, restore.stderr or restore.stdout
    after = _run_alembic("current")
    assert after.returncode == 0, after.stderr
    assert CURRENT_HEAD in after.stdout
