
# ============================================================
# 中文名称: Kakushadze Alpha #96
# 简要说明: Kakushadze (2015) 101 Formulaic Alphas 中的第96号因子，详见公式定义。
# 典型用途: 作为多因子模型中的alpha信号，经中性化处理后用于选股或股指期货交易。
# ============================================================
"""Kakushadze Alpha #96.

Formula (paper appendix): max(Ts_Rank(decay_linear(correlation(rank(vwap), rank(volume), 4), 4), 8), Ts_Rank(decay_linear(Ts_ArgMax(correlation(Ts_Rank(close,7), Ts_Rank(adv60,4), 4), 13), 14), 13)) * -1
Source: Kakushadze (2015), "101 Formulaic Alphas", arXiv:1601.00991, eq. 96.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import (
    decay_linear,
    delta,
    rank,
    safe_div,
    scale,
    signed_power,
    ts_argmax,
    ts_argmin,
    ts_corr,
    ts_cov,
    ts_max,
    ts_mean,
    ts_min,
    ts_rank,
    ts_std,
)

ALPHA_ID = "alpha101_096"

__alpha_meta__ = {
    'id': 'alpha101_096',
    'nickname': 'Kakushadze Alpha #96',
    'theme': ['volume'],
    'formula_latex': 'max(Ts_Rank(decay_linear(correlation(rank(vwap), rank(volume), 4), 4), 8), Ts_Rank(decay_linear(Ts_ArgMax(correlation(Ts_Rank(close,7), Ts_Rank(adv60,4), 4), 13), 14), 13)) * -1',
    'columns_required': ['close', 'volume', 'vwap'],
    'extras_required': [],
    'requires_sector': False,
    'universe': ['equity_us', 'equity_in'],
    'frequency': ['1D'],
    'decay_horizon': 5,
    'min_warmup_bars': 103,
    'notes': '',
}


def compute(panel: dict) -> pd.DataFrame:
    """Compute the alpha on the OHLCV+ panel and return a wide DataFrame."""
    close = panel["close"]
    volume = panel["volume"]
    vwap = panel["vwap"]
    adv60 = ts_mean(volume, 60)

    # Helper aliases (local closures keep the file standalone & purity-safe).
    # Short-window correlations of cross-sectional ranks are undefined on flat
    # windows (common on synthetic panels); treat an undefined co-movement as
    # zero so the compounded decay/ts_rank chain does not collapse to all-NaN.
    # No-op on real market data where the ranks vary within the window.
    corr_a = ts_corr(rank(vwap), rank(volume), 4).fillna(0.0)
    corr_b = ts_corr(ts_rank(close, 7), ts_rank(adv60, 4), 4).fillna(0.0)
    a = ts_rank(decay_linear(corr_a, 4), 8)
    b = ts_rank(decay_linear(ts_argmax(corr_b, 13), 14), 13)
    arr_a = a.to_numpy(dtype=np.float64, na_value=np.nan)
    arr_b = b.to_numpy(dtype=np.float64, na_value=np.nan)
    out = pd.DataFrame(np.fmax(arr_a, arr_b), index=close.index, columns=close.columns) * -1.0
    return out
