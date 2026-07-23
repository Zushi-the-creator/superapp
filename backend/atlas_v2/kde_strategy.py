"""
KDE Adaptive Cascade — Production strategy lane.
=================================================
Wraps the trained AdaptiveCascade model for live signal generation.

Architecture:
  - Models are trained offline weekly via `python3 -m atlas_v2.kde_train`
    on the full historical panel (~10yr × 500-3000 tickers)
  - Trained models persisted as joblib bundles in data/kde_models/
  - Live scoring loads the bundle, computes today's features per ticker,
    queries each horizon's GBM model, picks adaptive horizon

Sizing recommendations (validated on 6.2yr walk-forward):
  - Target 20 concurrent positions (5% of book each, fractional shares)
  - Max 10% per position (concentration cap)
  - 14-day same-name cooldown
  - No stop loss (kills momentum/long-tail upside)
  - Risk budget: tolerate ~65% portfolio drawdown for the +56%/yr CAGR

Backtest (500 tickers, 2020-2026, 20 slots, no stop, 14d cooldown):
  KDE Adaptive: $14K → $224K, CAGR +56.2%, Sharpe 1.82, max DD -66.9%
  V2.7 baseline:           $121K, CAGR +41.6%, Sharpe 1.74, max DD -58.1%
"""

from __future__ import annotations
import os
import time
import json
import sqlite3
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from atlas_v2.kde_cascade import (
    ADAPTIVE_HORIZONS, ADAPTIVE_FEATURES, REGIME_DUMMIES,
    _prepare_xy, AdaptiveCascade, build_macro_panel, build_panel,
    _spy_panel, _pick_tickers, FEE_PCT,
)

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(THIS_DIR)
DB_PATH = os.path.join(BACKEND_DIR, "data", "stock_cache.db")
MODEL_DIR = os.path.join(BACKEND_DIR, "data", "kde_models")
DEFAULT_TARGET_SLOTS = 20
DEFAULT_MAX_PER_POS_PCT = 10.0
DEFAULT_COOLDOWN_DAYS = 14
DEFAULT_PROFIT_THRESH_PCT = 5.0


@dataclass
class KDESignal:
    ticker: str
    price: float
    score: float
    expected_return_pct: float           # E[ret_h | features] at chosen horizon
    p_big_winner: float                  # P(ret > 5% | features) at chosen horizon
    best_horizon_days: int
    regime: str
    rsi2: float
    atr_pct: float
    sma50_buf_pct: float
    mom20_pct: float
    data_date: str
    horizon_breakdown: Dict[int, Dict[str, float]] = field(default_factory=dict)


def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def _model_bundle_path(label: str = "default") -> str:
    return os.path.join(MODEL_DIR, f"adaptive_{label}.joblib")


def _model_meta_path(label: str = "default") -> str:
    return os.path.join(MODEL_DIR, f"adaptive_{label}.meta.json")


# ── Training ──────────────────────────────────────────────────────────────────

def train_and_save(label: str = "default",
                   tickers_top_n: int = 500,
                   start_date: str = "2018-01-01",
                   skip_bear: bool = True) -> Dict:
    """Build panel, train AdaptiveCascade, persist bundle + meta."""
    import joblib

    _ensure_dir(MODEL_DIR)
    conn = sqlite3.connect(DB_PATH)

    print(f"[KDE-TRAIN] Loading SPY for regime…")
    regime_map = _spy_panel(conn)
    print(f"[KDE-TRAIN] {len(regime_map)} regime-labeled dates")

    print(f"[KDE-TRAIN] Loading macro panel…")
    macro = build_macro_panel(conn, start_date=start_date)

    tickers = _pick_tickers(conn, tickers_top_n)
    print(f"[KDE-TRAIN] Building panel: top {len(tickers)} liquid tickers, from {start_date}")
    t0 = time.time()
    panel = build_panel(conn, tickers, regime_map, start_date=start_date, macro=macro)
    print(f"[KDE-TRAIN] Panel: {len(panel):,} rows × {panel.shape[1]} cols  ({time.time()-t0:.0f}s)")

    if skip_bear:
        before = len(panel)
        panel = panel[panel["regime"] != "BEAR"]
        print(f"[KDE-TRAIN] Dropped {before - len(panel):,} BEAR rows")

    print(f"[KDE-TRAIN] Preparing features…")
    X, y_dict = _prepare_xy(panel.copy(), ADAPTIVE_HORIZONS)

    print(f"[KDE-TRAIN] Training AdaptiveCascade across horizons {ADAPTIVE_HORIZONS}…")
    t0 = time.time()
    cascade = AdaptiveCascade().fit(X, y_dict)
    print(f"[KDE-TRAIN] Trained {len(cascade.models)} horizon models in {time.time()-t0:.0f}s")

    bundle = {
        "cascade": cascade,
        "feature_cols": ADAPTIVE_FEATURES + REGIME_DUMMIES,
        "horizons": ADAPTIVE_HORIZONS,
        "trained_at": datetime.now().isoformat(),
        "panel_rows": len(panel),
        "tickers_count": len(tickers),
        "start_date": start_date,
        "skip_bear": skip_bear,
    }
    bundle_path = _model_bundle_path(label)
    joblib.dump(bundle, bundle_path)

    meta = {
        "trained_at": bundle["trained_at"],
        "tickers_count": bundle["tickers_count"],
        "panel_rows": bundle["panel_rows"],
        "horizons": ADAPTIVE_HORIZONS,
        "feature_cols": ADAPTIVE_FEATURES + REGIME_DUMMIES,
        "resid_std": {h: cascade.resid_std.get(h, 0.0) for h in ADAPTIVE_HORIZONS},
        "skip_bear": skip_bear,
        "start_date": start_date,
    }
    with open(_model_meta_path(label), "w") as f:
        json.dump(meta, f, indent=2)
    conn.close()
    print(f"[KDE-TRAIN] Saved {bundle_path}")
    print(f"[KDE-TRAIN] Saved {_model_meta_path(label)}")
    return meta


