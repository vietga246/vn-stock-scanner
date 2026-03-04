import { fetchGithubData } from '../_lib/github';

export async function GET() {
  return fetchGithubData('prices.json', { prices: {} });
}
