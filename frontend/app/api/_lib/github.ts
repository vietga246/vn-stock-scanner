import { NextResponse } from 'next/server';

const GITHUB_BASE_URL =
  'https://raw.githubusercontent.com/vietga246/vn-stock-scanner/main/data/exports';

/**
 * Shared utility for fetching JSON data from GitHub raw.
 * - Uses ISR with 5-minute revalidation (no more force-dynamic + no-store conflict)
 * - Sanitizes NaN/Infinity values that Python may produce
 * - Returns fallback on error
 */
export async function fetchGithubData<T>(
  filename: string,
  fallback: T
): Promise<NextResponse<T>> {
  try {
    const response = await fetch(`${GITHUB_BASE_URL}/${filename}`, {
      headers: {
        Accept: 'application/json',
        'User-Agent': 'VN-Stock-Scanner/1.0',
      },
      next: { revalidate: 300 }, // ISR: cache 5 minutes on server
    } as RequestInit & { next?: { revalidate?: number } });

    if (!response.ok) {
      return NextResponse.json(fallback);
    }

    // Get raw text to handle NaN/Infinity from Python serialization
    const text = await response.text();
    const cleanedText = text
      .replace(/:\s*NaN\s*([,\}\]])/g, ':null$1')
      .replace(/:\s*Infinity\s*([,\}\]])/g, ':null$1')
      .replace(/:\s*-Infinity\s*([,\}\]])/g, ':null$1');

    const data = JSON.parse(cleanedText) as T;

    return NextResponse.json(data, {
      headers: {
        'Cache-Control': 'public, s-maxage=300, stale-while-revalidate=600',
      },
    });
  } catch (error) {
    console.error(`Error fetching ${filename}:`, error);
    return NextResponse.json(fallback);
  }
}
