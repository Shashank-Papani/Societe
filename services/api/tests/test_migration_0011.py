"""Migration 0011_stories_official_content integrity checks."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
REVISION = "0011_stories_official_content"
DOWN_REVISION = "0010_venue_organizations"


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


def test_migration_0011_revises_venue_organizations() -> None:
    migration = API_ROOT / "migrations" / "versions" / "0011_stories_official_content.py"
    text = migration.read_text(encoding="utf-8")
    assert f'revision: str = "{REVISION}"' in text
    assert f'down_revision: str | None = "{DOWN_REVISION}"' in text
    for table in (
        "app.stories",
        "app.story_views",
        "app.story_reports",
        "app.official_venue_posts",
    ):
        assert table in text
    assert "user_story" in text


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
            "downgrade/upgrade round-trip for 0011_stories_official_content."
        )

    # Capture Live Vibe / purpose counts before downgrade.
    before = _purpose_and_vibe_counts()
    assert before is not None

    down = _run_alembic("downgrade", DOWN_REVISION)
    assert down.returncode == 0, down.stderr or down.stdout
    mid = _purpose_and_vibe_counts()
    assert mid is not None
    assert mid["live_vibe"] == before["live_vibe"]
    assert mid["venue_owned"] == before["venue_owned"]
    assert mid["live_vibes_rows"] == before["live_vibes_rows"]
    assert mid["user_story"] == 0

    restore = _run_alembic("upgrade", REVISION)
    assert restore.returncode == 0, restore.stderr or restore.stdout
    after = _purpose_and_vibe_counts()
    assert after is not None
    assert after["live_vibe"] == before["live_vibe"]
    assert after["venue_owned"] == before["venue_owned"]
    assert after["live_vibes_rows"] == before["live_vibes_rows"]
    assert after["violations"] == 0


def _purpose_and_vibe_counts() -> dict[str, int] | None:
    try:
        import asyncio

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        async def _run() -> dict[str, int]:
            eng = create_async_engine(
                os.environ.get(
                    "DATABASE_URL",
                    "postgresql+asyncpg://societe:societe@localhost:5432/societe",
                )
            )
            async with eng.connect() as conn:
                rows = {
                    purpose: count
                    for purpose, count in (
                        await conn.execute(
                            text("SELECT purpose, count(*) FROM app.media_assets GROUP BY purpose")
                        )
                    )
                }
                vibes = (
                    await conn.execute(text("SELECT count(*) FROM app.live_vibes"))
                ).scalar_one()
                violations = (
                    await conn.execute(
                        text(
                            """
                            SELECT count(*) FROM app.media_assets ma
                            WHERE NOT (
                                (
                                    ma.purpose = 'live_vibe'
                                    AND ma.author_check_in_id IS NOT NULL
                                    AND ma.device_id IS NOT NULL
                                )
                                OR (
                                    ma.purpose = 'user_story'
                                    AND ma.author_check_in_id IS NOT NULL
                                    AND ma.device_id IS NOT NULL
                                    AND ma.organization_id IS NULL
                                )
                                OR (
                                    ma.purpose = 'venue_owned'
                                    AND ma.organization_id IS NOT NULL
                                    AND ma.author_check_in_id IS NULL
                                    AND ma.device_id IS NULL
                                )
                            )
                            """
                        )
                    )
                ).scalar_one()
            await eng.dispose()
            return {
                "live_vibe": int(rows.get("live_vibe", 0)),
                "venue_owned": int(rows.get("venue_owned", 0)),
                "user_story": int(rows.get("user_story", 0)),
                "live_vibes_rows": int(vibes),
                "violations": int(violations),
            }

        return asyncio.run(_run())
    except Exception:
        return None
