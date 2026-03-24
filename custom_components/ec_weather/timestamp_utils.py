"""Timestamp utilities for EC Weather.

Centralizes ISO 8601 timestamp operations to avoid fragile string
indexing scattered across modules.
"""

from __future__ import annotations

from datetime import datetime


def hour_from_iso(iso_str: str, default: int = 12) -> int:
    """Extract the hour (0-23) from an ISO 8601 timestamp string.

    Uses datetime.fromisoformat for robust parsing instead of string slicing.
    Returns `default` if parsing fails.
    """
    if not iso_str:
        return default
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.hour
    except (ValueError, TypeError):
        return default
