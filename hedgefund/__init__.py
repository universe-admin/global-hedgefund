"""Global Hedgefund — a full hedge-fund desk in one package.

Three layers, mirroring the three open-source pillars it is modeled on:

- ``hedgefund.data``      market data (OpenBB / yfinance adapters + offline provider)
- ``hedgefund.agents``    the TradingAgents-style desk: analysts -> bull/bear debate
                          -> trader -> risk manager -> fund manager verdict
- ``hedgefund.brain``     the Hermes orchestrator: runs the desk, remembers every
                          decision, learns from outcomes, and manages the book
"""

__version__ = "0.1.0"

from hedgefund.brain.orchestrator import DeskRun, HermesBrain  # noqa: F401
