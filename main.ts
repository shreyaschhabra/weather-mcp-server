import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';

const server = new McpServer({
  name: 'weather-mcp-server',
  version: '2.0.0',
});

// ─── helpers ────────────────────────────────────────────────────────────────

interface GeoResult {
  name: string;
  latitude: number;
  longitude: number;
  country: string;
  admin1?: string;
}

async function geocode(city: string): Promise<GeoResult | null> {
  const res = await fetch(
    `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(city)}&count=1&language=en&format=json`
  );
  const data = await res.json();
  if (!data.results || data.results.length === 0) return null;
  return data.results[0];
}

function wmoCodeToDescription(code: number): string {
  const codes: Record<number, string> = {
    0: 'Clear sky', 1: 'Mainly clear', 2: 'Partly cloudy', 3: 'Overcast',
    45: 'Fog', 48: 'Icy fog',
    51: 'Light drizzle', 53: 'Moderate drizzle', 55: 'Dense drizzle',
    61: 'Slight rain', 63: 'Moderate rain', 65: 'Heavy rain',
    71: 'Slight snow', 73: 'Moderate snow', 75: 'Heavy snow',
    80: 'Slight rain showers', 81: 'Moderate rain showers', 82: 'Violent rain showers',
    95: 'Thunderstorm', 96: 'Thunderstorm with hail', 99: 'Thunderstorm with heavy hail',
  };
  return codes[code] ?? `WMO code ${code}`;
}

// ─── tool 1 (original): get current weather ─────────────────────────────────

server.tool(
  'get-weather',
  'Get the current weather for a city',
  { city: z.string().describe('City name') },
  async ({ city }) => {
    const geo = await geocode(city);
    if (!geo) return { content: [{ type: 'text', text: `City "${city}" not found.` }] };

    const res = await fetch(
      `https://api.open-meteo.com/v1/forecast?latitude=${geo.latitude}&longitude=${geo.longitude}` +
      `&current=temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,` +
      `precipitation,rain,showers,cloud_cover,weather_code` +
      `&temperature_unit=celsius&wind_speed_unit=kmh`
    );
    const data = await res.json();
    const c = data.current;

    const summary = [
      `📍 ${geo.name}, ${geo.admin1 ?? ''} ${geo.country}`,
      `🌡️  Temperature: ${c.temperature_2m}°C (feels like ${c.apparent_temperature}°C)`,
      `💧 Humidity: ${c.relative_humidity_2m}%`,
      `💨 Wind: ${c.wind_speed_10m} km/h`,
      `🌧️  Precipitation: ${c.precipitation} mm`,
      `☁️  Cloud cover: ${c.cloud_cover}%`,
      `🌤️  Condition: ${wmoCodeToDescription(c.weather_code)}`,
    ].join('\n');

    return { content: [{ type: 'text', text: summary }] };
  }
);

// ─── tool 2: 7-day daily forecast ───────────────────────────────────────────

server.tool(
  'get-forecast',
  'Get the 7-day daily weather forecast for a city',
  {
    city: z.string().describe('City name'),
    days: z.number().min(1).max(7).default(7).describe('Number of forecast days (1–7)'),
  },
  async ({ city, days }) => {
    const geo = await geocode(city);
    if (!geo) return { content: [{ type: 'text', text: `City "${city}" not found.` }] };

    const res = await fetch(
      `https://api.open-meteo.com/v1/forecast?latitude=${geo.latitude}&longitude=${geo.longitude}` +
      `&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code,wind_speed_10m_max` +
      `&temperature_unit=celsius&wind_speed_unit=kmh&forecast_days=${days}&timezone=auto`
    );
    const data = await res.json();
    const d = data.daily;

    const rows = d.time.map((date: string, i: number) =>
      `📅 ${date}  ${wmoCodeToDescription(d.weather_code[i]).padEnd(25)} ` +
      `🌡️ ${d.temperature_2m_min[i]}–${d.temperature_2m_max[i]}°C  ` +
      `🌧️ ${d.precipitation_sum[i]}mm  💨 ${d.wind_speed_10m_max[i]}km/h`
    );

    const text = [`📍 ${days}-day forecast for ${geo.name}, ${geo.country}`, ...rows].join('\n');
    return { content: [{ type: 'text', text }] };
  }
);

// ─── tool 3: hourly forecast for today ──────────────────────────────────────

