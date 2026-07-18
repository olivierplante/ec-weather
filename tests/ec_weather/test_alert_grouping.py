"""Tests for AI-assisted alert grouping.

The grouping layer is opt-in and must fail open on everything: any problem
leaves the alerts exactly as ``parse_alert_response`` produced them, with no
group annotations. Every test uses a mocked AI Task service or a patched
entry point — a real LLM is never contacted.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant, SupportsResponse

from ec_weather.const import (
    DEFAULT_AI_GROUPING_INSTRUCTIONS,
    LEGACY_AI_GROUPING_INSTRUCTIONS,
    resolve_ai_grouping_instructions,
)
from ec_weather.coordinator import ECAlertCoordinator
from ec_weather.coordinator.alert_grouping import (
    _OUTPUT_FORMAT_INSTRUCTIONS,
    alert_set_hash,
    annotate_alerts,
    build_alert_list,
    build_grouping_prompt,
    parse_group_strings,
    renormalize_grouping,
    request_alert_groups,
    validate_groups,
)

_BBOX = "44.420,-76.700,46.420,-74.700"
_FETCH = "ec_weather.coordinator.alerts.fetch_json_with_retry"
_REQUEST = "ec_weather.coordinator.alerts.request_alert_groups"


def _alert(headline: str, alert_type: str = "warning", text: str | None = None) -> dict:
    """Build a parsed-alert dict as parse_alert_response would produce."""
    return {
        "headline": headline,
        "type": alert_type,
        "expires": "2099-12-31T23:59:59Z",
        "text": text or f"Text for {headline}.",
    }


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

class TestPromptAssembly:
    def test_alert_list_numbering(self):
        """Each alert is numbered 0..n with headline, type, and full text."""
        alerts = [
            _alert("Severe Thunderstorm Warning", "warning", "Damaging winds."),
            _alert("Severe Thunderstorm Watch", "watch", "Conditions favourable."),
        ]
        listing = build_alert_list(alerts)

        assert "[0]" in listing
        assert "[1]" in listing
        assert "Severe Thunderstorm Warning" in listing
        assert "Severe Thunderstorm Watch" in listing
        assert "warning" in listing
        assert "watch" in listing
        assert "Damaging winds." in listing
        assert "Conditions favourable." in listing

    def test_default_judgment_included(self):
        """The default judgment prompt and mechanical wrapper both appear."""
        alerts = [_alert("A"), _alert("B", "watch")]
        prompt = build_grouping_prompt(alerts, DEFAULT_AI_GROUPING_INSTRUCTIONS)

        assert DEFAULT_AI_GROUPING_INSTRUCTIONS in prompt
        # Mechanical output-format instruction present.
        assert "comma" in prompt.lower()
        # Numbered list present.
        assert "[0]" in prompt and "[1]" in prompt

    def test_custom_judgment_replaces_default(self):
        """A custom judgment string replaces the default entirely."""
        alerts = [_alert("A"), _alert("B", "watch")]
        custom = "CUSTOM JUDGMENT TEXT ONLY."
        prompt = build_grouping_prompt(alerts, custom)

        assert custom in prompt
        assert DEFAULT_AI_GROUPING_INSTRUCTIONS not in prompt

    def test_output_format_has_worked_example_and_empty_list(self):
        """The mechanical format pins the larger-index-first worked example
        and the explicit empty-list instruction (both reached the prompt)."""
        alerts = [_alert("A"), _alert("B", "watch")]
        prompt = build_grouping_prompt(alerts, DEFAULT_AI_GROUPING_INSTRUCTIONS)

        assert '"2,0"' in _OUTPUT_FORMAT_INSTRUCTIONS
        assert '"2,0"' in prompt
        assert "return an empty list" in _OUTPUT_FORMAT_INSTRUCTIONS
        assert "return an empty list" in prompt

    def test_default_last_paragraph_is_severity_order(self):
        """The severity-order rule must stay the LAST paragraph: small models
        obey the most recent instruction, and moving it mid-prompt regressed."""
        last_paragraph = DEFAULT_AI_GROUPING_INSTRUCTIONS.split("\n\n")[-1]

        assert last_paragraph.startswith(
            "When you group alerts, put the most severe one first"
        )
        assert "warning outranks a watch" in last_paragraph


# ---------------------------------------------------------------------------
# Effective-instructions resolution (legacy-default auto-upgrade)
# ---------------------------------------------------------------------------

class TestResolveInstructions:
    """A stored options value that is blank or equals a superseded default
    resolves to the current default; anything customized is returned as-is."""

    def test_none_resolves_to_current_default(self):
        assert (
            resolve_ai_grouping_instructions(None)
            == DEFAULT_AI_GROUPING_INSTRUCTIONS
        )

    def test_empty_string_resolves_to_current_default(self):
        assert (
            resolve_ai_grouping_instructions("")
            == DEFAULT_AI_GROUPING_INSTRUCTIONS
        )

    def test_whitespace_resolves_to_current_default(self):
        assert (
            resolve_ai_grouping_instructions("   \n\t  ")
            == DEFAULT_AI_GROUPING_INSTRUCTIONS
        )

    def test_legacy_default_upgrades_to_current(self):
        assert len(LEGACY_AI_GROUPING_INSTRUCTIONS) >= 1
        for legacy in LEGACY_AI_GROUPING_INSTRUCTIONS:
            assert (
                resolve_ai_grouping_instructions(legacy)
                == DEFAULT_AI_GROUPING_INSTRUCTIONS
            )

    def test_customized_text_returned_unchanged(self):
        # One character different from a legacy default is a customization.
        legacy = LEGACY_AI_GROUPING_INSTRUCTIONS[0]
        customized = legacy + "!"
        assert resolve_ai_grouping_instructions(customized) == customized

    def test_current_default_returned_unchanged(self):
        assert (
            resolve_ai_grouping_instructions(DEFAULT_AI_GROUPING_INSTRUCTIONS)
            == DEFAULT_AI_GROUPING_INSTRUCTIONS
        )


# ---------------------------------------------------------------------------
# Verdict parsing + validation
# ---------------------------------------------------------------------------

class TestVerdictParsing:
    def test_happy_path(self):
        parsed = parse_group_strings(["0,1", "2,3"])
        assert parsed == [[0, 1], [2, 3]]
        assert validate_groups(parsed, 4) == [[0, 1], [2, 3]]

    def test_whitespace_tolerance(self):
        parsed = parse_group_strings([" 0 , 1 ", "2 ,3"])
        assert parsed == [[0, 1], [2, 3]]

    def test_empty_list_is_valid_empty(self):
        assert parse_group_strings([]) == []
        assert validate_groups([], 3) == []

    def test_non_integer_fails_open(self):
        assert parse_group_strings(["0,x"]) is None

    def test_non_list_fails_open(self):
        assert parse_group_strings("0,1") is None
        assert parse_group_strings(None) is None

    def test_non_string_element_fails_open(self):
        assert parse_group_strings([[0, 1]]) is None

    def test_out_of_range_fails_open(self):
        assert validate_groups([[0, 5]], 3) is None

    def test_negative_index_fails_open(self):
        assert validate_groups([[0, -1]], 3) is None

    def test_duplicate_index_across_groups_fails_open(self):
        assert validate_groups([[0, 1], [1, 2]], 3) is None

    def test_single_member_group_fails_open(self):
        assert validate_groups([[0]], 3) is None

    def test_validate_none_input(self):
        assert validate_groups(None, 3) is None


# ---------------------------------------------------------------------------
# Annotation
# ---------------------------------------------------------------------------

class TestAnnotation:
    def test_group_id_and_primary_placement(self):
        alerts = [_alert("A", "watch"), _alert("B", "warning"), _alert("C")]
        # Group indexes 1 (primary) and 0; alert 2 standalone.
        annotated = annotate_alerts(alerts, [[1, 0]])

        assert annotated[1]["group_id"] == 0
        assert annotated[1]["is_primary"] is True
        assert annotated[0]["group_id"] == 0
        assert annotated[0]["is_primary"] is False
        # Standalone alert gets no new keys.
        assert "group_id" not in annotated[2]
        assert "is_primary" not in annotated[2]

    def test_primary_is_first_index(self):
        alerts = [_alert("A"), _alert("B", "watch")]
        annotated = annotate_alerts(alerts, [[1, 0]])
        primaries = [a for a in annotated if a.get("is_primary")]
        assert len(primaries) == 1
        assert primaries[0]["headline"] == "B"

    def test_does_not_mutate_input(self):
        alerts = [_alert("A"), _alert("B")]
        annotate_alerts(alerts, [[0, 1]])
        assert "group_id" not in alerts[0]

    def test_empty_groups_no_annotation(self):
        alerts = [_alert("A"), _alert("B")]
        annotated = annotate_alerts(alerts, [])
        assert all("group_id" not in a for a in annotated)


# ---------------------------------------------------------------------------
# Prune renormalization
# ---------------------------------------------------------------------------

class TestRenormalize:
    def test_group_shrinks_below_two_strips_annotations(self):
        # A group of two where one member did not survive pruning: only the
        # primary is left, so its annotations must be stripped.
        survivors = [
            {"headline": "A", "type": "warning", "expires": "z",
             "text": "t", "group_id": 0, "is_primary": True},
        ]
        result = renormalize_grouping(survivors)
        assert "group_id" not in result[0]
        assert "is_primary" not in result[0]

    def test_primary_expired_promotes_by_type(self):
        # Primary (warning) expired; two survivors remain — the highest
        # priority type (warning > watch) is promoted.
        survivors = [
            {"headline": "Watch", "type": "watch", "expires": "z",
             "text": "t", "group_id": 0, "is_primary": False},
            {"headline": "Warn", "type": "warning", "expires": "z",
             "text": "t", "group_id": 0, "is_primary": False},
        ]
        result = renormalize_grouping(survivors)
        primaries = [a for a in result if a.get("is_primary")]
        assert len(primaries) == 1
        assert primaries[0]["headline"] == "Warn"

    def test_primary_expired_tie_breaks_to_first(self):
        survivors = [
            {"headline": "W1", "type": "watch", "expires": "z",
             "text": "t", "group_id": 0, "is_primary": False},
            {"headline": "W2", "type": "watch", "expires": "z",
             "text": "t", "group_id": 0, "is_primary": False},
        ]
        result = renormalize_grouping(survivors)
        primaries = [a for a in result if a.get("is_primary")]
        assert len(primaries) == 1
        assert primaries[0]["headline"] == "W1"

    def test_surviving_group_with_primary_unchanged(self):
        survivors = [
            {"headline": "Warn", "type": "warning", "expires": "z",
             "text": "t", "group_id": 0, "is_primary": True},
            {"headline": "Watch", "type": "watch", "expires": "z",
             "text": "t", "group_id": 0, "is_primary": False},
        ]
        result = renormalize_grouping(survivors)
        primaries = [a for a in result if a.get("is_primary")]
        assert len(primaries) == 1
        assert primaries[0]["headline"] == "Warn"

    def test_ungrouped_alerts_untouched(self):
        survivors = [
            {"headline": "A", "type": "warning", "expires": "z", "text": "t"},
        ]
        result = renormalize_grouping(survivors)
        assert "group_id" not in result[0]
        assert "is_primary" not in result[0]


# ---------------------------------------------------------------------------
# Alert-set hashing
# ---------------------------------------------------------------------------

class TestAlertSetHash:
    def test_same_set_same_hash_order_independent(self):
        first = [_alert("A"), _alert("B", "watch")]
        second = [_alert("B", "watch"), _alert("A")]
        assert alert_set_hash(first) == alert_set_hash(second)

    def test_different_text_changes_hash(self):
        first = [_alert("A", text="one")]
        second = [_alert("A", text="two")]
        assert alert_set_hash(first) != alert_set_hash(second)


# ---------------------------------------------------------------------------
# request_alert_groups — mocked ai_task service
# ---------------------------------------------------------------------------

class TestRequestAlertGroups:
    @staticmethod
    def _register(hass: HomeAssistant, handler) -> None:
        """Register a fake ai_task.generate_data service returning a response."""
        hass.services.async_register(
            "ai_task",
            "generate_data",
            handler,
            supports_response=SupportsResponse.OPTIONAL,
        )

    async def test_service_missing_returns_none(self, hass: HomeAssistant):
        alerts = [_alert("A"), _alert("B", "watch")]
        # No ai_task.generate_data service registered.
        result = await request_alert_groups(
            hass, alerts, DEFAULT_AI_GROUPING_INSTRUCTIONS, None,
        )
        assert result is None

    async def test_happy_path_returns_validated_groups(self, hass: HomeAssistant):
        alerts = [_alert("A"), _alert("B", "watch")]

        async def handler(call):
            return {"data": {"groups": ["1,0"]}}

        self._register(hass, handler)
        result = await request_alert_groups(
            hass, alerts, DEFAULT_AI_GROUPING_INSTRUCTIONS, None,
        )
        assert result == [[1, 0]]

    async def test_entity_id_passed_when_configured(self, hass: HomeAssistant):
        alerts = [_alert("A"), _alert("B", "watch")]
        captured = {}

        async def handler(call):
            captured.update(call.data)
            return {"data": {"groups": []}}

        self._register(hass, handler)
        await request_alert_groups(
            hass, alerts, DEFAULT_AI_GROUPING_INSTRUCTIONS, "ai_task.my_model",
        )
        assert captured.get("entity_id") == "ai_task.my_model"

    async def test_entity_id_absent_when_not_configured(self, hass: HomeAssistant):
        alerts = [_alert("A"), _alert("B", "watch")]
        captured = {}

        async def handler(call):
            captured.update(call.data)
            return {"data": {"groups": []}}

        self._register(hass, handler)
        await request_alert_groups(
            hass, alerts, DEFAULT_AI_GROUPING_INSTRUCTIONS, None,
        )
        assert "entity_id" not in captured

    async def test_missing_groups_key_returns_empty(self, hass: HomeAssistant):
        alerts = [_alert("A"), _alert("B", "watch")]

        async def handler(call):
            return {"data": {}}

        self._register(hass, handler)
        result = await request_alert_groups(
            hass, alerts, DEFAULT_AI_GROUPING_INSTRUCTIONS, None,
        )
        assert result == []

    async def test_garbage_response_returns_none(self, hass: HomeAssistant):
        alerts = [_alert("A"), _alert("B", "watch")]

        async def handler(call):
            return {"data": {"groups": ["not,a,number,x"]}}

        self._register(hass, handler)
        result = await request_alert_groups(
            hass, alerts, DEFAULT_AI_GROUPING_INSTRUCTIONS, None,
        )
        assert result is None

    async def test_invalid_verdict_returns_none(self, hass: HomeAssistant):
        alerts = [_alert("A"), _alert("B", "watch")]

        async def handler(call):
            # Out-of-range index → invalid.
            return {"data": {"groups": ["0,9"]}}

        self._register(hass, handler)
        result = await request_alert_groups(
            hass, alerts, DEFAULT_AI_GROUPING_INSTRUCTIONS, None,
        )
        assert result is None

    async def test_service_exception_returns_none(self, hass: HomeAssistant):
        alerts = [_alert("A"), _alert("B", "watch")]

        async def handler(call):
            raise RuntimeError("boom")

        self._register(hass, handler)
        result = await request_alert_groups(
            hass, alerts, DEFAULT_AI_GROUPING_INSTRUCTIONS, None,
        )
        assert result is None

    async def test_timeout_returns_none(self, hass: HomeAssistant):
        alerts = [_alert("A"), _alert("B", "watch")]

        async def handler(call):
            await asyncio.sleep(1)
            return {"data": {"groups": []}}

        self._register(hass, handler)
        # Squeeze the ceiling to force the asyncio.timeout path deterministically.
        with patch(
            "ec_weather.coordinator.alert_grouping.AI_GROUPING_TIMEOUT", 0.01,
        ):
            result = await request_alert_groups(
                hass, alerts, DEFAULT_AI_GROUPING_INSTRUCTIONS, None,
            )
        assert result is None


# ---------------------------------------------------------------------------
# Coordinator integration
# ---------------------------------------------------------------------------

def _two_alert_response(
    headline_a: str = "Severe Thunderstorm Warning",
    headline_b: str = "Severe Thunderstorm Watch",
) -> dict:
    future = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat().replace(
        "+00:00", "Z",
    )
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "alert_type": "warning",
                    "alert_name_en": headline_a,
                    "alert_text_en": "Damaging winds expected.",
                    "status_en": "active",
                    "expiration_datetime": future,
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "alert_type": "watch",
                    "alert_name_en": headline_b,
                    "alert_text_en": "Conditions favourable for storms.",
                    "status_en": "active",
                    "expiration_datetime": future,
                },
            },
        ],
    }


def _single_alert_response() -> dict:
    future = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat().replace(
        "+00:00", "Z",
    )
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "alert_type": "warning",
                    "alert_name_en": "Blizzard Warning",
                    "alert_text_en": "Heavy snow.",
                    "status_en": "active",
                    "expiration_datetime": future,
                },
            },
        ],
    }


class TestCoordinatorIntegration:
    async def test_disabled_never_calls(self, hass: HomeAssistant):
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en")
        with patch(_FETCH, return_value=_two_alert_response()), \
                patch(_REQUEST, new=AsyncMock()) as request:
            await coord.async_refresh()
        request.assert_not_awaited()
        assert coord.data["alert_count"] == 2
        assert all("group_id" not in a for a in coord.data["alerts"])

    async def test_single_alert_never_calls(self, hass: HomeAssistant):
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en", ai_grouping=True)
        with patch(_FETCH, return_value=_single_alert_response()), \
                patch(_REQUEST, new=AsyncMock()) as request:
            await coord.async_refresh()
        request.assert_not_awaited()

    async def test_enabled_annotates_and_calls_once(self, hass: HomeAssistant):
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en", ai_grouping=True)
        with patch(_FETCH, return_value=_two_alert_response()), \
                patch(_REQUEST, new=AsyncMock(return_value=[[0, 1]])) as request:
            await coord.async_refresh()
        request.assert_awaited_once()
        alerts = coord.data["alerts"]
        assert alerts[0]["group_id"] == 0
        assert alerts[0]["is_primary"] is True
        assert alerts[1]["group_id"] == 0
        assert alerts[1]["is_primary"] is False

    async def test_same_hash_uses_cache_no_second_call(self, hass: HomeAssistant):
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en", ai_grouping=True)
        with patch(_FETCH, return_value=_two_alert_response()), \
                patch(_REQUEST, new=AsyncMock(return_value=[[0, 1]])) as request:
            await coord.async_refresh()
            await coord.async_refresh()
        request.assert_awaited_once()
        # Cached annotation still applied on the second poll.
        assert coord.data["alerts"][0]["group_id"] == 0

    async def test_cache_keeps_only_latest_set(self, hass: HomeAssistant):
        """The verdict cache is bounded to the current alert set.

        Alert sets change indefinitely over months of uptime; an unbounded
        per-set cache would grow forever. Bounding it to the latest set means
        flipping back to a previously seen set re-asks the LLM — rare, and far
        cheaper than a slow leak.
        """
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en", ai_grouping=True)
        with patch(_REQUEST, new=AsyncMock(return_value=[[0, 1]])) as request:
            with patch(_FETCH, return_value=_two_alert_response()):
                await coord.async_refresh()
            with patch(_FETCH, return_value=_two_alert_response("New Warning", "New Watch")):
                await coord.async_refresh()
            with patch(_FETCH, return_value=_two_alert_response()):
                await coord.async_refresh()
        assert request.await_count == 3

    async def test_changed_set_triggers_new_call(self, hass: HomeAssistant):
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en", ai_grouping=True)
        with patch(_REQUEST, new=AsyncMock(return_value=[[0, 1]])) as request:
            with patch(_FETCH, return_value=_two_alert_response()):
                await coord.async_refresh()
            with patch(_FETCH, return_value=_two_alert_response("New Warning", "New Watch")):
                await coord.async_refresh()
        assert request.await_count == 2

    async def test_grouping_failure_leaves_alerts_unannotated(self, hass: HomeAssistant):
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en", ai_grouping=True)
        with patch(_FETCH, return_value=_two_alert_response()), \
                patch(_REQUEST, new=AsyncMock(return_value=None)):
            await coord.async_refresh()
        assert coord.last_update_success is True
        assert coord.data["alert_count"] == 2
        assert all("group_id" not in a for a in coord.data["alerts"])

    async def test_grouping_exception_does_not_fail_update(self, hass: HomeAssistant):
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en", ai_grouping=True)
        with patch(_FETCH, return_value=_two_alert_response()), \
                patch(_REQUEST, new=AsyncMock(side_effect=RuntimeError("boom"))):
            await coord.async_refresh()
        assert coord.last_update_success is True
        assert coord.data["alert_count"] == 2
        assert all("group_id" not in a for a in coord.data["alerts"])

    async def test_warns_once_per_hash_then_debug(
        self, hass: HomeAssistant, caplog,
    ):
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en", ai_grouping=True)
        with patch(_FETCH, return_value=_two_alert_response()), \
                patch(_REQUEST, new=AsyncMock(return_value=None)):
            with caplog.at_level(logging.DEBUG, logger="ec_weather.coordinator.alerts"):
                await coord.async_refresh()
                first_warnings = [
                    r for r in caplog.records if r.levelno == logging.WARNING
                ]
                caplog.clear()
                await coord.async_refresh()
                second_warnings = [
                    r for r in caplog.records if r.levelno == logging.WARNING
                ]
        assert len(first_warnings) == 1
        assert len(second_warnings) == 0

    async def test_warns_again_for_different_hash(
        self, hass: HomeAssistant, caplog,
    ):
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en", ai_grouping=True)
        with patch(_REQUEST, new=AsyncMock(return_value=None)):
            with caplog.at_level(logging.WARNING, logger="ec_weather.coordinator.alerts"):
                with patch(_FETCH, return_value=_two_alert_response()):
                    await coord.async_refresh()
                caplog.clear()
                with patch(_FETCH, return_value=_two_alert_response("X Warn", "X Watch")):
                    await coord.async_refresh()
                warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1


# ---------------------------------------------------------------------------
# Startup race: grouping fails-open while HA is still booting
# ---------------------------------------------------------------------------

_AT_STARTED = "ec_weather.coordinator.alerts.async_at_started"


async def _fire_started(hass: HomeAssistant) -> None:
    """Transition HA to STARTED and let queued callbacks run."""
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()


class TestStartupRetry:
    """The AI-task service registers during startup and can lose the race
    with EC Weather's first alert refresh. A grouping failure while HA is
    still booting is expected, not an anomaly: it must stay quiet (debug),
    register a one-shot retry, and re-group once HA reaches STARTED.
    """

    async def test_startup_failure_is_debug_only_and_registers_once(
        self, hass: HomeAssistant, caplog,
    ):
        """Two failing polls during startup: no WARNING, one retry registered."""
        hass.set_state(CoreState.not_running)
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en", ai_grouping=True)
        unsub = MagicMock()
        with patch(_FETCH, return_value=_two_alert_response()), \
                patch(_REQUEST, new=AsyncMock(return_value=None)), \
                patch(_AT_STARTED, return_value=unsub) as at_started:
            with caplog.at_level(logging.DEBUG, logger="ec_weather.coordinator.alerts"):
                await coord.async_refresh()
                await coord.async_refresh()
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings == []
        # Startup path must not poison the once-per-hash WARNING latch.
        assert coord._ai_group_warned_hash is None
        # Repeated failing startup polls register the retry exactly once.
        assert at_started.call_count == 1

    async def test_retry_annotates_and_notifies_without_new_fetch(
        self, hass: HomeAssistant,
    ):
        """When STARTED fires and the service now works, the retry regroups the
        CURRENT data and pushes it to listeners without a fresh EC fetch."""
        hass.set_state(CoreState.not_running)
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en", ai_grouping=True)
        listener = MagicMock()
        with patch(_FETCH, return_value=_two_alert_response()) as fetch:
            with patch(_REQUEST, new=AsyncMock(return_value=None)):
                await coord.async_refresh()
            assert all("group_id" not in a for a in coord.data["alerts"])
            assert fetch.await_count == 1
            coord.async_add_listener(listener)
            with patch(_REQUEST, new=AsyncMock(return_value=[[0, 1]])):
                await _fire_started(hass)
            # Retry must reuse held data, not re-hit the EC API.
            assert fetch.await_count == 1
        alerts = coord.data["alerts"]
        assert alerts[0]["group_id"] == 0
        assert alerts[0]["is_primary"] is True
        assert alerts[1]["group_id"] == 0
        listener.assert_called()

    async def test_retry_still_failing_falls_back_to_runtime_warning(
        self, hass: HomeAssistant, caplog,
    ):
        """If grouping still fails at STARTED, data stays unannotated, the
        update stays successful, and the normal once-per-hash WARNING fires
        (HA is running now, so this is a real runtime failure)."""
        hass.set_state(CoreState.not_running)
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en", ai_grouping=True)
        with patch(_FETCH, return_value=_two_alert_response()), \
                patch(_REQUEST, new=AsyncMock(return_value=None)):
            await coord.async_refresh()
            with caplog.at_level(logging.WARNING, logger="ec_weather.coordinator.alerts"):
                await _fire_started(hass)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert coord.last_update_success is True
        assert all("group_id" not in a for a in coord.data["alerts"])

    async def test_retry_skipped_when_grouping_disabled_meanwhile(
        self, hass: HomeAssistant,
    ):
        hass.set_state(CoreState.not_running)
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en", ai_grouping=True)
        with patch(_FETCH, return_value=_two_alert_response()), \
                patch(_REQUEST, new=AsyncMock(return_value=None)):
            await coord.async_refresh()
        coord._ai_grouping = False
        request = AsyncMock(return_value=[[0, 1]])
        with patch(_REQUEST, new=request):
            await _fire_started(hass)
        request.assert_not_awaited()
        assert all("group_id" not in a for a in coord.data["alerts"])

    async def test_retry_skipped_when_fewer_than_two_alerts(
        self, hass: HomeAssistant,
    ):
        hass.set_state(CoreState.not_running)
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en", ai_grouping=True)
        with patch(_REQUEST, new=AsyncMock(return_value=None)):
            with patch(_FETCH, return_value=_two_alert_response()):
                await coord.async_refresh()  # registers the retry
            with patch(_FETCH, return_value=_single_alert_response()):
                await coord.async_refresh()  # current data now has one alert
        request = AsyncMock(return_value=[[0, 1]])
        with patch(_REQUEST, new=request):
            await _fire_started(hass)
        request.assert_not_awaited()

    async def test_retry_skipped_when_already_annotated(
        self, hass: HomeAssistant,
    ):
        hass.set_state(CoreState.not_running)
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en", ai_grouping=True)
        with patch(_FETCH, return_value=_two_alert_response()):
            with patch(_REQUEST, new=AsyncMock(return_value=None)):
                await coord.async_refresh()  # fails, registers retry
            with patch(_REQUEST, new=AsyncMock(return_value=[[0, 1]])):
                await coord.async_refresh()  # a later startup poll annotates
        assert coord.data["alerts"][0]["group_id"] == 0
        request = AsyncMock(return_value=[[0, 1]])
        with patch(_REQUEST, new=request):
            await _fire_started(hass)
        request.assert_not_awaited()

    async def test_runtime_failure_warns_and_registers_no_retry(
        self, hass: HomeAssistant, caplog,
    ):
        """With HA already running, a grouping failure is the existing
        once-per-hash WARNING path and registers no startup retry."""
        hass.set_state(CoreState.running)
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en", ai_grouping=True)
        with patch(_AT_STARTED) as at_started, \
                patch(_FETCH, return_value=_two_alert_response()), \
                patch(_REQUEST, new=AsyncMock(return_value=None)):
            with caplog.at_level(logging.WARNING, logger="ec_weather.coordinator.alerts"):
                await coord.async_refresh()
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        at_started.assert_not_called()

    async def test_shutdown_cancels_pending_retry(self, hass: HomeAssistant):
        hass.set_state(CoreState.not_running)
        coord = ECAlertCoordinator(hass, bbox=_BBOX, language="en", ai_grouping=True)
        unsub = MagicMock()
        with patch(_AT_STARTED, return_value=unsub), \
                patch(_FETCH, return_value=_two_alert_response()), \
                patch(_REQUEST, new=AsyncMock(return_value=None)):
            await coord.async_refresh()
        await coord.async_shutdown()
        unsub.assert_called_once()
