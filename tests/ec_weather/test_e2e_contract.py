"""Contract pin: the e2e harness's role list must match CARD_ROLES.

The T3 e2e harness runs in dependency-free Node and cannot import
``websocket.py``'s ``CARD_ROLES`` — the card-entity-role contract. Instead it
carries a copy at ``.github/e2e/required-roles.json``. This test is the pin
that keeps that copy honest: every role the server resolves must appear in the
harness file with the same (domain, unique_id slug), and vice versa. If a role
is added/removed/re-domained in ``CARD_ROLES`` without updating the harness
copy, this fails — the same parity discipline the strings/translation tests
use, applied across the Python/Node boundary.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import ec_weather
from ec_weather.websocket import CARD_ROLES


def _find_required_roles_file() -> Path:
    """Locate required-roles.json across both repo layouts.

    Local monorepo: ``<pkg>/.github/e2e/required-roles.json``.
    Public HACS repo: ``<repo-root>/.github/e2e/required-roles.json`` while the
    package lives at ``custom_components/ec_weather``. Walk up from the package
    directory until a ``.github/e2e`` copy is found.
    """
    start = Path(ec_weather.__file__).resolve().parent
    for directory in (start, *start.parents):
        candidate = directory / ".github" / "e2e" / "required-roles.json"
        if candidate.is_file():
            return candidate
    raise AssertionError(
        "required-roles.json not found in any .github/e2e above "
        f"{start}"
    )


def _load_required_roles() -> dict:
    return json.loads(_find_required_roles_file().read_text(encoding="utf-8"))


def test_required_roles_keys_match_card_roles() -> None:
    """The harness role set is exactly the server's CARD_ROLES set."""
    required = _load_required_roles()
    assert set(required) == set(CARD_ROLES), (
        "e2e required-roles.json roles differ from CARD_ROLES: "
        f"only in harness={set(required) - set(CARD_ROLES)}, "
        f"only in CARD_ROLES={set(CARD_ROLES) - set(required)}"
    )


@pytest.mark.parametrize("role", sorted(CARD_ROLES))
def test_required_roles_domain_and_slug_match(role: str) -> None:
    """Each harness role pins the same (domain, unique_id slug) as the server."""
    required = _load_required_roles()
    domain, slug = CARD_ROLES[role]
    entry = required[role]
    assert entry["domain"] == domain, (
        f"role {role!r}: harness domain {entry['domain']!r} != "
        f"CARD_ROLES domain {domain!r}"
    )
    assert entry["slug"] == slug, (
        f"role {role!r}: harness slug {entry['slug']!r} != "
        f"CARD_ROLES slug {slug!r}"
    )
