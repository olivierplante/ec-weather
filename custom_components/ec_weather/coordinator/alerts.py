"""ECAlertCoordinator — 30-minute alert update."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.start import async_at_started

from ..api_client import FetchError, fetch_json_with_retry
from ..const import (
    DEFAULT_AI_GROUPING_INSTRUCTIONS,
    DEFAULT_LANGUAGE,
    DOMAIN,
    EC_API_BASE,
    SCAN_INTERVAL_ALERTS,
)
from .alert_grouping import (
    alert_set_hash,
    annotate_alerts,
    renormalize_grouping,
    request_alert_groups,
)
from .base import OnDemandCoordinator

_LOGGER = logging.getLogger(__name__)

# Priority order for determining "highest" alert type
_ALERT_TYPE_PRIORITY = ["warning", "watch", "advisory", "statement"]

# Sentinel that sorts before any real timestamp, so an alert copy with a
# missing or unparseable ``expires`` always loses to one with a valid value.
_NO_EXPIRES = datetime.min.replace(tzinfo=timezone.utc)


def _expires_at(alert: dict) -> datetime:
    """Parse an alert's ``expires`` the way the surrounding code does.

    Missing or unparseable values sort before every real timestamp.
    """
    expires_str = alert.get("expires")
    if not expires_str:
        return _NO_EXPIRES
    try:
        return datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return _NO_EXPIRES


def parse_alert_response(data: dict, language: str = "en") -> dict:
    """Parse an EC alerts API response into alert count, list, and highest type.

    Pure function — no HA dependencies. Testable without a hass instance.
    """
    features = data.get("features") or []
    if not isinstance(features, list):
        features = []

    now = datetime.now(timezone.utc)

    active: list[dict] = []
    for feature in features:
        props = feature.get("properties") or {}

        # Skip cancelled alerts
        status = props.get("status_en", "")
        if status == "cancelled":
            continue

        # Skip expired alerts
        expires_str = props.get("expiration_datetime")
        if expires_str:
            try:
                expires = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
                if expires <= now:
                    continue
            except ValueError:
                pass

        headline = (
            props.get(f"alert_name_{language}")
            or props.get("alert_name_en")
            or ""
        )
        text = props.get(f"alert_text_{language}") or props.get("alert_text_en") or ""

        # Skip alerts with no text content (EC sometimes publishes empty alerts)
        if not text.strip():
            continue

        active.append({
            "headline": headline,
            "type": props.get("alert_type", ""),
            "expires": expires_str,
            "text": text,
        })

    # Deduplicate alerts (EC API returns one per sub-zone)
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for alert in active:
        key = (alert["headline"], alert["text"])
        if key not in seen:
            seen.add(key)
            unique.append(alert)
    active = unique

    # Merge same-product copies (EC issues the SAME alert per forecast zone,
    # so a multi-zone bbox yields near-identical copies of one product whose
    # text differs only in regional phrasing). The card shows no zones, so we
    # keep one copy per (headline, type): the one that stays valid longest.
    # Kept wholesale — text and expires travel together, never mixed — so that
    # expires-driven retention pruning never drops an alert EC still deems
    # active somewhere in the bbox.
    merged: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    for alert in active:
        key = (alert["headline"], alert["type"])
        if key not in merged:
            merged[key] = alert
            order.append(key)
            continue
        if _expires_at(alert) > _expires_at(merged[key]):
            merged[key] = alert
    active = [merged[key] for key in order]

    # Determine the highest-priority alert type present
    highest_type: str | None = None
    for alert_type in _ALERT_TYPE_PRIORITY:
        if any(alert["type"] == alert_type for alert in active):
            highest_type = alert_type
            break

    return {
        "alert_count": len(active),
        "alerts": active,
        "highest_type": highest_type,
    }


def prune_retained_alerts(retained: dict, now: datetime | None = None) -> dict:
    """Prune expired alerts from a retained (last-known-good) payload.

    Used when an alerts refresh fails transiently but prior good data exists.
    Retention is naturally bounded by each alert's EC-declared expiration: an
    alert is dropped once its ``expires`` timestamp has passed, so a stale
    payload never outlives EC's own validity window. count / highest_type are
    recomputed over the survivors, and ``stale`` is flagged True. An all-expired
    retention collapses to the honest empty state (count 0, highest None) rather
    than serving stale garbage.

    Pure function — no HA dependencies.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    surviving: list[dict] = []
    for alert in retained.get("alerts") or []:
        expires_str = alert.get("expires")
        if expires_str:
            try:
                expires = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
                if expires <= now:
                    continue
            except ValueError:
                pass
        surviving.append(alert)

    # Re-validate any AI group annotations against the survivors: collapse
    # groups that fell below two members and promote a new primary if the
    # original expired. No-op when nothing is annotated.
    surviving = renormalize_grouping(surviving)

    highest_type: str | None = None
    for alert_type in _ALERT_TYPE_PRIORITY:
        if any(alert.get("type") == alert_type for alert in surviving):
            highest_type = alert_type
            break

    return {
        "alert_count": len(surviving),
        "alerts": surviving,
        "highest_type": highest_type,
        "stale": True,
    }


