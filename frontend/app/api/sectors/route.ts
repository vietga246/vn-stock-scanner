import { fetchGithubData } from '../_lib/github';

export async function GET() {
  return fetchGithubData('sectors.json', {
    sectors: [],
    rotation_signal: { accumulating: [], distributing: [] },
  });
}
