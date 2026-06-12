# Automated Stock Trading App — Specs

## Overview

A minimal-intervention automated trading system supporting both **intraday** and **swing** strategies, integrated with Alpaca for execution. Fidelity is kept for manual/long-term holdings only (no public API available).

---

## Broker Setup

| Broker | Role |
|---|---|
| **Alpaca** | Automated trading (paper → live) |
| **Fidelity** | Manual / long-term holdings only |

Alpaca provides commission-free trading, paper trading environment, and clean REST + WebSocket APIs for both equities and options.

### Alpaca Account Type

Configurable choice between a **personal** (individual) account and a **business** (entity) account — set via `alpaca.account_type` in `settings.yaml`:

| | Personal (Individual) | Business (Entity) |
|---|---|---|
| Onboarding | Standard individual signup | Entity onboarding (LLC/corp docs, EIN required) |
| Ownership | Trades under your own name/SSN | Trades under the entity |
| Taxes | Gains on personal return (1099) | Gains flow to the entity; possible trader tax status benefits |
| Liability | Personal | Limited to the entity |
| API | Same REST + WebSocket API and keys | Same REST + WebSocket API and keys |

- The trading API is identical for both — only the account opened on Alpaca's side and the API keys stored in Keychain differ
- Paper trading is available for both account types
- Default: `personal`; switch to `business` only if/when an LLC is set up for trading

---

## Trading Strategies

### Tier 1 — Start Here

**1. Dual Moving Average Crossover (Swing)**
- Buy when 20-day SMA crosses above 50-day SMA; sell on reverse
- Universe: ETFs (SPY, QQQ) to reduce single-stock risk
- Execution: once per day at market close

**2. Opening Range Breakout — ORB (Intraday)**
- Record the high/low of the first 30 minutes after market open
- Buy if price breaks above range with volume confirmation; short if breaks below
- Stop-loss at the opposite range boundary
- Execution: runs every 1–5 minutes during market hours

**3. Mean Reversion on Oversold Stocks (Swing)**
- Scan S&P 500 for stocks where RSI < 30 and price near 52-week support
- Buy small position; sell when RSI recovers above 50
- Target hold time: 2–5 days

### Tier 2 — Add After Validation

**4. Momentum / Trend Following (Swing)**
- Rank S&P 500 by 12-1 month return weekly
- Buy top 10%, rebalance monthly
- Low-maintenance, historically strong risk-adjusted returns

**5. Earnings Volatility Capture (Options — future)**
- Buy straddles before earnings on stocks with historically underpriced implied volatility
- Requires Alpaca options API

---

## Architecture

```
┌─────────────────┐
│  Raspberry Pi 3 │──── WoL magic packet ────► Mac wakes at 9:00 AM ET
└─────────────────┘

┌─────────────────────────────────────────────┐
│              Scheduler (APScheduler)         │
│  ┌──────────────┐    ┌─────────────────────┐ │
│  │  Daily Jobs  │    │   Intraday Jobs     │ │
│  │  (swing)     │    │  (every 1-5 min)    │ │
│  └──────┬───────┘    └──────────┬──────────┘ │
│  Shuts Mac down at 4:30 PM ET               │
└─────────┼──────────────────────┼────────────┘
          ▼                      ▼
┌─────────────────────────────────────────────┐
│            Strategy Engine                  │
│  SMA Crossover │ ORB │ RSI Mean Reversion  │
└─────────────────────────┬───────────────────┘
                          ▼
┌─────────────────────────────────────────────┐
│         Risk Manager (gates every order)    │
│  Max position 5% │ Daily loss -2% kill      │
│  Max 10 concurrent positions                │
└─────────────────────────┬───────────────────┘
                          ▼
┌─────────────────────────────────────────────┐
│   Messaging Confirmation (iMessage or       │
│   WhatsApp — configurable platform)         │
│  Sends trade details → waits for YES/NO     │
│  Timeout: 5 min → auto-skip trade           │
└─────────────────────────┬───────────────────┘
                          ▼ (YES received)
┌─────────────────────────────────────────────┐
│         Alpaca Broker API                   │
│  Paper → validate 3 months → Live          │
└─────────────────────────────────────────────┘
```

