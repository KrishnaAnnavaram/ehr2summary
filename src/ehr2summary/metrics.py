"""Reference metrics (ROUGE), rank correlation (Spearman, Kendall tau-b) and bootstrap intervals. NumPy only."""

from __future__ import annotations

import re
from collections import Counter

import numpy as np

_TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _f1(overlap: int, n_pred: int, n_ref: int) -> float:
    if overlap == 0 or n_pred == 0 or n_ref == 0:
        return 0.0
    p, r = overlap / n_pred, overlap / n_ref
    return 2 * p * r / (p + r)


def rouge_n(pred: str, ref: str, n: int = 1) -> float:
    def grams(t):
        return Counter(tuple(t[i:i + n]) for i in range(len(t) - n + 1))

    gp, gr = grams(tokens(pred)), grams(tokens(ref))
    return _f1(sum((gp & gr).values()), sum(gp.values()), sum(gr.values()))


def _lcs(a: list[str], b: list[str]) -> int:
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, start=1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1]


def rouge_l(pred: str, ref: str) -> float:
    tp, tr = tokens(pred), tokens(ref)
    return _f1(_lcs(tp, tr), len(tp), len(tr))


def rankdata(x) -> np.ndarray:
    """Average ranks (ties get the mean rank), 1-based."""
    x = np.asarray(x, dtype=float)
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x))
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and x[order[j + 1]] == x[order[i]]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(x, y) -> float:
    rx, ry = rankdata(x), rankdata(y)
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def kendall_tau_b(x, y) -> float:
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    n = len(x)
    conc = disc = tx = ty = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx, dy = np.sign(x[i] - x[j]), np.sign(y[i] - y[j])
            if dx == 0 and dy == 0:
                continue
            if dx == 0:
                tx += 1
            elif dy == 0:
                ty += 1
            elif dx == dy:
                conc += 1
            else:
                disc += 1
    denom = np.sqrt((conc + disc + tx) * (conc + disc + ty))
    return float((conc - disc) / denom) if denom else float("nan")


def bootstrap_ci(values, *, n_boot: int = 2000, seed: int = 0, alpha: float = 0.05) -> tuple[float, float, float]:
    """Mean and a percentile bootstrap interval."""
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = rng.choice(v, size=(n_boot, v.size), replace=True).mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return float(v.mean()), float(lo), float(hi)
