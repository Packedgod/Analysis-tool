"""Overfitting-honest performance statistics for backtests.

Raw risk-adjusted metrics (Sharpe, total return) systematically flatter a
strategy: they ignore how *short* the track record is, how *non-normal* the
returns are, and — above all — how many strategies were *tried* before this one
was selected. A Sharpe of 2 from a single honest attempt and a Sharpe of 2
cherry-picked from 500 backtests are wildly different evidence, yet a raw Sharpe
reports them identically. Most finance-research tools stop at the raw number;
this module reports the honest one.

Implements the Bailey & Lopez de Prado family of corrections:

  - Probabilistic Sharpe Ratio (PSR): probability the *true* Sharpe exceeds a
    benchmark, given track-record length, skew and kurtosis.
  - Deflated Sharpe Ratio (DSR): PSR against a benchmark raised to the expected
    maximum Sharpe under the null across ``n_trials`` attempts — i.e. corrected
    for multiple testing / selection bias.
  - Minimum Track Record Length (MinTRL): how many periods of the observed
    performance you would need before the Sharpe is statistically credible.

References:
  Bailey, D. & Lopez de Prado, M. (2012), "The Sharpe Ratio Efficient
    Frontier", Journal of Risk 15(2). (PSR, MinTRL)
  Bailey, D. & Lopez de Prado, M. (2014), "The Deflated Sharpe Ratio",
    Journal of Portfolio Management 40(5). (DSR)

Sharpe values inside the formulas are *per-period* (non-annualised); the report
also returns annualised figures for display.
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any, Dict, Optional, Sequence

import numpy as np

_N = NormalDist()
_EULER_MASCHERONI = 0.5772156649015329


def _moments(returns: Sequence[float]) -> tuple[float, float, float, int]:
    """Return (sharpe_per_period, skew, kurtosis_nonexcess, n_valid).

    Kurtosis is non-excess (a normal distribution scores 3.0). Degenerate
    inputs (fewer than 2 finite points, or zero volatility) have an *undefined*
    Sharpe, so the moments are returned as ``nan`` and propagate to ``nan``
    downstream rather than being silently reported as a real zero edge.
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = int(r.size)
    nan = float("nan")
    if n < 2:
        return nan, nan, nan, n
    mu = float(r.mean())
    sigma = float(r.std(ddof=1))
    if sigma <= 0.0:
        return nan, nan, nan, n
    sr = mu / sigma
    z = (r - mu) / sigma
    skew = float(np.mean(z ** 3))
    kurt = float(np.mean(z ** 4))  # non-excess; normal == 3.0
    return sr, skew, kurt, n


def _sr_estimator_variance(sr: float, skew: float, kurt: float, n: int) -> float:
    """Variance of the Sharpe-ratio estimator (Lo 2002; Bailey-LdP adjustment).

    Accounts for non-normality: negative skew and fat tails inflate the
    uncertainty of a Sharpe estimate.
    """
    if n < 2:
        return float("inf")
    return (1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr) / (n - 1)


def probabilistic_sharpe_ratio(
    returns: Sequence[float], sr_benchmark: float = 0.0
) -> float:
    """Probability the true (per-period) Sharpe exceeds ``sr_benchmark``.

    Returns a value in ``[0, 1]`` (``nan`` if the estimator variance is
    undefined). ``sr_benchmark`` is also per-period.
    """
    sr, skew, kurt, n = _moments(returns)
    var = _sr_estimator_variance(sr, skew, kurt, n)
    if not math.isfinite(var) or var <= 0.0:
        return float("nan")
    z = (sr - sr_benchmark) / math.sqrt(var)
    return float(_N.cdf(z))


def min_track_record_length(
    returns: Sequence[float], target_prob: float = 0.95, sr_benchmark: float = 0.0
) -> float:
    """Minimum number of periods for the Sharpe to be credible at ``target_prob``.

    ``inf`` when the observed Sharpe does not exceed ``sr_benchmark`` (no track
    record could make a non-positive edge significant).
    """
    sr, skew, kurt, n = _moments(returns)
    if sr <= sr_benchmark:
        return float("inf")
    zc = _N.inv_cdf(target_prob)
    return 1.0 + (1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr) * (
        zc / (sr - sr_benchmark)
    ) ** 2