---

## Core Modules

### 1. Strategy Engine
- Strategies defined as composable, pluggable rule sets
- Multiple strategies run in parallel on different tickers/portfolios
- Backtesting module: validate against 2+ years of historical OHLCV data before live deployment

### 2. Market Data
- Real-time price feeds via WebSocket
- Historical OHLCV data for backtesting and signal generation
- Primary provider: Alpaca Data; fallback: Polygon.io
- Watchlist management with configurable symbol universe

### 3. Order Execution
- Broker: Alpaca REST API
- Order types: market, limit, stop-loss, trailing stop
- Position sizing: fixed % of portfolio per trade
- Paper trading mode enforced until validation criteria are met

### 4. Risk Manager
- Runs as a gate before every order is submitted
- Rules:
  - Max single position: 5% of portfolio
  - Daily drawdown kill-switch: halt all trading if portfolio drops 2% in a day
  - Max concurrent open positions: 10
  - Max portfolio deployed: 50% (50% cash reserve)
  - Per-trade stop-loss: 1.5% from entry
- Emergency command: flatten all positions immediately

### 5. Scheduler
- Daily jobs: pre-market scan, end-of-day signal generation and rebalance
- Intraday jobs: signal check every 1–5 minutes during market hours (9:30–16:00 ET)
- End-of-day report job: compiles and sends daily summary via the configured messaging platform at 4:25 PM ET
- Shutdown job: runs `sudo shutdown -h now` at 4:30 PM ET after market close
- Auto-restart on crash with state recovery from database

### 6. Monitoring & Alerts
- Streamlit dashboard: live P&L, open positions, recent trades, strategy status
- Alerts via the configured **messaging platform** (`messaging.channel` in `settings.yaml` — see Messaging Platform section) for:
  - Trade confirmation request — bot waits for YES/NO reply before executing
  - Trade executed confirmation
  - Risk limit triggered
  - System error
- Confirmation timeout: **5 minutes** — if no reply received, trade is skipped and logged

#### Messaging Platform (configurable)

A single messenger abstraction with two interchangeable backends, selected via `messaging.channel: imessage | whatsapp`:

| | iMessage | WhatsApp (Twilio) |
|---|---|---|
| Outbound | AppleScript on the Mac | Twilio WhatsApp API (HTTPS) |
| Inbound replies | Polls Messages SQLite DB (`~/Library/Messages/chat.db`) | Polls Twilio API for inbound messages (no public webhook needed on local Mac; webhook mode used in the AWS variant) |
| Dependencies | None — native macOS | Twilio account + WhatsApp Business API approval (free sandbox for testing) |
| Encryption | Apple E2E (see Messaging Encryption) | Meta E2E / Signal Protocol (see Messaging Encryption) |
| Cost | Free | Per-message Twilio fees |

- Both backends implement the same interface: send alert, send report, await YES/NO confirmation, poll inbound commands
- Default: `imessage` (zero dependencies on a Mac); `whatsapp` recommended if the bot is ever moved off macOS (see AWS specs)

#### Transaction Ledger
- **Every single transaction is recorded** in the database — no exceptions, including:
  - Trades executed (strategy-driven and manual BUY/SELL)
  - Trades skipped (timeout, rejected by Risk Manager, price limit breach)
  - Order fills, partial fills, and cancellations
  - Risk limit triggers and kill-switch activations
  - Pause/resume/flatten commands and their outcomes
  - Configuration changes made via commands (e.g. `RISK MAXPOS 3%`)
- Each entry includes: timestamp, symbol, side, quantity, price, strategy/trigger source, order ID (if applicable), and resulting status
- Ledger is **append-only** — records are never edited or deleted, only marked with status changes (e.g. open → closed)
- Stored in the `trades` and `audit_log` tables (see Database section)

