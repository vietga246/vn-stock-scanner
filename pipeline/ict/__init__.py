"""
pipeline/ict/ — ICT / Smart Money Analysis Modules

Module structure (chạy theo thứ tự dependency):
  01 data_loader.py          — Load & normalize all JSON sources
  02 market_regime.py        — VNINDEX regime: BULL/BEAR/RANGE/TRANSITION
  03 sector_rotation.py      — Sector RS ranking + rotation detection
  04 market_structure.py     — Swing H/L + BOS + CHoCH + Equal H/L
  05 institutional_flow.py   — Foreign flow + buy_pressure composite

Dùng:
  from pipeline.ict.data_loader import load_all
  ctx    = load_all()
  regime = detect_regime(ctx)
"""
