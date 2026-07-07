/**
 * EC Weather Card — Custom Lovelace card for Environment Canada weather data.
 *
 * Sections: alerts, current, hourly, daily
 * Source: config/custom_components/ec_weather/
 */

// ─── Constants ───────────────────────────────────────────────────────────────

// Canonical source: icon_registry.py — keep in sync
const EC_ICON_MAP = {
  0:  'mdi:weather-sunny',
  1:  'mdi:weather-partly-cloudy',
  2:  'mdi:weather-partly-cloudy',
  3:  'mdi:weather-cloudy',
  4:  'mdi:weather-cloudy',
  5:  'mdi:weather-partly-cloudy',
  6:  'mdi:weather-rainy',
  7:  'mdi:weather-snowy-rainy',
  8:  'mdi:weather-snowy',
  9:  'mdi:weather-lightning-rainy',
  10: 'mdi:weather-cloudy',
  11: 'mdi:weather-rainy',
  12: 'mdi:weather-rainy',
  13: 'mdi:weather-rainy',
  14: 'mdi:weather-hail',
  15: 'mdi:weather-snowy-rainy',
  16: 'mdi:weather-snowy',
  17: 'mdi:weather-snowy',
  18: 'mdi:weather-snowy',
  19: 'mdi:weather-lightning-rainy',
  20: 'mdi:weather-windy',
  21: 'mdi:weather-fog',
  22: 'mdi:weather-partly-cloudy',
  23: 'mdi:weather-fog',
  24: 'mdi:weather-fog',
  25: 'mdi:weather-windy',
  26: 'mdi:weather-hail',
  27: 'mdi:weather-hail',
  28: 'mdi:weather-rainy',
  29: 'mdi:weather-cloudy',
  30: 'mdi:weather-night',
  31: 'mdi:weather-night-partly-cloudy',
  32: 'mdi:weather-night-partly-cloudy',
  33: 'mdi:weather-cloudy',
  34: 'mdi:weather-cloudy',
  35: 'mdi:weather-night-partly-cloudy',
  36: 'mdi:weather-rainy',
  37: 'mdi:weather-snowy-rainy',
  38: 'mdi:weather-snowy',
  39: 'mdi:weather-lightning-rainy',
  40: 'mdi:weather-snowy',
  41: 'mdi:weather-tornado',
  42: 'mdi:weather-tornado',
  43: 'mdi:weather-windy',
  44: 'mdi:weather-fog',
  45: 'mdi:weather-windy',
  46: 'mdi:weather-lightning',
  47: 'mdi:weather-lightning',
  48: 'mdi:weather-tornado',
};

// ─── Localization ───────────────────────────────────────────────────────────

const I18N = {
  en: {
    days: ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'],
    feels: 'Feels like',
    gusts: 'gusts',
    humidity: 'Humidity',
    yesterdayCombinedTooltip:
      'This station reports combined precipitation only. Snow is counted as its melted water equivalent in mm — not snow depth.',
    day: 'DAY',
    night: 'NIGHT',
    timeline: 'Timeline',
    dayDone: 'Day is over',
    noHourly: 'Hourly forecast isn’t available for this day yet.',
    ecAttribution: 'Environment Canada',
    hourly: 'HOURLY',
    loading: 'Loading\u2026',
    weatherUnavailable: 'Weather data unavailable',
    retry: 'Retry',
    expires: 'Expires',
    updatedAt: 'Updated at',
    precipTitle: 'Precipitation',
    todayForecast: 'Today\u2019s forecast',
    yesterday: 'Yesterday',
    none: 'None',
    noneExpected: 'None expected',
    noData: 'No data',
    calm: 'Calm',
    chance: 'chance',
    week: '7-day',
    sunriseIn: 'sunrise in',
    sunsetIn: 'sets in',
    ofDaylight: 'of daylight',
    aqhiLabel: 'AQHI',
    staleBanner: 'Data may be outdated',
    refresh: 'Refresh',
    sunUpAllDay: 'Sun up all day',
    polarNight: 'Polar night',
    unavailableMsg: 'Couldn’t reach Environment Canada. It’ll retry automatically.',
    dayAbbr: {
      Monday: 'Mon', Tuesday: 'Tue', Wednesday: 'Wed',
      Thursday: 'Thu', Friday: 'Fri', Saturday: 'Sat', Sunday: 'Sun',
      Tomorrow: 'Tmrw',
    },
  },
  fr: {
    days: ['DIM', 'LUN', 'MAR', 'MER', 'JEU', 'VEN', 'SAM'],
    feels: 'Ressenti',
    gusts: 'rafales',
    humidity: 'Humidité',
    yesterdayCombinedTooltip:
      'Cette station ne fournit que les précipitations combinées. La neige est comptée selon son équivalent en eau fondue en mm — pas la hauteur de neige.',
    day: 'JOUR',
    night: 'NUIT',
    timeline: 'Évolution',
    dayDone: 'Journée terminée',
    noHourly: 'Prévisions horaires pas encore disponibles pour cette journée.',
    ecAttribution: 'Environnement Canada',
    hourly: 'HORAIRE',
    loading: 'Chargement\u2026',
    weatherUnavailable: 'Données météo indisponibles',
    retry: 'Réessayer',
    expires: 'Expire',
    updatedAt: 'Mis à jour à',
    precipTitle: 'Précipitations',
    todayForecast: 'Prévision du jour',
    yesterday: 'Hier',
    none: 'Aucune',
    noneExpected: 'Aucune prévue',
    noData: 'Aucune donnée',
    calm: 'Calme',
    chance: 'de risque',
    week: '7 jours',
    sunriseIn: 'lever dans',
    sunsetIn: 'coucher dans',
    ofDaylight: 'd’ensoleillement',
    aqhiLabel: 'CAS',
    staleBanner: 'Données peut-être périmées',
    refresh: 'Actualiser',
    sunUpAllDay: 'Soleil toute la journée',
    polarNight: 'Nuit polaire',
    unavailableMsg: 'Impossible de joindre Environnement Canada. Nouvel essai automatique.',
    dayAbbr: {
      Monday: 'Lun', Tuesday: 'Mar', Wednesday: 'Mer',
      Thursday: 'Jeu', Friday: 'Ven', Saturday: 'Sam', Sunday: 'Dim',
      Tomorrow: 'Demain',
      Lundi: 'Lun', Mardi: 'Mar', Mercredi: 'Mer',
      Jeudi: 'Jeu', Vendredi: 'Ven', Samedi: 'Sam', Dimanche: 'Dim',
      Demain: 'Demain',
    },
  },
};

// ─── Design Tokens ───────────────────────────────────────────────────────────
//
// Shared token CSS injected into every section's shadow root. Neutral tokens
// bind to HA theme variables so the card follows the active theme; weather
// accents are design literals tuned per theme (dark defaults, .ecc.light
// overrides). Every accent resolves through a public --ec-weather-* variable
// first: user override → HA theme variable → design literal. The full token
// table lives in docs/card.md. NOT carried over from the pre-redesign
// contract: the per-severity alert variables (--ec-weather-alert-warning/
// -watch/-advisory/-statement, -bg) — alert bars are deliberately neutral.

const TOKEN_CSS = `
  .ecc {
    --ecw-text: var(--ec-weather-text-primary, var(--primary-text-color, #eef2f6));
    --ecw-text2: var(--ec-weather-text-secondary, var(--secondary-text-color, #c3ccd6));
    /* Small-label tokens ride the design audit's contrast floor: a higher
       color-mix ratio and darker/lighter raw fallbacks (#8290a0/#788595, the
       DC's dark literals) so 10-12px labels stay legible while still binding
       to the HA secondary-text color on themed installs. */
    --ecw-muted: var(--ec-weather-text-muted, color-mix(in srgb, var(--secondary-text-color, #8290a0) 90%, transparent));
    --ecw-faint: color-mix(in srgb, var(--secondary-text-color, #788595) 75%, transparent);
    --ecw-hair: var(--ec-weather-divider, var(--divider-color, rgba(255,255,255,0.08)));
    /* Card background for the hourly scroll fade; resolves through HA's card
       background chain so the gradient blends into whatever surface hosts it. */
    --ecw-alertbd: var(--ec-weather-alert-border, color-mix(in srgb, var(--primary-text-color, #fff) 11%, transparent));
    --ecw-tint: color-mix(in srgb, var(--primary-text-color, #fff) 3%, transparent);
    --ecw-track: color-mix(in srgb, var(--primary-text-color, #fff) 9%, transparent);
    --ecw-hover: color-mix(in srgb, var(--primary-text-color, #fff) 5%, transparent);
    --ecw-rain: var(--ec-weather-precip-rain, #46b0ec);
    --ecw-snow: var(--ec-weather-precip-snow, #c6d2dd);
    --ecw-snowbar: var(--ec-weather-snow-bar, rgba(205,217,227,0.72));
    --ecw-sun: var(--ec-weather-sun, #e6c98a);
    --ecw-sunarc: var(--ec-weather-sun-arc, rgba(230,201,138,0.45));
    --ecw-sunglow: rgba(230,201,138,0.16);
    --ecw-curve: var(--ec-weather-curve, #8ec6e8);
    --ecw-pop: var(--ec-weather-pop, #6f96b3);
    --ecw-heroicon: var(--ec-weather-hero-icon, var(--primary-text-color, #eaf1f8));
    --ecw-ppbg: var(--ec-weather-panel-bg, rgba(70,176,236,0.05));
    --ecw-ppbd: var(--ec-weather-panel-border, rgba(120,170,210,0.16));
    --ecw-pphead: var(--ec-weather-panel-head, #9db4c6);
    --ecw-pptitle: var(--ec-weather-panel-title, #8fb8d4);
    --ecw-btnbg: color-mix(in srgb, var(--primary-text-color, #fff) 6%, transparent);
    --ecw-btnbd: color-mix(in srgb, var(--primary-text-color, #fff) 14%, transparent);
  }
  .ecc.light {
    --ecw-rain: var(--ec-weather-precip-rain, #2b8fd1);
    --ecw-snow: var(--ec-weather-precip-snow, #748799);
    --ecw-snowbar: var(--ec-weather-snow-bar, rgba(120,140,158,0.5));
    --ecw-sun: var(--ec-weather-sun, #cf9a3a);
    --ecw-sunarc: var(--ec-weather-sun-arc, rgba(200,150,60,0.5));
    --ecw-sunglow: rgba(210,160,70,0.16);
    --ecw-curve: var(--ec-weather-curve, #3f9fd8);
    --ecw-pop: var(--ec-weather-pop, #4a7a9c);
    --ecw-heroicon: var(--ec-weather-hero-icon, #3f5568);
    --ecw-ppbg: var(--ec-weather-panel-bg, rgba(70,150,210,0.07));
    --ecw-ppbd: var(--ec-weather-panel-border, rgba(70,140,200,0.22));
    --ecw-pphead: var(--ec-weather-panel-head, #5a7f99);
    --ecw-pptitle: var(--ec-weather-panel-title, #3f7aa8);
  }
`;

// Daily-popup styles. The overlay lives in document.body (light DOM), so the
// card's shadow-root tokens aren't visible there — the popup content injects
// its own <style> carrying TOKEN_CSS (class-scoped under .ecc) plus these
// ecp-prefixed classes (and STRIP_CSS for the hourly timeline), wrapped in a
// .ecc theme div so the tokens resolve.
const POPUP_STYLE = `
  .ecp-root { display: flex; flex-direction: column; gap: 18px; color: var(--ecw-text); }
  .ecp-hdr { display: flex; flex-direction: column; gap: 2px; }
  .ecp-title { font-size: 23px; font-weight: 600; letter-spacing: -0.01em; color: var(--ecw-text); }
  .ecp-date { font-size: 12.5px; color: var(--ecw-muted); }
  .ecp-narr { font-size: 14px; line-height: 1.5; color: var(--ecw-text2); margin: 0; }
  .ecp-periods { display: flex; gap: 12px; }
  .ecp-period {
    flex: 1; display: flex; flex-direction: column; gap: 10px;
    padding: 14px; border: 1px solid var(--ecw-hair); border-radius: 14px;
  }
  .ecp-period.ecp-passed { opacity: 0.62; }
  .ecp-plabel {
    display: flex; align-items: center; gap: 7px; font-size: 11px; font-weight: 600;
    letter-spacing: 0.1em; color: var(--ecw-muted); text-transform: uppercase;
  }
  .ecp-prow { display: flex; align-items: center; gap: 14px; }
  .ecp-pico { --mdc-icon-size: 40px; color: var(--ecw-heroicon); }
  .ecp-ptemp { font-size: 38px; font-weight: 300; line-height: 1; color: var(--ecw-text); }
  .ecp-pcond { font-size: 12.5px; color: var(--ecw-text2); margin-top: 3px; }
  .ecp-passedbody { display: flex; flex-direction: column; gap: 8px; padding: 6px 0; }
  .ecp-passedbody ha-icon { --mdc-icon-size: 34px; color: var(--ecw-faint); opacity: 0.6; }
  .ecp-pmeta { display: flex; flex-direction: column; gap: 6px; margin-top: 2px; }
  .ecp-mline { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--ecw-text2); }
  .ecp-mline ha-icon { --mdc-icon-size: 16px; color: var(--ecw-muted); width: 17px; }
  .ecp-mline.ecp-rain ha-icon { color: var(--ecw-rain); }
  .ecp-mline.ecp-snow ha-icon { color: var(--ecw-snow); }
  .ecp-seclbl {
    font-size: 11px; font-weight: 600; letter-spacing: 0.12em;
    color: var(--ecw-muted); text-transform: uppercase; margin-bottom: 10px;
  }
  .ecp-scroll {
    overflow-x: auto; overflow-y: hidden;
    scrollbar-width: thin; scrollbar-color: var(--ecw-track) transparent;
    -webkit-overflow-scrolling: touch;
  }
  .ecp-scroll::-webkit-scrollbar { height: 6px; }
  .ecp-scroll::-webkit-scrollbar-thumb { background: var(--ecw-track); border-radius: 3px; }
  .ecp-noh {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 9px; padding: 26px 20px; border: 1px dashed var(--ecw-hair);
    border-radius: 13px; text-align: center;
  }
  .ecp-noh ha-icon { --mdc-icon-size: 28px; color: var(--ecw-muted); }
  .ecp-noh span { font-size: 13.5px; color: var(--ecw-text2); max-width: 320px; line-height: 1.45; }
  .ecp-foot {
    display: flex; align-items: center; justify-content: space-between;
    border-top: 1px solid var(--ecw-hair); padding-top: 12px;
    font-size: 11.5px; color: var(--ecw-muted);
  }
  .ecp-foot ha-icon { --mdc-icon-size: 13px; }
`;

