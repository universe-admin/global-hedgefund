"""Provider selection: openbb -> yfinance -> offline, or forced via config."""

from __future__ import annotations

from hedgefund.config import Config, DEFAULT_CONFIG
from hedgefund.data.base import MarketDataProvider
from hedgefund.data.offline_provider import OfflineProvider
from hedgefund.data.openbb_provider import OpenBBProvider
from hedgefund.data.yfinance_provider import YFinanceProvider

_REGISTRY = {
    "openbb": OpenBBProvider,
    "yfinance": YFinanceProvider,
    "offline": OfflineProvider,
}


def get_provider(config: Config = DEFAULT_CONFIG) -> MarketDataProvider:
    choice = (config.data_provider or "auto").lower()
    if choice != "auto":
        if choice not in _REGISTRY:
            raise ValueError(
                f"Unknown data provider {choice!r}; pick one of "
                f"{sorted(_REGISTRY)} or 'auto'"
            )
        provider = _REGISTRY[choice]()
        if not provider.available():
            raise RuntimeError(
                f"Data provider {choice!r} was requested but is not installed."
            )
        return provider

    for name in ("openbb", "yfinance"):
        provider = _REGISTRY[name]()
        if provider.available():
            return provider
    return OfflineProvider()
