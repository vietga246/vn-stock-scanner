import { fetchGithubData } from '../_lib/github';

export async function GET() {
  return fetchGithubData('stocks.json', {
    generated_at: new Date().toISOString(),
    total: 0,
    screener: [],
    details: {},
  });
}
