/**
 * Costs route — liest OpenSpace LLM-Kosten aus /tmp/openspace/costs/
 * GET /api/costs
 */
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { assertPathAllowed } from '../path-jail';

const COSTS_DIR = '/tmp/openspace/costs';

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

function readProviderFile(provider: string, date: string): ProviderData | null {
  const path = join(COSTS_DIR, `${provider}-daily-costs-${date}.json`);
  assertPathAllowed(path);
  if (!existsSync(path)) return null;
  try {
    return JSON.parse(readFileSync(path, 'utf-8'));
  } catch {
    return null;
  }
}

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

export async function handleCostsRequest(
  query: Record<string, string>,
): Promise<unknown> {
  const date = query.date || todayStr();
  const providers = ['openai', 'anthropic'];

  const by_provider: Record<string, ProviderData> = {};
  const allModels: Record<string, number> = {};
  let totalCost = 0;
  let totalCalls = 0;

  for (const provider of providers) {
    const data = readProviderFile(provider, date);
    if (data) {
      by_provider[provider] = data;
      totalCost += data.total || 0;
      totalCalls += data.calls || 0;
      for (const [model, cost] of Object.entries(data.models || {})) {
        allModels[model] = (allModels[model] || 0) + cost;
      }
    } else {
      by_provider[provider] = { total: 0, calls: 0, models: {} };
    }
  }

  // Also return last 7 days for sparkline
  const history: Array<{ date: string; total: number }> = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    const dateStr = d.toISOString().slice(0, 10);
    let dayTotal = 0;
    for (const provider of providers) {
      const data = readProviderFile(provider, dateStr);
      if (data) dayTotal += data.total || 0;
    }
    history.push({ date: dateStr, total: Math.round(dayTotal * 10000) / 10000 });
  }

  const summary: CostSummary = {
    date,
    total: Math.round(totalCost * 10000) / 10000,
    calls: totalCalls,
    by_provider,
    models: allModels,
  };

  return { summary, history };
}