#### Messaging Encryption
- **iMessage**: Apple end-to-end encryption by default — messages are encrypted on device and can only be read by sender and recipient
  - No configuration needed — E2E encryption is automatic when both parties use iMessage (blue bubbles)
  - Messages never stored in plaintext on Apple servers
  - Falls back to SMS (unencrypted) if iMessage is unavailable — bot should detect this and alert rather than send sensitive trade data over SMS
- **WhatsApp**: Meta end-to-end encryption (Signal Protocol) — messages cannot be read by Twilio or any third party in transit
  - Requires WhatsApp installed on your iPhone and a Twilio WhatsApp sender (sandbox or approved Business API number)
  - No unencrypted SMS fallback is used — if WhatsApp delivery fails, the bot logs an error and alerts on the dashboard

#### Credentials & Secrets Management
All sensitive values are stored in the **macOS Keychain** — never in plaintext config files, scripts, or version control:

| Secret | Description |
|---|---|
| `alpaca-api-key-id` | Alpaca API key ID (personal account) |
| `alpaca-api-secret-key` | Alpaca API secret key (personal account) |
| `alpaca-account-id` | Alpaca brokerage account ID (personal account) |
| `alpaca-business-api-key-id` | Alpaca API key ID (business account, if `alpaca.account_type: business`) |
| `alpaca-business-api-secret-key` | Alpaca API secret key (business account) |
| `alpaca-business-account-id` | Alpaca brokerage account ID (business account) |
| `dashboard-basic-auth` | Dashboard login credentials |
| `polygon-api-key` | Polygon.io API key (market data fallback) |
| `db-encryption-key` | Local database encryption passphrase |
| `twilio-account-sid` | Twilio Account SID (WhatsApp platform only) |
| `twilio-auth-token` | Twilio Auth Token (WhatsApp platform only) |
| `twilio-whatsapp-number` | Twilio WhatsApp sender number (WhatsApp platform only) |

**Access controls:**
- Secrets accessed at runtime via Python `keyring` library, which reads from macOS Keychain
- Bot process requests Keychain access on first run — macOS prompts for approval, then remembers the decision per-app
- `settings.yaml` contains **no secrets** — only non-sensitive config (risk params, symbol universe, schedules)
- `.gitignore` excludes any `.env`, `*.pem`, `*credentials*`, and `*.db` files from version control
- Allowed-sender phone number (iMessage or WhatsApp) stored in Keychain, not hardcoded
- Local PostgreSQL/SQLite database file permissions restricted to the bot's user account (`chmod 600`)
- Full disk encryption (FileVault) should be enabled on the Mac as a baseline — protects all stored secrets and trade data if the device is lost or stolen

#### Configuration File (`config/settings.yaml`)
All non-sensitive, version-controllable settings live in `settings.yaml`:

```yaml
# Trading mode
mode: paper                      # paper | live

# Broker
alpaca:
  account_type: personal         # personal | business

# Symbol universe
watchlist:
  - SPY
  - QQQ
  - AAPL

# Strategy parameters
strategies:
  sma_crossover:
    enabled: true
    fast_period: 20
    slow_period: 50
  orb:
    enabled: true
    range_minutes: 30
  rsi_mean_reversion:
    enabled: true
    rsi_oversold: 30
    rsi_exit: 50

# Risk parameters
risk:
  max_portfolio_deployed_pct: 50
  max_position_pct: 5
  daily_loss_kill_switch_pct: -2
  stop_loss_pct: -1.5
  max_concurrent_positions: 10

# Schedule
schedule:
  market_open: "09:30"
  market_close: "16:00"
  eod_report_time: "16:25"
  shutdown_time: "16:30"

# Messaging
messaging:
  channel: imessage              # imessage | whatsapp
  confirmation_timeout_minutes: 5
```

This file is safe to commit to version control — it contains no API keys, account IDs, or credentials.
- **End-of-day report** sent via the configured messaging platform at 4:25 PM ET (before shutdown), including:
  - Trades executed today (symbol, direction, entry/exit, P&L)
  - Net P&L for the day ($ and %)
  - Open positions carried overnight
  - Any risk limits triggered
  - Cash balance and portfolio value
