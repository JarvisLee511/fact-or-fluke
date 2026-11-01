"""How much a 'pattern' fun fact is backed by data.

1. Shrink the subject's rate k/n toward its baseline p0 with a Beta(m*p0, m*(1-p0)) prior, where the
   prior strength m is estimated per family from all candidates (empirical Bayes, method of moments):
   small samples get pulled back hard, big samples keep their own rate.
2. Evidence z = (shrunk rate - p0) / posterior sd (plus the baseline's own sampling noise when the
   baseline comes from a finite sample n0).
3. Benjamini-Hochberg across every candidate scanned in the family the same day, so scanning
   thousands of splits does not manufacture "discoveries" out of luck.
4. For the Fluke verdicts: how many of the N scanned would look at least this extreme if luck were the
   only thing at work, N x two-sided p of the unshrunk gap.
"""
from __future__ import annotations

import math

import numpy as np


def prior_strength(k, n, p0, min_n: int = 10) -> float:
    """Excess spread of observed rates over pure binomial noise = spread of true rates (tau^2);
    a Beta(m p0, m (1-p0)) prior has variance p0 (1-p0) / (m + 1)."""
    k, n, p0 = (np.asarray(v, dtype=float) for v in (k, n, p0))
    ok = n >= min_n
    if ok.sum() < 5:
        return 200.0
    r, n, p0 = k[ok] / n[ok], n[ok], p0[ok]
    tau2 = ((r - p0) ** 2).mean() - (p0 * (1 - p0) / n).mean()
    m = (p0 * (1 - p0)).mean() / max(tau2, 1e-6) - 1
    return float(min(max(m, 5.0), 5000.0))


def score(k: float, n: float, p0: float, m: float, n0: float | None = None) -> tuple[float, float, float]:
    """(shrunk rate, posterior sd, z)."""
    p_hat = (k + m * p0) / (n + m)
    var = p_hat * (1 - p_hat) / (n + m) + (p0 * (1 - p0) / n0 if n0 else 0.0)
    sd = math.sqrt(max(var, 1e-12))
    return p_hat, sd, (p_hat - p0) / sd


def raw_z(k: float, n: float, p0: float, n0: float | None = None) -> float:
    """The gap k/n - p0 in standard errors, before any shrinking."""
    var = p0 * (1 - p0) * (1 / n + (1 / n0 if n0 else 0.0))
    return (k / n - p0) / math.sqrt(max(var, 1e-12))


def two_sided_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2))


def bh(pvals: list[float], q: float = 0.05) -> list[bool]:
    """Benjamini-Hochberg discoveries at false discovery rate q."""
    p = np.asarray(pvals, dtype=float)
    m = len(p)
    if m == 0:
        return []
    order = np.argsort(p)
    passed = p[order] <= q * np.arange(1, m + 1) / m
    keep = (np.nonzero(passed)[0].max() + 1) if passed.any() else 0
    out = np.zeros(m, dtype=bool)
    out[order[:keep]] = True
    return out.tolist()
