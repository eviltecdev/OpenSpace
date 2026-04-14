/**
 * Costs Phase-2 Shadow Route — reads Phase-2 mirror costs from /tmp/phase2_costs/
 * GET /api/costs-debug
 *
 * This is a SHADOW/DEBUG endpoint for validation purposes.
 * It reads the same cost data structure but from the Phase-2 tracker (/tmp/phase2_costs/)
 * instead of OpenSpace (/tmp/openspace/costs/).
 *
 * Purpose:
 * - Parallel validation of Phase-2 cost tracking
 * - Compare OpenSpace vs Phase-2 costs side-by-side
 * - No production UI changes required
 * - Fully reversible (just delete endpoint)
 */
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { assertPathAllowed } from '../path-jail';

const COSTS_DIR_PHASE2 = '/tmp/phase2_costs';

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
  source: 'phase2-shadow';
}

function readProviderFile(provider: string, date: string): ProviderData | null {
  const path = join(COSTS_DIR_PHASE2, `${provider}-daily-costs-${date}.json`);
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

export async function handleCostsPhase2Request(
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
    history.push({ date: dateStr, total: Math.round(dayTotal * 1000000) / 1000000 });
  }

  const summary: CostSummary = {
    date,
    total: Math.round(totalCost * 1000000) / 1000000,
    calls: totalCalls,
    by_provider,
    models: allModels,
    source: 'phase2-shadow',
  };

  return { summary, history };
}