- Full audit log of every signal, decision, and order

### 7. Messaging Command Interface
Bot polls for inbound messages from your registered number — `~/Library/Messages/chat.db` on iMessage, the Twilio inbound-message API on WhatsApp. Supported commands:

| Command | Action |
|---|---|
| `STATUS` | Reply with current positions, P&L, and bot state |
| `PAUSE` | Suspend all new trade signals (open positions held) |
| `RESUME` | Resume normal trading after a pause |
| `FLATTEN` | Emergency: close all open positions immediately |
| `REPORT` | Send end-of-day report on demand |
| `HISTORY [period]` | Send historical transaction report, e.g. `HISTORY`, `HISTORY 7D`, `HISTORY 2026-01-01..2026-01-31` |
| `RISK <param> <value>` | Update a risk parameter, e.g. `RISK MAXPOS 3%` |
| `STOP <ticker>` | Stop trading a specific symbol |
| `BUY <ticker> <quantity> [MAX <price>]` | Buy specified quantity, optionally capped at max price, e.g. `BUY AAPL 10 MAX 190.00` |
| `SELL <ticker> <quantity> [MIN <price>]` | Sell specified quantity, optionally with minimum acceptable price, e.g. `SELL AAPL 10 MIN 185.00` |
| `HELP` | Reply with list of available commands |

- `BUY` and `SELL` orders are still gated through the Risk Manager — rejected if they breach position size or portfolio limits
- If `MAX` price specified on BUY: placed as a **limit order** — will not execute above that price
- If `MIN` price specified on SELL: placed as a **limit order** — will not execute below that price
- If no price limit specified: placed as a **market order**
- Bot replies with confirmation before executing manual BUY/SELL, e.g.:
  - `"BUY 10 AAPL @ limit $190.00 (current $189.50) — reply YES to confirm"`
  - `"SELL 10 AAPL @ limit $185.00 (current $186.20) — reply YES to confirm"`
- If current price already breaches the limit (e.g. BUY MAX $190 but price is $192), bot rejects immediately with a notification

#### HISTORY Command Details
- `HISTORY` with no argument: returns last 7 days of transactions
- `HISTORY <N>D`: returns last N days, e.g. `HISTORY 30D`
- `HISTORY <start>..<end>`: returns transactions within an explicit date range, e.g. `HISTORY 2026-01-01..2026-01-31`
- Report includes for the period:
  - Total trades executed (count, by strategy)
  - Win rate, total realized P&L ($ and %)
  - Largest win / largest loss
  - Trades skipped or rejected (with reasons)
  - Risk events triggered
- For longer ranges, summary is sent via the configured messaging platform and a detailed CSV export is made available on the Streamlit dashboard for download
- Commands are **case-insensitive**
- Unrecognized messages are ignored and logged
- All commands are logged to audit trail with timestamp
- Only messages from your registered phone number are accepted — all others are ignored

---

## Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Language | Python 3.11+ | Best ecosystem for quant/trading |
| Broker API | Alpaca | Commission-free, paper + live, REST + WebSocket |
| Market Data | Alpaca Data / Polygon.io | Real-time + historical |
| Indicators | `pandas-ta` | Technical indicators (SMA, RSI, etc.) |
| Secrets | macOS Keychain via `keyring` | API keys, account ID, credentials |
| Scheduler | APScheduler | Cron-like job scheduling |
| Database | PostgreSQL | Trade history, positions, audit log |
| Dashboard | Streamlit | Live monitoring UI |
| Alerts | iMessage (AppleScript) or WhatsApp (Twilio) | Configurable via `messaging.channel`; iMessage is native Mac→iPhone with no third-party accounts |
| Deployment | Runs locally on Mac | Woken daily by Raspberry Pi 3 via WoL |
| Wake Controller | Raspberry Pi 3 + `wakeonlan` | Sends magic packet at 9:00 AM ET Mon–Fri |