class ECAlertCoordinator(OnDemandCoordinator):
    """Fetches active weather alerts for the configured bounding box."""

    def __init__(
        self,
        hass: HomeAssistant,
        bbox: str,
        language: str = DEFAULT_LANGUAGE,
        *,
        ai_grouping: bool = False,
        ai_task_entity: str | None = None,
        ai_grouping_instructions: str | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_alerts",
            interval=SCAN_INTERVAL_ALERTS,
            polling=True,  # alerts always poll in all modes
        )
        self.bbox = bbox
        self.language = language
        # Timestamp of the last SUCCESSFUL fetch — drives the retention age in
        # the "serving retained" log line. None until the first success.
        self._last_success_dt: datetime | None = None
        # True while we are serving last-known-good data through a failure run,
        # so the INFO line is logged once per outage, then downgraded to debug.
        self._serving_retained = False
        # AI alert grouping (opt-in). Off by default so existing constructors
        # and tests are unaffected.
        self._ai_grouping = ai_grouping
        self._ai_task_entity = ai_task_entity or None
        self._ai_grouping_instructions = (
            ai_grouping_instructions or DEFAULT_AI_GROUPING_INSTRUCTIONS
        )
        # (alert-set hash, validated groups) for the CURRENT set only: the LLM
        # is called once per set change and the verdict re-applied on every
        # poll after. Bounded to one entry on purpose — sets change forever on
        # a long-running instance, and flipping back to a previously seen set
        # (rare) just costs one extra LLM call.
        self._ai_group_cache: tuple[str, list[list[int]]] | None = None
        # Hash of the set we last logged a failure WARNING for, so the same
        # failing set warns once and then stays at debug.
        self._ai_group_warned_hash: str | None = None
        # Unsubscribe for the one-shot "regroup once HA has STARTED" retry.
        # The coordinator's first refresh runs during EC Weather's setup, which
        # races the AI-task integration registering ai_task.generate_data. When
        # grouping fails-open purely because HA hasn't finished booting we defer
        # a single retry to the STARTED event instead of warning and waiting a
        # full poll interval. None means no retry is pending. Doubles as the
        # "register only once" guard across repeated failing startup polls.
        self._startup_retry_unsub = None

    async def _do_update(self) -> dict:
        url = (
            f"{EC_API_BASE}/collections/weather-alerts/items"
            f"?bbox={self.bbox}&f=json&skipGeometry=true"
        )
        session = async_get_clientsession(self.hass)
        try:
            data = await fetch_json_with_retry(
                session, url, label="alerts",
            )
        except FetchError:
            # Transient fetch failure. If we hold last-known-good data, keep it
            # (pruned to each alert's EC expiration) instead of dropping to
            # unknown — the alert bar must not blank during an active alert.
            retained = self.data
            if not isinstance(retained, dict) or "alerts" not in retained:
                # First-ever fetch failing: nothing to retain. Propagate so the
                # entities go unknown — never fabricate an alert state.
                raise
            return self._serve_retained(retained)

        result = parse_alert_response(data, self.language)

        # Opt-in AI grouping annotates the alerts in place. It only ever adds
        # group_id/is_primary keys; count, highest_type and the alert list are
        # unchanged. Wrapped so a grouping failure never fails the update.
        if self._ai_grouping and result["alert_count"] >= 2:
            try:
                await self._apply_ai_grouping(result)
            except Exception:  # noqa: BLE001 — grouping must never fail update
                _LOGGER.debug(
                    "EC Weather AI alert grouping failed unexpectedly",
                    exc_info=True,
                )

        # A successful fetch replaces retained data entirely (result carries no
        # ``stale`` key) and clears the outage-logging latch.
        self._last_success_dt = datetime.now(timezone.utc)
        self._serving_retained = False
        _LOGGER.debug(
            "EC alerts updated: %d active, highest=%s",
            result["alert_count"], result["highest_type"],
        )
        return result

    async def _apply_ai_grouping(self, result: dict) -> None:
        """Annotate result['alerts'] with AI group ids, using a bounded cache.

        The LLM is only called when the alert set (hash of sorted
        headline/text pairs) differs from the one currently cached. On a
        validated verdict the annotation is cached and applied; on any
        fail-open outcome the alerts are left untouched and a WARNING is
        logged once per failing set (then debug on repeats of that same set).
        """
        alerts = result["alerts"]
        current_hash = alert_set_hash(alerts)

        if self._ai_group_cache is not None and self._ai_group_cache[0] == current_hash:
            result["alerts"] = annotate_alerts(alerts, self._ai_group_cache[1])
            return

        groups = await request_alert_groups(
            self.hass,
            alerts,
            self._ai_grouping_instructions,
            self._ai_task_entity,
        )
        if groups is None:
            if not self.hass.is_running:
                # HA is still booting: the AI-task service almost certainly just
                # hasn't registered yet (this refresh runs during EC Weather's
                # own setup). That's expected, not an anomaly — stay at debug,
                # leave the WARNING latch untouched, and defer a single retry to
                # the STARTED event so we regroup within seconds instead of
                # blanking ungrouped for a full poll interval.
                _LOGGER.debug(
                    "EC Weather AI alert grouping unavailable during startup; "
                    "deferring grouping until Home Assistant has started",
                )
                self._register_startup_retry()
                return
            # Fail open — no annotations. Warn once per distinct alert set.
            if current_hash != self._ai_group_warned_hash:
                self._ai_group_warned_hash = current_hash
                _LOGGER.warning(
                    "EC Weather AI alert grouping is unavailable or returned "
                    "an invalid response; showing alerts ungrouped",
                )
            else:
                _LOGGER.debug(
                    "EC Weather AI alert grouping still failing for this "
                    "alert set; showing alerts ungrouped",
                )
            return

        self._ai_group_cache = (current_hash, groups)
        result["alerts"] = annotate_alerts(alerts, groups)

    def _register_startup_retry(self) -> None:
        """Arm a one-shot regroup for when HA reaches STARTED.

        Idempotent: repeated failing polls during startup keep the single
        already-registered callback (the stored unsub is the guard). Note
        ``async_at_started`` fires immediately if HA is already started, but the
        ``not is_running`` gate at the only call site rules that out here.
        """
        if self._startup_retry_unsub is not None:
            return
        self._startup_retry_unsub = async_at_started(
            self.hass, self._retry_grouping_when_started,
        )

    async def _retry_grouping_when_started(self, _hass: HomeAssistant) -> None:
        """Regroup the coordinator's current alerts once HA has started.

        Fired when every integration (including the AI-task provider) is set up.
        Re-runs the normal grouping path against the data we currently hold and
        republishes it so sensors and the card update immediately, without a
        fresh EC fetch. Guarded so a set that changed or was already resolved
        during startup is left alone. If grouping still fails here, HA is now
        running, so ``_apply_ai_grouping`` takes the ordinary once-per-hash
        WARNING path — no special casing.
        """
        self._startup_retry_unsub = None

        if not self._ai_grouping:
            return
        data = self.data
        if not isinstance(data, dict):
            return
        alerts = data.get("alerts") or []
        if len(alerts) < 2:
            return
        if any("group_id" in alert for alert in alerts):
            # A later startup poll already grouped this set.
            return

        result = dict(data)
        await self._apply_ai_grouping(result)
        self.async_set_updated_data(result)

    async def async_shutdown(self) -> None:
        """Cancel a pending startup retry, then defer to the base coordinator."""
        if self._startup_retry_unsub is not None:
            self._startup_retry_unsub()
            self._startup_retry_unsub = None
        await super().async_shutdown()

    def _serve_retained(self, retained: dict) -> dict:
        """Return the retained payload pruned to live alerts, and log once."""
        now = datetime.now(timezone.utc)
        pruned = prune_retained_alerts(retained, now)

        if self._last_success_dt is not None:
            age_min = (now - self._last_success_dt).total_seconds() / 60
            age_str = f"{age_min:.0f} min"
        else:
            age_str = "unknown time"

        if not self._serving_retained:
            self._serving_retained = True
            _LOGGER.info(
                "EC alerts fetch failed; serving %d retained alert(s) "
                "(last success %s ago, pruned to EC expirations)",
                pruned["alert_count"], age_str,
            )
        else:
            _LOGGER.debug(
                "EC alerts fetch failed again; still serving %d retained "
                "alert(s) (last success %s ago)",
                pruned["alert_count"], age_str,
            )
        return pruned