/** Root class for a section wrapper: light accents when HA runs a light theme. */
export function themeClass(hass) {
  const darkMode = hass && hass.themes && hass.themes.darkMode;
  // Older HA without the flag stays dark (the card's historical look).
  return darkMode === false ? 'ecc light' : 'ecc';
}

/**
 * Absolute-temperature color scale (range bars). Keys to the temperature
 * itself, never the row's position in the week, so cold weeks read blue and
 * hot weeks orange regardless of spread. Same literals in both themes.
 */
export function tempColor(temp) {
  if (temp <= -15) return 'var(--ec-weather-temp-frigid, #6a7fd0)';
  if (temp < 0) return 'var(--ec-weather-temp-freezing, #5b93d4)';
  if (temp < 6) return 'var(--ec-weather-temp-cold, #4fa6cf)';
  if (temp < 12) return 'var(--ec-weather-temp-cool, #5cbf9e)';
  if (temp < 18) return 'var(--ec-weather-temp-mild, #93c98a)';
  if (temp < 24) return 'var(--ec-weather-temp-warm, #dcc079)';
  if (temp < 30) return 'var(--ec-weather-temp-hot, #e59b5b)';
  return 'var(--ec-weather-temp-scorching, #e5793f)';
}

/** AQHI risk color; null when the value is absent (cell hidden entirely).
 *  Non-numeric values are rejected — a truthy color would let a malformed
 *  attribute flow into innerHTML. */
export function aqhiColor(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  if (value <= 3) return 'var(--ec-weather-aqhi-low, #4f9fd0)';
  if (value <= 6) return 'var(--ec-weather-aqhi-moderate, #dcae4e)';
  if (value <= 10) return 'var(--ec-weather-aqhi-high, #e08a3f)';
  return 'var(--ec-weather-aqhi-very-high, #d1495b)';
}

/** UV index color; null when the value is absent (cell hidden entirely).
 *  Non-numeric values are rejected — a truthy color would let a malformed
 *  attribute flow into innerHTML. */
export function uvColor(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  if (value <= 2) return 'var(--ec-weather-uv-low, #3f9f6e)';
  if (value <= 5) return 'var(--ec-weather-uv-moderate, #dcae4e)';
  if (value <= 7) return 'var(--ec-weather-uv-high, #e08a3f)';
  if (value <= 10) return 'var(--ec-weather-uv-very-high, #d1495b)';
  return 'var(--ec-weather-uv-extreme, #9b5fb8)';
}

/**
 * Clock preference: explicit hass.locale.time_format wins ('12'/'24'),
 * 'system' asks the browser, otherwise fall back to the language default
 * (fr → 24h, en → 12h).
 */
export function use24Hour(hass) {
  const pref = hass && hass.locale && hass.locale.time_format;
  if (pref === '24') return true;
  if (pref === '12') return false;
  if (pref === 'system') {
    const resolved = new Intl.DateTimeFormat(undefined, { hour: 'numeric' }).resolvedOptions();
    return resolved.hour12 === false;
  }
  const lang = (hass && hass.language) || 'en';
  return lang === 'fr';
}

/** Liquid-equivalent precip total for bar proportions: 1 cm snow ~ 1 mm water. */
export function liquidTotal(rainMm, snowCm) {
  return (rainMm || 0) + (snowCm || 0);
}

/**
 * Missing condition icon → a quiet dimmed dash. Not a placeholder weather
 * glyph (reads as a real condition) and not a "?" (too loud). Used in the
 * hero, hourly columns, and daily rows alike.
 */
export function missingIconHtml(sizePx) {
  return '<ha-icon icon="mdi:minus" style="--mdc-icon-size:' + sizePx
    + 'px;color:var(--ecw-faint);opacity:0.6"></ha-icon>';
}

/**
 * Daily-row day icon accent by condition family. Mixed precip reads as rain
 * (snowy-rainy is checked before snowy); clouds/fog/night stay neutral.
 */
export function dailyIconColor(mdiIcon) {
  if (mdiIcon.includes('snowy-rainy')) return 'var(--ecw-rain)';
  if (mdiIcon.includes('snowy')) return 'var(--ecw-snow)';
  if (mdiIcon.includes('rainy') || mdiIcon.includes('pouring')
    || mdiIcon.includes('lightning') || mdiIcon.includes('hail')) return 'var(--ecw-rain)';
  if (mdiIcon.includes('sunny')) return 'var(--ecw-sun)';
  return 'var(--ecw-text2)';
}

/**
 * Precip panel header decision. The chance % wins whenever there is a real
 * POP — 'None expected' is only claimed for a dry day we actually have data
 * for. No forecast at all → an empty header, not a dry-day claim.
 */
export function precipPanelHead(summary) {
  if (!summary) return { kind: 'empty' };
  if (summary.showPrecip) return { kind: 'chance', popRounded: summary.popRounded };
  if (summary.rainAmt > 0 || summary.snowAmt > 0) return { kind: 'empty' };
  return { kind: 'none-expected' };
}

/**
 * Wind metric cell state. A null reading (sensor unknown/unavailable) hides
 * the cell — 'Calm' is a measurement, never a fallback for missing data.
 */
export function windCellState(windSpeed) {
  if (windSpeed === null || windSpeed === undefined) return 'hidden';
  return Math.round(windSpeed) === 0 ? 'calm' : 'value';
}

/**
 * Sun cell mode. Polar day/night are real only poleward of the polar
 * circles (~66.5°); missing sunrise/sunset anywhere else is transient data
 * loss, not astronomy — hide the cell instead of claiming 'Polar night'
 * at mid-latitudes. Without sun.sun (or a latitude) we don't guess.
 */
export function sunCellMode(sunrise, sunset, latitude, sunElevation) {
  if (sunrise && sunset) return 'arc';
  if (latitude == null || Math.abs(latitude) < 66) return 'hidden';
  if (sunElevation === 'above_horizon') return 'polar-day';
  if (sunElevation === 'below_horizon') return 'polar-night';
  return 'hidden';
}

/**
 * A timestep with no temperature, no icon and no POP renders nothing useful
 * — the store creates such rows mid-load (per-element merges). POP 0 is a
 * real reading and keeps the hour.
 */
export function isEmptyTimestep(item) {
  return item.temp == null && item.icon_code == null
    && item.precipitation_probability == null;
}

/**
 * Tri-state for the daily popup's hourly timeline. EC removed the GDPS-WEonG
 * layers, so days 4-6 return zero timesteps. Any present timesteps win →
 * 'timeline'. Otherwise the coordinator's timesteps_state disambiguates
 * fetched-but-empty ('unavailable') from not-yet-fetched ('pending').
 */
export function timelineState(item) {
  const count = (item.timesteps_day || []).length
    + (item.timesteps_night || []).length;
  if (count > 0) return 'timeline';
  if (item.timesteps_state === 'unavailable') return 'unavailable';
  return 'pending';
}

/**
 * Hourly temperature curve geometry. Missing temps break the path (no
 * interpolation, no snap to zero); a point with gaps on both sides is
 * flagged isolated so the renderer can draw a dot — a lone SVG 'M' subpath
 * strokes nothing. Area fill only when every hour has a temperature.
 *
 * `geometry` describes the SVG band: `plotTop`/`plotHeight` map the warmest
 * temp to `plotTop` and the coldest to `plotTop + plotHeight`; the area fill
 * baselines at `chartHeight`. The default reproduces the card's original
 * hardcoded `40 - (t-min)*(30/span)` / baseline-50 formula byte-for-byte; the
 * popup passes a shorter band for its 42px chart.
 */
export function buildHourlyCurve(
  temps, colWidth = 64,
  geometry = { chartHeight: 50, plotTop: 10, plotHeight: 30 },
) {
  const { chartHeight, plotTop, plotHeight } = geometry;
  const plotBottom = plotTop + plotHeight;
  const presentTemps = temps.filter((temp) => temp != null);
  const tempMin = presentTemps.length ? Math.min.apply(null, presentTemps) : 0;
  const tempMax = presentTemps.length ? Math.max.apply(null, presentTemps) : 1;
  const span = (tempMax - tempMin) || 1;
  const yFor = (temp) => Math.round((plotBottom - (temp - tempMin) * (plotHeight / span)) * 10) / 10;

  const points = temps.map((temp, i) => temp != null
    ? {
      x: colWidth / 2 + i * colWidth,
      y: yFor(temp),
      isolated: temps[i - 1] == null && temps[i + 1] == null,
      // Per-point absolute-temperature color: the strip builder feeds these
      // into the stroke gradient (and lone-dot fill) so the line reads
      // cool→warm on the same scale as the daily range bars.
      color: tempColor(temp),
    }
    : null);

  let path = '';
  let started = false;
  points.forEach((point) => {
    if (!point) { started = false; return; }
    path += (started ? ' L ' : ' M ') + point.x + ',' + point.y;
    started = true;
  });

  const allPresent = presentTemps.length === temps.length && temps.length > 0;
  let areaPath = null;
  if (allPresent) {
    const coords = points.map((point) => point.x + ',' + point.y).join(' ');
    areaPath = 'M ' + coords + ' L ' + points[points.length - 1].x + ',' + chartHeight
      + ' L ' + points[0].x + ',' + chartHeight + ' Z';
  }
  return { path: path.trim(), areaPath, points, allPresent };
}

/**
 * CSS for the shared hourly strip (buildHourlyStripHtml). Emitted in TWO
 * places — the hourly section's shadow <style> AND the daily-popup light-DOM
 * <style> — because the popup overlay lives in document.body and can't see the
 * card's shadow-root rules. The strip classes are prefixed `ecs-` (ec-strip)
 * so that, living in light DOM, they don't collide with the host page.
 *
 * Card defaults live in the base rules; the `.ecs-strip-compact` modifier
 * carries the denser popup deltas (smaller fonts/heights/gaps/bars). Per-column
 * widths are inlined from the caller's colWidth, not set here.
 */
const STRIP_CSS = `
  /* Every cell carries an inline width; border-box keeps padding INSIDE it.
     (content-box let .ecs-daylbl's 2px padding widen each cell to 66px —
     44 columns of that = 88px of phantom scroll past the strip.) */
  .ecs-strip, .ecs-strip * { box-sizing: border-box; }
  .ecs-labels { display: flex; height: 14px; margin-bottom: 4px; }
  .ecs-daylbl {
    flex: none; white-space: nowrap; font-size: 10px;
    font-weight: 600; letter-spacing: 0.07em; color: var(--ecw-muted);
    padding-left: 2px;
  }
  /* The chart band pads 14px top+bottom so the temp curve breathes; the tint
     belt covers the whole band (chart + cluster + fill), not the day-label row
     that sits above it. */
  .ecs-band { position: relative; padding: 14px 0; }
  .ecs-tints {
    position: absolute; top: 0; bottom: 0; left: 0; right: 0;
    display: flex; pointer-events: none;
  }
  /* Header row: the time label sits ABOVE its condition icon, as a caption for
     the column; the temperature cluster lives below the curve (see the DC). */
  .ecs-header { display: flex; margin-bottom: 8px; }
  .ecs-col {
    flex: none; display: flex; flex-direction: column;
    align-items: center; gap: 5px;
  }
  .ecs-time { font-size: 12px; color: var(--ecw-text2); }
  .ecs-icon { --mdc-icon-size: 22px; color: var(--ecw-text2); }
  /* Temp cluster: temp / feels-like / POP read together as a unit. Feels-like
     and POP each ALWAYS reserve their line (blank = &nbsp;) so the cluster is a
     constant height — the strip never jitters vertically hour to hour. */
  .ecs-cluster { display: flex; margin-top: 10px; }
  .ecs-cell { flex: none; text-align: center; }
  .ecs-temp { font-size: 14px; font-weight: 600; color: var(--ecw-text); }
  .ecs-fl { font-size: 10.5px; color: var(--ecw-faint); margin-top: 2px; }
  .ecs-pop { font-size: 10.5px; color: var(--ecw-pop); font-weight: 600; margin-top: 3px; }
  /* Accumulation water-fill: a level rising in a fixed-height vessel scaled to
     the window's max. No divider above it (popup rule). The vessel carries NO
     background/border, so a dry hour in a wet window is an invisible-but-space-
     reserving column and the row stays aligned. */
  .ecs-fill { display: flex; margin-top: 14px; }
  .ecs-fillcol { flex: none; display: flex; flex-direction: column; align-items: center; gap: 4px; }
  .ecs-vessel { position: relative; margin: 0 auto; overflow: hidden; }
  .ecs-amt { font-size: 9.5px; line-height: 1.2; display: flex; gap: 4px; justify-content: center; }
  .ecs-rainamt { color: var(--ecw-rain); }
  .ecs-snowamt { color: var(--ecw-snow); }

  /* Popup deltas: the same strip, one calendar day, denser (no band padding,
     tighter gaps and fonts). */
  .ecs-strip-compact .ecs-band { padding: 0; }
  .ecs-strip-compact .ecs-header { margin-bottom: 6px; }
  .ecs-strip-compact .ecs-time { font-size: 11px; }
  .ecs-strip-compact .ecs-cluster { margin-top: 8px; }
  .ecs-strip-compact .ecs-temp { font-size: 13px; }
  .ecs-strip-compact .ecs-fl { font-size: 10px; }
  .ecs-strip-compact .ecs-pop { font-size: 10px; }
  .ecs-strip-compact .ecs-fill { margin-top: 12px; }
`;

