"""AI-assisted grouping of same-event weather alerts (opt-in).

EC frequently publishes several alerts for one weather event (a severe
thunderstorm warning alongside a watch, say). This module asks an LLM — via
HA's native ``ai_task.generate_data`` service, which enforces the output schema
server-side — which alerts describe the same event, then annotates the alert
dicts so the card can group them.

Everything here fails open: any problem (feature off, too few alerts, service
missing, timeout, exception, malformed or invalid response) leaves the alerts
exactly as ``parse_alert_response`` produced them, with no group annotations.
An LLM failure must never fail the coordinator update.

The pure functions are unit-testable without a hass instance; the single async
entry point (:func:`request_alert_groups`) performs the service call and never
raises — every failure collapses to ``None``.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging

from homeassistant.core import HomeAssistant

from ..const import AI_GROUPING_TIMEOUT

_LOGGER = logging.getLogger(__name__)

# Gravity order for promoting a new primary when the LLM's primary expires.
# Mirrors coordinator.alerts._ALERT_TYPE_PRIORITY (kept local to avoid an
# import cycle: alerts imports this module, not the other way around).
ALERT_TYPE_PRIORITY = ["warning", "watch", "advisory", "statement"]

# Fixed mechanical instruction appended after the user-editable judgment part.
# The concrete severity order plus a worked example that deliberately puts the
# LARGER index first counter the ascending-order default small models fall into.
_OUTPUT_FORMAT_INSTRUCTIONS = (
    "Return your answer in the 'groups' field as a list. Each element is one "
    "group, written as a string of that group's alert indexes separated by "
    "commas. In each group, list the most severe alert first: a warning comes "
    "before a watch, a watch before an advisory, an advisory before a "
    "statement. For example, if alert [2] is a severe thunderstorm warning and "
    "alert [0] is a severe thunderstorm watch for the same storm, write the "
    'group as "2,0" — the warning index goes first, even though 2 is the '
    "larger number. Only include a group when it has two or more alerts. Never "
    "place an alert index in more than one group. If no alerts describe the "
    "same event, return an empty list. Output nothing else."
)


def alert_set_hash(alerts: list[dict]) -> str:
    """Stable hash over the sorted (headline, text) pairs of an alert set.

    Order-independent: the same set of alerts in any order hashes the same, so
    the coordinator only calls the LLM when the alert content actually changes.
    """
    pairs = sorted(
        (alert.get("headline") or "", alert.get("text") or "") for alert in alerts
    )
    digest = hashlib.sha256()
    for headline, text in pairs:
        digest.update(headline.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(text.encode("utf-8"))
        digest.update(b"\x01")
    return digest.hexdigest()


def build_alert_list(alerts: list[dict]) -> str:
    """Render the numbered alert list (index, headline, type, full text)."""
    blocks: list[str] = []
    for index, alert in enumerate(alerts):
        headline = alert.get("headline") or ""
        alert_type = alert.get("type") or ""
        text = alert.get("text") or ""
        blocks.append(
            f"[{index}] headline: {headline}\n"
            f"    type: {alert_type}\n"
            f"    text: {text}"
        )
    return "\n\n".join(blocks)


def build_grouping_prompt(alerts: list[dict], instructions: str) -> str:
    """Assemble the full prompt: judgment part + mechanics + numbered list."""
    return (
        f"{instructions}\n\n"
        f"{_OUTPUT_FORMAT_INSTRUCTIONS}\n\n"
        f"Alerts:\n\n{build_alert_list(alerts)}"
    )


def parse_group_strings(raw_groups) -> list[list[int]] | None:
    """Parse the LLM 'groups' payload into a list of index lists.

    Each element is a string like ``"0,1"``; surrounding whitespace is
    tolerated. Returns ``None`` when the payload is not a list, an element is
    not a string, or a token is not an integer (fail open).
    """
    if not isinstance(raw_groups, list):
        return None
    parsed: list[list[int]] = []
    for element in raw_groups:
        if not isinstance(element, str):
            return None
        indexes: list[int] = []
        for token in element.split(","):
            token = token.strip()
            if token == "":
                continue
            try:
                indexes.append(int(token))
            except ValueError:
                return None
        parsed.append(indexes)
    return parsed


def validate_groups(
    groups: list[list[int]] | None, alert_count: int
) -> list[list[int]] | None:
    """Return the validated groups, or ``None`` if any rule is violated.

    Rules (any violation discards the whole verdict): every index is in range
    ``[0, alert_count)``, no index appears in more than one group, and every
    group has at least two members. An empty group list is valid and means
    "nothing to group".
    """
    if groups is None:
        return None
    seen: set[int] = set()
    validated: list[list[int]] = []
    for group in groups:
        if len(group) < 2:
            return None
        for index in group:
            if index < 0 or index >= alert_count:
                return None
            if index in seen:
                return None
            seen.add(index)
        validated.append(group)
    return validated


def annotate_alerts(alerts: list[dict], groups: list[list[int]]) -> list[dict]:
    """Return alert dicts annotated with ``group_id`` / ``is_primary``.

    Only alerts that belong to a multi-member group are annotated; the first
    index in each group is the primary. Alerts in no group are returned
    unchanged (no new keys). The input dicts are not mutated.
    """
    annotated = [dict(alert) for alert in alerts]
    for group_id, group in enumerate(groups):
        for position, index in enumerate(group):
            annotated[index]["group_id"] = group_id
            annotated[index]["is_primary"] = position == 0
    return annotated


def _highest_priority_position(alerts: list[dict], positions: list[int]) -> int:
    """Position of the highest-gravity-type alert; ties break to first in list."""

    def rank(position: int) -> tuple[int, int]:
        alert_type = alerts[position].get("type", "")
        type_rank = (
            ALERT_TYPE_PRIORITY.index(alert_type)
            if alert_type in ALERT_TYPE_PRIORITY
            else len(ALERT_TYPE_PRIORITY)
        )
        return (type_rank, position)

    return min(positions, key=rank)


def renormalize_grouping(alerts: list[dict]) -> list[dict]:
    """Re-validate group annotations after pruning expired alerts (pure).

    Once expired alerts are removed a group may have fewer than two surviving
    members — strip its annotations from the survivors. If a group's primary
    expired but two or more members survive, promote the highest-gravity-type
    survivor (warning > watch > advisory > statement; tie → first in list) to
    ``is_primary``. Returns a new list; the input dicts are not mutated.
    """
    result = [dict(alert) for alert in alerts]

    members_by_group: dict[int, list[int]] = {}
    for position, alert in enumerate(result):
        group_id = alert.get("group_id")
        if group_id is None:
            continue
        members_by_group.setdefault(group_id, []).append(position)

    for positions in members_by_group.values():
        if len(positions) < 2:
            # Group collapsed — strip annotations from the lone survivor(s).
            for position in positions:
                result[position].pop("group_id", None)
                result[position].pop("is_primary", None)
            continue
        # Ensure exactly one primary survives; promote by gravity if the
        # original primary expired.
        if not any(result[position].get("is_primary") for position in positions):
            promoted = _highest_priority_position(result, positions)
            result[promoted]["is_primary"] = True
        for position in positions:
            result[position].setdefault("is_primary", False)
    return result


async def request_alert_groups(
    hass: HomeAssistant,
    alerts: list[dict],
    instructions: str,
    entity_id: str | None = None,
) -> list[list[int]] | None:
    """Ask the AI Task service which alerts describe the same event.

    Returns validated groups (a list of index lists, possibly empty) on
    success, or ``None`` on any fail-open path: the service is missing, the
    call times out or raises, or the response is malformed/invalid. Never
    raises.
    """
    if not hass.services.has_service("ai_task", "generate_data"):
        return None

    service_data: dict = {
        "task_name": "EC Weather alert grouping",
        "instructions": build_grouping_prompt(alerts, instructions),
        "structure": {
            "groups": {
                "description": (
                    "Groups of alerts that describe the same weather event. "
                    "Each group is a string of comma-separated alert indexes, "
                    "primary first. Only groups with two or more alerts."
                ),
                "required": False,
                "selector": {"text": {"multiple": True}},
            },
        },
    }
    # Only pin an entity when the user configured one; an empty value lets HA
    # use its preferred AI Task entity.
    if entity_id:
        service_data["entity_id"] = entity_id

    try:
        async with asyncio.timeout(AI_GROUPING_TIMEOUT):
            response = await hass.services.async_call(
                "ai_task",
                "generate_data",
                service_data,
                blocking=True,
                return_response=True,
            )
    except TimeoutError:
        _LOGGER.debug("AI alert grouping timed out after %ds", AI_GROUPING_TIMEOUT)
        return None
    except Exception as err:  # noqa: BLE001 — fail open on everything
        _LOGGER.debug("AI alert grouping call failed: %s", err)
        return None

    data = (response or {}).get("data") or {}
    raw_groups = data.get("groups")
    if raw_groups is None:
        # Structured field omitted — a valid "nothing to group" verdict.
        return []
    return validate_groups(parse_group_strings(raw_groups), len(alerts))
