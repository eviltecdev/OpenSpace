/**
 * CostPanel — zeigt OpenSpace LLM-Kosten (OpenAI + Anthropic) in Echtzeit.
 * Sparkline der letzten 7 Tage, Aufschlüsselung nach Provider und Modell.
 */
import { Panel } from './Panel';

interface ProviderData {
  total: number;
  calls: number;
  models: Record<string, number>;
}

interface CostSummary {
  date: string;
  total: number;
  calls: number;
  by_provider: Record<string, ProviderData>;
  models: Record<string, number>;
}

interface HistoryPoint { date: string; total: number; }

export class CostPanel extends Panel {
  constructor() {
    super({ id: 'llm-costs', title: '💰 LLM Costs' });
    setTimeout(() => this.refresh(), 0);
  }

  async refresh(): Promise<void> {
    this.showLoading('Loading costs...');
    try {
      const res = await fetch('/api/costs');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json() as { summary: CostSummary; history: HistoryPoint[] };
      this.setContent(this.renderCosts(data.summary, data.history));
    } catch (err: any) {
      this.showError(`Cost data unavailable: ${err.message}`, () => this.refresh());
    }
  }

  private renderCosts(summary: CostSummary, history: HistoryPoint[]): string {
    const { total, calls, by_provider, models } = summary;
    const openai = by_provider['openai'] || { total: 0, calls: 0, models: {} };
    const anthropic = by_provider['anthropic'] || { total: 0, calls: 0, models: {} };

    const sparkline = this.renderSparkline(history);
    const modelRows = Object.entries(models)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 5)
      .map(([model, cost]) => `
        <div class="cp-model-row">
          <span class="cp-model-name">${model}</span>
          <span class="cp-model-cost">$${cost.toFixed(4)}</span>
        </div>`).join('');

    return `
      <div class="cp-total">
        <span class="cp-total-label">Today</span>
        <span class="cp-total-value">$${total.toFixed(4)}</span>
        <span class="cp-calls">${calls} calls</span>
      </div>

      ${sparkline}

      <div class="cp-providers">
        <div class="cp-provider">
          <span class="cp-provider-icon">⚡</span>
          <span class="cp-provider-name">OpenAI</span>
          <span class="cp-provider-cost">$${openai.total.toFixed(4)}</span>
          <span class="cp-provider-calls">${openai.calls}×</span>
        </div>
        <div class="cp-provider">
          <span class="cp-provider-icon">🤖</span>
          <span class="cp-provider-name">Anthropic</span>
          <span class="cp-provider-cost">$${anthropic.total.toFixed(4)}</span>
          <span class="cp-provider-calls">${anthropic.calls}×</span>
        </div>
      </div>

      ${modelRows ? `<div class="cp-models"><div class="cp-section-title">Top Models</div>${modelRows}</div>` : ''}
    `;
  }

  private renderSparkline(history: HistoryPoint[]): string {
    if (history.length < 2) return '';
    const max = Math.max(...history.map(h => h.total), 0.0001);
    const W = 200; const H = 32; const pad = 2;
    const points = history.map((h, i) => {
      const x = pad + (i / (history.length - 1)) * (W - pad * 2);
      const y = H - pad - (h.total / max) * (H - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    const weekTotal = history.reduce((s, h) => s + h.total, 0);
    return `
      <div class="cp-sparkline">
        <svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
          <polyline points="${points}" fill="none" stroke="var(--accent,#3b82f6)" stroke-width="1.5" stroke-linejoin="round"/>
        </svg>
        <span class="cp-spark-label">7d: $${weekTotal.toFixed(3)}</span>
      </div>
    `;
  }
}