def _expected_max_sharpe(sr_variance: float, n_trials: int) -> float:
    """Expected maximum per-period Sharpe under the null across independent trials.

    This is the benchmark the Deflated Sharpe must clear: the Sharpe you would
    expect to see *by luck alone* as the best of ``n_trials`` attempts.
    """
    if n_trials <= 1 or sr_variance <= 0.0 or not math.isfinite(sr_variance):
        return 0.0
    sd = math.sqrt(sr_variance)
    a = _N.inv_cdf(1.0 - 1.0 / n_trials)
    b = _N.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return sd * ((1.0 - _EULER_MASCHERONI) * a + _EULER_MASCHERONI * b)


def deflated_sharpe_ratio(
    returns: Sequence[float],
    n_trials: int = 1,
    trial_sharpes: Optional[Sequence[float]] = None,
) -> Dict[str, float]:
    """Deflated Sharpe Ratio: PSR against the expected best-of-``n_trials`` null.

    When the full set of trial Sharpes is available, its sample variance drives
    the deflation; otherwise the Sharpe-estimator variance of this strategy is
    used as a documented proxy for cross-trial dispersion.
    """
    sr, skew, kurt, n = _moments(returns)
    if trial_sharpes is not None and len(trial_sharpes) > 1:
        sr_variance = float(np.var(np.asarray(trial_sharpes, dtype=float), ddof=1))
    else:
        sr_variance = _sr_estimator_variance(sr, skew, kurt, n)
    sr_star = _expected_max_sharpe(sr_variance, int(n_trials))
    dsr = probabilistic_sharpe_ratio(returns, sr_benchmark=sr_star)
    return {"dsr": dsr, "deflated_benchmark_sr": sr_star, "n_trials": int(n_trials)}


def _r(x: Any, ndigits: int = 4) -> Optional[float]:
    """Round to a JSON-safe float; None for nan/inf/non-numeric."""
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(xf):
        return None
    return round(xf, ndigits)


def _interpret(psr: float, dsr: float, mintrl: float, n: int, n_trials: int) -> str:
    """One honest sentence a non-quant can act on."""
    if not math.isfinite(dsr):
        return "Not enough data to judge statistical credibility."
    if dsr >= 0.95:
        return (
            f"Credible: after correcting for {n_trials} trial(s), a "
            f"{n}-period record, skew and fat tails, the edge is statistically "
            f"significant (deflated confidence {dsr:.0%})."
        )
    need = "an indefinite" if not math.isfinite(mintrl) else f"~{int(math.ceil(mintrl))}"
    return (
        f"Not yet credible: deflated confidence is only {dsr:.0%} after "
        f"correcting for {n_trials} trial(s) and non-normality. You would need "
        f"{need}-period track record of this performance to trust the Sharpe."
    )


def overfitting_report(
    returns: Sequence[float],
    n_trials: int = 1,
    bars_per_year: int = 252,
    trial_sharpes: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """Full overfitting-honesty summary for a return series.

    Args:
        returns: Per-period (e.g. daily) strategy returns.
        n_trials: Number of strategy configurations tried before selecting this
            one. 1 means no multiple-testing correction; set to the size of the
            search (e.g. the alpha-zoo sweep) for an honest deflation.
        bars_per_year: Annualisation factor for the display Sharpe.
        trial_sharpes: Optional per-period Sharpe of every trial; when given,
            drives the deflation directly instead of the single-strategy proxy.

    Returns:
        A JSON-serialisable dict of raw + corrected statistics and a plain
        interpretation. Never raises on degenerate input.
    """
    sr, skew, kurt, n = _moments(returns)
    if n < 3:
        return {
            "note": "insufficient observations for overfitting statistics",
            "n_periods": int(n),
        }
    psr0 = probabilistic_sharpe_ratio(returns, sr_benchmark=0.0)
    dsr = deflated_sharpe_ratio(returns, n_trials=n_trials, trial_sharpes=trial_sharpes)
    mintrl = min_track_record_length(returns, target_prob=0.95, sr_benchmark=0.0)
    ann_factor = math.sqrt(bars_per_year)
    return {
        "sharpe_annualized": _r(sr * ann_factor),
        "sharpe_per_period": _r(sr, 6),
        "skew": _r(skew),
        "kurtosis": _r(kurt),
        "n_periods": int(n),
        "n_trials": int(n_trials),
        "probabilistic_sharpe_ratio": _r(psr0),
        "deflated_sharpe_ratio": _r(dsr["dsr"]),
        "deflated_benchmark_sharpe_annualized": _r(dsr["deflated_benchmark_sr"] * ann_factor),
        "min_track_record_length_periods": _r(mintrl, 1),
        "credible_at_95": bool(math.isfinite(dsr["dsr"]) and dsr["dsr"] >= 0.95),
        "interpretation": _interpret(psr0, dsr["dsr"], mintrl, n, int(n_trials)),
    }