// Card-strip defaults for buildHourlyStripHtml. The popup overrides each key.
const STRIP_DEFAULTS = {
  colWidth: 64,
  curveGeometry: { chartHeight: 50, plotTop: 10, plotHeight: 30 },
  showDayBands: true,    // alternating day tints + midnight labels
  vesselWidth: 38,       // water-fill vessel px (inside each column)
  vesselHeight: 30,      // fixed vessel height; fill scales against it
  compact: false,        // toggles the .ecs-strip-compact size deltas
};

/**
 * Hour-label formatter shared by both strips. Takes a Date (callers pass
 * `new Date(timestep.time)`); 24h zero-pads to HH:00, 12h names midnight/noon
 * and uses AM/PM otherwise.
 */
export function fmtHourLabel(date, use24) {
  const hour = date.getHours();
  if (use24) return (hour < 10 ? '0' : '') + hour + ':00';
  if (hour === 0) return '12 AM';
  if (hour === 12) return '12 PM';
  return hour < 12 ? hour + ' AM' : (hour - 12) + ' PM';
}

/**
 * The one hourly-strip builder behind both the card's multi-day section and
 * the popup's single-day timeline. Returns the strip root's full HTML (a
 * positioned `.ecs-strip` wrapper); callers only add their scroll container.
 *
 * Timesteps are rendered one column each (index spacing, no time-gap
 * interpolation). Options (defaults = the card):
 *   colWidth       per-column px (inlined onto every column cell)
 *   curveGeometry  {chartHeight, plotTop, plotHeight} for buildHourlyCurve + SVG
 *   showDayBands   alternating day tints + a weekday+date label at each midnight
 *   vesselWidth    water-fill vessel width px
 *   vesselHeight   fixed water-fill vessel height px (fill scales against it)
 *   compact        emit the .ecs-strip-compact modifier (popup size deltas)
 *
 * Column order (top→bottom): day label (bands only) → time + condition icon
 * (header) → temp curve → temp + feels-like + POP% cluster → accumulation
 * water-fill zone. Invariants: feels-like and POP each ALWAYS reserve a line
 * (constant cluster height); the fill zone is omitted for the whole window when
 * NO hour has a real amount (POP alone lives in the cluster, never the fill); a
 * missing temp is a blank cell + a curve gap (isolated points become dots).
 */
export function buildHourlyStripHtml(timesteps, hass, options = {}) {
  const opts = { ...STRIP_DEFAULTS, ...options };
  const { colWidth, curveGeometry, showDayBands, vesselWidth, vesselHeight, compact } = opts;
  const use24 = use24Hour(hass);
  const dayNames = t(hass, 'days');
  const totalWidth = timesteps.length * colWidth;
  const colStyle = 'style="width:' + colWidth + 'px"';

  // Curve geometry (gaps, isolated points, area-fill rule) — see buildHourlyCurve.
  const curve = buildHourlyCurve(
    timesteps.map((ts) => (ts.temp != null ? ts.temp : null)), colWidth, curveGeometry);

  // Water-fill zone shows only when some hour has a real amount; POP never
  // gates it (POP is an always-reserved cluster line). Rain and snow scale
  // against the window's max total (guarded > 0 so a dry window can't /0).
  const qtyTotals = timesteps.map((ts) => (ts.rain_mm || 0) + (ts.snow_cm || 0));
  const hasQty = qtyTotals.some((v) => v > 0);
  const windowMaxQty = Math.max.apply(null, qtyTotals.concat([0.0001]));
  const fillPx = (v) => v > 0
    ? Math.min(vesselHeight, Math.max(3, Math.round(vesselHeight * v / windowMaxQty))) : 0;

  let dayCount = 0;
  let tintsHtml = '';
  let labelsHtml = '';
  let headerHtml = '';
  let clusterHtml = '';
  let fillHtml = '';

  timesteps.forEach((ts, i) => {
    const date = new Date(ts.time);
    const isMidnight = date.getHours() === 0;
    if (i > 0 && isMidnight) dayCount++;
    const hasTemp = ts.temp != null;

    if (showDayBands) {
      // Alternating faint tint per calendar day, label at index 0 and each midnight.
      tintsHtml += '<div style="width:' + colWidth + 'px;flex:none;height:100%;background:'
        + ((dayCount % 2) ? 'var(--ecw-tint)' : 'transparent') + '"></div>';
      const dayLabel = (i === 0 || isMidnight)
        ? dayNames[date.getDay()] + ' ' + date.getDate() : '';
      labelsHtml += '<div class="ecs-daylbl" ' + colStyle + '>' + dayLabel + '</div>';
    }

    // Header: time label over the condition icon.
    const iconHtml = ts.icon_code != null
      ? '<ha-icon icon="' + ecIcon(ts.icon_code) + '" class="ecs-icon"></ha-icon>'
      : missingIconHtml(22);
    headerHtml += '<div class="ecs-col" ' + colStyle + '>'
      + '<span class="ecs-time">' + fmtHourLabel(date, use24) + '</span>'
      + iconHtml + '</div>';

    // Cluster: temp / feels-like / POP. FL and POP always emit their line
    // (&nbsp; when absent) so the cluster height is constant.
    const feels = ts.feels_like != null ? Math.round(ts.feels_like) : null;
    const showFeels = feels !== null && hasTemp && feels !== Math.round(ts.temp);
    const pop = Math.round(ts.precipitation_probability || 0);
    clusterHtml += '<div class="ecs-cell" ' + colStyle + '>'
      + '<div class="ecs-temp">' + (hasTemp ? Math.round(ts.temp) + '°' : '') + '</div>'
      + '<div class="ecs-fl">' + (showFeels ? 'FL ' + feels + '°' : '&nbsp;') + '</div>'
      + '<div class="ecs-pop">' + (pop > 0 ? pop + '%' : '&nbsp;') + '</div>'
      + '</div>';

    // Water-fill vessel: rain rises from the bottom, snow (lighter) stacks
    // above it. An empty vessel is invisible but still reserves the column.
    if (hasQty) {
      const rain = ts.rain_mm || 0;
      const snow = ts.snow_cm || 0;
      const rainH = fillPx(rain);
      const snowH = fillPx(snow);
      let segs = '';
      if (rain > 0) {
        segs += '<div style="position:absolute;left:0;right:0;bottom:0;height:' + rainH
          + 'px;background:var(--ecw-rain);border-radius:' + (snow > 0 ? '0' : '3px 3px 0 0') + '"></div>';
      }
      if (snow > 0) {
        segs += '<div style="position:absolute;left:0;right:0;bottom:' + rainH + 'px;height:' + snowH
          + 'px;background:var(--ecw-snowbar);border-radius:3px 3px 0 0"></div>';
      }
      const rainLabel = rain > 0 ? '<span class="ecs-rainamt">' + fmtAmtUnit(rain, 'mm') + '</span>' : '';
      const snowLabel = snow > 0 ? '<span class="ecs-snowamt">' + fmtAmtUnit(snow, 'cm') + '</span>' : '';
      fillHtml += '<div class="ecs-fillcol" ' + colStyle + '>'
        + '<div class="ecs-vessel" style="width:' + vesselWidth + 'px;height:' + vesselHeight + 'px">'
        + segs + '</div>'
        + '<div class="ecs-amt">' + rainLabel + snowLabel + '</div></div>';
    }
  });

  let areaHtml = '';
  if (curve.areaPath) {
    areaHtml = '<path d="' + curve.areaPath + '" fill="url(#ecs-curve-fill)"></path>';
  }
  // Isolated points (gaps on both sides) stroke nothing as a path — draw dots
  // tinted by their own temperature (the stroke gradient can't paint a subpath
  // of zero length).
  let dotsHtml = '';
  curve.points.forEach((point) => {
    if (point && point.isolated) {
      dotsHtml += '<circle cx="' + point.x + '" cy="' + point.y
        + '" r="2.5" fill="' + point.color + '"></circle>';
    }
  });

  // Temperature-gradient stroke: one stop per present hour, colored on the
  // absolute-temperature scale (same language as the daily range bars). Offsets
  // are relative to the PATH's own x-extent (first→last present point), NOT the
  // full strip: objectBoundingBox maps offset 0/1 to the path's bounding box,
  // so a series that starts/ends on gaps still lands its stops on the right
  // hours. stop-color goes in style= (not a bare attribute) so the CSS
  // var()+fallback in each color actually resolves.
  const presentPoints = curve.points.filter((point) => point != null);
  let strokeStops = '';
  if (presentPoints.length) {
    const firstX = presentPoints[0].x;
    const extent = presentPoints[presentPoints.length - 1].x - firstX;
    presentPoints.forEach((point) => {
      const offset = extent > 0 ? Math.round(((point.x - firstX) / extent) * 1000) / 1000 : 0;
      strokeStops += '<stop offset="' + offset + '" style="stop-color:' + point.color + '"></stop>';
    });
  }

  const chartHeight = curveGeometry.chartHeight;
  const fillZoneHtml = hasQty ? '<div class="ecs-fill">' + fillHtml + '</div>' : '';
  const tintsBeltHtml = showDayBands ? '<div class="ecs-tints">' + tintsHtml + '</div>' : '';
  const labelsRowHtml = showDayBands ? '<div class="ecs-labels">' + labelsHtml + '</div>' : '';

  return '<div class="ecs-strip' + (compact ? ' ecs-strip-compact' : '')
    + '" style="width:' + totalWidth + 'px;position:relative">'
    + labelsRowHtml
    + '<div class="ecs-band">'
    + tintsBeltHtml
    + '<div style="position:relative">'
    + '<div class="ecs-header">' + headerHtml + '</div>'
    + '<svg viewBox="0 0 ' + totalWidth + ' ' + chartHeight + '" width="' + totalWidth
    + '" height="' + chartHeight + '" style="display:block">'
    + '<defs><linearGradient id="ecs-curve-fill" x1="0" y1="0" x2="0" y2="1">'
    + '<stop offset="0" stop-color="var(--ecw-curve)" stop-opacity="0.20"></stop>'
    + '<stop offset="1" stop-color="var(--ecw-curve)" stop-opacity="0"></stop></linearGradient>'
    + (strokeStops
      ? '<linearGradient id="ecs-curve-stroke" x1="0" y1="0" x2="1" y2="0">' + strokeStops + '</linearGradient>'
      : '')
    + '</defs>'
    + areaHtml
    + '<path d="' + curve.path + '" fill="none" stroke="'
    + (strokeStops ? 'url(#ecs-curve-stroke)' : 'var(--ecw-curve)')
    + '" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"></path>'
    + dotsHtml + '</svg>'
    + '<div class="ecs-cluster">' + clusterHtml + '</div>'
    + fillZoneHtml
    + '</div></div></div>';
}

/**
 * Day/Night period-card model for the daily popup. The Day half of a
 * night-only period (icon_code === null — the day has elapsed) is 'passed':
 * the card dims to a single dash instead of showing "—°" with an empty icon.
 * Otherwise it carries the half's temperature (high for day, low for night),
 * condition icon, and the raw wind/POP/precip values the renderer turns into
 * meta lines. Line-suppression rules live here so they stay testable:
 * wind via windCellState (null hides, 0 is Calm), POP only when > 0, precip
 * amounts only for types > 0.
 */
export function popupPeriodModel(item, half) {
  const isDay = half === 'day';
  if (isDay && item.icon_code === null) return { passed: true };

  const temp = isDay ? item.temp_high : item.temp_low;
  let iconCode;
  if (isDay) {
    iconCode = item.icon_code != null ? item.icon_code : null;
  } else {
    iconCode = item.icon_code_night != null ? item.icon_code_night
      : (item.icon_code != null ? item.icon_code : null);
  }
  const condition = isDay
    ? (item.condition || item.condition_night || '')
    : (item.condition_night || item.condition || '');
  const windSpeed = isDay ? item.wind_speed : item.wind_speed_night;
  const pop = isDay ? item.precip_prob_day : item.precip_prob_night;
  const rain = (isDay ? item.rain_mm_day : item.rain_mm_night) || 0;
  const snow = (isDay ? item.snow_cm_day : item.snow_cm_night) || 0;
  // Detail-view extras the compact card omits (see the popup handoff). Feels-like
  // follows the hero's rule (hidden when absent or equal to the temp after
  // rounding); UV is a Day-only line, gated on uvColor rejecting non-numbers.
  const feels = isDay ? item.feels_like_high : item.feels_like_low;
  const humidity = isDay ? item.humidity : item.humidity_night;

  return {
    passed: false,
    temp: temp != null ? temp : null,
    iconCode,
    condition,
    feels: feels != null ? feels : null,
    showFeels: feels != null && temp != null && Math.round(feels) !== Math.round(temp),
    humidity: humidity != null ? humidity : null,
    uvIndex: isDay && item.uv_index != null ? item.uv_index : null,
    uvCategory: isDay && item.uv_category != null ? item.uv_category : null,
    windState: windCellState(windSpeed),
    windSpeed,
    windGust: isDay ? item.wind_gust : item.wind_gust_night,
    windDirection: isDay ? item.wind_direction : item.wind_direction_night,
    pop: (pop != null && pop > 0) ? pop : null,
    rain,
    snow,
    showRain: rain > 0,
    showSnow: snow > 0,
  };
}

