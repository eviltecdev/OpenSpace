/**
 * Weather API proxy — uses Open-Meteo (free, no API key, reliable).
 * Browser calls /api/weather?city=... → server geocodes city + fetches forecast.
 */
import type { IncomingHttpHeaders } from 'node:http';

const CACHE_TTL = 10 * 60_000; // 10 min
const cache = new Map<string, { data: unknown; ts: number }>();

export async function handleWeatherRequest(
  query: Record<string, string>,
  _body: string,
  _headers: IncomingHttpHeaders | Record<string, string | string[] | undefined>,
): Promise<unknown> {
  const city = query.city || 'Uluwatu';
  const cacheKey = city.toLowerCase();

  const cached = cache.get(cacheKey);
  if (cached && Date.now() - cached.ts < CACHE_TTL) return cached.data;

  // Step 1: Geocode city to lat/lon
  const geoUrl = `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(city)}&count=1&language=en`;
  const geoResp = await fetch(geoUrl);
  if (!geoResp.ok) throw new Error(`Geocoding failed: ${geoResp.status}`);
  const geoData = (await geoResp.json()) as any;
  if (!geoData.results?.[0]) throw new Error(`City not found: ${city}`);

  const { latitude, longitude } = geoData.results[0];

  // Step 2: Fetch forecast from Open-Meteo
  const forecastUrl =
    `https://api.open-meteo.com/v1/forecast?latitude=${latitude}&longitude=${longitude}` +
    `&current=temperature_2m,is_day,weather_code,relative_humidity_2m,apparent_temperature,wind_speed_10m` +
    `&daily=weather_code,temperature_2m_max,temperature_2m_min&timezone=auto`;

  const forecastResp = await fetch(forecastUrl);
  if (!forecastResp.ok) throw new Error(`Forecast failed: ${forecastResp.status}`);
  const forecast = (await forecastResp.json()) as any;
  const cur = forecast.current;
  const daily = forecast.daily;

  if (!cur) throw new Error('No current data from Open-Meteo');

  // Build 5-day forecast (WMO codes are native to Open-Meteo)
  const forecastDays = (daily?.time || []).slice(0, 5).map((date: string, idx: number) => ({
    date,
    tempMax: daily.temperature_2m_max[idx],
    tempMin: daily.temperature_2m_min[idx],
    code: daily.weather_code[idx],
  }));

  const result = {
    temperature: cur.temperature_2m,
    feelsLike: cur.apparent_temperature,
    humidity: cur.relative_humidity_2m,
    windSpeed: cur.wind_speed_10m,
    weatherCode: cur.weather_code,
    isDay: cur.is_day === 1,
    timezone: forecast.timezone,
    city: geoData.results[0].name,
    daily: forecastDays,
  };

  cache.set(cacheKey, { data: result, ts: Date.now() });
  return result;
}
