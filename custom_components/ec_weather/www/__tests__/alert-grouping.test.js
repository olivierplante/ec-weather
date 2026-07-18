/**
 * Alert grouping render tests.
 *
 * When alerts carry AI group annotations (group_id / is_primary), members of a
 * group render as ONE alert bar: the primary's headline/expiry as the header
 * plus a numeral related-count pill, and expanding shows the primary's text
 * then one collapsed row per related alert (headline + chevron), each opening
 * on click to reveal its own expiry+text. Alerts without group_id (and the
 * whole list when nothing is annotated) render exactly as before — the flat,
 * per-alert bars.
 */

import { beforeAll, describe, expect, it } from "vitest";

import { ECWeatherCard } from "../ec-weather-card.js";

beforeAll(() => {
  if (!customElements.get("ec-weather-card")) {
    customElements.define("ec-weather-card", ECWeatherCard);
  }
});

const state = (value, attributes = {}) => ({
  state: String(value),
  attributes,
  last_updated: new Date().toISOString(),
});

const buildHass = (alerts, language = "en") => ({
  language,
  themes: { darkMode: true },
  locale: { time_format: "24" },
  states: {
    "binary_sensor.ec_alert_active": state("on"),
    "sensor.ec_alerts": state(String(alerts.length), { alerts }),
  },
});

const makeCard = (alerts, language = "en") => {
  const card = document.createElement("ec-weather-card");
  card.setConfig({ section: "alerts" });
  card.hass = buildHass(alerts, language);
  return card;
};

const renderAlerts = (alerts, language = "en") =>
  makeCard(alerts, language).shadowRoot;

const EXP = "2099-12-31T12:00:00Z";

describe("alert grouping — flat rendering unchanged (regression)", () => {
  it("no annotations → one bar per alert", () => {
    const root = renderAlerts([
      { type: "warning", headline: "Blizzard Warning", text: "Heavy snow.", expires: EXP },
      { type: "watch", headline: "Wind Watch", text: "Strong winds.", expires: EXP },
    ]);
    expect(root.querySelectorAll(".alert-wrap")).toHaveLength(2);
    expect(root.innerHTML).toContain("Blizzard Warning");
    expect(root.innerHTML).toContain("Wind Watch");
    // No related indicator when nothing is grouped.
    expect(root.querySelector(".alert-related-count")).toBeNull();
  });
});

