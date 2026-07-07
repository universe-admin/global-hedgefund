"""A tiny online logistic-regression, pure Python, fully deterministic.

Trained prequentially in the walk-forward loop: predict day t first, score
the prediction, then update on day t's realized label. The model never sees
a label before it has predicted it, which is the whole point.
"""

from __future__ import annotations

import math
from typing import List, Sequence


class OnlineLogit:
    def __init__(self, n_features: int, lr: float = 0.05, l2: float = 1e-4):
        self.w: List[float] = [0.0] * n_features
        self.lr = lr
        self.l2 = l2
        self.n_updates = 0

    def predict_proba(self, x: Sequence[float]) -> float:
        z = sum(wi * xi for wi, xi in zip(self.w, x))
        z = max(-30.0, min(30.0, z))
        return 1.0 / (1.0 + math.exp(-z))

    def update(self, x: Sequence[float], label: int) -> None:
        p = self.predict_proba(x)
        err = label - p
        # decaying learning rate keeps early noise from dominating
        lr = self.lr / (1.0 + self.n_updates / 500.0)
        self.w = [
            wi + lr * (err * xi - self.l2 * wi)
            for wi, xi in zip(self.w, x)
        ]
        self.n_updates += 1