# ── Live scoring ──────────────────────────────────────────────────────────────

class KDEStrategyEngine:
    """Loads trained AdaptiveCascade, scores live signals from cache."""

    def __init__(self, label: str = "default"):
        import joblib
        self.label = label
        self.bundle_path = _model_bundle_path(label)
        if not os.path.exists(self.bundle_path):
            raise FileNotFoundError(
                f"No KDE model at {self.bundle_path}. "
                f"Run: python3 -m atlas_v2.kde_train --label {label}")
        self.bundle = joblib.load(self.bundle_path)
        self.cascade: AdaptiveCascade = self.bundle["cascade"]
        self.feature_cols = self.bundle["feature_cols"]
        self.horizons = self.bundle["horizons"]

    def meta(self) -> Dict:
        with open(_model_meta_path(self.label)) as f:
            return json.load(f)

    def score_universe(self, min_price: float = 5.0,
                       held_tickers: Optional[set] = None,
                       limit: Optional[int] = None,
                       breakdown_top_n: int = 30) -> List[KDESignal]:
        """Batch-score every cached ticker. Compute features in one pass,
        predict in one batched GBM call per horizon. Per-horizon breakdown only
        for the top breakdown_top_n picks (cheap predict on small slice)."""
        from atlas_v2.kde_cascade import (
            rsi2, atr_pct as atr_pct_fn, sma,
        )
        from scipy.stats import norm

        held = held_tickers or set()
        conn = sqlite3.connect(DB_PATH)

        regime_map = _spy_panel(conn)
        latest_date = max(regime_map.keys()) if regime_map else datetime.now().strftime("%Y-%m-%d")
        regime_today = regime_map.get(latest_date, "HEALTHY")

        macro = build_macro_panel(conn, start_date=(datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d"))
        macro_today = macro.iloc[-1].to_dict() if len(macro) > 0 else {}

        rows = conn.execute(
            "SELECT ticker FROM daily_prices GROUP BY ticker HAVING COUNT(*) >= 250"
        ).fetchall()
        all_tickers = [r[0] for r in rows]

        # Phase 1 — pull last 260 bars per ticker, build feature row vector
        feature_rows: List[List[float]] = []
        meta_rows: List[Dict] = []
        for tk in all_tickers:
            if tk in held:
                continue
            data = conn.execute(
                "SELECT date, open, high, low, close, volume FROM daily_prices "
                "WHERE ticker=? ORDER BY date DESC LIMIT 260", (tk,)
            ).fetchall()
            if len(data) < 200:
                continue
            data.reverse()
            opens = np.fromiter((r[1] for r in data), dtype=float, count=len(data))
            highs = np.fromiter((r[2] for r in data), dtype=float, count=len(data))
            lows = np.fromiter((r[3] for r in data), dtype=float, count=len(data))
            closes = np.fromiter((r[4] for r in data), dtype=float, count=len(data))
            volumes = np.fromiter((r[5] for r in data), dtype=float, count=len(data))
            n = len(closes)
            price = closes[-1]
            if price < min_price:
                continue

            rsi_v = rsi2(closes)[-1]
            atr14 = atr_pct_fn(highs, lows, closes, 14)[-1]
            atr50 = atr_pct_fn(highs, lows, closes, 50)[-1]
            sma50_v = sma(closes, 50)[-1]
            sma200_v = sma(closes, 200)[-1]
            buf_v = (price - sma50_v) / sma50_v * 100 if sma50_v > 0 else 0
            buf200_v = (price - sma200_v) / sma200_v * 100 if sma200_v > 0 else 0
            mom20_v = (price / closes[-21] - 1) * 100 if n >= 21 else 0
            ret5_v = (price / closes[-6] - 1) * 100 if n >= 6 else 0
            vol20_avg = volumes[-20:].mean() if n >= 20 else 0
            vol_ratio_v = volumes[-1] / vol20_avg if vol20_avg > 0 else 0
            squeeze_v = atr14 / atr50 if atr50 > 0 else 1
            hi252 = highs[-min(252, n):].max()
            lo252 = lows[-min(252, n):].min()
            hi52_pct = (price / hi252 - 1) * 100 if hi252 > 0 else 0
            lo52_pct = (price / lo252 - 1) * 100 if lo252 > 0 else 0

            feature_dict = {
                "rsi2": rsi_v, "atr_pct": atr14, "buf_pct": buf_v, "buf200_pct": buf200_v,
                "mom20_pct": mom20_v, "ret5_pct": ret5_v,
                "vol_ratio": vol_ratio_v, "atr_squeeze": squeeze_v,
                "hi52_pct": hi52_pct, "lo52_pct": lo52_pct,
                "spy_ret_5d": macro_today.get("spy_ret_5d", 0.0),
                "spy_ret_20d": macro_today.get("spy_ret_20d", 0.0),
                "spy_sma200_gap": macro_today.get("spy_sma200_gap", 0.0),
                "spy_realvol_20d": macro_today.get("spy_realvol_20d", 0.0),
                "iwm_spy_5d": macro_today.get("iwm_spy_5d", 0.0),
                "qqq_spy_5d": macro_today.get("qqq_spy_5d", 0.0),
                "regime_HEALTHY": 1.0 if regime_today == "HEALTHY" else 0.0,
                "regime_CAUTION": 1.0 if regime_today == "CAUTION" else 0.0,
                "regime_CORRECTION": 1.0 if regime_today == "CORRECTION" else 0.0,
                "regime_BEAR": 1.0 if regime_today == "BEAR" else 0.0,
            }
            feature_rows.append([float(feature_dict.get(c, 0.0)) for c in self.feature_cols])
            meta_rows.append({
                "ticker": tk, "price": price, "data_date": str(data[-1][0])[:10],
                "rsi2": rsi_v, "atr_pct": atr14, "buf_pct": buf_v, "mom20_pct": mom20_v,
            })

        conn.close()
        if not feature_rows:
            return []

        # Phase 2 — single batched score call across all tickers
        X = np.asarray(feature_rows, dtype=np.float32)
        best_score, best_h, eret, pbig = self.cascade.score(X)

        # Phase 3 — sort, cap, attach per-horizon breakdown for the kept slice
        order = np.argsort(-best_score)
        if limit is not None:
            order = order[:limit]
        kept_X = X[order]
        # Per-horizon predictions (vectorized) — only for kept rows
        horizon_preds = {}
        for h in self.horizons:
            if h in self.cascade.models:
                ep = self.cascade.models[h].predict(kept_X)
                std = max(self.cascade.resid_std.get(h, 1e-6), 1e-6)
                pb = 1.0 - norm.cdf(DEFAULT_PROFIT_THRESH_PCT, loc=ep, scale=std)
                horizon_preds[h] = (ep, pb)

        signals: List[KDESignal] = []
        for j, idx in enumerate(order.tolist()):
            m = meta_rows[idx]
            breakdown = {}
            for h, (ep, pb) in horizon_preds.items():
                breakdown[h] = {"expected_return_pct": float(ep[j]), "p_big": float(pb[j])}
            signals.append(KDESignal(
                ticker=m["ticker"], price=round(m["price"], 2),
                score=float(best_score[idx]),
                expected_return_pct=float(eret[idx]),
                p_big_winner=float(pbig[idx]),
                best_horizon_days=int(best_h[idx]),
                regime=regime_today,
                rsi2=round(m["rsi2"], 1), atr_pct=round(m["atr_pct"], 2),
                sma50_buf_pct=round(m["buf_pct"], 2), mom20_pct=round(m["mom20_pct"], 2),
                data_date=m["data_date"], horizon_breakdown=breakdown,
            ))
        return signals


def position_size_pct(target_slots: int = DEFAULT_TARGET_SLOTS,
                      max_per_pos_pct: float = DEFAULT_MAX_PER_POS_PCT) -> float:
    """Suggested position size as % of book."""
    return min(100.0 / target_slots, max_per_pos_pct)