describe("alert grouping — grouped rendering", () => {
  const grouped = [
    {
      type: "warning", headline: "Severe Thunderstorm Warning",
      text: "Damaging winds expected.", expires: EXP,
      group_id: 0, is_primary: true,
    },
    {
      type: "watch", headline: "Severe Thunderstorm Watch",
      text: "Conditions favourable.", expires: EXP,
      group_id: 0, is_primary: false,
    },
  ];

  // Three-member group: one primary + two related.
  const groupedTwoRelated = [
    {
      type: "warning", headline: "Severe Thunderstorm Warning",
      text: "Damaging winds expected.", expires: EXP,
      group_id: 0, is_primary: true,
    },
    {
      type: "watch", headline: "Severe Thunderstorm Watch",
      text: "Conditions favourable.", expires: EXP,
      group_id: 0, is_primary: false,
    },
    {
      type: "statement", headline: "Special Weather Statement",
      text: "Stay informed.", expires: EXP,
      group_id: 0, is_primary: false,
    },
  ];

  it("renders a group as one bar with the primary headline", () => {
    const root = renderAlerts(grouped);
    expect(root.querySelectorAll(".alert-wrap")).toHaveLength(1);
    const header = root.querySelector(".alert-header .alert-title");
    expect(header.textContent).toContain("Severe Thunderstorm Warning");
  });

  it("pill shows only the numeral +1 for one related alert", () => {
    const root = renderAlerts(grouped);
    const badge = root.querySelector(".alert-related-count");
    expect(badge).not.toBeNull();
    expect(badge.textContent.trim()).toBe("+1");
    // Full wording lives in the accessible attributes, not the visible text.
    expect(badge.getAttribute("aria-label")).toBe("+1 related alert");
    expect(badge.getAttribute("title")).toBe("+1 related alert");
  });

  it("pill shows +2 with pluralized wording for two related alerts", () => {
    const root = renderAlerts(groupedTwoRelated);
    const badge = root.querySelector(".alert-related-count");
    expect(badge.textContent.trim()).toBe("+2");
    expect(badge.getAttribute("aria-label")).toBe("+2 related alerts");
    expect(badge.getAttribute("title")).toBe("+2 related alerts");
  });

  it("renders one collapsed row per related alert", () => {
    const root = renderAlerts(grouped);
    const related = root.querySelectorAll(".alert-related");
    expect(related).toHaveLength(1);
    // The related headline is always visible in the collapsed row.
    const title = related[0].querySelector(".alert-related-title");
    expect(title.textContent).toContain("Severe Thunderstorm Watch");
    // The primary's own text is shown in the (expandable) detail.
    const detail = root.querySelector(".alert-detail");
    expect(detail.textContent).toContain("Damaging winds expected.");
  });

  it("related rows render no stray whitespace text nodes", () => {
    // .alert-detail uses white-space: pre-wrap, so any literal newline or
    // indentation between the related-row tags renders as visible blank
    // lines (the "huge empty space around the title" bug). The row and its
    // header must contain element nodes only.
    const root = renderAlerts(grouped);
    const rowsAndHeaders = root.querySelectorAll(
      ".alert-related, .alert-related-header",
    );
    expect(rowsAndHeaders.length).toBeGreaterThan(0);
    for (const element of rowsAndHeaders) {
      const strayTextNodes = [...element.childNodes].filter(
        (node) => node.nodeType === 3 && node.textContent.length > 0,
      );
      expect(strayTextNodes).toHaveLength(0);
    }
  });

  it("related alert body stays collapsed until its row is clicked", () => {
    const root = renderAlerts(grouped);
    const relatedDetail = root.querySelector(".alert-related-detail");
    // Collapsed by default: no inline block display (CSS keeps it hidden).
    expect(relatedDetail.style.display).not.toBe("block");
    // Clicking the related row reveals its expiry + text.
    root.querySelector(".alert-related-header").click();
    expect(relatedDetail.style.display).toBe("block");
    expect(relatedDetail.textContent).toContain("Conditions favourable.");
    // Clicking again hides it.
    root.querySelector(".alert-related-header").click();
    expect(relatedDetail.style.display).toBe("none");
  });

  it("toggling one related row leaves the others untouched", () => {
    const root = renderAlerts(groupedTwoRelated);
    const rows = root.querySelectorAll(".alert-related");
    expect(rows).toHaveLength(2);
    const firstDetail = rows[0].querySelector(".alert-related-detail");
    const secondDetail = rows[1].querySelector(".alert-related-detail");
    rows[0].querySelector(".alert-related-header").click();
    expect(firstDetail.style.display).toBe("block");
    // The sibling row is unaffected.
    expect(secondDetail.style.display).not.toBe("block");
  });

  it("an open related row survives a re-render", () => {
    const card = makeCard(grouped);
    let root = card.shadowRoot;
    root.querySelector(".alert-related-header").click();
    expect(root.querySelector(".alert-related-detail").style.display).toBe("block");
    // A hass update re-renders the whole card from scratch.
    card.hass = buildHass(grouped);
    root = card.shadowRoot;
    expect(root.querySelector(".alert-related-detail").style.display).toBe("block");
  });

  it("clicking a related row does not collapse the outer bar", () => {
    const card = makeCard(grouped);
    // Open the outer bar the way a re-render restores it (primary index 0).
    card._expandedAlerts.add("0");
    card.hass = buildHass(grouped);
    const root = card.shadowRoot;
    const outerDetail = root.getElementById("alert-detail-0");
    expect(outerDetail.style.display).toBe("block");
    root.querySelector(".alert-related-header").click();
    // The outer bar remains open.
    expect(outerDetail.style.display).toBe("block");
  });

  it("French pill uses the numeral, French wording in the aria-label", () => {
    const root = renderAlerts(grouped, "fr");
    const badge = root.querySelector(".alert-related-count");
    expect(badge.textContent.trim()).toBe("+1");
    expect(badge.getAttribute("aria-label")).toBe("+1 alerte connexe");
    expect(badge.getAttribute("title")).toBe("+1 alerte connexe");
  });
});

describe("alert grouping — defensive", () => {
  it("a group_id on only one alert renders standalone", () => {
    const root = renderAlerts([
      {
        type: "warning", headline: "Lonely Warning",
        text: "Solo.", expires: EXP, group_id: 0, is_primary: true,
      },
      {
        type: "watch", headline: "Ungrouped Watch",
        text: "Alone.", expires: EXP,
      },
    ]);
    // Two standalone bars, no related indicator.
    expect(root.querySelectorAll(".alert-wrap")).toHaveLength(2);
    expect(root.querySelector(".alert-related-count")).toBeNull();
    expect(root.innerHTML).toContain("Lonely Warning");
    expect(root.innerHTML).toContain("Ungrouped Watch");
  });

  it("group with members but no is_primary flag still renders one bar", () => {
    const root = renderAlerts([
      { type: "watch", headline: "A Watch", text: "a.", expires: EXP, group_id: 3 },
      { type: "warning", headline: "A Warning", text: "b.", expires: EXP, group_id: 3 },
    ]);
    expect(root.querySelectorAll(".alert-wrap")).toHaveLength(1);
    // A primary is chosen defensively (first member) so a header renders.
    expect(root.querySelector(".alert-header .alert-title")).not.toBeNull();
    expect(root.querySelector(".alert-related-count")).not.toBeNull();
  });
});
