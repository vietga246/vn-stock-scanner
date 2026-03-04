import { NextResponse } from 'next/server';

const GITHUB_RAW_URL = 'https://raw.githubusercontent.com/vietga246/vn-stock-scanner/main/data/exports';

export async function GET() {
  try {
    const response = await fetch(`${GITHUB_RAW_URL}/summary.json`, {
      next: { revalidate: 300 }, // Cache 5 minutes
    });
    
    if (!response.ok) {
      // Return default summary if file doesn't exist
      return NextResponse.json({
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
      });
    }
    
    let text = await response.text();
    
    // Sanitize NaN/Infinity values
    text = text
      .replace(/:\s*NaN\s*([,\}])/g, ':null$1')
      .replace(/:\s*Infinity\s*([,\}])/g, ':null$1')
      .replace(/:\s*-Infinity\s*([,\}])/g, ':null$1');
    
    const data = JSON.parse(text);
    
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error fetching summary:', error);
    return NextResponse.json({
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
    });
  }
}
