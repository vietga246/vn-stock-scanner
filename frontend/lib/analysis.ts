// AI Analysis Generator - Client-side analysis based on stock data
// This generates analysis when ai_analysis.json is not available from backend

import type { Stock, AIAnalysis, AnalysisPoint } from './types';

export function generateAnalysis(stock: Stock, sectorStatus?: 'accumulating' | 'distributing' | 'neutral'): AIAnalysis {
  const analysis: AIAnalysis = {
    symbol: stock.symbol,
    recommendation: 'HOLD',
    summary: '',
    highlights: [],
    risks: [],
    fundamental_view: '',
    technical_view: '',
    flow_view: '',
  };

  const score = stock.composite_score;
  const f = stock.fundamental_score;
  const s = stock.smart_money_score;
  const m = stock.momentum_score;
  const t = stock.technical_score;

  // ============ Determine Recommendation ============
  if (score >= 75) {
    analysis.recommendation = 'STRONG_BUY';
    analysis.summary = `${stock.symbol} đang có điểm số xuất sắc (${score.toFixed(1)}) với tất cả các chỉ báo đều tích cực. Cổ phiếu thuộc nhóm chất lượng cao, đây là thời điểm tốt để tích lũy.`;
  } else if (score >= 65) {
    analysis.recommendation = 'BUY';
    analysis.summary = `${stock.symbol} có điểm số tốt (${score.toFixed(1)}) với nhiều yếu tố hỗ trợ. Có thể xem xét mua vào khi giá điều chỉnh về vùng hỗ trợ.`;
  } else if (score >= 55) {
    analysis.recommendation = 'HOLD';
    analysis.summary = `${stock.symbol} đang trong vùng trung tính (${score.toFixed(1)}). Nên giữ nếu đã có vị thế và chờ tín hiệu rõ ràng hơn trước khi hành động.`;
  } else if (score >= 45) {
    analysis.recommendation = 'SELL';
    analysis.summary = `${stock.symbol} có nhiều chỉ báo tiêu cực (${score.toFixed(1)}). Nên cân nhắc chốt lời hoặc cắt lỗ để bảo toàn vốn.`;
  } else {
    analysis.recommendation = 'STRONG_SELL';
    analysis.summary = `${stock.symbol} đang trong xu hướng giảm mạnh (${score.toFixed(1)}) với nhiều rủi ro. Khuyến nghị thoát hàng và chờ cơ hội tốt hơn.`;
  }

  // ============ Fundamental Analysis ============
  if (f >= 75) {
    analysis.fundamental_view = 'Nền tảng tài chính vững chắc với các chỉ số cơ bản ấn tượng.';
    analysis.highlights.push({
      text: `Điểm cơ bản ${f.toFixed(0)}/100 - Tài chính lành mạnh`,
      type: 'positive'
    });
    
    if (stock.roe && stock.roe > 15) {
      analysis.highlights.push({
        text: `ROE ${stock.roe.toFixed(1)}% - Sinh lời trên vốn cao`,
        type: 'positive'
      });
    }
    
    if (stock.pe && stock.pe < 15 && stock.pe > 0) {
      analysis.highlights.push({
        text: `P/E ${stock.pe.toFixed(1)} - Định giá hấp dẫn`,
        type: 'positive'
      });
    }
  } else if (f >= 55) {
    analysis.fundamental_view = 'Tài chính ổn định, các chỉ số trong ngưỡng chấp nhận được.';
    analysis.highlights.push({
      text: `Điểm cơ bản ${f.toFixed(0)}/100 - Tài chính ổn định`,
      type: 'neutral'
    });
  } else {
    analysis.fundamental_view = 'Nền tảng tài chính cần được cải thiện, theo dõi khả năng trả nợ.';
    analysis.risks.push({
      text: `Điểm cơ bản ${f.toFixed(0)}/100 - Tài chính cần cải thiện`,
      type: 'negative'
    });
    
    if (stock.debt_equity && stock.debt_equity > 2) {
      analysis.risks.push({
        text: `D/E ${stock.debt_equity.toFixed(1)} - Đòn bẩy tài chính cao`,
        type: 'negative'
      });
    }
  }

  // ============ Smart Money Flow Analysis ============
  const nn7d = stock.foreign_net_7d || 0;
  const nn30d = stock.foreign_net_30d || 0;
  
  if (s >= 70 && nn7d > 0) {
    analysis.flow_view = 'Dòng tiền lớn đang tích lũy mạnh, khối ngoại mua ròng liên tục.';
    analysis.highlights.push({
      text: `Khối ngoại mua ròng +${nn7d.toFixed(1)}B trong 7 ngày`,
      type: 'positive'
    });
    
    if (nn30d > nn7d * 3) {
      analysis.highlights.push({
        text: `Tích lũy bền vững: +${nn30d.toFixed(1)}B trong 30 ngày`,
        type: 'positive'
      });
    }
  } else if (s >= 55) {
    analysis.flow_view = 'Dòng tiền ổn định, không có dấu hiệu phân phối lớn.';
  } else {
    analysis.flow_view = 'Dòng tiền đang rút ra, khối ngoại bán ròng.';
    if (nn7d < 0) {
      analysis.risks.push({
        text: `Khối ngoại bán ròng ${nn7d.toFixed(1)}B trong 7 ngày`,
        type: 'negative'
      });
    }
  }

  // ============ Momentum Analysis ============
  const change5d = stock.change_5d || 0;
  const change20d = stock.change_20d || 0;
  
  if (m >= 70) {
    analysis.highlights.push({
      text: 'Momentum mạnh - Đà tăng tích cực',
      type: 'positive'
    });
    
    if (change20d > 10) {
      analysis.highlights.push({
        text: `Tăng ${change20d.toFixed(1)}% trong 20 phiên - Uptrend mạnh`,
        type: 'positive'
      });
    }
  } else if (m < 45) {
    analysis.risks.push({
      text: 'Momentum yếu - Đà tăng suy giảm',
      type: 'negative'
    });
    
    if (change20d < -10) {
      analysis.risks.push({
        text: `Giảm ${Math.abs(change20d).toFixed(1)}% trong 20 phiên - Downtrend`,
        type: 'negative'
      });
    }
  }

  // ============ Technical Analysis ============
  const rsi = stock.rsi14 || 50;
  const trend = stock.trend_short || 0;
  
  if (t >= 70) {
    analysis.technical_view = 'Kỹ thuật tích cực, giá trên các đường MA, xu hướng tăng rõ ràng.';
    analysis.highlights.push({
      text: 'Tín hiệu kỹ thuật tích cực',
      type: 'positive'
    });
    
    if (rsi >= 50 && rsi <= 70) {
      analysis.highlights.push({
        text: `RSI ${rsi.toFixed(0)} - Vùng tăng bền vững`,
        type: 'positive'
      });
    }
  } else if (t >= 55) {
    analysis.technical_view = 'Kỹ thuật trung tính, đang tích lũy trong biên độ hẹp.';
    
    if (rsi > 70) {
      analysis.risks.push({
        text: `RSI ${rsi.toFixed(0)} - Vùng quá mua, cẩn thận điều chỉnh`,
        type: 'warning'
      });
    }
  } else {
    analysis.technical_view = 'Kỹ thuật tiêu cực, giá dưới MA, momentum giảm.';
    analysis.risks.push({
      text: 'Tín hiệu kỹ thuật tiêu cực',
      type: 'negative'
    });
    
    if (rsi < 30) {
      analysis.highlights.push({
        text: `RSI ${rsi.toFixed(0)} - Quá bán, có thể rebound`,
        type: 'neutral'
      });
    }
  }

  // ============ Sector Analysis ============
  if (sectorStatus === 'accumulating') {
    analysis.highlights.push({
      text: `Ngành ${stock.industry} đang được tích lũy`,
      type: 'positive'
    });
  } else if (sectorStatus === 'distributing') {
    analysis.risks.push({
      text: `Ngành ${stock.industry} đang bị phân phối`,
      type: 'negative'
    });
  }

  // ============ Tier Analysis ============
  if (stock.tier === 'A') {
    analysis.highlights.push({
      text: 'Tier A - Cổ phiếu chất lượng cao, thanh khoản tốt',
      type: 'positive'
    });
  } else if (stock.tier === 'D' || stock.tier === 'F') {
    analysis.risks.push({
      text: `Tier ${stock.tier} - Cần theo dõi chặt chẽ, rủi ro cao`,
      type: 'warning'
    });
  }

  return analysis;
}

// Get recommendation display info
export function getRecommendationDisplay(rec: AIAnalysis['recommendation']): {
  text: string;
  color: string;
  icon: 'up' | 'down' | 'hold';
} {
  const map: Record<string, { text: string; color: string; icon: 'up' | 'down' | 'hold' }> = {
    'STRONG_BUY': { text: 'STRONG BUY', color: '#00ff88', icon: 'up' },
    'BUY': { text: 'BUY', color: '#00ff88', icon: 'up' },
    'HOLD': { text: 'HOLD', color: '#ffcc00', icon: 'hold' },
    'SELL': { text: 'SELL', color: '#ff3366', icon: 'down' },
    'STRONG_SELL': { text: 'STRONG SELL', color: '#ff3366', icon: 'down' },
  };
  
  return map[rec] || map['HOLD'];
}