server.tool(
  'get-hourly-forecast',
  'Get today\'s hour-by-hour weather forecast for a city',
  { city: z.string().describe('City name') },
  async ({ city }) => {
    const geo = await geocode(city);
    if (!geo) return { content: [{ type: 'text', text: `City "${city}" not found.` }] };

    const res = await fetch(
      `https://api.open-meteo.com/v1/forecast?latitude=${geo.latitude}&longitude=${geo.longitude}` +
      `&hourly=temperature_2m,precipitation_probability,weather_code,wind_speed_10m` +
      `&temperature_unit=celsius&wind_speed_unit=kmh&forecast_days=1&timezone=auto`
    );
    const data = await res.json();
    const h = data.hourly;

    const rows = h.time.map((t: string, i: number) => {
      const hour = t.split('T')[1];
      return `${hour}  ${wmoCodeToDescription(h.weather_code[i]).padEnd(22)} ` +
        `${h.temperature_2m[i]}°C  🌧️${h.precipitation_probability[i]}%  💨${h.wind_speed_10m[i]}km/h`;
    });

    const text = [`📍 Hourly forecast for ${geo.name}, ${geo.country}`, ...rows].join('\n');
    return { content: [{ type: 'text', text }] };
  }
);

// ─── tool 4: compare weather across multiple cities ─────────────────────────

server.tool(
  'compare-cities-weather',
  'Compare current weather across multiple cities side by side',
  {
    cities: z
      .array(z.string())
      .min(2)
      .max(5)
      .describe('List of 2–5 city names to compare'),
  },
  async ({ cities }) => {
    const results = await Promise.all(
      cities.map(async (city) => {
        const geo = await geocode(city);
        if (!geo) return { city, error: 'not found' };

        const res = await fetch(
          `https://api.open-meteo.com/v1/forecast?latitude=${geo.latitude}&longitude=${geo.longitude}` +
          `&current=temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code` +
          `&temperature_unit=celsius&wind_speed_unit=kmh`
        );
        const data = await res.json();
        const c = data.current;
        return {
          city: `${geo.name}, ${geo.country}`,
          temp: c.temperature_2m,
          feelsLike: c.apparent_temperature,
          humidity: c.relative_humidity_2m,
          wind: c.wind_speed_10m,
          condition: wmoCodeToDescription(c.weather_code),
        };
      })
    );

    const lines = results.map((r) => {
      if ('error' in r) return `❌ ${r.city}: not found`;
      return (
        `📍 ${r.city}\n` +
        `   🌡️ ${r.temp}°C (feels ${r.feelsLike}°C)  💧${r.humidity}%  💨${r.wind}km/h\n` +
        `   ${r.condition}`
      );
    });

    return { content: [{ type: 'text', text: lines.join('\n\n') }] };
  }
);

// ─── tool 5: rain / umbrella check ──────────────────────────────────────────

server.tool(
  'should-i-bring-umbrella',
  'Check if you need an umbrella in a city today',
  { city: z.string().describe('City name') },
  async ({ city }) => {
    const geo = await geocode(city);
    if (!geo) return { content: [{ type: 'text', text: `City "${city}" not found.` }] };

    const res = await fetch(
      `https://api.open-meteo.com/v1/forecast?latitude=${geo.latitude}&longitude=${geo.longitude}` +
      `&hourly=precipitation_probability,precipitation&forecast_days=1&timezone=auto`
    );
    const data = await res.json();
    const h = data.hourly;

    const maxProb = Math.max(...h.precipitation_probability);
    const totalRain = h.precipitation.reduce((a: number, b: number) => a + b, 0);
    const rainyHours = h.precipitation_probability.filter((p: number) => p >= 50).length;

    let advice: string;
    if (maxProb >= 70 || totalRain > 5) {
      advice = `🌂 Yes, definitely bring an umbrella! (max rain chance: ${maxProb}%, expected total: ${totalRain.toFixed(1)}mm)`;
    } else if (maxProb >= 30) {
      advice = `☂️ Maybe bring one just in case. (max rain chance: ${maxProb}%, ${rainyHours}h with >50% chance)`;
    } else {
      advice = `☀️ No umbrella needed today! (max rain chance: only ${maxProb}%)`;
    }

    return { content: [{ type: 'text', text: `📍 ${geo.name}, ${geo.country}\n${advice}` }] };
  }
);

// ─── tool 6: air quality index ──────────────────────────────────────────────

server.tool(
  'get-air-quality',
  'Get current air quality index (AQI) and pollutant levels for a city',
  { city: z.string().describe('City name') },
  async ({ city }) => {
    const geo = await geocode(city);
    if (!geo) return { content: [{ type: 'text', text: `City "${city}" not found.` }] };

    const res = await fetch(
      `https://air-quality-api.open-meteo.com/v1/air-quality?latitude=${geo.latitude}&longitude=${geo.longitude}` +
      `&current=european_aqi,pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,ozone`
    );
    const data = await res.json();
    const c = data.current;

    const aqiLabel = (aqi: number) => {
      if (aqi <= 20) return 'Good 🟢';
      if (aqi <= 40) return 'Fair 🟡';
      if (aqi <= 60) return 'Moderate 🟠';
      if (aqi <= 80) return 'Poor 🔴';
      if (aqi <= 100) return 'Very Poor 🟣';
      return 'Extremely Poor ⚫';
    };

    const text = [
      `📍 Air quality in ${geo.name}, ${geo.country}`,
      `🌬️  AQI (European): ${c.european_aqi} — ${aqiLabel(c.european_aqi)}`,
      `   PM2.5:  ${c.pm2_5} µg/m³`,
      `   PM10:   ${c.pm10} µg/m³`,
      `   NO₂:    ${c.nitrogen_dioxide} µg/m³`,
      `   O₃:     ${c.ozone} µg/m³`,
      `   CO:     ${c.carbon_monoxide} µg/m³`,
    ].join('\n');

    return { content: [{ type: 'text', text }] };
  }
);

