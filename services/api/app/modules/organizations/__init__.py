"""Venue organizations and ownership module."""

from __future__ import annotations

from app.modules.organizations.admin import router as admin_router
from app.modules.organizations.router import router

__all__ = ["admin_router", "router"]
