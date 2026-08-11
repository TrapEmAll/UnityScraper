"""Compatibility wrapper for the package-owned external tool catalog."""

from __future__ import annotations

from unityscraper.domains.tools.catalog import (
    TOOLS,
    ToolCatalog,
    ToolDefinition,
    ToolOperation,
    operation_for,
    platform_key,
)

__all__ = [
    "TOOLS",
    "ToolCatalog",
    "ToolDefinition",
    "ToolOperation",
    "operation_for",
    "platform_key",
]
