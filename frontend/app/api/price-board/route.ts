import { fetchGithubData } from '../_lib/github';

export async function GET() {
  return fetchGithubData('price_board.json', {
    generated_at: new Date().toISOString(),
    snapshot_time: null,
    total_symbols: 0,
    summary: {
      symbols_with_price: 0,
      total_foreign_net_qty: 0,
      total_foreign_net_value_bn: 0,
      avg_buy_pressure_pct: null,
    },
    stocks: [],
  });
}