/**
 * Daily range-bar geometry against the week's min/max, in track percent.
 * The 6% minimum span width is re-clamped so left+width never exceeds the
 * track; a single value (or low == high) is a dot; an isothermal week
 * centers everything instead of dividing by zero.
 */
export function rangeBarGeometry(low, high, weekMin, weekMax) {
  const hasLow = low != null;
  const hasHigh = high != null;
  if (!hasLow && !hasHigh) return { kind: 'none' };
  const range = weekMax - weekMin;
  const pos = (temp) => range > 0 ? ((temp - weekMin) / range) * 100 : 50;
  if (hasLow && hasHigh && low !== high) {
    const width = Math.max(6, pos(high) - pos(low));
    const left = Math.max(0, Math.min(pos(low), 100 - width));
    return { kind: 'span', left, width };
  }
  const value = hasLow ? low : high;
  return { kind: 'dot', left: pos(value), value };
}

/**
 * Next sun event for the arc caption: sunset while the sun is up, sunrise
 * otherwise (today's if still ahead, tomorrow's after sunset). All times in
 * minutes since local midnight.
 */
export function nextSunEvent(nowMinutes, riseMinutes, setMinutes) {
  if (nowMinutes >= riseMinutes && nowMinutes < setMinutes) {
    return { event: 'sunset', minutesUntil: setMinutes - nowMinutes };
  }
  const minutesUntil = nowMinutes < riseMinutes
    ? riseMinutes - nowMinutes
    : riseMinutes + 1440 - nowMinutes;
  return { event: 'sunrise', minutesUntil };
}

/**
 * Sun-loop model for the arc cell: one continuous day→night loop, position
 * recomputed from `now` vs. sunrise/sunset on each render (not animated).
 *
 * Daytime (rise ≤ now ≤ set): the dot rides the top arc at fraction
 * f = (now-rise)/(set-rise); `th = π − π·f` maps f=0 → the left horizon
 * (12,26) and f=1 → the right horizon (156,26), bowing up (y = 26 − 21·sin th,
 * SVG-y grows downward so a positive sin lifts the dot above the horizon).
 * Countdown is to sunset.
 *
 * Nighttime: the dot continues BELOW the horizon along a shallower dip
 * (ry 13, not 21, so the below-horizon half stays compact). g runs from
 * sunset on the right to sunrise on the left over the night's length; elapsed
 * wraps past midnight. Countdown is to sunrise.
 *
 * Returns { phase, dot:{x,y}, event, countdownMinutes }. The dot doubles as
 * the spent-trail endpoint (the trail is drawn from the horizon to it).
 */
export function sunLoopModel(nowMinutes, riseMinutes, setMinutes) {
  const round1 = (point) => ({
    x: Math.round(point.x * 10) / 10,
    y: Math.round(point.y * 10) / 10,
  });
  if (nowMinutes >= riseMinutes && nowMinutes <= setMinutes) {
    const fraction = (nowMinutes - riseMinutes) / ((setMinutes - riseMinutes) || 1);
    const th = Math.PI - Math.PI * fraction;
    return {
      phase: 'day',
      dot: round1({ x: 84 + 72 * Math.cos(th), y: 26 - 21 * Math.sin(th) }),
      event: 'sunset',
      countdownMinutes: setMinutes - nowMinutes,
    };
  }
  const elapsed = nowMinutes > setMinutes
    ? nowMinutes - setMinutes : nowMinutes + 1440 - setMinutes;
  const g = elapsed / ((1440 - (setMinutes - riseMinutes)) || 1);
  const th = Math.PI * g;
  const countdown = nowMinutes > setMinutes
    ? (1440 - nowMinutes) + riseMinutes : riseMinutes - nowMinutes;
  return {
    phase: 'night',
    dot: round1({ x: 84 + 72 * Math.cos(th), y: 26 + 13 * Math.sin(th) }),
    event: 'sunrise',
    countdownMinutes: countdown,
  };
}

/**
 * Stale-banner decision. Measures the integration's success heartbeat
 * (attributes.fetched_at, stamped on every successful EC fetch), NOT
 * last_updated — HA only writes a new state object when a value changes,
 * so a stable temperature makes last_updated look hours old across
 * perfectly healthy refreshes. last_updated is only the fallback for
 * servers running an older integration build without the heartbeat.
 * Returns { agoHours } past the 2 h threshold, else null.
 */
export function staleInfo(tempState, nowMs) {
  if (!tempState) return null;
  const heartbeat = (tempState.attributes && tempState.attributes.fetched_at)
    || tempState.last_updated;
  if (!heartbeat) return null;
  const heartbeatMs = new Date(heartbeat).getTime();
  if (!Number.isFinite(heartbeatMs)) return null;
  const ageMinutes = (nowMs - heartbeatMs) / 60000;
  if (ageMinutes <= 120) return null;
  return { agoHours: Math.round(ageMinutes / 60) };
}

