#!/usr/bin/env python3
"""Export OpenAPI from the FastAPI app into packages/contracts/openapi."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "services" / "api"
OUT_JSON = ROOT / "packages" / "contracts" / "openapi" / "openapi.json"
OUT_YAML = ROOT / "packages" / "contracts" / "openapi" / "openapi.yaml"


def _prepare_env() -> None:
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("AUTH_PROVIDER", "local")
    os.environ.setdefault("JWT_SECRET", "openapi-export-secret-not-for-production-012345")
    os.environ.setdefault("OTEL_ENABLED", "false")
    sys.path.insert(0, str(API_ROOT))


def export_schema() -> dict:
    _prepare_env()
    from app.core.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    return app.openapi()


def write_outputs(schema: dict) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        # Minimal YAML dump without PyYAML dependency for Phase 0.
        OUT_YAML.write_text(
            "# Generated from FastAPI. Prefer openapi.json for machine use.\n"
            f"# paths: {', '.join(sorted(schema.get('paths', {})))}\n"
            "openapi: " + json.dumps(schema.get("openapi", "3.1.0")) + "\n"
            "info:\n"
            f"  title: {json.dumps(schema.get('info', {}).get('title', 'Société API'))}\n"
            f"  version: {json.dumps(schema.get('info', {}).get('version', '0.1.0'))}\n"
            "paths: {}\n"
            "# Full document is in openapi.json\n",
            encoding="utf-8",
        )
    else:
        OUT_YAML.write_text(yaml.safe_dump(schema, sort_keys=True), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if committed openapi.json differs from generated output.",
    )
    args = parser.parse_args()
    schema = export_schema()
    rendered = json.dumps(schema, indent=2, sort_keys=True) + "\n"

    if args.check:
        if not OUT_JSON.exists():
            print(f"Missing {OUT_JSON}; run: make openapi", file=sys.stderr)
            return 1
        existing = OUT_JSON.read_text(encoding="utf-8")
        if existing != rendered:
            print("OpenAPI drift detected. Run `make openapi` and commit.", file=sys.stderr)
            return 1
        print("OpenAPI contract is up to date.")
        return 0

    write_outputs(schema)
    print(f"Wrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
