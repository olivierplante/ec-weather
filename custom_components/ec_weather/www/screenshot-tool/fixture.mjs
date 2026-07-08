/**
 * Synthetic demo data for release screenshots. Everything here is invented
 * (per the repo rule: no real personal data) but shaped exactly like the
 * live sensors — a believable July day with enough variety to show every
 * card feature: an alert, a wet today, a water-fill rain window in the
 * hourly, dual icons and range bars across a 7-day spread, and a rich
 * popup day with a full timeline.
 */

const HOUR_MS = 3600000;

function isoAtHourOffset(baseMs, offsetHours) {
  const d = new Date(baseMs + offsetHours * HOUR_MS);
  d.setMinutes(0, 0, 0);
  return d.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

function dateStrAtDayOffset(baseMs, offsetDays) {
  const d = new Date(baseMs + offsetDays * 86400000);
  return d.toISOString().slice(0, 10);
}

/** ~30 hours of hourly data: warm evening, overnight cool-off, a morning
 *  rain window (POP + amounts → water-fill zone), sunny afternoon. */
function buildHourly(nowMs) {
  const temps = [24, 23, 22, 21, 20, 19, 19, 18, 18, 18, 19, 20, 21, 22,
    22, 21, 20, 21, 22, 24, 25, 26, 27, 27, 26, 25, 24, 23, 22, 21];
  const icons = [2, 2, 30, 30, 30, 30, 30, 30, 33, 33, 12, 12, 12, 6,
    6, 12, 12, 2, 2, 1, 0, 0, 0, 0, 1, 1, 2, 30, 30, 30];
  const pops = [0, 0, 10, 40, 70, 80, 80, 60, 50, 30, 20, 10, 0, 0,
    0, 0, 0, 0, 10, 0, 0, 0, 0, 0, 0, 0, 10, 10, 0, 0];
  const rains = [null, null, null, 0.4, 1.8, 3.6, 2.9, 1.2, 0.8, 0.4, null, null, null, null,
    null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null];
  return temps.map((temp, i) => ({
    time: isoAtHourOffset(nowMs, i),
    temp,
    icon_code: icons[i],
    feels_like: i < 6 ? temp + 3 : (pops[i] >= 60 ? temp - 1 : null),
    precipitation_probability: pops[i],
    rain_mm: rains[i],
    snow_cm: null,
    wind_speed: i < 4 ? 14 : null,
    wind_gust: i < 4 ? 32 : null,
    wind_direction: i < 4 ? 'SW' : null,
  }));
}

/** Timesteps for the popup day (3-hourly, wet morning). */
function buildDayTimesteps(nowMs, dayOffset, half) {
  const specs = half === 'day'
    ? [[8, 18, 12, 40, 1.8], [11, 20, 12, 80, 3.6], [14, 22, 6, 60, 1.2], [17, 23, 2, 30, 0.6]]
    : [[20, 21, 30, 10, null], [23, 19, 30, 0, null], [2, 18, 30, 0, null], [5, 17, 30, 0, null]];
  return specs.map(([hourOfDay, temp, icon, pop, rain]) => {
    // Small-hour night steps (2AM, 5AM) belong to the NEXT calendar day.
    const daySpill = half === 'night' && hourOfDay < 6 ? 1 : 0;
    const d = new Date(nowMs + (dayOffset + daySpill) * 86400000);
    d.setHours(hourOfDay, 0, 0, 0);
    return {
      time: d.toISOString().replace(/\.\d{3}Z$/, 'Z'),
      temp,
      icon_code: icon,
      feels_like: pop >= 60 ? temp - 1 : null,
      precipitation_probability: pop,
      rain_mm: rain,
      snow_cm: null,
    };
  });
}

/** GEPS far-day (4-6) 3h timesteps: amounts ALWAYS null — the amount lives in
 *  the window-spanning vessels, driven by precip_windows below. */
function buildGepsTimesteps(nowMs, dayOffset, half) {
  const specs = half === 'day'
    ? [[8, 22, 12, 60], [11, 23, 12, 60], [14, 21, 6, 50], [17, 19, 2, 40]]
    : [[20, 18, 30, 20], [23, 17, 30, 10], [2, 16, 30, 5], [5, 15, 30, 5]];
  return specs.map(([hourOfDay, temp, icon, pop]) => {
    const d = new Date(nowMs + dayOffset * 86400000);
    d.setHours(hourOfDay, 0, 0, 0);
    return {
      time: d.toISOString().replace(/\.\d{3}Z$/, 'Z'),
      temp,
      icon_code: icon,
      feels_like: pop >= 60 ? temp - 1 : null,
      precipitation_probability: pop,
      rain_mm: null,
      snow_cm: null,
    };
  });
}

/** Two 12h GEPS windows for a far day: a wet daytime window (pop >= 30 + band →
 *  a spanning vessel) and a dry night window (renders nothing). */
function buildPrecipWindows(nowMs, dayOffset) {
  const at = (hourOfDay, dayShift = 0) => {
    const d = new Date(nowMs + (dayOffset + dayShift) * 86400000);
    d.setHours(hourOfDay, 0, 0, 0);
    return d.toISOString().replace(/\.\d{3}Z$/, 'Z');
  };
  return [
    { start: at(6), end: at(18), pop: 60, amount_p25: 4.0, amount_p75: 9.0 },
    { start: at(18), end: at(6, 1), pop: 15, amount_p25: null, amount_p75: null },
  ];
}

/** GEPS outlook entry (days 8+): medians + bands, muted row, summary popup. */
function buildOutlookEntry(nowMs, offset, spec) {
  return {
    period: dateStrAtDayOffset(nowMs, offset),
    date: dateStrAtDayOffset(nowMs, offset),
    source: 'outlook',
    timesteps_state: 'outlook',
    ...spec,
  };
}

function buildDaily(nowMs) {
  const day = (offset) => dateStrAtDayOffset(nowMs, offset);
  const weekday = (offset) => new Date(nowMs + offset * 86400000)
    .toLocaleDateString('en-CA', { weekday: 'long' });
  return [
    {
      period: 'Today', date: day(0),
      condition: 'Chance of showers', condition_night: 'Partly cloudy',
      icon_code: 12, icon_code_night: 33,
      temp_high: 24, temp_low: 17,
      feels_like_high: 28, feels_like_low: 16,
      humidity: 68, humidity_night: 82,
      uv_index: 7, uv_category: 'high',
      precip_prob: 70, precip_prob_day: 70, precip_prob_night: 20,
      precip_accum_amount: 8, precip_accum_unit: 'mm', precip_accum_name: 'rain',
      rain_mm_day: 8, rain_mm_night: null, snow_cm_day: null, snow_cm_night: null,
      wind_speed: 14, wind_gust: 32, wind_direction: 'SW',
      wind_speed_night: 8, wind_gust_night: 0, wind_direction_night: 'W',
      text_summary: 'Mainly cloudy with a 70 percent chance of showers. '
        + 'Risk of a thunderstorm this afternoon. High 24. Humidex 28. UV index 7 or high.',
      text_summary_night: 'Partly cloudy. Becoming clear after midnight. Low 17.',
      timesteps_day: buildDayTimesteps(nowMs, 0, 'day'),
      timesteps_night: buildDayTimesteps(nowMs, 0, 'night'),
      timesteps_state: 'loaded', icons_complete: true,
      updated: new Date(nowMs).toISOString(),
    },
    { period: weekday(1), date: day(1), icon_code: 0, icon_code_night: 30, temp_high: 29, temp_low: 16, precip_prob_day: 0, timesteps_day: [], timesteps_night: [], timesteps_state: 'loaded', icons_complete: true },
    { period: weekday(2), date: day(2), icon_code: 2, icon_code_night: 33, temp_high: 30, temp_low: 17, precip_prob_day: 20, timesteps_day: [], timesteps_night: [], timesteps_state: 'loaded', icons_complete: true },
    { period: weekday(3), date: day(3), icon_code: 12, icon_code_night: 12, temp_high: 22, temp_low: 15, precip_prob_day: 80, rain_mm_day: 12, timesteps_day: [], timesteps_night: [], timesteps_state: 'unavailable', icons_complete: true },
    { period: weekday(4), date: day(4), icon_code: 1, icon_code_night: 30, temp_high: 26, temp_low: 13, precip_prob_day: 0, timesteps_day: [], timesteps_night: [], timesteps_state: 'unavailable', icons_complete: true },
    { period: weekday(5), date: day(5), icon_code: 0, icon_code_night: 30, temp_high: 28, temp_low: 14, precip_prob_day: 0, timesteps_day: [], timesteps_night: [], timesteps_state: 'unavailable', icons_complete: true },
    // A GEPS far day (4-6): 3h timesteps with null amounts + precip_windows, so
    // the popup timeline shows the window-spanning amount vessels.
    {
      period: weekday(6), date: day(6), icon_code: 12, icon_code_night: 33,
      temp_high: 23, temp_low: 15, precip_prob_day: 60,
      timesteps_day: buildGepsTimesteps(nowMs, 6, 'day'),
      timesteps_night: buildGepsTimesteps(nowMs, 6, 'night'),
      timesteps_state: 'loaded', icons_complete: true,
      precip_windows: buildPrecipWindows(nowMs, 6),
    },
    // GEPS outlook rows (days 8-10): a wet day with an amount band, a dry
    // temperature-only day, and a chance-band day.
    buildOutlookEntry(nowMs, 7, {
      temp_high: 22, temp_low: 12, temp_range: { low: 10, high: 24 },
      pop_day: 55, pop_night: 20, pop_day_display: 55, pop_night_display: null,
      icon_day: 12, icon_night: 30, feels_like_day: 26, feels_like_night: null,
      amount_band: { low: 4.0, high: 9.0 },
      sentence: { range_low: 10, range_high: 24, dominant_pop: 55, amount_band: { low: 4.0, high: 9.0 } },
    }),
    buildOutlookEntry(nowMs, 8, {
      temp_high: 24, temp_low: 13, temp_range: { low: 11, high: 26 },
      pop_day: 20, pop_night: 10, pop_day_display: null, pop_night_display: null,
      icon_day: 1, icon_night: 30, feels_like_day: null, feels_like_night: null,
      amount_band: null,
      sentence: { range_low: 11, range_high: 26, dominant_pop: null, amount_band: null },
    }),
    buildOutlookEntry(nowMs, 9, {
      temp_high: 26, temp_low: 14, temp_range: { low: 12, high: 28 },
      pop_day: 40, pop_night: 15, pop_day_display: 40, pop_night_display: null,
      icon_day: 2, icon_night: 33, feels_like_day: null, feels_like_night: null,
      amount_band: null,
      sentence: { range_low: 12, range_high: 28, dominant_pop: 40, amount_band: null },
    }),
    buildOutlookEntry(nowMs, 10, {
      temp_high: 24, temp_low: 13, temp_range: { low: 10, high: 27 },
      pop_day: 30, pop_night: 25, pop_day_display: 30, pop_night_display: null,
      icon_day: 6, icon_night: 32, feels_like_day: null, feels_like_night: null,
      amount_band: null,
      sentence: { range_low: 10, range_high: 27, dominant_pop: 30, amount_band: null },
    }),
    buildOutlookEntry(nowMs, 11, {
      temp_high: 27, temp_low: 15, temp_range: { low: 12, high: 30 },
      pop_day: 20, pop_night: 10, pop_day_display: null, pop_night_display: null,
      icon_day: 0, icon_night: 30, feels_like_day: 29, feels_like_night: null,
      amount_band: null,
      sentence: { range_low: 12, range_high: 30, dominant_pop: 20, amount_band: null },
    }),
    buildOutlookEntry(nowMs, 12, {
      temp_high: 29, temp_low: 17, temp_range: { low: 14, high: 33 },
      pop_day: 55, pop_night: 45, pop_day_display: 55, pop_night_display: 45,
      icon_day: 6, icon_night: 36, feels_like_day: 32, feels_like_night: null,
      amount_band: { low: 2, high: 7 },
      sentence: { range_low: 14, range_high: 33, dominant_pop: 55, amount_band: { low: 2, high: 7 } },
    }),
    buildOutlookEntry(nowMs, 13, {
      temp_high: 25, temp_low: 14, temp_range: { low: 10, high: 29 },
      pop_day: 25, pop_night: 20, pop_day_display: null, pop_night_display: null,
      icon_day: 2, icon_night: 33, feels_like_day: null, feels_like_night: null,
      amount_band: null,
      sentence: { range_low: 10, range_high: 29, dominant_pop: 25, amount_band: null },
    }),
  ];
}

const state = (value, attributes = {}) => ({
  state: String(value),
  attributes,
  last_updated: new Date().toISOString(),
});

export function buildHass({ dark = true } = {}) {
  const nowMs = Date.now();
  return {
    language: 'en',
    themes: { darkMode: dark },
    locale: { time_format: '12' },
    config: { latitude: 45.5017 },
    callService: () => {},
    states: {
      'binary_sensor.ec_alert_active': state('on'),
      'sensor.ec_alerts': state('1', {
        alerts: [{
          type: 'watch',
          headline: 'severe thunderstorm watch',
          text: 'Conditions are favourable for the development of severe '
            + 'thunderstorms that may be capable of producing strong wind '
            + 'gusts, large hail and heavy rain.',
          expires: new Date(nowMs + 8 * HOUR_MS).toISOString(),
        }],
      }),
      'sensor.ec_temperature': state('24.3', { fetched_at: new Date().toISOString() }),
      'sensor.ec_feels_like': state('28.1'),
      'sensor.ec_humidity': state('68'),
      'sensor.ec_wind_speed': state('14'),
      'sensor.ec_wind_gust': state('32'),
      'sensor.ec_wind_direction': state('SW'),
      'sensor.ec_condition': state('Partly cloudy'),
      'sensor.ec_icon_code': state('2'),
      'sensor.ec_sunrise': state('05:14'),
      'sensor.ec_sunset': state('20:47'),
      'sensor.ec_air_quality': state('3', { risk_level: 'low' }),
      'sensor.ec_yesterday_precipitation': state('3.2', { published: true, data_type: 'split' }),
      'sensor.ec_yesterday_rain': state('3.2'),
      'sensor.ec_yesterday_snow': state('0'),
      'sun.sun': state('above_horizon'),
      'sensor.ec_hourly_forecast': state('ok', { forecast: buildHourly(nowMs) }),
      'sensor.ec_daily_forecast': state('ok', { forecast: buildDaily(nowMs) }),
    },
  };
}
