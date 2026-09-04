"""Price data loading for the TradingAI system."""

import pandas as pd

DEFAULT_TICKERS = [
    "NVDA",
    "AAPL",
    "MSFT",
    "TSLA",
    "AMZN",
    "BTC-USD",
    "ETH-USD"
]

REQUIRED_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def flatten_columns(asset):
    """Drop the ticker level yfinance adds to its column index."""

    if asset.columns.nlevels > 1:
        asset = asset.copy()
        asset.columns = asset.columns.get_level_values(0)

    return asset


def download_prices(ticker, period="1y"):
    """Download daily candles for one ticker.

    Returns an empty frame when the download yields nothing, so callers
    can report the problem instead of raising.
    """

    import yfinance as yf

    asset = yf.download(
        ticker,
        period=period,
        progress=False,
        auto_adjust=True
    )

    if asset is None or asset.empty:
        return pd.DataFrame()

    return flatten_columns(asset)


def csv_loader(directory):
    """Build a loader that reads ``<TICKER>.csv`` out of a directory.

    Matches the ``download_prices`` signature so it can be handed to
    the analysis and backtest entry points for offline runs.
    """

    from pathlib import Path

    directory = Path(directory)

    def load(ticker, period=None):
        path = directory / f"{ticker}.csv"

        if not path.exists():
            return pd.DataFrame()

        return load_prices_from_csv(path)

    return load


def load_prices_from_csv(path):
    """Read candles from a CSV file with a date index.

    Useful for reproducible runs and for testing without network access.
    """

    asset = pd.read_csv(path, index_col=0, parse_dates=True)

    return flatten_columns(asset)