/** Escape HTML special characters to prevent XSS from API-sourced strings. */
export function escapeHtml(str) {
  if (str == null) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

export function t(hass, key) {
  const lang = (hass && hass.language) || 'en';
  const strings = I18N[lang] || I18N.en;
  return strings[key] != null ? strings[key] : (I18N.en[key] != null ? I18N.en[key] : key);
}

const VALID_SECTIONS = ['alerts', 'current', 'hourly', 'daily'];

// Entity IDs consumed by each section
const SECTION_ENTITIES = {
  alerts: [
    'binary_sensor.ec_alert_active',
    'sensor.ec_alerts',
  ],
  current: [
    'sensor.ec_temperature',
    'sensor.ec_feels_like',
    'sensor.ec_wind_speed',
    'sensor.ec_wind_direction',
    'sensor.ec_condition',
    'sensor.ec_icon_code',
    // sensor.ec_sunrise / ec_sunset are optional — their absence renders the
    // polar day/night sun states, so they must not block availability.
    // sensor.ec_humidity, ec_wind_gust, ec_air_quality and the
    // sensor.ec_yesterday_* family are optional — read but don't block.
  ],
  hourly: [
    'sensor.ec_hourly_forecast',
  ],
  daily: [
    'sensor.ec_daily_forecast',
  ],
};

// Entities a section reads for display but must NOT gate availability on —
// they still need to trigger a re-render when they change. Without this,
// e.g. the precip panel keeps saying 'None expected' from before the daily
// forecast populated, until an unrelated current sensor happens to change.
const SECTION_WATCH = {
  current: [
    'sensor.ec_daily_forecast',
    'sensor.ec_sunrise',
    'sensor.ec_sunset',
    'sensor.ec_humidity',
    'sensor.ec_wind_gust',
    'sensor.ec_air_quality',
    'sensor.ec_yesterday_precipitation',
    'sensor.ec_yesterday_rain',
    'sensor.ec_yesterday_snow',
  ],
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

export function ecIcon(code) {
  return EC_ICON_MAP[code] || 'mdi:weather-cloudy';
}

export function titleCase(str) {
  if (!str) return '';
  return str.replace(/\b\w/g, c => c.toUpperCase());
}

export function fmtAmt(val) {
  if (val == null || val <= 0) return null;
  return val < 1 ? '<1' : String(Math.round(val));
}

/**
 * Compact amount+unit with NO space ("3mm", "<1mm", "5cm") — the design
 * audit's one consistent format across the precip panel, hourly fill labels,
 * daily amounts, and popup period lines. Returns null for absent/zero amounts
 * (call sites guard on > 0 before appending).
 */
export function fmtAmtUnit(value, unit) {
  const amt = fmtAmt(value);
  return amt === null ? null : amt + unit;
}

/** Determine precip color based on rain/snow amounts and precip type. */
export function precipAmtColor(rain, snow, precipType) {
  if ((snow || 0) > 0 && (rain || 0) > 0) return 'var(--ec-weather-precip-rain, #4FC3F7)';
  if ((snow || 0) > 0) return 'var(--ec-weather-precip-snow, var(--primary-text-color, rgba(255,255,255,0.85)))';
  if ((rain || 0) > 0) return 'var(--ec-weather-precip-rain, #4FC3F7)';
  if (precipType === 'snow') return 'var(--ec-weather-precip-snow, var(--primary-text-color, rgba(255,255,255,0.85)))';
  return 'var(--ec-weather-precip-rain, #4FC3F7)';
}

/**
 * Single source of truth for a day's precipitation summary, used by both the
 * daily column and the current-conditions "today" line so they never diverge.
 *
 * POP is max(day, night) rounded up to the nearest 5%; shown only when >= 5%.
 * Amounts prefer EC accumulation (meteorologist-interpreted, days 0-2) and
 * fall back to WEonG model amounts. Rain (mm) and snow (cm) are kept separate
 * — different units, never summed.
 */
export function dailyPrecip(item) {
  const popDay = item.precip_prob_day || 0;
  const popNight = item.precip_prob_night || 0;
  const popRounded = Math.ceil(Math.max(popDay, popNight) / 5) * 5;

  const ecAccumDay = item.precip_accum_amount || 0;
  const ecAccumNight = item.precip_accum_amount_night || 0;
  const ecAccumUnit = item.precip_accum_unit || item.precip_accum_unit_night || '';
  let rainAmt, snowAmt;
  if (ecAccumDay > 0 || ecAccumNight > 0) {
    const ecTotal = ecAccumDay + ecAccumNight;
    if (ecAccumUnit === 'cm') { rainAmt = 0; snowAmt = ecTotal; }
    else { rainAmt = ecTotal; snowAmt = 0; }
  } else {
    rainAmt = (item.rain_mm_day || 0) + (item.rain_mm_night || 0);
    snowAmt = (item.snow_cm_day || 0) + (item.snow_cm_night || 0);
  }

  return {
    popRounded,
    showPrecip: popRounded >= 5,
    rainAmt,
    snowAmt,
    pColor: precipAmtColor(rainAmt, snowAmt, item.precip_type),
  };
}

/** Read an entity state, returning null if unavailable/unknown/missing. */
export function entityVal(hass, entityId) {
  const s = hass.states[entityId];
  if (!s || s.state === 'unavailable' || s.state === 'unknown') return null;
  return s.state;
}

/** Read an entity state as a number, returning null if invalid. */
export function entityNum(hass, entityId) {
  const v = entityVal(hass, entityId);
  if (v === null) return null;
  const n = parseFloat(v);
  return isNaN(n) ? null : n;
}

// ─── Reusable Overlay ────────────────────────────────────────────────────────
//
// Persistent popup overlay that lives outside the card render cycle.
// Created once, attached to document.body, reused by any section.
// Card re-renders never touch this element.
//
// Usage:
//   const overlay = ECOverlay.get();             // shared instance
//   overlay.open(ownerRef, htmlContent);          // show with content
//   overlay.update(ownerRef, htmlContent);        // update if owner matches
//   overlay.close();                              // hide
//   overlay.onClose = () => { ... };              // callback when closed

class ECOverlay {
  static _instance = null;

  static get() {
    if (!ECOverlay._instance) {
      ECOverlay._instance = new ECOverlay();
    }
    return ECOverlay._instance;
  }

  constructor() {
    this._el = document.createElement('div');
    this._el.innerHTML = `
      <style>
        .ec-overlay { display: none; position: fixed; inset: 0; z-index: 999; align-items: center; justify-content: center; }
        .ec-overlay.open { display: flex; }
        .ec-overlay-backdrop { position: absolute; inset: 0; background: var(--mdc-dialog-scrim-color, rgba(0,0,0,0.8)); }
        .ec-overlay-content {
          position: relative; z-index: 1;
          background: var(--primary-background-color, #0a1520); border-radius: 12px;
          padding: 24px; max-width: 420px; width: 90vw;
          max-height: 85vh; overflow-y: auto;
          scrollbar-width: none; touch-action: pan-y;
          transition: transform 150ms ease;
        }
        .ec-overlay-content::-webkit-scrollbar { display: none; }
        .ec-overlay-close {
          position: absolute; top: 12px; right: 12px;
          background: none; border: none; color: var(--secondary-text-color, rgba(255,255,255,0.5));
          font-size: 20px; cursor: pointer; padding: 4px 8px; line-height: 1;
        }
        .ec-overlay-close:hover { color: var(--primary-text-color, #fff); }
        @media (max-width: 768px) {
          .ec-overlay-content {
            max-width: 100%; width: 100%; max-height: 100%; height: 100%;
            border-radius: 0; box-sizing: border-box;
          }
        }
      </style>
      <div class="ec-overlay">
        <div class="ec-overlay-backdrop"></div>
        <div class="ec-overlay-content">
          <button class="ec-overlay-close">\u2715</button>
          <div class="ec-overlay-body"></div>
        </div>
      </div>
    `;
    document.body.appendChild(this._el);

    this._overlay = this._el.querySelector('.ec-overlay');
    this._body = this._el.querySelector('.ec-overlay-body');
    this._content = this._el.querySelector('.ec-overlay-content');
    this.onClose = null;
    this.isOpen = false;
    this._owner = null;  // reference to the card instance that opened the overlay

    // Close on backdrop click
    this._el.querySelector('.ec-overlay-backdrop').addEventListener('click', () => this.close());
    this._el.querySelector('.ec-overlay-close').addEventListener('click', () => this.close());

    // Escape key
    this._escHandler = (e) => { if (e.key === 'Escape' && this.isOpen) this.close(); };
    document.addEventListener('keydown', this._escHandler);

    // Swipe down to close (mobile)
    this._touchStartY = 0;
    this._touchCurrentY = 0;
    this._isDragging = false;

    this._content.addEventListener('touchstart', (e) => {
      if (this._content.scrollTop > 0) return;
      this._touchStartY = e.touches[0].clientY;
      this._touchCurrentY = this._touchStartY;
      this._isDragging = false;
    }, { passive: true });

    this._content.addEventListener('touchmove', (e) => {
      if (!this._touchStartY) return;
      this._touchCurrentY = e.touches[0].clientY;
      const delta = this._touchCurrentY - this._touchStartY;
      if (delta > 10) {
        this._isDragging = true;
        e.preventDefault();
        this._content.style.transform = 'translateY(' + delta + 'px)';
        this._content.style.transition = 'none';
      }
    }, { passive: false });

    this._content.addEventListener('touchend', () => {
      const delta = this._touchCurrentY - this._touchStartY;
      if (this._isDragging && delta > 80) {
        this._content.style.transition = 'transform 200ms ease';
        this._content.style.transform = 'translateY(100vh)';
        setTimeout(() => this.close(), 200);
      } else {
        this._content.style.transition = 'transform 150ms ease';
        this._content.style.transform = '';
      }
      this._touchStartY = 0;
      this._touchCurrentY = 0;
      this._isDragging = false;
    }, { passive: true });
  }

  open(owner, htmlContent) {
    // If another caller had the overlay open, notify it that it's being replaced
    if (this.isOpen && this.onClose) {
      this.onClose();
    }
    this._owner = owner;
    this.onClose = null;
    this._body.innerHTML = htmlContent;
    this._overlay.classList.add('open');
    this._content.style.transform = '';
    document.body.style.overflow = 'hidden';
    this.isOpen = true;
  }

  update(owner, htmlContent) {
    // Only the card that opened the overlay can update it
    if (this.isOpen && this._owner === owner) {
      this._body.innerHTML = htmlContent;
    }
  }

  close() {
    this._overlay.classList.remove('open');
    document.body.style.overflow = '';
    this.isOpen = false;
    this._owner = null;
    if (this.onClose) {
      this.onClose();
      this.onClose = null;
    }
  }
}


// ─── Card Class ──────────────────────────────────────────────────────────────

export class ECWeatherCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._config = null;
    this._rendered = false;
    this._expandedAlerts = new Set();
  }

  setConfig(config) {
    if (!config.section || !VALID_SECTIONS.includes(config.section)) {
      throw new Error(
        `ec-weather-card: invalid section "${config.section}". ` +
        `Valid: ${VALID_SECTIONS.join(', ')}`
      );
    }
    this._config = config;
    this._rendered = false;
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;

    if (!hass) return;

    // On-demand refresh: trigger update_entity if data might be stale.
    // Only the 'current' section triggers refresh (avoids 4 sections all firing).
    if (this._config.section === 'current' && !this._refreshTriggered) {
      const tempState = hass.states['sensor.ec_temperature'];
      if (tempState && tempState.state !== 'unavailable') {
        const lastUpdated = new Date(tempState.last_updated);
        const ageMinutes = (Date.now() - lastUpdated.getTime()) / 60000;
        if (ageMinutes > 30) {
          this._refreshTriggered = true;
          hass.callService('homeassistant', 'update_entity', {
            entity_id: [
              'sensor.ec_temperature',
              'sensor.ec_hourly_forecast',
              'sensor.ec_daily_forecast',
            ],
          });
        }
      }
    }

    // Check if required entities are available
    const entities = SECTION_ENTITIES[this._config.section] || [];
    const allAvailable = entities.every(e => {
      const state = hass.states[e];
      return state && state.state !== 'unavailable';
    });

    if (!allAvailable) {
      this._renderUnavailable();
      return;
    }

    // Change detection covers required + watched entities (SECTION_WATCH):
    // optional data sources must re-render too, they just don't gate
    // availability above.
    const watched = entities.concat(SECTION_WATCH[this._config.section] || []);

    // Reset refresh trigger when entities actually change
    if (oldHass && this._refreshTriggered) {
      const changed = watched.some(e => oldHass.states[e] !== hass.states[e]);
      if (changed) this._refreshTriggered = false;
    }

    // Only re-render if relevant entities changed
    if (oldHass) {
      const changed = watched.some(e => oldHass.states[e] !== hass.states[e]);
      if (!changed) return;
    }

    this._updateDisplay();
  }

  getCardSize() {
    switch (this._config?.section) {
      case 'alerts': return 1;
      case 'current': return 3;
      case 'hourly': return 4;
      case 'daily': return 4;
      default: return 1;
    }
  }

  _renderUnavailable() {
    const h = this._hass;

    // Alerts: always hide when unavailable (same as no alerts)
    if (this._config.section === 'alerts') {
      this.shadowRoot.innerHTML = '';
      this._rendered = true;
      return;
    }

    this._rendered = true;

    const stateCss = `
      :host { display: block; contain: inline-size; }
      ${TOKEN_CSS}
      @keyframes spin { to { transform: rotate(360deg); } }
      .seclbl {
        font-size: 11.5px; font-weight: 600; letter-spacing: 0.11em;
        color: var(--ecw-muted); text-transform: uppercase;
        margin-top: 24px; margin-bottom: 12px;
      }
      .ustate {
        display: flex; flex-direction: column; align-items: center;
        justify-content: center; gap: 12px; padding: 44px 20px;
        min-height: 170px; text-align: center;
      }
      .uicon { --mdc-icon-size: 42px; color: var(--ecw-muted); }
      .utitle { font-size: 17px; font-weight: 600; color: var(--ecw-text); }
      .umsg { font-size: 13.5px; color: var(--ecw-text2); max-width: 320px; line-height: 1.45; }
      .ubtn {
        display: inline-flex; align-items: center; gap: 7px; margin-top: 4px;
        padding: 9px 18px; border-radius: 10px; border: 1px solid var(--ecw-btnbd);
        background: var(--ecw-btnbg); color: var(--ecw-text); font-family: inherit;
        font-size: 13.5px; font-weight: 500; cursor: pointer;
      }
      .ubtn ha-icon { --mdc-icon-size: 17px; }
      .umeta { font-size: 11.5px; color: var(--ecw-muted); }
    `;

    // Hourly/daily while the weather coordinator is up: WEonG data is still
    // loading → quiet transient spinner, no error styling. If the weather
    // coordinator is down too, it's a real outage — hide entirely (the
    // current section carries the single unavailable state).
    if (this._config.section === 'hourly' || this._config.section === 'daily') {
      const tempState = h?.states?.['sensor.ec_temperature'];
      const weatherUp = tempState && tempState.state !== 'unavailable';
      if (weatherUp) {
        const title = this._config.section === 'hourly' ? t(h, 'hourly') : t(h, 'week');
        this.shadowRoot.innerHTML = `
          <style>${stateCss}</style>
          <div class="${themeClass(h)}">
            <div class="seclbl">${title}</div>
            <div class="ustate" style="min-height:90px;padding:20px">
              <ha-icon icon="mdi:loading" class="uicon" style="--mdc-icon-size:26px;animation:spin 1s linear infinite"></ha-icon>
              <div class="umsg">${t(h, 'loading')}</div>
            </div>
          </div>
        `;
        return;
      }
      this.shadowRoot.innerHTML = '';
      return;
    }

    // Single "Weather unavailable" state: quiet icon + title + explanation +
    // retry + last-updated time. No fake zeros.
    const tempState = h?.states?.['sensor.ec_temperature'];
    let updatedMeta = '';
    if (tempState && tempState.last_updated) {
      const updDate = new Date(tempState.last_updated);
      if (!isNaN(updDate)) {
        const lang = (h && h.language) || 'en';
        const timeStr = updDate.toLocaleTimeString(lang === 'fr' ? 'fr-CA' : 'en-CA', {
          hour: 'numeric', minute: '2-digit',
        });
        updatedMeta = '<div class="umeta">' + t(h, 'updatedAt') + ' ' + timeStr + '</div>';
      }
    }

    this.shadowRoot.innerHTML = `
      <style>${stateCss}</style>
      <div class="${themeClass(h)}">
        <div class="ustate">
          <ha-icon icon="mdi:cloud-off-outline" class="uicon"></ha-icon>
          <div class="utitle">${t(h, 'weatherUnavailable')}</div>
          <div class="umsg">${t(h, 'unavailableMsg')}</div>
          <button class="ubtn" id="retry">
            <ha-icon icon="mdi:refresh"></ha-icon>${t(h, 'retry')}
          </button>
          ${updatedMeta}
        </div>
      </div>
    `;

    this.shadowRoot.getElementById('retry').addEventListener('click', () => {
      if (!this._hass) return;
      this._hass.callService('homeassistant', 'update_entity', {
        entity_id: 'sensor.ec_temperature',
      });
    });
  }

  _updateDisplay() {
    this._rendered = true;
    switch (this._config.section) {
      case 'alerts':  this._renderAlerts(); break;
      case 'current': this._renderCurrent(); break;
      case 'hourly':  this._renderHourly(); break;
      case 'daily':   this._renderDaily(); break;
    }
  }

  // ─── Section Renderers (to be implemented per phase) ─────────────────────

  _renderAlerts() {
    const h = this._hass;
    const active = entityVal(h, 'binary_sensor.ec_alert_active');
    const alertsSensor = h.states['sensor.ec_alerts'];
    const alerts = alertsSensor?.attributes?.alerts;

    // Hide entirely when no alerts
    if (active !== 'on' || !alerts || alerts.length === 0) {
      this.shadowRoot.innerHTML = '';
      return;
    }

    const lang = (h && h.language) || 'en';
    const fmtExp = (iso) => {
      if (!iso) return '';
      const d = new Date(iso);
      if (isNaN(d)) return '';
      return d.toLocaleDateString(lang === 'fr' ? 'fr-CA' : 'en-CA', {
        weekday: 'short', month: 'short', day: 'numeric',
        hour: 'numeric', minute: '2-digit',
      });
    };

    // One neutral style for every warning type — severity never colors the bar.
    let bannersHtml = '';
    alerts.forEach((alert, i) => {
      const headline = escapeHtml(titleCase(alert.headline || alert.type));
      const exp = fmtExp(alert.expires);
      const expLine = exp
        ? '<div style="margin-bottom:8px;font-weight:500;opacity:0.85">' + t(h, 'expires') + ': ' + exp + '</div>'
        : '';
      const text = escapeHtml(alert.text || '');

      bannersHtml += `
        <div class="alert-wrap">
          <div class="alert-header" data-index="${i}">
            <ha-icon icon="mdi:alert-outline" class="alert-icon"></ha-icon>
            <span class="alert-title">${headline}</span>
          </div>
          <div class="alert-detail" id="alert-detail-${i}">
            ${expLine}${text}
          </div>
        </div>`;
    });

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; margin-bottom: 16px; contain: inline-size; }
        ${TOKEN_CSS}
        .alert-stack {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .alert-wrap {
          width: 100%;
          border: 1px solid var(--ecw-alertbd);
          border-radius: 12px;
          overflow: hidden;
          box-sizing: border-box;
        }
        .alert-header {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 10px;
          width: 100%;
          /* border-box, or width:100% + padding pushes the box past the wrap
             and the "centered" icon+title sit ~13px right of true center
             (most visible on narrow tiles). */
          box-sizing: border-box;
          padding: 13px;
          cursor: pointer;
          pointer-events: auto;
        }
        .alert-icon {
          --mdc-icon-size: 22px;
          color: var(--ecw-text);
          flex-shrink: 0;
        }
        .alert-title {
          font-size: 16px;
          font-weight: 500;
          text-align: center;
          color: var(--ecw-text);
        }
        .alert-detail {
          display: none;
          padding: 0 14px 13px;
          font-size: 13px;
          color: var(--ecw-text2);
          white-space: pre-wrap;
          line-height: 1.4;
          text-align: left;
        }
      </style>
      <div class="${themeClass(h)}"><div class="alert-stack" id="alerts">${bannersHtml}</div></div>
    `;

    // Restore expanded state and attach click handlers
    this.shadowRoot.querySelectorAll('.alert-header').forEach(el => {
      const idx = el.dataset.index;
      const detail = this.shadowRoot.getElementById('alert-detail-' + idx);
      if (detail && this._expandedAlerts.has(idx)) {
        detail.style.display = 'block';
      }
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        if (!detail) return;
        const isHidden = getComputedStyle(detail).display === 'none';
        detail.style.display = isHidden ? 'block' : 'none';
        if (isHidden) {
          this._expandedAlerts.add(idx);
        } else {
          this._expandedAlerts.delete(idx);
        }
      });
    });
  }

  _renderCurrent() {
    const h = this._hass;
    const lang = (h && h.language) || 'en';

    // ── Hero: temperature + condition + feels-like ─────────────────────────
    const temp = entityNum(h, 'sensor.ec_temperature');
    const feelsRaw = entityNum(h, 'sensor.ec_feels_like');
    const tVal = temp !== null ? Math.round(temp) : null;
    const feels = feelsRaw !== null ? Math.round(feelsRaw) : null;
    // Feels-like is dropped when absent OR equal to the temperature.
    const showFeels = feels !== null && tVal !== null && feels !== tVal;
    const condition = entityVal(h, 'sensor.ec_condition');
    const iconCode = entityNum(h, 'sensor.ec_icon_code');
    const heroIconHtml = iconCode !== null
      ? '<ha-icon icon="' + ecIcon(iconCode) + '" class="heroicon"></ha-icon>'
      : missingIconHtml(52);
    const tempText = tVal !== null ? tVal + '°' : '—°';
    const condText = condition ? escapeHtml(titleCase(condition)) : '—';
    const feelsHtml = showFeels
      ? '<span class="hfeels"> · ' + t(h, 'feels').toLowerCase() + ' ' + feels + '°</span>'
      : '';

    // ── Precipitation panel ─────────────────────────────────────────────────
    // Today's row shares dailyPrecip() with the daily column so they never
    // diverge. A dry today collapses its row; the header shows "None expected"
    // where the chance % normally sits.
    const todayEntry = (h.states['sensor.ec_daily_forecast']
      ?.attributes?.forecast || [])[0];
    const todayPrecip = todayEntry ? dailyPrecip(todayEntry) : null;
    const todayRain = todayPrecip ? todayPrecip.rainAmt : 0;
    const todaySnow = todayPrecip ? todayPrecip.snowAmt : 0;
    const todayWet = todayRain > 0 || todaySnow > 0;

    // Yesterday: null = opted out (row omitted entirely); 'pending' = opted in
    // but EC hasn't published ("No data"); otherwise {rain, snow} measured.
    // Combined stations report the melted water equivalent as one total —
    // rendered as water only, with the explanatory tooltip.
    let yday = null;
    let ydayTooltip = '';
    const ydayState = h.states['sensor.ec_yesterday_precipitation'];
    if (ydayState) {
      const ydayAttrs = ydayState.attributes || {};
      const ydayTotal = entityNum(h, 'sensor.ec_yesterday_precipitation');
      if (!ydayAttrs.published || ydayTotal === null) {
        yday = 'pending';
      } else if (ydayAttrs.data_type === 'split') {
        yday = {
          rain: entityNum(h, 'sensor.ec_yesterday_rain') || 0,
          snow: entityNum(h, 'sensor.ec_yesterday_snow') || 0,
        };
      } else {
        yday = { rain: ydayTotal, snow: 0 };
        ydayTooltip = t(h, 'yesterdayCombinedTooltip');
      }
    }
    const ydayWet = yday !== null && yday !== 'pending'
      && (yday.rain > 0 || yday.snow > 0);

    // Bars scale to the largest row via liquid equivalent (1 cm snow ~ 1 mm
    // water) so a heavy dump can't overflow the panel.
    const wetTotals = [];
    if (todayWet) wetTotals.push(liquidTotal(todayRain, todaySnow));
    if (ydayWet) wetTotals.push(liquidTotal(yday.rain, yday.snow));
    const barRef = wetTotals.length ? Math.max.apply(null, wetTotals) : 1;

    const chipHtml = (icon, colorVar, text) =>
      '<span class="pv" style="color:' + colorVar + '">'
      + '<ha-icon icon="' + icon + '"></ha-icon>' + text + '</span>';
    const segHtml = (amount, background) =>
      '<div style="width:' + Math.max(3, Math.round(amount / barRef * 90))
      + '%;background:' + background + '"></div>';

    const wetRowHtml = (label, rain, snow, tooltip) => {
      let chips = '';
      let segs = '';
      if (rain > 0) {
        chips += chipHtml('mdi:water', 'var(--ecw-rain)', fmtAmtUnit(rain, 'mm'));
        segs += segHtml(rain, 'var(--ecw-rain)');
      }
      if (snow > 0) {
        chips += chipHtml('mdi:snowflake', 'var(--ecw-snow)', fmtAmtUnit(snow, 'cm'));
        segs += segHtml(snow, 'var(--ecw-snowbar)');
      }
      return '<div class="prow"' + (tooltip ? ' title="' + escapeHtml(tooltip) + '"' : '') + '>'
        + '<div class="prowhead"><span class="plabel">' + label + '</span>'
        + '<span class="pchips">' + chips + '</span></div>'
        + '<div class="pbar">' + segs + '</div></div>';
    };
    const dryRowHtml = (label, statusText) =>
      '<div class="prow"><div class="prowhead"><span class="plabel">' + label
      + '</span><span class="pstatus">' + statusText + '</span></div></div>';

    let panelRows = '';
    if (todayWet) panelRows += wetRowHtml(t(h, 'todayForecast'), todayRain, todaySnow, '');
    if (yday === 'pending') panelRows += dryRowHtml(t(h, 'yesterday'), t(h, 'noData'));
    else if (ydayWet) panelRows += wetRowHtml(t(h, 'yesterday'), yday.rain, yday.snow, ydayTooltip);
    else if (yday !== null) panelRows += dryRowHtml(t(h, 'yesterday'), t(h, 'none'));

    const headState = precipPanelHead(todayPrecip);
    let panelHeadRight = '';
    if (headState.kind === 'none-expected') {
      panelHeadRight = '<span class="phead-none">' + t(h, 'noneExpected') + '</span>';
    } else if (headState.kind === 'chance') {
      panelHeadRight = '<span class="phead-chance">' + headState.popRounded
        + '% ' + t(h, 'chance') + '</span>';
    }

    const panelHtml = '<div class="ppanel">'
      + '<div class="phead"><span class="ptitle">'
      + '<ha-icon icon="mdi:weather-snowy-rainy"></ha-icon>' + t(h, 'precipTitle')
      + '</span>' + panelHeadRight + '</div>'
      + panelRows + '</div>';

    // ── Metric bar: humidity · wind · AQHI · UV · sun ───────────────────────
    // Cells with no data are not rendered; the rest reflow evenly (flex).
    const humidity = entityNum(h, 'sensor.ec_humidity');
    const windSpeed = entityNum(h, 'sensor.ec_wind_speed');
    const windGust = entityNum(h, 'sensor.ec_wind_gust');
    const windDir = entityVal(h, 'sensor.ec_wind_direction');
    const windState = windCellState(windSpeed);
    // Headline is speed + unit ("12 km/h") so it survives the narrow-tile wrap
    // unambiguously; the secondary line carries direction and gusts joined by a
    // middot ("NW · gusts 29"). Either can be absent: dir-only "NW", gust-only
    // "gusts 29", calm → a reserved blank secondary.
    const windText = windState === 'calm' ? t(h, 'calm') : Math.round(windSpeed) + ' km/h';
    let gustText = '';
    if (windState === 'value') {
      const subParts = [];
      if (windDir) subParts.push(escapeHtml(windDir));
      if (windGust !== null) subParts.push(t(h, 'gusts') + ' ' + Math.round(windGust) + ' km/h');
      gustText = subParts.join(' · ');
    }

    const aqhi = entityNum(h, 'sensor.ec_air_quality');
    const aqhiCol = aqhiColor(aqhi);
    const uvIndex = todayEntry && todayEntry.uv_index != null ? todayEntry.uv_index : null;
    const uvCol = uvColor(uvIndex);

    const metricCell = (icon, valueText, label, color) => {
      const tint = color ? ' style="color:' + color + '"' : '';
      return '<div class="mcell"><ha-icon icon="' + icon + '" class="mi"' + tint + '></ha-icon>'
        + '<span class="mv"' + tint + '>' + valueText + '</span>'
        + '<span class="ml">' + label + '</span></div>';
    };

    let cellsHtml = '';
    if (humidity !== null) {
      cellsHtml += metricCell('mdi:water-percent', Math.round(humidity) + '%',
        t(h, 'humidity').toLowerCase(), '');
    }
    if (windState !== 'hidden') {
      cellsHtml += '<div class="mcell"><ha-icon icon="mdi:weather-windy" class="mi"></ha-icon>'
        + '<span class="mv">' + windText + '</span>'
        + '<span class="ml">' + (gustText || '&nbsp;') + '</span></div>';
    }
    if (aqhiCol) cellsHtml += metricCell('mdi:air-filter', String(Math.round(aqhi)), t(h, 'aqhiLabel'), aqhiCol);
    if (uvCol) cellsHtml += metricCell('mdi:white-balance-sunny', String(uvIndex), 'UV', uvCol);

    // ── Sun cell: arc with the dot placed by time of day; polar day/night
    // only at polar latitudes (sunCellMode) — transient rise/set outages
    // hide the cell instead of claiming 'Polar night' at 45°N ──
    const sunrise = entityVal(h, 'sensor.ec_sunrise');
    const sunset = entityVal(h, 'sensor.ec_sunset');
    const latitude = h.config != null ? h.config.latitude : null;
    const sunMode = sunCellMode(sunrise, sunset, latitude, h.states['sun.sun']?.state);
    const toMinutes = (hhmm) => {
      const parts = hhmm.split(':');
      return parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
    };
    const fmtClock = (hhmm) => {
      if (use24Hour(h)) return hhmm;
      const parts = hhmm.split(':');
      let hour = parseInt(parts[0], 10);
      const ampm = hour < 12 ? 'AM' : 'PM';
      hour = hour % 12 || 12;
      return hour + ':' + parts[1] + ' ' + ampm;
    };
    // Countdown format per the design: EN "9h 46m" (minutes-only "46m");
    // FR "9 h 46" — no zero-padding, no trailing minutes unit.
    const fmtDuration = (minutes) => {
      const total = Math.max(0, Math.round(minutes));
      const hours = Math.floor(total / 60);
      const mins = total % 60;
      return (hours ? hours + (lang === 'fr' ? ' h ' : 'h ') : '')
        + mins + (lang === 'fr' ? '' : 'm');
    };

    // Shared sun-loop SVG pieces. The dip guide (rx 72, ry 13 — shallower
    // than the day arc so the below-horizon half stays compact) makes the
    // whole loop visible; the 48px box exists to fit it, so every mode that
    // draws the dip uses viewBox 168x48 (polar day stays 30 — no dip).
    const horizonLine = '<line x1="8" y1="26" x2="160" y2="26" stroke="var(--ecw-hair)" stroke-width="1"></line>';
    const baseArc = '<path d="M12,26 A72,21 0 0 1 156,26" fill="none" stroke="var(--ecw-sunarc)" stroke-width="1.5" stroke-dasharray="1.5 3.5" stroke-linecap="round"></path>';
    const dipGuide = '<path d="M12,26 A72,13 0 0 0 156,26" fill="none" stroke="var(--ecw-sunarc)" stroke-width="1.5" stroke-dasharray="1.5 3.5" stroke-linecap="round" opacity="0.4"></path>';
    const sunSvg = (kids, withDip) => {
      const boxHeight = withDip ? 48 : 30;
      return '<svg width="168" height="' + boxHeight + '" viewBox="0 0 168 ' + boxHeight
        + '" style="display:block;overflow:visible">' + kids + '</svg>';
    };
    const glowDot = (x, y, fill) =>
      '<circle cx="' + x + '" cy="' + y + '" r="7" fill="var(--ecw-sunglow)"></circle>'
      + '<circle cx="' + x + '" cy="' + y + '" r="3.5" fill="' + fill + '"></circle>';

    let sunCellHtml = '';
    if (sunMode === 'arc') {
      const riseMin = toMinutes(sunrise);
      const setMin = toMinutes(sunset);
      const now = new Date();
      const nowMin = now.getHours() * 60 + now.getMinutes();
      // One continuous loop: dot on the top arc by day, on the below-horizon
      // dip by night, with a solid spent trail over the traveled part
      // (sunLoopModel, vitest-covered).
      const loop = sunLoopModel(nowMin, riseMin, setMin);
      const spentTrail = loop.phase === 'day'
        ? '<path d="M12,26 A72,21 0 0 1 ' + loop.dot.x + ',' + loop.dot.y
          + '" fill="none" stroke="var(--ecw-sun)" stroke-width="1.6" stroke-linecap="round" opacity="0.55"></path>'
        : '<path d="M12,26 A72,13 0 0 0 ' + loop.dot.x + ',' + loop.dot.y
          + '" fill="none" stroke="var(--ecw-muted)" stroke-width="1.6" stroke-linecap="round" opacity="0.5"></path>';
      const dotFill = loop.phase === 'day' ? 'var(--ecw-sun)' : 'var(--ecw-muted)';
      // Countdown first, then the daylight duration (user feedback kept it
      // over the DC's countdown-only caption): "sets in 1h 26m · 15h 38m of
      // daylight".
      const daylightMin = Math.max(1, setMin - riseMin);
      const caption = t(h, loop.event === 'sunset' ? 'sunsetIn' : 'sunriseIn')
        + ' ' + fmtDuration(loop.countdownMinutes)
        + ' · ' + fmtDuration(daylightMin) + ' ' + t(h, 'ofDaylight');
      sunCellHtml = '<div class="mcell sun">'
        + sunSvg(horizonLine + baseArc + dipGuide + spentTrail
          + glowDot(loop.dot.x, loop.dot.y, dotFill), true)
        + '<div class="suntimes">'
        + '<span><ha-icon icon="mdi:weather-sunset-up"></ha-icon> ' + fmtClock(sunrise) + '</span>'
        + '<span>' + fmtClock(sunset) + ' <ha-icon icon="mdi:weather-sunset-down"></ha-icon></span>'
        + '</div>'
        + '<span class="suncap">' + caption + '</span>'
        + '</div>';
    } else if (sunMode === 'polar-day') {
      // Dot parked at the day arc's apex (dayPt(0.5) = 84,5) on a SOLID lit
      // arc — the sun never sets, so no dip, no times, cap only.
      const litArc = '<path d="M12,26 A72,21 0 0 1 156,26" fill="none" stroke="var(--ecw-sun)" stroke-width="1.6" stroke-linecap="round"></path>';
      sunCellHtml = '<div class="mcell sun">'
        + sunSvg(horizonLine + litArc + glowDot(84, 5, 'var(--ecw-sun)'), false)
        + '<span class="suncap suncap-title">' + t(h, 'sunUpAllDay') + '</span>'
        + '</div>';
    } else if (sunMode === 'polar-night') {
      // Dot resting at the dip's bottom (nightPt(0.5) = 84,39); the base arc
      // and dip guide stay idle above it. Cap only, no subline.
      sunCellHtml = '<div class="mcell sun">'
        + sunSvg(horizonLine + baseArc + dipGuide + glowDot(84, 39, 'var(--ecw-muted)'), true)
        + '<span class="suncap suncap-title">' + t(h, 'polarNight') + '</span>'
        + '</div>';
    }
    // sunMode 'hidden' → no sun cell; the metric bar reflows.

    // ── Stale but present: slim neutral banner + dimmed body, keep the last
    // reading visible. staleInfo() measures the fetch heartbeat — 2 h without
    // a SUCCESSFUL fetch, not 2 h without a value change. ──
    const stale = staleInfo(h.states['sensor.ec_temperature'], Date.now());
    let staleBannerHtml = '';
    let bodyOpacity = 1;
    if (stale) {
      const agoText = lang === 'fr'
        ? 'il y a ' + stale.agoHours + ' h' : stale.agoHours + 'h ago';
      staleBannerHtml = '<div class="stalebar">'
        + '<ha-icon icon="mdi:clock-alert-outline"></ha-icon>'
        + '<span>' + t(h, 'staleBanner') + ' · ' + agoText + '</span>'
        + '<span class="sretry" id="stale-refresh">' + t(h, 'refresh') + '</span>'
        + '</div>';
      bodyOpacity = 0.62;
    }

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; contain: inline-size; container-type: inline-size; }
        ${TOKEN_CSS}
        .stalebar {
          display: flex; align-items: center; gap: 10px; padding: 11px 14px;
          margin-bottom: 16px; border: 1px solid var(--ecw-hair);
          border-radius: 11px; font-size: 13px; color: var(--ecw-text2);
        }
        .stalebar ha-icon { --mdc-icon-size: 19px; color: var(--ecw-muted); }
        .sretry {
          margin-left: auto; color: var(--ecw-text); font-weight: 500;
          cursor: pointer; white-space: nowrap;
        }
        .herorow { display: flex; align-items: stretch; justify-content: space-between; gap: 22px; }
        .heroleft { display: flex; align-items: center; gap: 22px; }
        .heroicon { --mdc-icon-size: 52px; color: var(--ecw-heroicon); }
        .temp {
          font-size: 88px; font-weight: 300; line-height: 0.86;
          letter-spacing: -0.02em; color: var(--ecw-text);
        }
        .hsub { margin-top: 8px; font-size: 15px; color: var(--ecw-text2); }
        .hfeels { color: var(--ecw-muted); }
        .ppanel {
          min-width: 250px; background: var(--ecw-ppbg);
          border: 1px solid var(--ecw-ppbd); border-radius: 13px;
          padding: 13px 15px; display: flex; flex-direction: column; gap: 10px;
        }
        .phead { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
        .ptitle {
          display: flex; align-items: center; gap: 7px;
          font-size: 11.5px; font-weight: 600; letter-spacing: 0.08em;
          color: var(--ecw-pphead); text-transform: uppercase;
        }
        .ptitle ha-icon { --mdc-icon-size: 17px; color: var(--ecw-pptitle); }
        .phead-chance { font-size: 13px; white-space: nowrap; color: var(--ecw-text2); }
        .phead-none { font-size: 13px; white-space: nowrap; color: var(--ecw-muted); }
        .prow { display: flex; flex-direction: column; }
        .prowhead {
          display: flex; align-items: baseline; justify-content: space-between;
          gap: 12px; margin-bottom: 5px;
        }
        .plabel { font-size: 13px; color: var(--ecw-text2); white-space: nowrap; }
        .pstatus { font-size: 13px; color: var(--ecw-muted); }
        .pchips { display: flex; gap: 10px; }
        .pv {
          display: flex; align-items: center; gap: 3px;
          font-size: 13px; font-weight: 600; white-space: nowrap;
        }
        .pv ha-icon { --mdc-icon-size: 14px; }
        .pbar { display: flex; height: 5px; border-radius: 3px; overflow: hidden; background: var(--ecw-hair); }
        .mbar {
          display: flex; margin-top: 24px;
          border-top: 1px solid var(--ecw-hair); border-bottom: 1px solid var(--ecw-hair);
        }
        .mcell {
          flex: 1; display: flex; flex-direction: column; align-items: center;
          gap: 6px; padding: 14px 4px; border-left: 1px solid var(--ecw-hair);
        }
        .mcell:first-child { border-left: 0; }
        .mi { --mdc-icon-size: 22px; color: var(--ecw-muted); }
        .mv { font-size: 17px; font-weight: 600; color: var(--ecw-text); }
        /* nowrap: the wind secondary must never break mid-phrase — on narrow
           tiles the wrapping mbar re-flows whole cells instead. */
        .ml { font-size: 11px; color: var(--ecw-muted); white-space: nowrap; }
        .mcell.sun { flex: 1.75; justify-content: center; padding: 12px 14px; }
        .suntimes {
          display: flex; justify-content: space-between; width: 100%;
          max-width: 200px; font-size: 12.5px; color: var(--ecw-text2);
        }
        .suntimes ha-icon { --mdc-icon-size: 16px; color: var(--ecw-muted); }
        .suncap { font-size: 10.5px; color: var(--ecw-muted); text-align: center; }
        .suncap-title { font-size: 12px; color: var(--ecw-text2); }
        @container (max-width: 430px) {
          .herorow { flex-direction: column; align-items: stretch; gap: 18px; }
          .ppanel { min-width: 0; width: 100%; box-sizing: border-box; }
          .mbar { flex-wrap: wrap; }
          .mcell.sun { flex: 1 1 100%; border-left: 0; border-top: 1px solid var(--ecw-hair); }
          .temp { font-size: 70px; }
        }
      </style>
      <div class="${themeClass(h)}">
        ${staleBannerHtml}
        <div style="opacity:${bodyOpacity}">
          <div class="herorow">
            <div class="heroleft">
              ${heroIconHtml}
              <div>
                <div class="temp">${tempText}</div>
                <div class="hsub">${condText}${feelsHtml}</div>
              </div>
            </div>
            ${panelHtml}
          </div>
          <div class="mbar">${cellsHtml}${sunCellHtml}</div>
        </div>
      </div>
    `;

    this.shadowRoot.getElementById('stale-refresh')?.addEventListener('click', () => {
      if (!this._hass) return;
      this._hass.callService('homeassistant', 'update_entity', {
        entity_id: [
          'sensor.ec_temperature',
          'sensor.ec_hourly_forecast',
          'sensor.ec_daily_forecast',
        ],
      });
    });
  }

  _renderHourly() {
    const h = this._hass;
    const sensor = h.states['sensor.ec_hourly_forecast'];
    const rawForecast = sensor?.attributes?.forecast;

    // Store rows mid-load can have temp, icon and POP all null — skip them
    // instead of rendering blank columns.
    const forecast = (rawForecast || []).filter((item) => !isEmptyTimestep(item));
    if (forecast.length === 0) {
      this.shadowRoot.innerHTML = '';
      return;
    }

    // The multi-day card strip: day bands + midnight labels, 64px columns,
    // time atop each column. buildHourlyStripHtml owns the markup; this method
    // only supplies the section chrome and scroll container. STRIP_CSS ships
    // here AND in the popup — the overlay can't see this shadow root.
    const strip = buildHourlyStripHtml(forecast, h);

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; contain: inline-size; overflow: hidden; }
        ${TOKEN_CSS}
        .seclbl {
          font-size: 11.5px; font-weight: 600; letter-spacing: 0.11em;
          color: var(--ecw-muted); text-transform: uppercase;
          margin-top: 24px; margin-bottom: 12px;
        }
        .hscroll {
          overflow-x: auto; overflow-y: hidden;
          scrollbar-width: thin; scrollbar-color: var(--ecw-track) transparent;
          -webkit-overflow-scrolling: touch;
        }
        .hscroll::-webkit-scrollbar { height: 6px; }
        .hscroll::-webkit-scrollbar-thumb { background: var(--ecw-track); border-radius: 3px; }
        ${STRIP_CSS}
      </style>
      <div class="${themeClass(h)}">
        <div class="seclbl">${t(h, 'hourly')}</div>
        <div class="hscroll">${strip}</div>
      </div>
    `;
  }

  _renderDaily() {
    const h = this._hass;
    const sensor = h.states['sensor.ec_daily_forecast'];
    const forecast = sensor?.attributes?.forecast;

    if (!forecast || forecast.length === 0) {
      this.shadowRoot.innerHTML = '';
      return;
    }

    const dayAbbr = t(h, 'dayAbbr');
    const lang = (h && h.language) || 'en';

    // Store forecast for lazy popup fetch reference
    this._lastForecast = forecast;

    // Pre-compute popup content for each day. The overlay renders this in the
    // light DOM (document.body), where the card's shadow-root tokens aren't
    // visible — so each popup carries its own <style> (TOKEN_CSS + the ecp-
    // classes), wrapped in a .ecc theme div so the tokens resolve.
    this._dailyPopups = forecast.map((item) => {
      const title = escapeHtml(item.period || '');

      let dateLine = '';
      if (item.date) {
        // A bare 'YYYY-MM-DD' parses as UTC; anchor to local midnight so the
        // weekday/day don't shift west of Greenwich.
        const dayDate = new Date(item.date + 'T00:00:00');
        if (!isNaN(dayDate)) {
          dateLine = escapeHtml(dayDate.toLocaleDateString(lang === 'fr' ? 'fr-CA' : 'en-CA', {
            weekday: 'short', month: 'short', day: 'numeric',
          }));
        }
      }

      const narrative = escapeHtml(
        [item.text_summary, item.text_summary_night].filter(Boolean).join(' '));

      const dayCard = this._renderPopupPeriod(item, 'day');
      const nightCard = this._renderPopupPeriod(item, 'night');

      // Timeline — the card's hourly treatment over the day's timesteps.
      const tlState = timelineState(item);
      let timelineBody;
      if (tlState === 'timeline') {
        const timesteps = (item.timesteps_day || []).concat(item.timesteps_night || []);
        timelineBody = this._renderPopupTimeline(timesteps);
      } else {
        // Empty is normal for far-out days (GDPS-WEonG dropped). 'unavailable'
        // — fetched and EC has no hourly product; 'pending' — not fetched yet.
        const msg = tlState === 'unavailable' ? t(h, 'noHourly') : t(h, 'loading');
        timelineBody = '<div class="ecp-noh"><ha-icon icon="mdi:clock-outline"></ha-icon>'
          + '<span>' + msg + '</span></div>';
      }
      const timelineSection = '<div><div class="ecp-seclbl">' + t(h, 'timeline') + '</div>'
        + timelineBody + '</div>';

      // Footer: per-period last-updated time (oldest of EC / WEonG) + source.
      let footLeft = '';
      if (item.updated) {
        const updDate = new Date(item.updated);
        if (!isNaN(updDate)) {
          const timeStr = updDate.toLocaleTimeString(lang === 'fr' ? 'fr-CA' : 'en-CA', {
            hour: 'numeric', minute: '2-digit',
          });
          footLeft = t(h, 'updatedAt') + ' ' + escapeHtml(timeStr);
        }
      }
      const footer = '<div class="ecp-foot"><span>' + footLeft + '</span>'
        + '<span style="display:flex;align-items:center;gap:5px">'
        + '<ha-icon icon="mdi:map-marker"></ha-icon>' + t(h, 'ecAttribution') + '</span></div>';

      const header = '<div class="ecp-hdr"><span class="ecp-title">' + title + '</span>'
        + (dateLine ? '<span class="ecp-date">' + dateLine + '</span>' : '') + '</div>';
      const narrativeHtml = narrative ? '<p class="ecp-narr">' + narrative + '</p>' : '';
      const periods = '<div class="ecp-periods">' + dayCard + nightCard + '</div>';

      // STRIP_CSS rides along: the popup's hourly timeline reuses the shared
      // .ecs-* strip classes, which the card's shadow-root copy can't reach here.
      const content = '<style>' + TOKEN_CSS + POPUP_STYLE + STRIP_CSS + '</style>'
        + '<div class="' + themeClass(h) + '"><div class="ecp-root">'
        + header + narrativeHtml + periods + timelineSection + footer
        + '</div></div>';

      return { title, content };
    });

    // ── Summary rows ────────────────────────────────────────────────────────
    // Range bars are positioned against the week's own min/max and colored by
    // absolute temperature (cold weeks read blue, hot weeks orange).
    const weekTemps = [];
    forecast.forEach((item) => {
      if (item.temp_low != null) weekTemps.push(item.temp_low);
      if (item.temp_high != null) weekTemps.push(item.temp_high);
    });
    const weekMin = weekTemps.length ? Math.min.apply(null, weekTemps) : 0;
    const weekMax = weekTemps.length ? Math.max.apply(null, weekTemps) : 0;

    let rowsHtml = '';
    forecast.forEach((item, i) => {
      const firstWord = (item.period || '').split(' ')[0];
      const dayLabel = escapeHtml(dayAbbr[firstWord] || firstWord);

      // Dual icons: day colored by condition family, night dimmed.
      const dayIconHtml = item.icon_code != null
        ? '<ha-icon icon="' + ecIcon(item.icon_code) + '" style="--mdc-icon-size:18px;color:'
          + dailyIconColor(ecIcon(item.icon_code)) + '"></ha-icon>'
        : missingIconHtml(18);
      const nightIcon = item.icon_code_night != null
        ? ecIcon(item.icon_code_night) : 'mdi:weather-night';
      const nightIconHtml = '<ha-icon icon="' + nightIcon
        + '" style="--mdc-icon-size:18px;color:var(--ecw-muted)"></ha-icon>';

      // Range bar geometry (span clamping, single-value dot, isothermal
      // guard) — see rangeBarGeometry for the semantics.
      const bar = rangeBarGeometry(item.temp_low, item.temp_high, weekMin, weekMax);
      let barHtml = '';
      if (bar.kind === 'span') {
        barHtml = '<div class="dspan" style="left:' + bar.left + '%;width:' + bar.width
          + '%;background:linear-gradient(90deg,' + tempColor(item.temp_low)
          + ',' + tempColor(item.temp_high) + ')"></div>';
      } else if (bar.kind === 'dot') {
        barHtml = '<div class="ddot" style="left:' + bar.left
          + '%;background:' + tempColor(bar.value) + '"></div>';
      }

      // Precip: POP% + amounts. A WET day renders it TWICE — the fixed
      // .dprecip column (wide) and a .dfloat centered above the bar (narrow
      // tile); the container query (below) swaps which one shows. The wide
      // column is ALWAYS emitted — empty on dry days — so every row's range
      // bar shares one length/scale (user feedback: the DC's dry-day
      // omission misaligned the bars). The narrow float stays wet-only.
      const precip = dailyPrecip(item);
      const isWet = precip.showPrecip || precip.rainAmt > 0 || precip.snowAmt > 0;
      let precipColHtml = '<span class="dprecip"></span>';
      let floatHtml = '';
      if (isWet) {
        let precipHtml = '';
        const floatParts = [];
        if (precip.showPrecip) {
          precipHtml += '<span class="dpop">' + precip.popRounded + '%</span>';
          floatParts.push('<span style="color:var(--ecw-pop);font-weight:600">' + precip.popRounded + '%</span>');
        }
        let amtsHtml = '';
        if (precip.rainAmt > 0) {
          amtsHtml += '<span style="color:var(--ecw-rain)">' + fmtAmtUnit(precip.rainAmt, 'mm') + '</span>';
          floatParts.push('<span style="color:var(--ecw-rain)">' + fmtAmtUnit(precip.rainAmt, 'mm') + '</span>');
        }
        if (precip.snowAmt > 0) {
          amtsHtml += '<span style="color:var(--ecw-snow)">' + fmtAmtUnit(precip.snowAmt, 'cm') + '</span>';
          floatParts.push('<span style="color:var(--ecw-snow)">' + fmtAmtUnit(precip.snowAmt, 'cm') + '</span>');
        }
        if (amtsHtml) precipHtml += '<span class="damts">' + amtsHtml + '</span>';
        precipColHtml = '<span class="dprecip">' + precipHtml + '</span>';
        floatHtml = '<div class="dfloat">' + floatParts.join('') + '</div>';
      }

      rowsHtml += '<div class="drow' + (i === 0 ? ' dtoday' : '') + '" data-index="' + i + '">'
        + '<span class="dday">' + dayLabel + '</span>'
        + '<span class="dicons">' + dayIconHtml + nightIconHtml + '</span>'
        + precipColHtml
        + '<div class="dtemps">'
        + '<span class="dlow">' + (item.temp_low != null ? Math.round(item.temp_low) + '°' : '') + '</span>'
        + '<div class="dbar">' + barHtml + floatHtml + '</div>'
        + '<span class="dhigh">' + (item.temp_high != null ? Math.round(item.temp_high) + '°' : '') + '</span>'
        + '</div>'
        + '</div>';
    });

    // If popup is open, update only the popup content and skip the re-render.
    if (this._openPopupIndex != null) {
      const popup = this._dailyPopups?.[this._openPopupIndex];
      if (popup) ECOverlay.get().update(this, popup.content);
      return;
    }

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; contain: inline-size; container-type: inline-size; }
        ${TOKEN_CSS}
        .seclbl {
          font-size: 11.5px; font-weight: 600; letter-spacing: 0.11em;
          color: var(--ecw-muted); text-transform: uppercase;
          margin-top: 24px; margin-bottom: 12px;
        }
        .drows { display: flex; flex-direction: column; }
        .drow {
          display: flex; align-items: center; gap: 12px; padding: 8px;
          border-radius: 9px; cursor: pointer; transition: background 120ms ease;
        }
        .drow:active { background: var(--ecw-hover); }
        @media (hover: hover) { .drow:hover { background: var(--ecw-hover); } }
        .dday { width: 60px; font-size: 14px; white-space: nowrap; color: var(--ecw-text2); }
        .dtoday .dday { color: var(--ecw-text); font-weight: 600; }
        .dicons { width: 44px; display: flex; align-items: center; justify-content: center; gap: 3px; }
        .dprecip {
          width: 84px; display: flex; flex-direction: column; gap: 2px;
          line-height: 1; overflow: hidden;
        }
        .dpop { font-size: 11.5px; color: var(--ecw-pop); }
        .damts { display: flex; gap: 8px; font-size: 11px; }
        /* low · range bar · high are one group so the week's min/max always
           align and the bar keeps real width; the 12px gap matches the row's,
           so the wide layout is pixel-identical to the pre-group markup. */
        .dtemps { flex: 1; display: flex; align-items: center; gap: 12px; }
        .dlow { width: 26px; text-align: right; font-size: 15px; color: var(--ecw-text2); }
        .dbar { flex: 1; position: relative; height: 6px; border-radius: 3px; background: var(--ecw-track); }
        .dspan { position: absolute; top: 0; bottom: 0; border-radius: 3px; }
        .ddot {
          position: absolute; top: 50%; width: 8px; height: 8px;
          border-radius: 50%; transform: translate(-50%, -50%);
        }
        .dhigh { width: 26px; font-size: 15px; font-weight: 600; color: var(--ecw-text); }
        /* Narrow-tile precip float: centered just above its day's bar
           (DC .dprecipfloat metrics). Absolutely positioned so it never adds
           a column or grows row height (no compensating margins). Hidden on
           wide, shown by the container query below, which simultaneously
           drops the fixed .dprecip column. */
        .dfloat {
          display: none; position: absolute; bottom: 100%; left: 0; right: 0;
          justify-content: center; margin-bottom: 5px;
          gap: 7px; white-space: nowrap; font-size: 10px;
          line-height: 1; pointer-events: none;
        }
        @container (max-width: 430px) {
          .dprecip { display: none; }
          .dfloat { display: flex; }
          /* The bar is the structural spine on narrow — it can't be squeezed
             to nothing by long day labels (DC .ecc.narrow .dbar). */
          .dbar { min-width: 58px; }
        }
      </style>
      <div class="${themeClass(h)}">
        <div class="seclbl">${t(h, 'week')}</div>
        <div class="drows" id="daily-rows">${rowsHtml}</div>
      </div>
    `;

    // Event delegation for row clicks — survives innerHTML updates
    this.shadowRoot.getElementById('daily-rows')?.addEventListener('click', (e) => {
      const row = e.target.closest('.drow');
      if (row) {
        e.stopPropagation();
        this._openDailyPopup(parseInt(row.dataset.index));
      }
    });
  }

  /**
   * One Day/Night period card for the daily popup. Renders in the light DOM,
   * so it relies only on the ecp- classes + tokens carried by the popup style.
   * The Day half of a night-only period dims to "Day is over" instead of an
   * empty dash — see popupPeriodModel for the 'passed' rule.
   */
  _renderPopupPeriod(item, half) {
    const h = this._hass;
    const model = popupPeriodModel(item, half);
    const labelIcon = half === 'day'
      ? '<ha-icon icon="mdi:weather-sunny" style="--mdc-icon-size:15px;color:var(--ecw-sun)"></ha-icon>'
      : '<ha-icon icon="mdi:weather-night" style="--mdc-icon-size:15px;color:var(--ecw-muted)"></ha-icon>';

    let card = '<div class="ecp-period' + (model.passed ? ' ecp-passed' : '') + '">';
    card += '<span class="ecp-plabel">' + labelIcon + t(h, half) + '</span>';

    if (model.passed) {
      card += '<div class="ecp-passedbody"><ha-icon icon="mdi:minus"></ha-icon>'
        + '<span class="ecp-pcond" style="color:var(--ecw-muted)">' + t(h, 'dayDone') + '</span></div>';
      return card + '</div>';
    }

    const iconHtml = model.iconCode != null
      ? '<ha-icon icon="' + ecIcon(model.iconCode) + '" class="ecp-pico"></ha-icon>'
      : missingIconHtml(40);
    const tempTxt = model.temp != null ? Math.round(model.temp) + '°' : '—°';
    card += '<div class="ecp-prow">' + iconHtml
      + '<div><div class="ecp-ptemp">' + tempTxt + '</div>'
      + '<div class="ecp-pcond">' + escapeHtml(model.condition) + '</div></div></div>';

    let meta = '';
    if (model.showFeels) {
      meta += '<div class="ecp-mline"><ha-icon icon="mdi:thermometer"></ha-icon>'
        + t(h, 'feels') + ' ' + Math.round(model.feels) + '°</div>';
    }
    if (model.humidity != null) {
      meta += '<div class="ecp-mline"><ha-icon icon="mdi:water-percent"></ha-icon>'
        + Math.round(model.humidity) + '% ' + t(h, 'humidity').toLowerCase() + '</div>';
    }
    if (model.windState === 'calm') {
      meta += '<div class="ecp-mline"><ha-icon icon="mdi:weather-windy"></ha-icon>' + t(h, 'calm') + '</div>';
    } else if (model.windState === 'value') {
      let wind = Math.round(model.windSpeed) + ' km/h';
      if (model.windDirection) wind += ' ' + escapeHtml(model.windDirection);
      // EC sends gust 0s — keep them (they're real readings), so gate on != null.
      if (model.windGust != null) wind += ' · ' + t(h, 'gusts') + ' ' + Math.round(model.windGust) + ' km/h';
      meta += '<div class="ecp-mline"><ha-icon icon="mdi:weather-windy"></ha-icon>' + wind + '</div>';
    }
    if (model.pop != null) {
      meta += '<div class="ecp-mline"><ha-icon icon="mdi:water-percent"></ha-icon>'
        + Math.round(model.pop) + '% ' + t(h, 'chance') + '</div>';
    }
    if (model.showRain) {
      meta += '<div class="ecp-mline ecp-rain"><ha-icon icon="mdi:water"></ha-icon>'
        + fmtAmtUnit(model.rain, 'mm') + '</div>';
    }
    if (model.showSnow) {
      meta += '<div class="ecp-mline ecp-snow"><ha-icon icon="mdi:snowflake"></ha-icon>'
        + fmtAmtUnit(model.snow, 'cm') + '</div>';
    }
    // UV is Day-only; uvColor returns null for Night (uvIndex null) and any
    // non-numeric value, so this gate doubles as the "hidden when absent" rule.
    const uvCol = uvColor(model.uvIndex);
    if (uvCol) {
      let uvTxt = '<span style="color:' + uvCol + '">UV ' + model.uvIndex + '</span>';
      if (model.uvCategory) uvTxt += ' (' + escapeHtml(model.uvCategory) + ')';
      meta += '<div class="ecp-mline"><ha-icon icon="mdi:white-balance-sunny" style="color:'
        + uvCol + '"></ha-icon>' + uvTxt + '</div>';
    }
    if (meta) card += '<div class="ecp-pmeta">' + meta + '</div>';

    return card + '</div>';
  }

  /**
   * The popup's single-day hourly strip. Same builder (and same header-top
   * column order) as the card section, driven compact: no day bands/labels,
   * 60px columns, a 42px chart, a smaller 34x28 water-fill vessel. Only the
   * scroll container is added here — no right-edge fade (card section only).
   */
  _renderPopupTimeline(timesteps) {
    const strip = buildHourlyStripHtml(timesteps, this._hass, {
      colWidth: 60,
      curveGeometry: { chartHeight: 42, plotTop: 6, plotHeight: 24 },
      showDayBands: false,
      vesselWidth: 34,
      vesselHeight: 28,
      compact: true,
    });
    return '<div class="ecp-scroll">' + strip + '</div>';
  }

  _openDailyPopup(index) {
    const popup = this._dailyPopups?.[index];
    if (!popup) return;

    this._openPopupIndex = index;

    // Fire-and-forget: fetch popup detail if icons not yet complete.
    // The coordinator's cache deduplicates — repeated calls are no-ops.
    const item = this._lastForecast?.[index];
    if (item && item.date && this._hass && item.icons_complete === false) {
      this._hass.callService('ec_weather', 'fetch_day_timesteps', {
        date: item.date,
      });
    }

    const overlay = ECOverlay.get();
    overlay.open(this, popup.content);
    overlay.onClose = () => { this._openPopupIndex = null; };
  }

  // ─── Static ──────────────────────────────────────────────────────────────

  static getStubConfig() {
    return { section: 'current' };
  }
}

// ─── Registration ────────────────────────────────────────────────────────────
// Skipped under the vitest harness (setup.js sets the flag before import):
// tests exercise the exported pure helpers, not the custom element.

if (!window.__EC_WEATHER_CARD_TEST__) {
  customElements.define('ec-weather-card', ECWeatherCard);

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: 'ec-weather-card',
    name: 'EC Weather Card',
    description: 'Environment Canada weather card with alerts, current conditions, hourly and daily forecasts.',
  });

  console.info('%c EC-WEATHER-CARD %c loaded ', 'background:#4FC3F7;color:#000;font-weight:bold', '');
}
