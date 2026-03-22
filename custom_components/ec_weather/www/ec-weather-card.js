/**
 * EC Weather Card — Custom Lovelace card for Environment Canada weather data.
 *
 * Sections: alerts, current, hourly, daily
 * Source: config/custom_components/ec_weather/
 */

// ─── Constants ───────────────────────────────────────────────────────────────

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

const DAY_NAMES = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];

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
  return val < 1 ? '<1' : String(Math.round(val * 10) / 10);
}

function fmtWind(speed, gust, dir) {
  if (!speed && !gust) return '';
  let s = dir ? dir + ' ' : '';
  s += Math.round(speed) + ' km/h';
  if (gust && gust > speed) s += ' (gusts ' + Math.round(gust) + ')';
  return s;
}

function fmtTime(isoStr) {
  const d = new Date(isoStr);
  const h = d.getHours();
  const ampm = h >= 12 ? 'PM' : 'AM';
  const h12 = h % 12 || 12;
  return h12 + ampm;
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

function precipColor(rain, snow, precipType) {
  if (snow > 0) return 'rgba(255,255,255,0.85)';
  if (rain > 0) return 'var(--ec-weather-precip-rain, #4FC3F7)';
  if (precipType === 'snow') return 'rgba(255,255,255,0.85)';
  return 'var(--ec-weather-precip-rain, #4FC3F7)';
}

// ─── Card Class ──────────────────────────────────────────────────────────────

class ECWeatherCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._config = null;
    this._rendered = false;
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
    // Only the "current" section shows the error banner with retry.
    // Other sections hide entirely to avoid repeating the message.
    if (this._config.section !== 'current') {
      this.shadowRoot.innerHTML = '';
      this._rendered = true;
      return;
    }

    this._rendered = true;
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; contain: inline-size; }
        .unavailable {
          background: rgba(10, 21, 32, 0.7);
          border-radius: 12px;
          padding: 24px 16px;
          text-align: center;
          color: rgba(255, 255, 255, 0.6);
          font-family: var(--ha-card-font-family, 'Segoe UI', sans-serif);
        }
        .unavailable ha-icon {
          --mdc-icon-size: 32px;
          color: rgba(255, 255, 255, 0.3);
          margin-bottom: 8px;
          display: block;
        }
        .unavailable .msg {
          font-size: 14px;
          margin-bottom: 12px;
        }
        .retry-btn {
          background: rgba(255, 255, 255, 0.1);
          border: 1px solid rgba(255, 255, 255, 0.15);
          border-radius: 8px;
          color: rgba(255, 255, 255, 0.7);
          padding: 8px 16px;
          font-size: 13px;
          cursor: pointer;
          transition: background 0.2s;
          font-family: inherit;
        }
        .retry-btn:hover {
          background: rgba(255, 255, 255, 0.18);
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
        <div class="msg">Weather data unavailable</div>
        <button class="retry-btn" id="retry">
          <ha-icon icon="mdi:refresh"></ha-icon>Retry
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
      statement: 'var(--ec-weather-alert-statement, rgba(255,255,255,0.6))',
    };

    const fmtExp = (iso) => {
      if (!iso) return '';
      const d = new Date(iso);
      if (isNaN(d)) return '';
      return d.toLocaleDateString('en-CA', {
        weekday: 'short', month: 'short', day: 'numeric',
        hour: 'numeric', minute: '2-digit',
      });
    };

    let bannersHtml = '';
    alerts.forEach((alert, i) => {
      const color = colors[alert.type] || colors.advisory;
      const headline = titleCase(alert.headline || alert.type);
      const exp = fmtExp(alert.expires);
      const expLine = exp
        ? '<div style="margin-bottom:8px;font-weight:500;opacity:0.85">Expires: ' + exp + '</div>'
        : '';
      const text = (alert.text || '').replace(/</g, '&lt;');

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
          background: #0a1520;
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
          color: #FFF;
          flex-shrink: 0;
        }
        .alert-title {
          font-size: 14px;
          font-weight: 500;
          color: #FFF;
        }
        .alert-detail {
          display: none;
          padding: 12px;
          font-size: 13px;
          color: rgba(255,255,255,0.85);
          white-space: pre-wrap;
          line-height: 1.4;
          text-align: left;
        }
      </style>
      <div id="alerts">${bannersHtml}</div>
    `;

    // Attach click handlers
    this.shadowRoot.querySelectorAll('.alert-header').forEach(el => {
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        const idx = el.dataset.index;
        const detail = this.shadowRoot.getElementById('alert-detail-' + idx);
        if (detail) {
          detail.style.display = detail.style.display === 'none' ? 'block' : 'none';
        }
      });
    });
  }

  _renderCurrent() {
    const h = this._hass;

    // Temperature + feels-like
    const temp = entityNum(h, 'sensor.ec_temperature');
    const fl = entityNum(h, 'sensor.ec_feels_like');
    const t = temp !== null ? Math.round(temp) : null;
    const f = fl !== null ? Math.round(fl) : null;
    const showFl = f !== null && t !== null && f !== t;

    // Wind
    const windSpeed = entityNum(h, 'sensor.ec_wind_speed');
    const windGust = entityNum(h, 'sensor.ec_wind_gust');
    const windDir = entityVal(h, 'sensor.ec_wind_direction');
    let windText = '';
    if (windSpeed !== null) {
      windText = 'Wind ' + Math.round(windSpeed) + ' km/h';
      if (windDir) windText += ' ' + windDir;
      if (windGust !== null && windGust > windSpeed)
        windText += ' (gusts ' + Math.round(windGust) + ' km/h)';
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
          : 'var(--ec-weather-text-secondary, rgba(255,255,255,0.6))';
      aqhiHtml = `<div class="aqhi" style="color:${color}">Air Quality: ${Math.round(aqhi)} \u00b7 ${risk}</div>`;
    }

    // Condition + icon
    const condition = entityVal(h, 'sensor.ec_condition');
    const iconCode = entityNum(h, 'sensor.ec_icon_code');
    const icon = ecIcon(iconCode);
    const condText = condition ? titleCase(condition) : '';

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
            if (hours === 0 && mins < 1)
              daylightHtml = '<div class="daylight">&lt; 1m daylight remaining</div>';
            else if (hours === 0)
              daylightHtml = `<div class="daylight">${mins}m daylight remaining</div>`;
            else
              daylightHtml = `<div class="daylight">${hours}h ${mins}m daylight remaining</div>`;
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
          color: var(--ec-weather-text-primary, #FFFFFF);
        }
        .t-fl {
          font-size: 14px;
          font-weight: 400;
          color: var(--ec-weather-text-secondary, rgba(255,255,255,0.6));
        }
        .wind {
          font-size: 14px;
          font-weight: 400;
          color: var(--ec-weather-text-secondary, rgba(255,255,255,0.6));
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
          color: var(--ec-weather-text-primary, #FFFFFF);
        }
        .condition-text {
          font-size: 14px;
          color: var(--ec-weather-text-primary, #FFFFFF);
        }
        .sun-times {
          font-size: 14px;
          color: var(--ec-weather-text-secondary, rgba(255,255,255,0.6));
          margin-top: 12px;
        }
        .daylight {
          font-size: 12px;
          color: var(--ec-weather-text-secondary, rgba(255,255,255,0.6));
          margin-top: 4px;
        }
      </style>
      <div class="temp-row">
        <span class="t-val">${t !== null ? t + '\u00b0' : '--\u00b0'}</span>
        ${showFl ? '<span class="t-fl">Feels like ' + f + '\u00b0</span>' : ''}
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

    // Pre-scan: determine which optional rows have any data
    const anyFeels = forecast.some(i => {
      const fl = i.feels_like;
      const t = i.temp !== null && i.temp !== undefined ? Math.round(i.temp) : null;
      return fl !== null && fl !== undefined && Math.round(fl) !== t;
    });
    const anyPop = forecast.some(i => Math.ceil((i.precip_prob || 0) / 5) * 5 >= 5);
    const anyRain = forecast.some(i => (i.rain_amt_mm || 0) > 0);
    const anySnow = forecast.some(i => (i.snow_amt_cm || 0) > 0);

    // Build grid-template-rows based on which optional rows are present
    let gridRows = '20px 36px 22px'; // time, icon, temp (always)
    if (anyFeels) gridRows += ' 18px';
    if (anyPop) gridRows += ' 16px';
    if (anyRain) gridRows += ' 16px';
    if (anySnow) gridRows += ' 16px';

    let itemsHtml = '';
    let prevDateStr = null;

    forecast.forEach(item => {
      if (item.temp === null && item.temp === undefined) return;
      const date = new Date(item.datetime);
      const dateStr = date.toLocaleDateString('en-CA');

      // Day separator
      if (prevDateStr !== null && dateStr !== prevDateStr) {
        itemsHtml += `
          <div class="hourly-day-sep">
            <div class="hourly-day-label">${DAY_NAMES[date.getDay()]}</div>
          </div>`;
      }
      prevDateStr = dateStr;

      const hour = date.getHours();
      const ampm = hour >= 12 ? 'PM' : 'AM';
      const hour12 = hour % 12 || 12;
      const timeStr = hour12 + ' ' + ampm;

      const icon = ecIcon(item.icon_code);
      const temp = item.temp !== null && item.temp !== undefined
        ? Math.round(item.temp) : '\u2014';
      const precipProbRaw = item.precip_prob || 0;
      const precipProb = Math.ceil(precipProbRaw / 5) * 5;

      const feelsLikeRaw = item.feels_like;
      const feelsLike = feelsLikeRaw !== null && feelsLikeRaw !== undefined
        ? Math.round(feelsLikeRaw) : null;
      const showFeels = feelsLike !== null && feelsLike !== temp;

      const rainAmt = item.rain_amt_mm || 0;
      const snowAmt = item.snow_amt_cm || 0;

      itemsHtml += `
        <div class="hourly-item" style="grid-template-rows:${gridRows}">
          <div class="hourly-time">${timeStr}</div>
          <ha-icon icon="${icon}" class="hourly-icon"></ha-icon>
          <div class="hourly-temp">${temp}\u00b0</div>
          ${anyFeels ? '<div class="hourly-feels" style="'
            + (showFeels ? '' : 'visibility:hidden')
            + '">' + (showFeels ? 'FL ' + feelsLike + '\u00b0' : '\u2014') + '</div>' : ''}
          ${anyPop ? '<div class="hourly-precip" style="'
            + (precipProb >= 5 ? '' : 'visibility:hidden')
            + '">' + (precipProb >= 5 ? precipProb + '%' : '') + '</div>' : ''}
          ${anyRain ? '<div class="hourly-rain-amt" style="'
            + (rainAmt > 0 ? '' : 'visibility:hidden')
            + '">' + (rainAmt > 0 ? rainAmt + 'mm' : '0') + '</div>' : ''}
          ${anySnow ? '<div class="hourly-snow-amt" style="'
            + (snowAmt > 0 ? '' : 'visibility:hidden')
            + '">' + (snowAmt > 0 ? snowAmt + 'cm' : '0') + '</div>' : ''}
        </div>`;
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
          color: var(--ec-weather-text-muted, rgba(255,255,255,0.4));
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
        .hourly-item {
          flex: 0 0 54px;
          min-width: 54px;
          display: grid;
          justify-items: center;
          align-items: center;
          padding: 8px 0;
          border-right: 1px solid var(--ec-weather-divider, rgba(255,255,255,0.06));
        }
        .hourly-item:last-child { border-right: none; }
        .hourly-time {
          font-size: 12px;
          font-weight: 500;
          color: var(--ec-weather-text-secondary, rgba(255,255,255,0.6));
        }
        .hourly-icon {
          --mdc-icon-size: 28px;
          color: var(--ec-weather-text-primary, rgba(255,255,255,0.85));
        }
        .hourly-temp {
          font-size: 16px;
          font-weight: 700;
          line-height: 20px;
          color: var(--ec-weather-text-primary, #FFFFFF);
        }
        .hourly-feels {
          font-size: 12px;
          font-weight: 400;
          line-height: 16px;
          color: var(--ec-weather-text-muted, rgba(255,255,255,0.45));
        }
        .hourly-precip {
          font-size: 12px;
          font-weight: 600;
          line-height: 16px;
          color: var(--ec-weather-precip-rain, #4FC3F7);
        }
        .hourly-rain-amt {
          font-size: 12px;
          font-weight: 500;
          line-height: 16px;
          color: var(--ec-weather-precip-rain, #4FC3F7);
        }
        .hourly-snow-amt {
          font-size: 12px;
          font-weight: 500;
          line-height: 16px;
          color: var(--ec-weather-precip-snow, rgba(255,255,255,0.85));
        }
        .hourly-day-sep {
          flex: 0 0 36px;
          min-width: 36px;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 8px 0;
          border-right: 1px solid rgba(255,255,255,0.15);
          border-left: 1px solid rgba(255,255,255,0.15);
        }
        .hourly-day-label {
          font-size: 11px;
          font-weight: 700;
          color: rgba(255,255,255,0.5);
          letter-spacing: 0.5px;
          writing-mode: vertical-lr;
          text-orientation: mixed;
          transform: rotate(180deg);
        }
      </style>
      <div class="section-header">HOURLY</div>
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
    const SNOW_COLOR = 'var(--ec-weather-precip-snow, rgba(255,255,255,0.85))';
    const dayAbbr = {
      Monday: 'Mon', Tuesday: 'Tue', Wednesday: 'Wed',
      Thursday: 'Thu', Friday: 'Fri', Saturday: 'Sat', Sunday: 'Sun',
      Tomorrow: 'Tmrw',
    };

    const colPrecipColor = (rainAmt, snowAmt, precipType) => {
      if ((snowAmt || 0) > 0 && (rainAmt || 0) > 0) return RAIN_COLOR;
      if ((snowAmt || 0) > 0) return SNOW_COLOR;
      if ((rainAmt || 0) > 0) return RAIN_COLOR;
      if (precipType === 'snow') return SNOW_COLOR;
      return RAIN_COLOR;
    };

    const dailyPrecipColor = (rainDay, rainNight, snowDay, snowNight, precipType) => {
      const rain = (rainDay || 0) + (rainNight || 0);
      const snow = (snowDay || 0) + (snowNight || 0);
      if (snow > 0 && rain > 0) return RAIN_COLOR;
      if (snow > 0) return SNOW_COLOR;
      if (rain > 0) return RAIN_COLOR;
      if (precipType === 'snow') return SNOW_COLOR;
      return RAIN_COLOR;
    };

    const localFmtAmt = (v) => v < 1 ? '<1' : Math.round(v);

    const localFmtWind = (speed, gust, dir) => {
      if (speed == null) return null;
      let w = dir ? dir + ' ' : '';
      w += Math.round(speed) + ' km/h';
      if (gust != null) w += ' gusts ' + Math.round(gust);
      return w;
    };

    const localFmtTime = (iso) => {
      const d = new Date(iso);
      const hr = d.getHours();
      if (hr === 0) return '12AM';
      if (hr === 12) return '12PM';
      return hr > 12 ? (hr - 12) + 'PM' : hr + 'AM';
    };

    // Pre-compute popup data for each day
    this._dailyPopups = forecast.map((item) => {
      const fullName = (item.period || '').split(' ')[0];
      const isNightOnly = item.icon_code === null;

      const dayIconStr = item.icon_code != null ? ecIcon(item.icon_code) : null;
      const nightCode = item.icon_code_night != null ? item.icon_code_night : item.icon_code;
      const nightIconStr = nightCode != null ? ecIcon(nightCode) : 'mdi:weather-night';

      const condText = item.condition || item.condition_night || '';
      const dTemp = item.temp_high != null ? Math.round(item.temp_high) + '\u00b0' : '\u2014';
      const nTemp = item.temp_low != null ? Math.round(item.temp_low) + '\u00b0' : '\u2014';

      const flH = item.feels_like_high != null ? Math.round(item.feels_like_high) : null;
      const flL = item.feels_like_low != null ? Math.round(item.feels_like_low) : null;
      const showFlH = flH !== null && item.temp_high !== null && Math.abs(flH - Math.round(item.temp_high)) >= 3;
      const showFlL = flL !== null && item.temp_low !== null && Math.abs(flL - Math.round(item.temp_low)) >= 3;

      const dPrecipCol = colPrecipColor(item.rain_amt_mm_day, item.snow_amt_cm_day, item.precip_type);
      const nPrecipCol = colPrecipColor(item.rain_amt_mm_night, item.snow_amt_cm_night, item.precip_type);

      const muted = 'color:rgba(255,255,255,0.35)';
      const dash = '<span style="' + muted + '">\u2014</span>';
      const mutedSm = 'font-size:13px;color:rgba(255,255,255,0.45)';
      const icoSm = '--mdc-icon-size:14px;vertical-align:middle;margin-right:3px;color:rgba(255,255,255,0.4)';

      const popupCol = (label, iconStr, temp, showFl, flVal, pop, rain, snow, pColor,
                        windStr, humidity, accumAmt, accumUnit, accumName, uvIdx, uvCat) => {
        let c = '<div style="text-align:center">';
        c += '<div style="font-size:13px;font-weight:600;color:rgba(255,255,255,0.35);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px">' + label + '</div>';
        if (iconStr) {
          c += '<ha-icon icon="' + iconStr + '" style="--mdc-icon-size:32px;color:rgba(255,255,255,0.85)"></ha-icon>';
        } else {
          c += '<div style="height:32px;display:flex;align-items:center;justify-content:center">' + dash + '</div>';
        }
        c += '<div style="font-size:24px;font-weight:700;color:#fff;margin-top:8px;margin-bottom:2px">' + temp + '</div>';
        const flVis = showFl ? '' : 'visibility:hidden;';
        const flTxt = showFl ? 'FL ' + flVal + '\u00b0' : '\u00a0';
        c += '<div style="font-size:13px;font-weight:400;color:rgba(255,255,255,0.45);min-height:18px;' + flVis + '">' + flTxt + '</div>';
        if (windStr) c += '<div style="' + mutedSm + ';margin-top:8px"><ha-icon icon="mdi:weather-windy" style="' + icoSm + '"></ha-icon>' + windStr + '</div>';
        if (humidity != null) c += '<div style="' + mutedSm + ';margin-top:4px"><ha-icon icon="mdi:water-percent" style="' + icoSm + '"></ha-icon>' + humidity + '%</div>';
        if (uvIdx != null) c += '<div style="' + mutedSm + ';margin-top:4px"><ha-icon icon="mdi:weather-sunny-alert" style="' + icoSm + '"></ha-icon>UV ' + uvIdx + (uvCat ? ' (' + uvCat + ')' : '') + '</div>';
        if (accumAmt != null && accumAmt > 0) {
          const accumColor = (accumName === 'snow') ? SNOW_COLOR : RAIN_COLOR;
          c += '<div style="margin-top:10px"><div style="font-size:13px;font-weight:500;color:' + accumColor + '">' + accumAmt + (accumUnit || '') + ' ' + (accumName || '') + '</div></div>';
        }
        if ((rain || 0) > 0 || (snow || 0) > 0) {
          c += '<div style="margin-top:' + (accumAmt > 0 ? '4' : '10') + 'px">';
          if ((rain || 0) > 0) c += '<div style="font-size:11px;font-weight:400;color:' + RAIN_COLOR + ';opacity:0.6;margin-top:2px">\u03a3 ' + localFmtAmt(rain) + 'mm</div>';
          if ((snow || 0) > 0) c += '<div style="font-size:11px;font-weight:400;color:' + SNOW_COLOR + ';opacity:0.6;margin-top:2px">\u03a3 ' + localFmtAmt(snow) + 'cm</div>';
          c += '</div>';
        }
        c += '</div>';
        return c;
      };

      const dayCol = popupCol('DAY',
        isNightOnly ? null : dayIconStr, isNightOnly ? dash : dTemp,
        isNightOnly ? false : showFlH, flH,
        isNightOnly ? null : item.precip_prob_day, isNightOnly ? null : item.rain_amt_mm_day,
        isNightOnly ? null : item.snow_amt_cm_day, dPrecipCol,
        isNightOnly ? null : localFmtWind(item.wind_speed, item.wind_gust, item.wind_direction),
        isNightOnly ? null : item.humidity,
        isNightOnly ? null : item.precip_accum_amount, isNightOnly ? null : item.precip_accum_unit,
        isNightOnly ? null : item.precip_accum_name,
        isNightOnly ? null : item.uv_index, isNightOnly ? null : item.uv_category);

      const nightCol = popupCol('NIGHT', nightIconStr, nTemp, showFlL, flL,
        item.precip_prob_night, item.rain_amt_mm_night, item.snow_amt_cm_night, nPrecipCol,
        localFmtWind(item.wind_speed_night, item.wind_gust_night, item.wind_direction_night),
        item.humidity_night,
        item.precip_accum_amount_night, item.precip_accum_unit_night, item.precip_accum_name_night,
        null, null);

      const textSummary = item.text_summary || item.text_summary_night || '';

      // Timeline
      const allTimesteps = (item.timesteps_day || []).concat(item.timesteps_night || []);
      let timelineHtml = '';
      if (allTimesteps.length > 0) {
        timelineHtml += '<div style="margin-top:16px;border-top:1px solid rgba(255,255,255,0.08);padding-top:12px">';
        timelineHtml += '<div style="font-size:13px;font-weight:600;color:rgba(255,255,255,0.35);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px">Timeline</div>';
        timelineHtml += '<div style="display:flex;overflow-x:auto;gap:0;scrollbar-width:none;-webkit-overflow-scrolling:touch">';
        allTimesteps.forEach(ts => {
          const hasIcon = ts.icon_code != null;
          const tsIcon = hasIcon ? ecIcon(ts.icon_code) : null;
          const tsTemp = ts.temp_c != null ? Math.round(ts.temp_c) + '\u00b0' : '';
          const tsPop = ts.pop != null && ts.pop > 0 ? ts.pop + '%' : '';
          const tsPopColor = ((ts.snow_cm || 0) > 0 && (ts.rain_mm || 0) === 0) ? SNOW_COLOR : RAIN_COLOR;
          let tsRain = (ts.rain_mm || 0) > 0 ? localFmtAmt(ts.rain_mm) + 'mm' : '';
          let tsSnow = (ts.snow_cm || 0) > 0 ? localFmtAmt(ts.snow_cm) + 'cm' : '';

          timelineHtml += '<div style="min-width:56px;flex:0 0 56px;text-align:center;padding:6px 0">';
          timelineHtml += '<div style="font-size:12px;font-weight:500;color:rgba(255,255,255,0.5)">' + localFmtTime(ts.time) + '</div>';
          if (tsIcon) timelineHtml += '<ha-icon icon="' + tsIcon + '" style="--mdc-icon-size:24px;color:rgba(255,255,255,0.7);margin:4px 0"></ha-icon>';
          else timelineHtml += '<div style="height:32px"></div>';
          if (tsTemp) timelineHtml += '<div style="font-size:15px;font-weight:700;color:#fff">' + tsTemp + '</div>';
          if (tsPop) timelineHtml += '<div style="font-size:13px;font-weight:600;color:' + tsPopColor + '">' + tsPop + '</div>';
          if (tsRain) timelineHtml += '<div style="font-size:12px;font-weight:500;color:' + RAIN_COLOR + '">' + tsRain + '</div>';
          if (tsSnow) timelineHtml += '<div style="font-size:12px;font-weight:500;color:' + SNOW_COLOR + '">' + tsSnow + '</div>';
          timelineHtml += '</div>';
        });
        timelineHtml += '</div></div>';
      }

      let popupHtml = '<div style="text-align:center;margin-bottom:4px">';
      popupHtml += '<div style="font-size:18px;font-weight:700;color:#fff;margin-bottom:8px">' + fullName + '</div>';
      if (textSummary) popupHtml += '<div style="font-size:13px;font-weight:400;color:rgba(255,255,255,0.45);line-height:1.4;max-width:380px;margin:0 auto 12px">' + textSummary + '</div>';
      else if (condText) popupHtml += '<div style="font-size:13px;font-weight:400;color:rgba(255,255,255,0.5);margin-bottom:12px">' + condText + '</div>';
      popupHtml += '</div>';
      popupHtml += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;max-width:380px;margin:0 auto">';
      popupHtml += dayCol + nightCol + '</div>' + timelineHtml;

      return { title: fullName, content: popupHtml };
    });

    // Build summary columns
    let columnsHtml = '';
    forecast.forEach((item, i) => {
      const firstWord = (item.period || '').split(' ')[0];
      const dayLabel = dayAbbr[firstWord] || firstWord;
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
        rainTotal = (item.rain_amt_mm_day || 0) + (item.rain_amt_mm_night || 0);
        snowTotal = (item.snow_amt_cm_day || 0) + (item.snow_amt_cm_night || 0);
      }
      const pColor = dailyPrecipColor(item.rain_amt_mm_day, item.rain_amt_mm_night,
        item.snow_amt_cm_day, item.snow_amt_cm_night, item.precip_type);

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
        columnsHtml += '<span class="d-temp-lo" style="color:#fff">' + Math.round(low) + '\u00b0</span>';
      } else if (high !== null && low !== null) {
        columnsHtml += '<span class="d-temp-hi">' + Math.round(high) + '\u00b0</span>';
        columnsHtml += '<span class="d-temp-lo">' + Math.round(low) + '\u00b0</span>';
      } else if (high !== null) {
        columnsHtml += '<span class="d-temp-hi">' + Math.round(high) + '\u00b0</span>';
      } else if (low !== null) {
        columnsHtml += '<span class="d-temp-lo" style="color:#fff">' + Math.round(low) + '\u00b0</span>';
      }
      columnsHtml += '</div>';

      columnsHtml += '<div class="d-fl" style="' + (showFl ? '' : 'visibility:hidden') + '">'
        + (showFl ? 'FL ' + flH + '\u00b0' : '\u00a0') + '</div>';

      if (showPrecip) {
        columnsHtml += '<div class="d-pop" style="color:' + pColor + '">' + roundedPop + '%</div>';
        if (rainTotal > 0) columnsHtml += '<div class="d-amt" style="color:' + RAIN_COLOR + '">' + localFmtAmt(rainTotal) + 'mm</div>';
        if (snowTotal > 0) columnsHtml += '<div class="d-amt" style="color:' + SNOW_COLOR + '">' + localFmtAmt(snowTotal) + 'cm</div>';
      }
      columnsHtml += '</div>';
    });

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          contain: inline-size;
          overflow: hidden;
        }
        .section-header {
          font-size: 12px; font-weight: 600;
          color: var(--ec-weather-text-muted, rgba(255,255,255,0.4));
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
          border-right: 1px solid var(--ec-weather-divider, rgba(255,255,255,0.06));
        }
        .daily-col:last-child { border-right: none; }
        .daily-col:active { background: rgba(255,255,255,0.06); }
        @media (hover: hover) { .daily-col:hover { background: rgba(255,255,255,0.04); } }
        .d-label { font-size: 13px; font-weight: 500; color: var(--ec-weather-text-secondary, rgba(255,255,255,0.6)); margin-bottom: 10px; text-align: center; }
        .d-icon-row { display: flex; align-items: center; justify-content: center; gap: 4px; margin-bottom: 10px; }
        .d-icon-day { --mdc-icon-size: 28px; color: var(--ec-weather-text-primary, rgba(255,255,255,0.85)); }
        .d-icon-night { --mdc-icon-size: 14px; color: rgba(255,255,255,0.55); }
        .d-icon-sep { font-size: 10px; color: rgba(255,255,255,0.2); line-height: 1; }
        .d-temp-row { display: flex; justify-content: center; gap: 10px; font-size: 18px; font-weight: 700; margin-bottom: 2px; white-space: nowrap; }
        .d-temp-hi { color: var(--ec-weather-text-primary, #FFFFFF); }
        .d-temp-lo { color: var(--ec-weather-text-secondary, rgba(255,255,255,0.6)); }
        .d-fl { font-size: 12px; font-weight: 400; color: var(--ec-weather-text-muted, rgba(255,255,255,0.45)); min-height: 16px; text-align: center; }
        .d-pop { font-size: 13px; font-weight: 600; margin-top: 8px; text-align: center; }
        .d-amt { font-size: 13px; font-weight: 500; margin-top: 2px; text-align: center; }

        /* Overlay popup */
        .overlay { display: none; position: fixed; inset: 0; z-index: 999; align-items: center; justify-content: center; }
        .overlay.open { display: flex; }
        .overlay-backdrop { position: absolute; inset: 0; background: rgba(0,0,0,0.8); }
        .overlay-content {
          position: relative; z-index: 1;
          background: #0a1520; border-radius: 12px;
          padding: 24px; max-width: 420px; width: 90vw;
          max-height: 85vh; overflow-y: auto;
          scrollbar-width: none;
          touch-action: pan-y;
          transition: transform 150ms ease;
        }
        .overlay-content::-webkit-scrollbar { display: none; }
        .overlay-close {
          position: absolute; top: 12px; right: 12px;
          background: none; border: none; color: rgba(255,255,255,0.5);
          font-size: 20px; cursor: pointer; padding: 4px 8px; line-height: 1;
        }
        .overlay-close:hover { color: #fff; }
        @media (max-width: 768px) {
          .overlay-content {
            max-width: 100%; width: 100%; max-height: 100%; height: 100%;
            border-radius: 0; box-sizing: border-box;
          }
        }
      </style>
      <div class="section-header">DAILY</div>
      <div class="daily-scroll">${columnsHtml}</div>
      <div class="overlay" id="daily-overlay">
        <div class="overlay-backdrop" id="overlay-backdrop"></div>
        <div class="overlay-content">
          <button class="overlay-close" id="overlay-close">\u2715</button>
          <div id="overlay-body"></div>
        </div>
      </div>
    `;

    // Attach click handlers for daily columns
    this.shadowRoot.querySelectorAll('.daily-col').forEach(el => {
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        this._openDailyPopup(parseInt(el.dataset.index));
      });
    });

    // Overlay close handlers
    this.shadowRoot.getElementById('overlay-backdrop')?.addEventListener('click', () => this._closeDailyPopup());
    this.shadowRoot.getElementById('overlay-close')?.addEventListener('click', () => this._closeDailyPopup());
  }

  _openDailyPopup(index) {
    const popup = this._dailyPopups?.[index];
    if (!popup) return;

    const overlay = this.shadowRoot.getElementById('daily-overlay');
    const body = this.shadowRoot.getElementById('overlay-body');
    if (!overlay || !body) return;

    body.innerHTML = popup.content;
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';

    // Escape key listener
    this._escHandler = (e) => { if (e.key === 'Escape') this._closeDailyPopup(); };
    document.addEventListener('keydown', this._escHandler);

    // Swipe down to close (mobile)
    const content = this.shadowRoot.querySelector('.overlay-content');
    this._touchStartY = 0;
    this._touchCurrentY = 0;
    this._isDragging = false;

    this._onTouchStart = (e) => {
      if (content.scrollTop > 0) return;
      this._touchStartY = e.touches[0].clientY;
      this._touchCurrentY = this._touchStartY;
      this._isDragging = false;
    };
    this._onTouchMove = (e) => {
      if (!this._touchStartY) return;
      this._touchCurrentY = e.touches[0].clientY;
      const delta = this._touchCurrentY - this._touchStartY;
      if (delta > 10) {
        this._isDragging = true;
        e.preventDefault();
        content.style.transform = 'translateY(' + delta + 'px)';
        content.style.transition = 'none';
      }
    };
    this._onTouchEnd = () => {
      const delta = this._touchCurrentY - this._touchStartY;
      if (this._isDragging && delta > 80) {
        content.style.transition = 'transform 200ms ease';
        content.style.transform = 'translateY(100vh)';
        setTimeout(() => this._closeDailyPopup(), 200);
      } else {
        content.style.transition = 'transform 150ms ease';
        content.style.transform = '';
      }
      this._touchStartY = 0;
      this._touchCurrentY = 0;
      this._isDragging = false;
    };

    content.addEventListener('touchstart', this._onTouchStart, { passive: true });
    content.addEventListener('touchmove', this._onTouchMove, { passive: false });
    content.addEventListener('touchend', this._onTouchEnd, { passive: true });
  }

  _closeDailyPopup() {
    const overlay = this.shadowRoot.getElementById('daily-overlay');
    if (overlay) overlay.classList.remove('open');
    document.body.style.overflow = '';
    if (this._escHandler) {
      document.removeEventListener('keydown', this._escHandler);
      this._escHandler = null;
    }
    // Clean up touch listeners
    const content = this.shadowRoot?.querySelector('.overlay-content');
    if (content) {
      content.style.transform = '';
      if (this._onTouchStart) content.removeEventListener('touchstart', this._onTouchStart);
      if (this._onTouchMove) content.removeEventListener('touchmove', this._onTouchMove);
      if (this._onTouchEnd) content.removeEventListener('touchend', this._onTouchEnd);
    }
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
