"""Entry point: score the default watchlist, then backtest every ticker."""

import sys

from tradingai.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
