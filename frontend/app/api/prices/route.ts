import { NextResponse } from 'next/server';

const GITHUB_RAW_URL = 'https://raw.githubusercontent.com/vietga246/vn-stock-scanner/main/data/exports/prices.json';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function GET() {
  try {
    const response = await fetch(GITHUB_RAW_URL, {
      headers: {
        'Accept': 'application/json',
        'User-Agent': 'VN-Stock-Scanner/1.0',
      },
      cache: 'no-store',
    });

    if (!response.ok) {
      // prices.json might not exist, return empty
      return NextResponse.json({ prices: {} });
    }

    // Get raw text first to handle potential NaN values
    const text = await response.text();
    
    // Replace NaN/Infinity with null
    const cleanedText = text
      .replace(/:\s*NaN\s*([,\}\]])/g, ':null$1')
      .replace(/:\s*Infinity\s*([,\}\]])/g, ':null$1')
      .replace(/:\s*-Infinity\s*([,\}\]])/g, ':null$1');
    
    const data = JSON.parse(cleanedText);
    
    return NextResponse.json(data, {
      headers: {
        'Cache-Control': 'public, s-maxage=300, stale-while-revalidate=600',
      },
    });
  } catch (error) {
    console.error('Error fetching prices:', error);
    return NextResponse.json({ prices: {} });
  }
}
