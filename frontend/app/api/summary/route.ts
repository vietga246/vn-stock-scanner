import { fetchGithubData } from '../_lib/github';

const DEFAULT_SUMMARY = {
  generated_at: new Date().toISOString(),
  market: {
    vnindex: null,
    vnindex_change: null,
  },
  top_gainers: [],
  top_losers: [],
  most_active: [],
  foreign_buy: [],
  foreign_sell: [],
};

export async function GET() {
  return fetchGithubData('summary.json', DEFAULT_SUMMARY);
}
