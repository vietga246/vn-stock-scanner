import { NextResponse } from 'next/server';

const GITHUB_BASE_URL =
  'https://raw.githubusercontent.com/vietga246/vn-stock-scanner/main/data/exports';

// ─── Cache TTL ──────────────────────────────────────────────────────────────
//
// GitHub Actions chạy 2 lần/ngày: 11:45 ICT và 15:20 ICT.
// TTL 5 phút (300s) cũ gây trễ tối đa 15 phút (3 tầng cache cộng dồn).
//
// Fix:
//  - revalidate: 60s  → Vercel ISR tái fetch GitHub raw sau tối đa 1 phút
//  - s-maxage: 60s    → CDN cache 1 phút (đủ để giảm tải GitHub)
//  - stale-while-revalidate: 120s → vẫn serve data cũ trong khi refetch
//  - Cache bust bằng ?t=<epoch-minute> → buộc GitHub CDN trả file mới
//    mỗi khi Vercel re-fetch (tránh GitHub's own CDN stale cache)
//
const REVALIDATE_SECONDS = 60;   // ISR revalidate interval
const CDN_MAX_AGE        = 60;   // s-maxage cho Vercel Edge
const STALE_REVALIDATE   = 120;  // stale-while-revalidate

/**
 * Shared utility for fetching JSON data from GitHub raw.
 *
 * - ISR với 60s revalidation (giảm từ 300s để data phiên mới cập nhật nhanh hơn)
 * - Cache bust ?t=<epoch-minute> để bypass GitHub CDN stale cache
 * - Sanitizes NaN/Infinity values từ Python serialization
 * - Returns fallback on error
 */
export async function fetchGithubData<T>(
  filename: string,
  fallback: T
): Promise<NextResponse<T>> {
  try {
    // Cache bust: thay đổi mỗi phút → GitHub CDN không trả stale response
    const cacheBust = Math.floor(Date.now() / 1000 / 60); // epoch-minute
    const url = `${GITHUB_BASE_URL}/${filename}?t=${cacheBust}`;

    const response = await fetch(url, {
      headers: {
        Accept: 'application/json',
        'User-Agent': 'VN-Stock-Scanner/1.0',
        // Nói rõ với GitHub CDN không cache lâu
        'Cache-Control': 'no-cache',
      },
      next: { revalidate: REVALIDATE_SECONDS },
    } as RequestInit & { next?: { revalidate?: number } });

    if (!response.ok) {
      console.error(`GitHub fetch failed for ${filename}: ${response.status}`);
      return NextResponse.json(fallback);
    }

    // Get raw text để xử lý NaN/Infinity từ Python
    const text = await response.text();
    const cleanedText = text
      .replace(/:\s*NaN\s*([,\}\]])/g, ':null$1')
      .replace(/:\s*Infinity\s*([,\}\]])/g, ':null$1')
      .replace(/:\s*-Infinity\s*([,\}\]])/g, ':null$1');

    const data = JSON.parse(cleanedText) as T;

    return NextResponse.json(data, {
      headers: {
        'Cache-Control': `public, s-maxage=${CDN_MAX_AGE}, stale-while-revalidate=${STALE_REVALIDATE}`,
        // Header debug: kiểm tra trong DevTools > Network tab
        'X-Data-Source': 'github-raw',
        'X-Cache-Bust': String(cacheBust),
      },
    });
  } catch (error) {
    console.error(`Error fetching ${filename}:`, error);
    return NextResponse.json(fallback);
  }
}