// ─── tool 7: weather alerts ──────────────────────────────────────────────────

interface Alert {
  date: string;
  severity: 'WARNING' | 'WATCH' | 'ADVISORY';
  type: string;
  detail: string;
}

const SEVERE_CODES = new Set([55, 65, 67, 75, 77, 82, 85, 86, 95, 96, 99]);
const MODERATE_CODES = new Set([53, 63, 73, 80, 81]);

server.tool(
  'get-weather-alerts',
  'Get weather alerts and warnings for the next 7 days for a city',
  { city: z.string().describe('City name') },
  async ({ city }) => {
    const geo = await geocode(city);
    if (!geo) return { content: [{ type: 'text', text: `City "${city}" not found.` }] };

    const res = await fetch(
      `https://api.open-meteo.com/v1/forecast?latitude=${geo.latitude}&longitude=${geo.longitude}` +
      `&daily=weather_code,temperature_2m_max,temperature_2m_min,wind_speed_10m_max,` +
      `precipitation_sum,precipitation_probability_max` +
      `&temperature_unit=celsius&wind_speed_unit=kmh&forecast_days=7&timezone=auto`
    );
    const data = await res.json();
    const d = data.daily;

    const alerts: Alert[] = [];

    for (let i = 0; i < d.time.length; i++) {
      const date = d.time[i] as string;
      const code = d.weather_code[i] as number;
      const tempMax = d.temperature_2m_max[i] as number;
      const tempMin = d.temperature_2m_min[i] as number;
      const wind = d.wind_speed_10m_max[i] as number;
      const precip = d.precipitation_sum[i] as number;
      const rainProb = d.precipitation_probability_max[i] as number;
      const condition = wmoCodeToDescription(code);

      if (SEVERE_CODES.has(code)) {
        alerts.push({
          date, severity: 'WARNING',
          type: code >= 95 ? 'Thunderstorm' : code >= 71 ? 'Heavy Snow' : 'Heavy Rain/Storms',
          detail: `${condition} expected.`,
        });
      } else if (MODERATE_CODES.has(code)) {
        alerts.push({
          date, severity: 'WATCH',
          type: 'Precipitation',
          detail: `${condition} expected (${rainProb}% chance, ${precip.toFixed(1)}mm).`,
        });
      }

      if (wind >= 75) {
        alerts.push({
          date, severity: 'WARNING', type: 'High Wind',
          detail: `Dangerous wind speeds up to ${wind} km/h.`,
        });
      } else if (wind >= 50) {
        alerts.push({
          date, severity: 'WATCH', type: 'Wind',
          detail: `Strong winds up to ${wind} km/h.`,
        });
      }

      if (tempMax >= 40) {
        alerts.push({
          date, severity: 'WARNING', type: 'Extreme Heat',
          detail: `High of ${tempMax}°C — dangerous heat.`,
        });
      } else if (tempMax >= 35) {
        alerts.push({
          date, severity: 'ADVISORY', type: 'Heat',
          detail: `High of ${tempMax}°C — stay hydrated.`,
        });
      }

      if (tempMin <= -15) {
        alerts.push({
          date, severity: 'WARNING', type: 'Extreme Cold',
          detail: `Low of ${tempMin}°C — dangerous wind chill risk.`,
        });
      } else if (tempMin <= -5) {
        alerts.push({
          date, severity: 'ADVISORY', type: 'Cold',
          detail: `Low of ${tempMin}°C — dress in layers.`,
        });
      }

      if (precip >= 30) {
        alerts.push({
          date, severity: 'WARNING', type: 'Flooding Risk',
          detail: `${precip.toFixed(1)}mm of precipitation expected — flooding possible.`,
        });
      }
    }

    if (alerts.length === 0) {
      return {
        content: [{
          type: 'text',
          text: `✅ No weather alerts for ${geo.name}, ${geo.country} in the next 7 days. Conditions look calm.`,
        }],
      };
    }

    const severityIcon = { WARNING: '🔴', WATCH: '🟡', ADVISORY: '🔵' };
    const lines = [
      `⚠️  Weather alerts for ${geo.name}, ${geo.country}`,
      '',
      ...alerts.map(a =>
        `${severityIcon[a.severity]} [${a.severity}] ${a.date} — ${a.type}\n   ${a.detail}`
      ),
    ];

    return { content: [{ type: 'text', text: lines.join('\n') }] };
  }
);

// ─── transport ───────────────────────────────────────────────────────────────

const transport = new StdioServerTransport();
server.connect(transport);
