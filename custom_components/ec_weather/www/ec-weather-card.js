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
    feelsShort: 'Feels',
    gusts: 'gusts',
    wind: 'Wind',
    humidity: 'Humidity',
    aqhi: 'Air Quality',
    uv: 'UV',
    daylightRemaining: 'daylight remaining',
    day: 'DAY',
    night: 'NIGHT',
    timeline: 'Timeline',
    hourly: 'HOURLY',
    daily: 'DAILY',
    loading: 'Loading\u2026',
    weatherUnavailable: 'Weather data unavailable',
    retry: 'Retry',
    expires: 'Expires',
    dayAbbr: {
      Monday: 'Mon', Tuesday: 'Tue', Wednesday: 'Wed',
      Thursday: 'Thu', Friday: 'Fri', Saturday: 'Sat', Sunday: 'Sun',
      Tomorrow: 'Tmrw',
    },
  },
  fr: {
    days: ['DIM', 'LUN', 'MAR', 'MER', 'JEU', 'VEN', 'SAM'],
    feels: 'Ressenti',
    feelsShort: 'Ressenti',
    gusts: 'rafales',
    wind: 'Vent',
    humidity: 'Humidité',
    aqhi: 'Qualité de l\u2019air',
    uv: 'UV',
    daylightRemaining: 'de lumière restante',
    day: 'JOUR',
    night: 'NUIT',
    timeline: 'Chronologie',
    hourly: 'HORAIRE',
    daily: 'QUOTIDIEN',
    loading: 'Chargement\u2026',
    weatherUnavailable: 'Données météo indisponibles',
    retry: 'Réessayer',
    expires: 'Expire',
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

/** Escape HTML special characters to prevent XSS from API-sourced strings. */
function escapeHtml(str) {
  if (str == null) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function t(hass, key) {
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
    'sensor.ec_sunrise',
    'sensor.ec_sunset',
    // sensor.ec_wind_gust and sensor.ec_air_quality are optional — read but don't block
  ],
  hourly: [
    'sensor.ec_hourly_forecast',
  ],
  daily: [
    'sensor.ec_daily_forecast',
  ],
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function ecIcon(code) {
  return EC_ICON_MAP[code] || 'mdi:weather-cloudy';
}

function titleCase(str) {
  if (!str) return '';
  return str.replace(/\b\w/g, c => c.toUpperCase());
}

function fmtAmt(val) {
  if (val == null || val <= 0) return null;
  return val < 1 ? '<1' : String(Math.round(val));
}

function fmtWind(speed, gust, dir, hass) {
  if (!speed && !gust) return '';
  let s = dir ? escapeHtml(dir) + ' ' : '';
  s += Math.round(speed) + ' km/h';
  if (gust && gust > speed) s += ' (' + t(hass, 'gusts') + ' ' + Math.round(gust) + ')';
  return s;
}

function fmtTime(isoStr, hass) {
  const d = new Date(isoStr);
  const lang = (hass && hass.language) || 'en';
  if (lang === 'fr') {
    return d.getHours() + 'h';
  }
  const hr = d.getHours();
  if (hr === 0) return '12AM';
  if (hr === 12) return '12PM';
  return hr > 12 ? (hr - 12) + 'PM' : hr + 'AM';
}

/** Determine precip color based on rain/snow amounts and precip type. */
function precipAmtColor(rain, snow, precipType) {
  if ((snow || 0) > 0 && (rain || 0) > 0) return 'var(--ec-weather-precip-rain, #4FC3F7)';
  if ((snow || 0) > 0) return 'var(--ec-weather-precip-snow, var(--primary-text-color, rgba(255,255,255,0.85)))';
  if ((rain || 0) > 0) return 'var(--ec-weather-precip-rain, #4FC3F7)';
  if (precipType === 'snow') return 'var(--ec-weather-precip-snow, var(--primary-text-color, rgba(255,255,255,0.85)))';
  return 'var(--ec-weather-precip-rain, #4FC3F7)';
}

/** Pre-scan a list of timestep items to determine which optional rows have data. */
function scanTimestepFlags(items) {
  return {
    anyFeels: items.some(i => {
      const fl = i.feels_like;
      const t = i.temp != null ? Math.round(i.temp) : null;
      return fl != null && Math.round(fl) !== t;
    }),
    anyPop: items.some(i => (i.precipitation_probability || 0) > 0),
    anyRain: items.some(i => (i.rain_mm || 0) > 0),
    anySnow: items.some(i => (i.snow_cm || 0) > 0),
  };
}

/** Build grid-template-rows string based on which optional rows are present. */
function buildGridRows(flags) {
  let rows = '20px 36px 22px'; // time, icon, temp (always)
  if (flags.anyFeels) rows += ' 18px';
  if (flags.anyPop) rows += ' 16px';
  if (flags.anyRain) rows += ' 16px';
  if (flags.anySnow) rows += ' 16px';
  return rows;
}

/** Render a single timestep column (shared by hourly forecast and daily popup timeline). */
function renderTimestepCol(ts, gridRows, flags, colors, hass) {
  const icon = ts.icon_code != null ? ecIcon(ts.icon_code) : null;
  const temp = ts.temp != null ? Math.round(ts.temp) : null;
  const tempStr = temp != null ? temp + '\u00b0' : '\u2014';
  const feelsRaw = ts.feels_like;
  const feels = feelsRaw != null ? Math.round(feelsRaw) : null;
  const showFeels = feels != null && feels !== temp;
  const pop = Math.ceil((ts.precipitation_probability || 0) / 5) * 5;
  const popColor = ((ts.snow_cm || 0) > 0 && (ts.rain_mm || 0) === 0) ? colors.snow : colors.rain;
  const rain = ts.rain_mm || 0;
  const snow = ts.snow_cm || 0;

  let html = '<div style="min-width:54px;flex:0 0 54px;display:grid;justify-items:center;align-items:center;padding:8px 0;'
    + 'grid-template-rows:' + gridRows + ';border-right:1px solid var(--ec-weather-divider, var(--divider-color, rgba(255,255,255,0.06)))">';
  html += '<div style="font-size:12px;font-weight:500;color:var(--ec-weather-text-secondary, var(--secondary-text-color, rgba(255,255,255,0.5)))">' + fmtTime(ts.time, hass) + '</div>';
  if (icon) {
    html += '<ha-icon icon="' + icon + '" style="--mdc-icon-size:28px;color:var(--ec-weather-text-primary, var(--primary-text-color, rgba(255,255,255,0.85)))"></ha-icon>';
  } else if (colors.showLoadingDot) {
    html += '<div style="height:28px;display:flex;align-items:center;justify-content:center">'
      + '<div style="width:8px;height:8px;border-radius:50%;background:var(--divider-color, rgba(255,255,255,0.15))"></div></div>';
  } else {
    html += '<div style="height:28px"></div>';
  }
  html += '<div style="font-size:16px;font-weight:700;color:var(--ec-weather-text-primary, var(--primary-text-color, #fff))">' + tempStr + '</div>';
  if (flags.anyFeels) html += '<div style="font-size:12px;font-weight:400;color:var(--ec-weather-text-muted, var(--secondary-text-color, rgba(255,255,255,0.45)));'
    + (showFeels ? '' : 'visibility:hidden') + '">FL ' + (showFeels ? feels + '\u00b0' : '0') + '</div>';
  if (flags.anyPop) html += '<div style="font-size:12px;font-weight:600;color:' + popColor + ';'
    + (pop >= 5 ? '' : 'visibility:hidden') + '">' + (pop >= 5 ? pop + '%' : '0') + '</div>';
  if (flags.anyRain) html += '<div style="font-size:12px;font-weight:500;color:' + colors.rain + ';'
    + (rain > 0 ? '' : 'visibility:hidden') + '">' + (rain > 0 ? fmtAmt(rain) + 'mm' : '0') + '</div>';
  if (flags.anySnow) html += '<div style="font-size:12px;font-weight:500;color:' + colors.snow + ';'
    + (snow > 0 ? '' : 'visibility:hidden') + '">' + (snow > 0 ? fmtAmt(snow) + 'cm' : '0') + '</div>';
  html += '</div>';
  return html;
}

/** Read an entity state, returning null if unavailable/unknown/missing. */
function entityVal(hass, entityId) {
  const s = hass.states[entityId];
  if (!s || s.state === 'unavailable' || s.state === 'unknown') return null;
  return s.state;
}

/** Read an entity state as a number, returning null if invalid. */
function entityNum(hass, entityId) {
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

class ECWeatherCard extends HTMLElement {
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

    // Reset refresh trigger when entities actually change
    if (oldHass && this._refreshTriggered) {
      const changed = entities.some(e => oldHass.states[e] !== hass.states[e]);
      if (changed) this._refreshTriggered = false;
    }

    // Only re-render if relevant entities changed
    if (oldHass) {
      const changed = entities.some(e => oldHass.states[e] !== hass.states[e]);
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
    // Alerts: always hide when unavailable (same as no alerts)
    if (this._config.section === 'alerts') {
      this.shadowRoot.innerHTML = '';
      this._rendered = true;
      return;
    }

    // Hourly/daily: show loading placeholder while WEonG data is pending
    if (this._config.section === 'hourly' || this._config.section === 'daily') {
      // Check if weather coordinator is up (ec_temperature available)
      // If yes, WEonG is still loading. If no, it's a real outage — hide.
      const tempState = this._hass?.states?.['sensor.ec_temperature'];
      const weatherUp = tempState && tempState.state !== 'unavailable';
      if (weatherUp) {
        this._rendered = true;
        const title = this._config.section === 'hourly' ? t(this._hass, 'hourly') : t(this._hass, 'daily');
        this.shadowRoot.innerHTML = `
          <style>
            :host { display: block; contain: inline-size; }
            .section-header {
              font-size: 12px;
              font-weight: 600;
              color: var(--ec-weather-text-muted, var(--secondary-text-color, rgba(255,255,255,0.4)));
              letter-spacing: 0.5px;
              margin-top: 24px;
            }
            .loading {
              padding: 16px;
              text-align: center;
              color: var(--secondary-text-color, rgba(255, 255, 255, 0.25));
              font-size: 13px;
              font-family: var(--ha-card-font-family, 'Segoe UI', sans-serif);
            }
          </style>
          <div class="section-header">${title}</div>
          <div class="loading">${t(this._hass, 'loading')}</div>
        `;
        return;
      }
      // Weather coordinator also down — hide entirely
      this.shadowRoot.innerHTML = '';
      this._rendered = true;
      return;
    }

    this._rendered = true;
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; contain: inline-size; }
        .unavailable {
          background: var(--ha-card-background, rgba(10, 21, 32, 0.7));
          border-radius: 12px;
          padding: 24px 16px;
          text-align: center;
          color: var(--secondary-text-color, rgba(255, 255, 255, 0.6));
          font-family: var(--ha-card-font-family, 'Segoe UI', sans-serif);
        }
        .unavailable ha-icon {
          --mdc-icon-size: 32px;
          color: var(--secondary-text-color, rgba(255, 255, 255, 0.3));
          margin-bottom: 8px;
          display: block;
        }
        .unavailable .msg {
          font-size: 14px;
          margin-bottom: 12px;
        }
        .retry-btn {
          background: var(--ha-card-background, rgba(255, 255, 255, 0.1));
          border: 1px solid var(--divider-color, rgba(255, 255, 255, 0.15));
          border-radius: 8px;
          color: var(--primary-text-color, rgba(255, 255, 255, 0.7));
          padding: 8px 16px;
          font-size: 13px;
          cursor: pointer;
          transition: background 0.2s;
          font-family: inherit;
        }
        .retry-btn:hover {
          opacity: 0.8;
        }
        .retry-btn ha-icon {
          --mdc-icon-size: 16px;
          vertical-align: middle;
          margin-right: 4px;
          display: inline;
          color: inherit;
        }
      </style>
      <div class="unavailable">
        <ha-icon icon="mdi:weather-cloudy-alert"></ha-icon>
        <div class="msg">${t(this._hass, 'weatherUnavailable')}</div>
        <button class="retry-btn" id="retry">
          <ha-icon icon="mdi:refresh"></ha-icon>${t(this._hass, 'retry')}
        </button>
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

    const colors = {
      warning: 'var(--ec-weather-alert-warning, #EF5350)',
      watch: 'var(--ec-weather-alert-watch, #FFA726)',
      advisory: 'var(--ec-weather-alert-advisory, #FFEE58)',
      statement: 'var(--ec-weather-alert-statement, var(--secondary-text-color, rgba(255,255,255,0.6)))',
    };

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

    let bannersHtml = '';
    alerts.forEach((alert, i) => {
      const color = colors[alert.type] || colors.advisory;
      const headline = escapeHtml(titleCase(alert.headline || alert.type));
      const exp = fmtExp(alert.expires);
      const expLine = exp
        ? '<div style="margin-bottom:8px;font-weight:500;opacity:0.85">' + t(h, 'expires') + ': ' + exp + '</div>'
        : '';
      const text = escapeHtml(alert.text || '');

      if (i > 0) bannersHtml += '<div style="height:8px"></div>';
      bannersHtml += `
        <div class="alert-wrap">
          <div class="alert-header" data-index="${i}">
            <ha-icon icon="mdi:weather-cloudy-alert" class="alert-icon"></ha-icon>
            <span class="alert-title">${headline}</span>
          </div>
          <div class="alert-detail" id="alert-detail-${i}">
            ${expLine}${text}
          </div>
        </div>`;
    });

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; margin-bottom: 16px; }
        .alert-wrap {
          width: 100%;
          background: var(--ec-weather-alert-bg, var(--card-background-color, #0a1520));
          border: 1px solid var(--ec-weather-divider, var(--divider-color, rgba(255,255,255,0.08)));
          border-radius: 8px;
          overflow: hidden;
          box-sizing: border-box;
        }
        .alert-header {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          width: 100%;
          padding: 12px;
          cursor: pointer;
          pointer-events: auto;
        }
        .alert-icon {
          --mdc-icon-size: 24px;
          color: var(--primary-text-color, #FFF);
          flex-shrink: 0;
        }
        .alert-title {
          font-size: 14px;
          font-weight: 500;
          color: var(--primary-text-color, #FFF);
        }
        .alert-detail {
          display: none;
          padding: 12px;
          font-size: 13px;
          color: var(--primary-text-color, rgba(255,255,255,0.85));
          white-space: pre-wrap;
          line-height: 1.4;
          text-align: left;
        }
      </style>
      <div id="alerts">${bannersHtml}</div>
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

    // Temperature + feels-like
    const temp = entityNum(h, 'sensor.ec_temperature');
    const fl = entityNum(h, 'sensor.ec_feels_like');
    const tVal = temp !== null ? Math.round(temp) : null;
    const f = fl !== null ? Math.round(fl) : null;
    const showFl = f !== null && tVal !== null && f !== tVal;

    // Wind
    const windSpeed = entityNum(h, 'sensor.ec_wind_speed');
    const windGust = entityNum(h, 'sensor.ec_wind_gust');
    const windDir = entityVal(h, 'sensor.ec_wind_direction');
    let windText = '';
    if (windSpeed !== null) {
      windText = t(h, 'wind') + ' ' + Math.round(windSpeed) + ' km/h';
      if (windDir) windText += ' ' + windDir;
      if (windGust !== null && windGust > windSpeed)
        windText += ' (' + t(h, 'gusts') + ' ' + Math.round(windGust) + ' km/h)';
    }

    // AQHI (optional, hidden when < 4)
    const aqhi = entityNum(h, 'sensor.ec_air_quality');
    let aqhiHtml = '';
    if (aqhi !== null && aqhi >= 4) {
      const risk = aqhi >= 10 ? 'Very High' : aqhi >= 7 ? 'High' : 'Moderate';
      const color = aqhi >= 10
        ? 'var(--ec-weather-alert-warning, #EF4444)'
        : aqhi >= 7
          ? 'var(--ec-weather-alert-watch, #F97316)'
          : 'var(--ec-weather-text-secondary, var(--secondary-text-color, rgba(255,255,255,0.6)))';
      aqhiHtml = `<div class="aqhi" style="color:${color}">${t(h, 'aqhi')}: ${Math.round(aqhi)} \u00b7 ${risk}</div>`;
    }

    // Condition + icon
    const condition = entityVal(h, 'sensor.ec_condition');
    const iconCode = entityNum(h, 'sensor.ec_icon_code');
    const icon = ecIcon(iconCode);
    const condText = condition ? escapeHtml(titleCase(condition)) : '';

    // Sun times
    const sunrise = entityVal(h, 'sensor.ec_sunrise');
    const sunset = entityVal(h, 'sensor.ec_sunset');
    let sunHtml = '';
    if (sunrise && sunset) {
      sunHtml = `<div class="sun-times">\u2191 ${sunrise}  \u2193 ${sunset}</div>`;
    }

    // Daylight remaining (replaces sun.sun dependency)
    let daylightHtml = '';
    if (sunset) {
      const parts = sunset.split(':');
      if (parts.length === 2) {
        const now = new Date();
        const sunsetTime = new Date(now);
        sunsetTime.setHours(parseInt(parts[0]), parseInt(parts[1]), 0, 0);
        const diff = sunsetTime - now;
        if (diff > 0) {
          // Sun is still up — also check sunrise to confirm we're past it
          let pastSunrise = true;
          if (sunrise) {
            const rParts = sunrise.split(':');
            const sunriseTime = new Date(now);
            sunriseTime.setHours(parseInt(rParts[0]), parseInt(rParts[1]), 0, 0);
            pastSunrise = now >= sunriseTime;
          }
          if (pastSunrise) {
            const hours = Math.floor(diff / (1000 * 60 * 60));
            const mins = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
            const dlLabel = t(h, 'daylightRemaining');
            if (hours === 0 && mins < 1)
              daylightHtml = '<div class="daylight">&lt; 1m ' + dlLabel + '</div>';
            else if (hours === 0)
              daylightHtml = `<div class="daylight">${mins}m ${dlLabel}</div>`;
            else
              daylightHtml = `<div class="daylight">${hours}h ${mins}m ${dlLabel}</div>`;
          }
        }
      }
    }

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        .temp-row {
          display: flex;
          align-items: baseline;
          gap: 12px;
        }
        .t-val {
          font-size: 48px;
          font-weight: 700;
          color: var(--ec-weather-text-primary, var(--primary-text-color, #FFFFFF));
        }
        .t-fl {
          font-size: 14px;
          font-weight: 400;
          color: var(--ec-weather-text-secondary, var(--secondary-text-color, rgba(255,255,255,0.6)));
        }
        .wind {
          font-size: 14px;
          font-weight: 400;
          color: var(--ec-weather-text-secondary, var(--secondary-text-color, rgba(255,255,255,0.6)));
          margin-top: 4px;
          margin-bottom: 8px;
        }
        .aqhi {
          font-size: 14px;
          font-weight: 400;
          margin-bottom: 8px;
        }
        .condition {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .condition ha-icon {
          --mdc-icon-size: 24px;
          color: var(--ec-weather-text-primary, var(--primary-text-color, #FFFFFF));
        }
        .condition-text {
          font-size: 14px;
          color: var(--ec-weather-text-primary, var(--primary-text-color, #FFFFFF));
        }
        .sun-times {
          font-size: 14px;
          color: var(--ec-weather-text-secondary, var(--secondary-text-color, rgba(255,255,255,0.6)));
          margin-top: 12px;
        }
        .daylight {
          font-size: 12px;
          color: var(--ec-weather-text-secondary, var(--secondary-text-color, rgba(255,255,255,0.6)));
          margin-top: 4px;
        }
      </style>
      <div class="temp-row">
        <span class="t-val">${tVal !== null ? tVal + '\u00b0' : '--\u00b0'}</span>
        ${showFl ? '<span class="t-fl">' + t(h, 'feels') + ' ' + f + '\u00b0</span>' : ''}
      </div>
      ${windText ? '<div class="wind">' + windText + '</div>' : ''}
      ${aqhiHtml}
      <div class="condition">
        <ha-icon icon="${icon}"></ha-icon>
        <span class="condition-text">${condText}</span>
      </div>
      ${sunHtml}
      ${daylightHtml}
    `;
  }

  _renderHourly() {
    const h = this._hass;
    const sensor = h.states['sensor.ec_hourly_forecast'];
    const forecast = sensor?.attributes?.forecast;

    if (!forecast || forecast.length === 0) {
      this.shadowRoot.innerHTML = '';
      return;
    }

    const RAIN_COLOR = 'var(--ec-weather-precip-rain, #4FC3F7)';
    const SNOW_COLOR = 'var(--ec-weather-precip-snow, var(--primary-text-color, rgba(255,255,255,0.85)))';
    const flags = scanTimestepFlags(forecast);
    const gridRows = buildGridRows(flags);
    const colors = { rain: RAIN_COLOR, snow: SNOW_COLOR, showLoadingDot: false };

    let itemsHtml = '';
    let prevDateStr = null;

    forecast.forEach(item => {
      if (item.temp == null && item.icon_code == null && item.precipitation_probability == null) return;
      const date = new Date(item.time);
      const dateStr = date.toLocaleDateString('en-CA');

      // Day separator
      if (prevDateStr !== null && dateStr !== prevDateStr) {
        itemsHtml += `
          <div class="hourly-day-sep">
            <div class="hourly-day-label">${t(h, 'days')[date.getDay()]}</div>
          </div>`;
      }
      prevDateStr = dateStr;

      itemsHtml += renderTimestepCol(item, gridRows, flags, colors, h);
    });

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          contain: inline-size;
          overflow: hidden;
        }
        .section-header {
          font-size: 12px;
          font-weight: 600;
          color: var(--ec-weather-text-muted, var(--secondary-text-color, rgba(255,255,255,0.4)));
          letter-spacing: 0.5px;
          margin-top: 24px;
        }
        .hourly-scroll {
          display: flex;
          flex-direction: row;
          overflow-x: auto;
          overflow-y: hidden;
          scroll-behavior: smooth;
          -webkit-overflow-scrolling: touch;
          scrollbar-width: none;
          padding: 8px 0;
          gap: 0;
        }
        .hourly-scroll::-webkit-scrollbar { display: none; }
        .hourly-day-sep {
          flex: 0 0 36px;
          min-width: 36px;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 8px 0;
          border-right: 1px solid var(--divider-color, rgba(255,255,255,0.15));
          border-left: 1px solid var(--divider-color, rgba(255,255,255,0.15));
        }
        .hourly-day-label {
          font-size: 11px;
          font-weight: 700;
          color: var(--secondary-text-color, rgba(255,255,255,0.5));
          letter-spacing: 0.5px;
          writing-mode: vertical-lr;
          text-orientation: mixed;
          transform: rotate(180deg);
        }
      </style>
      <div class="section-header">${t(h, 'hourly')}</div>
      <div class="hourly-scroll">${itemsHtml}</div>
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

    const RAIN_COLOR = 'var(--ec-weather-precip-rain, #4FC3F7)';
    const SNOW_COLOR = 'var(--ec-weather-precip-snow, var(--primary-text-color, rgba(255,255,255,0.85)))';
    const dayAbbr = t(h, 'dayAbbr');

    const localFmtWind = (speed, gust, dir) => {
      if (speed == null) return null;
      let w = dir ? dir + ' ' : '';
      w += Math.round(speed) + ' km/h';
      if (gust != null) w += ' ' + t(h, 'gusts') + ' ' + Math.round(gust);
      return w;
    };

    // Store forecast for lazy popup fetch reference
    this._lastForecast = forecast;

    // Pre-compute popup data for each day
    this._dailyPopups = forecast.map((item) => {
      const fullName = escapeHtml((item.period || '').split(' ')[0]);
      const isNightOnly = item.icon_code === null;

      const dayIconStr = item.icon_code != null ? ecIcon(item.icon_code) : null;
      const nightCode = item.icon_code_night != null ? item.icon_code_night : item.icon_code;
      const nightIconStr = nightCode != null ? ecIcon(nightCode) : 'mdi:weather-night';

      const condText = escapeHtml(item.condition || item.condition_night || '');
      const dTemp = item.temp_high != null ? Math.round(item.temp_high) + '\u00b0' : '\u2014';
      const nTemp = item.temp_low != null ? Math.round(item.temp_low) + '\u00b0' : '\u2014';

      const flH = item.feels_like_high != null ? Math.round(item.feels_like_high) : null;
      const flL = item.feels_like_low != null ? Math.round(item.feels_like_low) : null;
      const showFlH = flH !== null && item.temp_high !== null && Math.abs(flH - Math.round(item.temp_high)) >= 3;
      const showFlL = flL !== null && item.temp_low !== null && Math.abs(flL - Math.round(item.temp_low)) >= 3;

      const dPrecipCol = precipAmtColor(item.rain_mm_day, item.snow_cm_day, item.precip_type);
      const nPrecipCol = precipAmtColor(item.rain_mm_night, item.snow_cm_night, item.precip_type);

      const muted = 'color:var(--secondary-text-color, rgba(255,255,255,0.35))';
      const dash = '<span style="' + muted + '">\u2014</span>';
      const mutedSm = 'font-size:13px;color:var(--secondary-text-color, rgba(255,255,255,0.45))';
      const icoSm = '--mdc-icon-size:14px;vertical-align:middle;margin-right:3px;color:var(--secondary-text-color, rgba(255,255,255,0.4))';

      const popupCol = (label, iconStr, temp, showFl, flVal, pop, rain, snow, pColor,
                        windStr, humidity, accumAmt, accumUnit, accumName, uvIdx, uvCat) => {
        let c = '<div style="text-align:center">';
        c += '<div style="font-size:13px;font-weight:600;color:var(--secondary-text-color, rgba(255,255,255,0.35));text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px">' + label + '</div>';
        if (iconStr) {
          c += '<ha-icon icon="' + iconStr + '" style="--mdc-icon-size:32px;color:var(--primary-text-color, rgba(255,255,255,0.85))"></ha-icon>';
        } else {
          c += '<div style="height:32px;display:flex;align-items:center;justify-content:center">' + dash + '</div>';
        }
        c += '<div style="font-size:24px;font-weight:700;color:var(--primary-text-color, #fff);margin-top:8px;margin-bottom:2px">' + temp + '</div>';
        const flVis = showFl ? '' : 'visibility:hidden;';
        const flTxt = showFl ? 'FL ' + flVal + '\u00b0' : '\u00a0';
        c += '<div style="font-size:13px;font-weight:400;color:var(--secondary-text-color, rgba(255,255,255,0.45));min-height:18px;' + flVis + '">' + flTxt + '</div>';
        if (windStr) c += '<div style="' + mutedSm + ';margin-top:8px"><ha-icon icon="mdi:weather-windy" style="' + icoSm + '"></ha-icon>' + windStr + '</div>';
        if (humidity != null) c += '<div style="' + mutedSm + ';margin-top:4px"><ha-icon icon="mdi:water-percent" style="' + icoSm + '"></ha-icon>' + humidity + '%</div>';
        if (uvIdx != null) c += '<div style="' + mutedSm + ';margin-top:4px"><ha-icon icon="mdi:weather-sunny-alert" style="' + icoSm + '"></ha-icon>UV ' + uvIdx + (uvCat ? ' (' + escapeHtml(uvCat) + ')' : '') + '</div>';
        if (accumAmt != null && accumAmt > 0) {
          const accumColor = (accumName === 'snow') ? SNOW_COLOR : RAIN_COLOR;
          c += '<div style="margin-top:10px"><div style="font-size:13px;font-weight:500;color:' + accumColor + '">' + accumAmt + escapeHtml(accumUnit || '') + ' ' + escapeHtml(accumName || '') + '</div></div>';
        }
        if ((rain || 0) > 0 || (snow || 0) > 0) {
          c += '<div style="margin-top:' + (accumAmt > 0 ? '4' : '10') + 'px">';
          if ((rain || 0) > 0) c += '<div style="font-size:11px;font-weight:400;color:' + RAIN_COLOR + ';opacity:0.6;margin-top:2px">\u03a3 ' + fmtAmt(rain) + 'mm</div>';
          if ((snow || 0) > 0) c += '<div style="font-size:11px;font-weight:400;color:' + SNOW_COLOR + ';opacity:0.6;margin-top:2px">\u03a3 ' + fmtAmt(snow) + 'cm</div>';
          c += '</div>';
        }
        c += '</div>';
        return c;
      };

      const dayCol = popupCol(t(h, 'day'),
        isNightOnly ? null : dayIconStr, isNightOnly ? dash : dTemp,
        isNightOnly ? false : showFlH, flH,
        isNightOnly ? null : item.precip_prob_day, isNightOnly ? null : item.rain_mm_day,
        isNightOnly ? null : item.snow_cm_day, dPrecipCol,
        isNightOnly ? null : localFmtWind(item.wind_speed, item.wind_gust, item.wind_direction),
        isNightOnly ? null : item.humidity,
        isNightOnly ? null : item.precip_accum_amount, isNightOnly ? null : item.precip_accum_unit,
        isNightOnly ? null : item.precip_accum_name,
        isNightOnly ? null : item.uv_index, isNightOnly ? null : item.uv_category);

      const nightCol = popupCol(t(h, 'night'), nightIconStr, nTemp, showFlL, flL,
        item.precip_prob_night, item.rain_mm_night, item.snow_cm_night, nPrecipCol,
        localFmtWind(item.wind_speed_night, item.wind_gust_night, item.wind_direction_night),
        item.humidity_night,
        item.precip_accum_amount_night, item.precip_accum_unit_night, item.precip_accum_name_night,
        null, null);

      const textSummary = escapeHtml(item.text_summary || item.text_summary_night || '');

      // Timeline — uses shared timestep rendering
      const allTimesteps = (item.timesteps_day || []).concat(item.timesteps_night || []);
      let timelineHtml = '';
      if (allTimesteps.length > 0) {
        const tlFlags = scanTimestepFlags(allTimesteps);
        const tlGridRows = buildGridRows(tlFlags);
        const showLoadingDot = item.icons_complete === false;
        const tlColors = { rain: RAIN_COLOR, snow: SNOW_COLOR, showLoadingDot };

        timelineHtml += '<div style="margin-top:16px;border-top:1px solid var(--divider-color, rgba(255,255,255,0.08));padding-top:12px">';
        timelineHtml += '<div style="font-size:13px;font-weight:600;color:var(--secondary-text-color, rgba(255,255,255,0.35));text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px">' + t(h, 'timeline') + '</div>';
        timelineHtml += '<div style="display:flex;overflow-x:auto;gap:0;scrollbar-width:none;-webkit-overflow-scrolling:touch">';
        allTimesteps.forEach(ts => {
          timelineHtml += renderTimestepCol(ts, tlGridRows, tlFlags, tlColors, h);
        });
        timelineHtml += '</div></div>';
      }

      let popupHtml = '<div style="text-align:center;margin-bottom:4px">';
      popupHtml += '<div style="font-size:18px;font-weight:700;color:var(--primary-text-color, #fff);margin-bottom:8px">' + fullName + '</div>';
      if (textSummary) popupHtml += '<div style="font-size:13px;font-weight:400;color:var(--secondary-text-color, rgba(255,255,255,0.45));line-height:1.4;max-width:380px;margin:0 auto 12px">' + textSummary + '</div>';
      else if (condText) popupHtml += '<div style="font-size:13px;font-weight:400;color:var(--secondary-text-color, rgba(255,255,255,0.5));margin-bottom:12px">' + condText + '</div>';
      popupHtml += '</div>';
      popupHtml += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;max-width:380px;margin:0 auto">';
      popupHtml += dayCol + nightCol + '</div>' + timelineHtml;

      // Last update footer — per-period timestamp (oldest of EC / WEonG)
      const periodUpdated = item.updated;
      if (periodUpdated) {
        const updDate = new Date(periodUpdated);
        if (!isNaN(updDate)) {
          const lang = (h && h.language) || 'en';
          const timeStr = updDate.toLocaleTimeString(lang === 'fr' ? 'fr-CA' : 'en-CA', {
            hour: 'numeric', minute: '2-digit',
          });
          const label = lang === 'fr' ? 'Mis à jour à' : 'Updated at';
          popupHtml += '<div style="text-align:left;font-size:11px;color:var(--secondary-text-color, rgba(255,255,255,0.25));margin-top:16px">'
            + label + ' ' + timeStr + '</div>';
        }
      }

      return { title: fullName, content: popupHtml };
    });

    // Build summary columns
    let columnsHtml = '';
    forecast.forEach((item, i) => {
      const firstWord = (item.period || '').split(' ')[0];
      const dayLabel = escapeHtml(dayAbbr[firstWord] || firstWord);
      const isNightOnly = item.icon_code === null;

      const dayIcon = item.icon_code != null ? ecIcon(item.icon_code) : null;
      const nightCode = item.icon_code_night != null ? item.icon_code_night : item.icon_code;
      const nightIcon = nightCode != null ? ecIcon(nightCode) : 'mdi:weather-night';
      const showBadge = !isNightOnly && item.icon_code_night != null && item.icon_code_night !== item.icon_code;

      const high = item.temp_high;
      const low = item.temp_low;
      const flH = item.feels_like_high != null ? Math.round(item.feels_like_high) : null;
      const showFl = !isNightOnly && flH !== null && high !== null && Math.abs(flH - Math.round(high)) >= 3;

      const popDay = item.precip_prob_day || 0;
      const popNight = item.precip_prob_night || 0;
      const maxPop = Math.max(popDay, popNight);
      const roundedPop = Math.ceil(maxPop / 5) * 5;
      const showPrecip = roundedPop >= 5;

      // Daily columns prefer EC precip_accum (meteorologist-interpreted, days 0-2).
      // For days 3+ where EC has no accumulation, fall back to WEonG model amounts.
      const ecAccumDay = item.precip_accum_amount || 0;
      const ecAccumNight = item.precip_accum_amount_night || 0;
      const ecAccumUnit = item.precip_accum_unit || item.precip_accum_unit_night || '';
      const hasEcAccum = ecAccumDay > 0 || ecAccumNight > 0;
      let rainTotal, snowTotal;
      if (hasEcAccum) {
        const ecTotal = ecAccumDay + ecAccumNight;
        if (ecAccumUnit === 'cm') { rainTotal = 0; snowTotal = ecTotal; }
        else { rainTotal = ecTotal; snowTotal = 0; }
      } else {
        rainTotal = (item.rain_mm_day || 0) + (item.rain_mm_night || 0);
        snowTotal = (item.snow_cm_day || 0) + (item.snow_cm_night || 0);
      }
      const pColor = precipAmtColor(rainTotal, snowTotal, item.precip_type);

      columnsHtml += '<div class="daily-col" data-index="' + i + '">';
      columnsHtml += '<div class="d-label">' + dayLabel + '</div>';
      columnsHtml += '<div class="d-icon-row">';
      if (isNightOnly) {
        columnsHtml += '<ha-icon icon="' + nightIcon + '" class="d-icon-day"></ha-icon>';
      } else {
        columnsHtml += '<ha-icon icon="' + dayIcon + '" class="d-icon-day"></ha-icon>';
        if (showBadge) {
          columnsHtml += '<span class="d-icon-sep">\u00b7</span>';
          columnsHtml += '<ha-icon icon="' + nightIcon + '" class="d-icon-night"></ha-icon>';
        }
      }
      columnsHtml += '</div>';

      columnsHtml += '<div class="d-temp-row">';
      if (isNightOnly) {
        columnsHtml += '<span class="d-temp-lo" >' + Math.round(low) + '\u00b0</span>';
      } else if (high !== null && low !== null) {
        columnsHtml += '<span class="d-temp-hi">' + Math.round(high) + '\u00b0</span>';
        columnsHtml += '<span class="d-temp-lo">' + Math.round(low) + '\u00b0</span>';
      } else if (high !== null) {
        columnsHtml += '<span class="d-temp-hi">' + Math.round(high) + '\u00b0</span>';
      } else if (low !== null) {
        columnsHtml += '<span class="d-temp-lo" >' + Math.round(low) + '\u00b0</span>';
      }
      columnsHtml += '</div>';

      columnsHtml += '<div class="d-fl" style="' + (showFl ? '' : 'visibility:hidden') + '">'
        + (showFl ? 'FL ' + flH + '\u00b0' : '\u00a0') + '</div>';

      if (showPrecip) {
        columnsHtml += '<div class="d-pop" style="color:' + pColor + '">' + roundedPop + '%</div>';
        if (rainTotal > 0) columnsHtml += '<div class="d-amt" style="color:' + RAIN_COLOR + '">' + fmtAmt(rainTotal) + 'mm</div>';
        if (snowTotal > 0) columnsHtml += '<div class="d-amt" style="color:' + SNOW_COLOR + '">' + fmtAmt(snowTotal) + 'cm</div>';
      }
      columnsHtml += '</div>';
    });

    // If popup is open, update its content without re-rendering the card.
    // If popup is open, update only the popup content and skip the card re-render.
    if (this._openPopupIndex != null) {
      const popup = this._dailyPopups?.[this._openPopupIndex];
      if (popup) ECOverlay.get().update(this, popup.content);
      return;
    }

    // Preserve scroll position across re-renders
    const prevScroll = this.shadowRoot.querySelector('.daily-scroll')?.scrollLeft || 0;

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          contain: inline-size;
          overflow: hidden;
        }
        .section-header {
          font-size: 12px; font-weight: 600;
          color: var(--ec-weather-text-muted, var(--secondary-text-color, rgba(255,255,255,0.4)));
          letter-spacing: 0.5px; margin-top: 24px;
        }
        .daily-scroll {
          display: flex; flex-direction: row; justify-content: flex-start;
          overflow-x: auto; overflow-y: hidden;
          -webkit-overflow-scrolling: touch; scrollbar-width: none;
          padding: 8px 0; gap: 0;
        }
        .daily-scroll::-webkit-scrollbar { display: none; }
        .daily-col {
          flex: 0 0 100px; min-width: 100px;
          display: flex; flex-direction: column; align-items: center;
          padding: 12px 0; cursor: pointer;
          transition: background 120ms ease;
          border-right: 1px solid var(--ec-weather-divider, var(--divider-color, rgba(255,255,255,0.06)));
        }
        .daily-col:last-child { border-right: none; }
        .daily-col:active { background: var(--ha-card-background, rgba(255,255,255,0.06)); }
        @media (hover: hover) { .daily-col:hover { background: var(--ha-card-background, rgba(255,255,255,0.04)); } }
        .d-label { font-size: 13px; font-weight: 500; color: var(--ec-weather-text-secondary, var(--secondary-text-color, rgba(255,255,255,0.6))); margin-bottom: 10px; text-align: center; }
        .d-icon-row { display: flex; align-items: center; justify-content: center; gap: 4px; margin-bottom: 10px; }
        .d-icon-day { --mdc-icon-size: 28px; color: var(--ec-weather-text-primary, var(--primary-text-color, rgba(255,255,255,0.85))); }
        .d-icon-night { --mdc-icon-size: 14px; color: var(--secondary-text-color, rgba(255,255,255,0.55)); }
        .d-icon-sep { font-size: 10px; color: var(--secondary-text-color, rgba(255,255,255,0.2)); line-height: 1; }
        .d-temp-row { display: flex; justify-content: center; gap: 10px; font-size: 18px; font-weight: 700; margin-bottom: 2px; white-space: nowrap; }
        .d-temp-hi { color: var(--ec-weather-text-primary, var(--primary-text-color, #FFFFFF)); }
        .d-temp-lo { color: var(--ec-weather-text-secondary, var(--secondary-text-color, rgba(255,255,255,0.6))); }
        .d-fl { font-size: 12px; font-weight: 400; color: var(--ec-weather-text-muted, var(--secondary-text-color, rgba(255,255,255,0.45))); min-height: 16px; text-align: center; }
        .d-pop { font-size: 13px; font-weight: 600; margin-top: 8px; text-align: center; }
        .d-amt { font-size: 13px; font-weight: 500; margin-top: 2px; text-align: center; }

      </style>
      <div class="section-header">${t(h, 'daily')}</div>
      <div class="daily-scroll">${columnsHtml}</div>
    `;

    // Event delegation for daily column clicks — survives innerHTML updates
    this.shadowRoot.querySelector('.daily-scroll')?.addEventListener('click', (e) => {
      const col = e.target.closest('.daily-col');
      if (col) {
        e.stopPropagation();
        this._openDailyPopup(parseInt(col.dataset.index));
      }
    });

    // Restore scroll position
    if (prevScroll) {
      this.shadowRoot.querySelector('.daily-scroll').scrollLeft = prevScroll;
    }
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

customElements.define('ec-weather-card', ECWeatherCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'ec-weather-card',
  name: 'EC Weather Card',
  description: 'Environment Canada weather card with alerts, current conditions, hourly and daily forecasts.',
});

console.info('%c EC-WEATHER-CARD %c loaded ', 'background:#4FC3F7;color:#000;font-weight:bold', '');
