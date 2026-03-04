import { fetchGithubData } from '../_lib/github';

export async function GET() {
  return fetchGithubData('ai_analysis.json', null);
}
