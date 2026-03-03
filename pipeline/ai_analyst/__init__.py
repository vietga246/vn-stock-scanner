"""
AI Analyst Module — Automated Stock Analysis

Components:
- ai_analyst: AI-powered analysis using OpenAI/Claude
- report_generator: Multi-format report generation
"""

from .ai_analyst import (
    run as run_analysis,
    analyze_stocks,
    generate_daily_report,
    create_fallback_analysis,
)

from .report_generator import (
    run as run_reports,
    generate_daily_report as generate_daily_md,
    generate_stock_detail,
    export_reports,
)

__all__ = [
    "run_analysis",
    "run_reports",
    "analyze_stocks",
    "generate_daily_report",
    "generate_daily_md",
    "generate_stock_detail",
    "create_fallback_analysis",
    "export_reports",
]
