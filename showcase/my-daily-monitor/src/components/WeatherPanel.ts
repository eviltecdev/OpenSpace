/**
 * WeatherPanel — weather + local clock + AoE clock.
 * Fetches weather via server-side proxy (/api/weather) which uses wttr.in.
 * Location configured via settings (WEATHER_CITY).
 */
import { Panel } from './Panel';
import { getSecret } from '@/services/settings-store';

function weatherIcon(code: number, isDay: boolean): string {
  if (code === 0) return isDay ? '☀️' : '🌙';
  if (code <= 3) return isDay ? '⛅' : '☁️';
  if (code <= 48) return '🌫️';
  if (code <= 57) return '🌧️';
  if (code <= 67) return '🌧️';
  if (code <= 77) return '❄️';
  if (code <= 82) return '🌧️';
  if (code <= 86) return '❄️';
  if (code <= 99) return '⛈️';
  return '🌡️';
}

function weatherDesc(code: number): string {
  if (code === 0) return 'Clear';
  if (code <= 3) return 'Partly cloudy';
  if (code <= 48) return 'Foggy';
  if (code <= 57) return 'Drizzle';
  if (code <= 67) return 'Rain';
  if (code <= 77) return 'Snow';
  if (code <= 82) return 'Rain showers';
  if (code <= 86) return 'Snow showers';
  if (code <= 99) return 'Thunderstorm';
  return 'Unknown';
}

export class WeatherPanel extends Panel {
  private clockTimer: ReturnType<typeof setInterval> | null = null;

  constructor() {
    super({ id: 'weather', title: 'Weather & Time', showCount: false });
    this.clockTimer = setInterval(() => this.updateClocks(), 1000);
    // Fetch immediately on load
    setTimeout(() => this.refresh(), 0);
  }

  async refresh(): Promise<void> {
    if (this.isFetching) return;
    this.setFetching(true);
    this.showLoading('Loading weather...');
    try {
      const city = getSecret('WEATHER_CITY') || 'Uluwatu';
      const resp = await fetch(`/api/weather?city=${encodeURIComponent(city)}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json() as any;
      this.render(data);
      this.setDataBadge('live');
    } catch (err: any) {
      this.showError(`Weather unavailable: ${err.message}`, () => this.refresh());
    } finally {
      this.setFetching(false);
    }
  }

  private updateClocks(): void {
    const localEl = this.content.querySelector('#localClock');
    const berlinEl = this.content.querySelector('#berlinClock');
    if (!localEl || !berlinEl) return;

    const now = new Date();
    localEl.textContent = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    berlinEl.textContent = now.toLocaleTimeString('en-US', { timeZone: 'Europe/Berlin', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  }

  private render(w: any): void {
    const icon = weatherIcon(w.weatherCode ?? 0, w.isDay ?? true);
    const desc = weatherDesc(w.weatherCode ?? 0);
    const cityName = w.city || getSecret('WEATHER_CITY') || 'Uluwatu';
    const now = new Date();
    const localTime = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    const berlinTime = now.toLocaleTimeString('en-US', { timeZone: 'Europe/Berlin', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    const localDate = now.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
    const berlinDate = now.toLocaleDateString('en-US', { timeZone: 'Europe/Berlin', weekday: 'short', month: 'short', day: 'numeric' });

    const forecastHtml = (w.daily || []).slice(1).map((d: any) => {
      const dayName = new Date(d.date + 'T12:00:00').toLocaleDateString('en', { weekday: 'short' });
      return `
        <div class="weather-forecast-day">
          <span class="weather-forecast-name">${dayName}</span>
          <span class="weather-forecast-icon">${weatherIcon(d.code ?? 0, true)}</span>
          <span class="weather-forecast-temps">
            <span class="weather-temp-hi">${Math.round(d.tempMax)}°</span>
            <span class="weather-temp-lo">${Math.round(d.tempMin)}°</span>
          </span>
        </div>`;
    }).join('');

    this.setContent(`
      <div class="weather-container">
        <div class="weather-clocks">
          <div class="weather-clock-item">
            <span class="weather-clock-label">${cityName}</span>
            <span class="weather-clock-time" id="localClock">${localTime}</span>
            <span class="weather-clock-date">${localDate}</span>
          </div>
          <div class="weather-clock-item">
            <span class="weather-clock-label">Berlin</span>
            <span class="weather-clock-time" id="berlinClock">${berlinTime}</span>
            <span class="weather-clock-date">${berlinDate}</span>
          </div>
        </div>
        <div class="weather-current">
          <div class="weather-main">
            <span class="weather-icon-lg">${icon}</span>
            <div>
              <span class="weather-temp-lg">${Math.round(w.temperature ?? 0)}°C</span>
              <div class="weather-desc">${desc} · ${cityName}</div>
            </div>
          </div>
          <div class="weather-details">
            <span>Feels ${Math.round(w.feelsLike ?? 0)}°</span>
            <span>💧 ${w.humidity ?? 0}%</span>
            <span>💨 ${Math.round(w.windSpeed ?? 0)} km/h</span>
          </div>
        </div>
        <div class="weather-forecast">${forecastHtml}</div>
      </div>
    `);
  }

  public destroy(): void {
    if (this.clockTimer) clearInterval(this.clockTimer);
    super.destroy();
  }
}
