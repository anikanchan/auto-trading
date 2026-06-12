# Auto-Trading

A minimal-intervention automated stock trading system. It runs intraday and
swing strategies against [Alpaca](https://alpaca.markets) (paper first, live
only after validation), gates every order through a risk manager, and asks for
confirmation on your phone before executing a trade.

## How it works

```
Scheduler ──► Strategy Engine ──► Risk Manager ──► Phone confirmation ──► Alpaca
 (APScheduler)  (SMA / ORB / RSI)   (position &        (iMessage or          (paper → live)
                                     drawdown limits)    WhatsApp, YES/NO)
```

- **Strategies** — SMA crossover and RSI mean reversion (swing), opening range
  breakout (intraday); momentum and options strategies planned
- **Risk manager** — gates every order: max 5% per position, max 50% of the
  portfolio deployed, 10 concurrent positions, -1.5% per-trade stop-loss, and a
  -2% daily drawdown kill-switch
- **Human in the loop** — every trade is confirmed via iMessage or WhatsApp
  (configurable); no reply within 5 minutes means the trade is skipped. A
  two-way command interface (`STATUS`, `PAUSE`, `FLATTEN`, `BUY`, `SELL`,
  `HISTORY`, …) controls the bot from your phone
- **Audit trail** — every trade, skip, rejection, and command is recorded in an
  append-only ledger; a Streamlit dashboard shows live P&L, positions, and
  trade history
- **Unattended operation** — a Raspberry Pi wakes the Mac before market open
  via Wake-on-LAN; the bot shuts it down after the end-of-day report
- **Secrets** — API keys live in the macOS Keychain, never in config files.
  Supports both personal and business Alpaca accounts
  (`alpaca.account_type` in `app/config/settings.yaml`)

## Repository layout

| Path | Contents |
|---|---|
| [`app/`](app/) | The application — see [`app/README.md`](app/README.md) for setup and usage |
| [`auto-trading-specs.md`](auto-trading-specs.md) | Full specs for the local (Mac + Raspberry Pi) deployment |
| [`auto-trading-specs-aws.md`](auto-trading-specs-aws.md) | Alternate specs for an AWS deployment (Fargate + Twilio webhooks) |

## Quick start

```bash
cd app
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pytest                          # run the test suite
```

Then follow [`app/README.md`](app/README.md) to store your Alpaca API keys in
the Keychain, verify connectivity, and run the bot in paper mode.

## Status

Paper trading. Live trading is gated behind 3 months of paper validation with
a Sharpe ratio above 1.0, and starts with at most 10% of capital.

## Disclaimer

This is a personal project, not financial advice. Automated trading carries
real risk of loss — use paper trading, and trade live at your own risk.