---

## Risk Parameters

| Parameter | Value |
|---|---|
| Max portfolio deployed | 50% |
| Max single position | 5% of portfolio |
| Daily loss kill-switch | -2% of total portfolio |
| Stop-loss per trade | -1.5% from entry |
| Max concurrent positions | 10 |
| Live trading unlock criteria | 3 months paper trading + Sharpe ratio > 1.0 |

---

## Wake Schedule (Raspberry Pi 3)

### Runtime Behavior
- Pi 3 stays on 24/7, connected to home WiFi
- Sends WoL magic packet to Mac at **9:00 AM ET Mon–Fri**
- Mac must have "Wake for network access" enabled: System Settings → Battery → Options
- Trading bot shuts Mac down at **4:30 PM ET** after market close via `sudo shutdown -h now`
- Pi cron job:
  ```cron
  0 9 * * 1-5 wakeonlan <Mac-MAC-address>
  ```

### Pi 3 Configuration

**OS:** Raspberry Pi OS Lite (64-bit) — headless, no desktop  
**Flash tool:** Raspberry Pi Imager on Mac

**Pre-configure in Imager before flashing:**
- WiFi network + password
- SSH enabled
- Hostname: `trading-pi`
- Username + password

**Packages to install after first boot:**
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install wakeonlan -y
# Note: ntpdate is deprecated — time sync is handled by systemd-timesyncd (pre-installed)
```

**Hardware required:**
| Item | Spec |
|---|---|
| MicroSD card | 8GB minimum, Class 10 |
| Power supply | 5V/2.5A micro-USB |

**One-time Mac setup:**
1. System Settings → Battery → Options → enable "Wake for network access"
2. Get WiFi MAC address: System Settings → Network → WiFi → Details
3. Paste MAC address into Pi cron job

---

## Build Phases

### Phase 1 — Paper Trading Foundation
- Alpaca account setup + data feed integration
- Backtester: validate SMA crossover and ORB on 2 years of historical data
- Implement Risk Manager (non-negotiable before any orders)
- Paper trade all Tier 1 strategies

### Phase 2 — Monitoring
- Streamlit dashboard: P&L, positions, trade log
- Trade confirmations and alerts via iMessage or WhatsApp (configurable)
- PostgreSQL audit log

### Phase 3 — Strategy Expansion
- Add Tier 2 strategies (momentum, options)
- Signal combining across strategies
- Performance analytics: Sharpe, max drawdown, win rate

### Phase 4 — Live Trading
- Switch 10% of capital to live after 3 months paper validation
- Scale up only if live results track paper results within acceptable variance
- Human approval gate for orders above a configurable size threshold

---

## Project Structure (Proposed)

```
auto-trading/
├── config/
│   └── settings.yaml          # Risk params, symbol universe (no secrets — see Keychain)
├── data/
│   └── market_data.py         # Alpaca/Polygon data fetching
├── strategies/
│   ├── base.py                # Abstract strategy class
│   ├── sma_crossover.py
│   ├── orb.py
│   └── rsi_mean_reversion.py
├── risk/
│   └── risk_manager.py        # Order gating, kill-switch logic
├── execution/
│   └── alpaca_broker.py       # Order submission, position tracking
├── scheduler/
│   └── jobs.py                # APScheduler job definitions
├── backtest/
│   └── engine.py              # Historical simulation engine
├── dashboard/
│   └── app.py                 # Streamlit monitoring UI
├── alerts/
│   ├── notifier.py            # Platform-agnostic messenger interface
│   ├── imessage.py            # iMessage backend (AppleScript + chat.db polling)
│   └── whatsapp.py            # WhatsApp backend (Twilio API send + inbound polling)
├── db/
│   └── models.py              # SQLAlchemy models (trades, positions, logs)
├── pi/
│   └── cron_setup.sh          # Pi setup script + cron job for WoL
└── main.py                    # Entry point
```
