import { fetchGithubData } from '../_lib/github';

export async function GET() {
  return fetchGithubData('ict_signals.json', {
    generated_at: new Date().toISOString(),
    total_symbols: 0,
    actionable_count: 0,
    regime: { regime: 'UNKNOWN', bull_weight: 0.5, composite_score: 50 },
    sector_rotation: { leading: [], lagging: [], accumulating: [], distributing: [], hot_sectors: [] },
    market_stats: {},
    quality_distribution: { 'A+': 0, A: 0, B: 0, C: 0, SKIP: 0 },
    signals: [],
  });
}
