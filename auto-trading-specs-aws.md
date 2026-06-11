# Automated Stock Trading App — Specs (AWS Setup)

## Overview

A minimal-intervention automated trading system supporting both **intraday** and **swing** strategies, integrated with Alpaca for execution. Runs on AWS Fargate in `us-east-1` (N. Virginia) for proximity to US market servers, with cost-saving measures to run only during market hours. Fidelity is kept for manual/long-term holdings only (no public API available).

---

## Broker Setup

| Broker | Role |
|---|---|
| **Alpaca** | Automated trading (paper → live) |
| **Fidelity** | Manual / long-term holdings only |

Alpaca provides commission-free trading, paper trading environment, and clean REST + WebSocket APIs for both equities and options.

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
                        Your iPhone
                            │ HTTPS SMS (Twilio)
                            ▼
┌──────────────────────────────────────────────────────────┐
│                  AWS (us-east-1)                         │
│                                                          │
│  Route 53 (DNS)                                          │
│  trading-bot.yourdomain.com → ALB                        │
│                                                          │
│  Application Load Balancer (HTTPS/443)                   │
│  ┌─────────────────────────────────────────────────┐     │
│  │  /dashboard  → Dashboard Fargate task           │     │
│  │  /webhook    → Dashboard Fargate task           │     │
│  │  TLS via ACM certificate (free)                 │     │
│  └───────────────┬─────────────────────────────────┘     │
│                  │                                       │
│  ┌───────────────▼───────────────────────────────┐       │
│  │  Private Subnet                               │       │
│  │                                               │       │
│  │  Fargate: Trading Bot (market hours only)     │       │
│  │  ┌─────────────┐   ┌──────────────────────┐   │       │
│  │  │ Daily Jobs  │   │ Intraday Jobs        │   │       │
│  │  └──────┬──────┘   └──────────┬───────────┘   │       │
│  │         ▼                     ▼               │       │
│  │      Strategy Engine                          │       │
│  │  SMA Crossover │ ORB │ RSI Mean Reversion     │       │
│  │                    ▼                          │       │
│  │             Risk Manager                      │       │
│  │  Max 5% position │ -2% daily kill switch      │       │
│  │                    ▼                          │       │
│  │        Twilio SMS Confirmation                │       │
│  │  Sends trade details → waits for YES/NO       │       │
│  │  Timeout: 5 min → auto-skip trade             │       │
│  │                    ▼ (YES received)           │       │
│  │           Alpaca Broker API (HTTPS)           │       │
│  │                                               │       │
│  │  Fargate: Streamlit Dashboard (always-on)     │       │
│  │  + Twilio webhook listener                    │       │
│  │                                               │       │
│  │  Amazon EFS (SQLite)                          │       │
│  │  Mounted by both Fargate tasks                │       │
│  └───────────────┬───────────────────────────────┘       │
│                  │                                       │
│  NAT Gateway ────┘  (outbound to Alpaca, Twilio)         │
│                                                          │
│  VPC Endpoints → Secrets Manager, ECR, S3, CloudWatch    │
│  (avoids NAT Gateway cost for AWS-internal traffic)      │
│                                                          │
│  EventBridge: Start bot 9:00 AM ET / Stop 4:35 PM ET     │
│  Secrets Manager: API keys, Twilio credentials           │
│  CloudWatch: Logs + crash alerts                         │
│  S3: Daily SQLite database backup                        │
└──────────────────────────────────────────────────────────┘
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
- End-of-day report job: compiles and sends daily summary via SMS at 4:25 PM ET
- Fargate task starts at 9:00 AM ET and stops at 4:35 PM ET via EventBridge — no compute cost outside market hours
- Auto-restart on crash via ECS task retry policy

### 6. Monitoring & Alerts
- Streamlit dashboard: live P&L, open positions, recent trades, strategy status
  - Runs as a separate always-on Fargate task (no strategy logic, just reads DB)
  - Accessible from any browser (Mac or iPhone) via HTTPS URL
  - Secured with HTTP basic auth over HTTPS (TLS via ACM)
- Alerts via **Twilio WhatsApp** for:
  - Trade confirmation request — bot waits for YES/NO reply before executing
  - Trade executed confirmation
  - Risk limit triggered
  - System error
- Confirmation timeout: **5 minutes** — if no reply received, trade is skipped and logged
- **End-of-day report** sent via WhatsApp at 4:25 PM ET, including:
  - Trades executed today (symbol, direction, entry/exit, P&L)
  - Net P&L for the day ($ and %)
  - Open positions carried overnight
  - Any risk limits triggered
  - Cash balance and portfolio value
- Full audit log of every signal, decision, and order

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
- Stored in the `trades` and `audit_log` tables on SQLite/EFS, backed up daily to S3

### 7. WhatsApp Command Interface
Bot listens for inbound WhatsApp messages via Twilio webhook (always-on Dashboard Fargate task handles incoming messages). Supported commands:

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
- For longer ranges, summary is sent via WhatsApp and a detailed CSV export is made available on the Streamlit dashboard for download

- Commands are **case-insensitive**
- Unrecognized messages are ignored and logged
- All commands are logged to audit trail with timestamp

---

## Security

### Messaging Encryption
- All bot communications use **Twilio WhatsApp** instead of plain SMS
- WhatsApp uses **Meta's end-to-end encryption** (Signal Protocol) — messages are encrypted on device and cannot be read by Twilio, AWS, or any third party in transit
- Trade details, confirmations, and commands are fully E2E encrypted between bot and your iPhone
- Requires WhatsApp installed on your iPhone and Twilio WhatsApp Business API approval (free sandbox available for testing)

### Phone Number Allowlist
- Twilio webhook handler checks the `From` field of every inbound WhatsApp message
- Only messages from pre-registered WhatsApp numbers are processed
- All other senders receive no response and are silently logged
- Allowed numbers stored in AWS Secrets Manager (not in code or config files)

### Twilio Webhook Signature Validation
- Every inbound Twilio request includes an `X-Twilio-Signature` header
- Webhook handler validates the signature using the Twilio Auth Token before processing any message
- Requests with invalid or missing signatures are rejected with HTTP 403
- Prevents anyone from spoofing commands by hitting the webhook URL directly

### Encryption in Transit
- All external communication uses **HTTPS/TLS**:
  - ALB terminates TLS using ACM-issued certificate (free, auto-renews)
  - Twilio → ALB → Dashboard Fargate task: HTTPS end-to-end
  - Bot → Alpaca API: HTTPS
  - Bot → Twilio WhatsApp API: HTTPS
- Dashboard accessible only over HTTPS — no plain HTTP

### Encryption at Rest
- EFS storage encrypted at rest using AWS-managed KMS key
- S3 backup bucket encrypted with SSE-S3 (server-side encryption)
- Secrets Manager encrypts all credentials at rest by default

### Credentials & Secrets Management
All sensitive values are stored in **AWS Secrets Manager** — never in code, Docker images, config files, or environment variable defaults:

| Secret | Description |
|---|---|
| `alpaca/api-key-id` | Alpaca API key ID |
| `alpaca/api-secret-key` | Alpaca API secret key |
| `alpaca/account-id` | Alpaca brokerage account ID |
| `twilio/account-sid` | Twilio Account SID |
| `twilio/auth-token` | Twilio Auth Token (used for webhook signature validation) |
| `twilio/whatsapp-number` | Twilio WhatsApp sender number |
| `app/allowed-phone-numbers` | Allowlist of WhatsApp numbers permitted to send commands |
| `dashboard/basic-auth-user` | Dashboard login username |
| `dashboard/basic-auth-password` | Dashboard login password |
| `polygon/api-key` | Polygon.io API key (market data fallback) |

**Access controls:**
- ECS task definitions reference secrets via `secrets` field — injected as environment variables at container start, never baked into the image
- IAM task execution role granted `secretsmanager:GetSecretValue` only for the specific secret ARNs needed — least privilege
- Trading Bot task role cannot access dashboard credentials; Dashboard task role cannot access Alpaca trading keys beyond what's needed for read-only display
- Secrets encrypted at rest with AWS-managed KMS key (default) or customer-managed key for additional control
- Secret rotation: Alpaca and Twilio credentials rotated manually every 90 days (no auto-rotation API available from these providers); rotation reminder set via CloudWatch scheduled alert
- `.env` files and `settings.yaml` contain **no secrets** — only non-sensitive config (risk params, symbol universe, schedules)
- `.gitignore` excludes any `.env`, `*.pem`, `*credentials*` files from version control

#### Configuration File (`config/settings.yaml`)
All non-sensitive, version-controllable settings live in `settings.yaml`, baked into the Docker image at build time:

```yaml
# Trading mode
mode: paper                      # paper | live

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
  fargate_stop_time: "16:35"

# Messaging
messaging:
  confirmation_timeout_minutes: 5

# AWS resource references (non-sensitive)
aws:
  region: us-east-1
  secrets_manager_prefix: "auto-trading/"
```

This file is safe to commit to version control — it contains no API keys, account IDs, or credentials. AWS resource ARNs and secret names are referenced by prefix only; actual values are resolved at runtime via Secrets Manager.

### Network Isolation
- Fargate tasks run in **private subnets** — no direct inbound internet access
- Only the ALB (in public subnet) accepts inbound traffic from the internet
- Security groups:
  - ALB: accepts HTTPS (443) from anywhere (Twilio needs this for webhooks)
  - Dashboard Fargate: accepts traffic from ALB only
  - Trading Bot Fargate: no inbound rules — outbound only
  - EFS: accepts NFS (2049) from Fargate tasks only
- NAT Gateway handles outbound traffic from private subnets to Alpaca and Twilio

---

## Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Language | Python 3.11+ | Best ecosystem for quant/trading |
| Broker API | Alpaca | Commission-free, paper + live, REST + WebSocket |
| Market Data | Alpaca Data / Polygon.io | Real-time + historical |
| Indicators | `pandas-ta` | Technical indicators (SMA, RSI, etc.) |
| Scheduler | APScheduler | Cron-like job scheduling within container |
| Database | SQLite on Amazon EFS | Lightweight, shared across Fargate tasks |
| Dashboard | Streamlit on Fargate | Always-on, browser accessible via HTTPS |
| Alerts | Twilio WhatsApp | E2E encrypted trade confirmations + end-of-day report |
| Containers | Docker + Amazon ECR | Image registry for Fargate |
| Orchestration | AWS ECS Fargate | Serverless containers, no EC2 to manage |
| Scheduling | Amazon EventBridge | Start/stop Fargate task on market schedule |
| Load Balancer | AWS ALB | HTTPS termination, routes dashboard + webhook |
| TLS Certificate | AWS ACM | Free, auto-renewing HTTPS certificate |
| DNS | AWS Route 53 | Stable domain for dashboard and Twilio webhook |
| Secrets | AWS Secrets Manager | API keys, Twilio credentials, allowed phone numbers |
| Monitoring | AWS CloudWatch | Container logs, crash alerts |
| Backup | S3 | Daily SQLite snapshot, encrypted at rest |

---

## AWS Infrastructure

### Fargate Tasks

| Task | Schedule | vCPU | RAM | Est. Cost |
|---|---|---|---|---|
| Trading Bot | 9:00 AM–4:35 PM ET Mon–Fri | 0.5 | 1 GB | ~$8/month |
| Streamlit Dashboard | Always on | 0.25 | 0.5 GB | ~$5/month |

### SQLite on Amazon EFS
| Parameter | Value |
|---|---|
| Storage | 5 GB (more than sufficient) |
| Encryption | AES-256 via AWS KMS |
| Access | Mounted by both Fargate tasks (bot + dashboard) |
| Persistence | Survives container restarts and daily start/stop cycle |
| Estimated cost | ~$1/month |

### Networking
| Component | Details |
|---|---|
| VPC | Single VPC, us-east-1 |
| Public subnets (x2) | ALB + NAT Gateway |
| Private subnets (x2) | Fargate tasks + EFS |
| NAT Gateway | Outbound internet for Fargate (Alpaca, Twilio) |
| VPC Endpoints | ECR, S3, Secrets Manager, CloudWatch (avoids NAT cost for AWS traffic) |
| ALB | Public-facing, HTTPS only, routes /dashboard and /webhook |

### Total Estimated Monthly Cost

| Service | Cost |
|---|---|
| Fargate — Trading Bot | ~$8 |
| Fargate — Dashboard | ~$5 |
| EFS (SQLite storage) | ~$1 |
| ALB | ~$16 |
| NAT Gateway | ~$5 |
| Route 53 | ~$1 |
| ACM Certificate | Free |
| CloudWatch logs | ~$1 |
| S3 backups | ~$0.50 |
| Secrets Manager | ~$0.50 |
| **Total** | **~$38/month** |

### Cost Saving Measures
- Trading bot Fargate task runs **only during market hours** (~7.5 hrs/day × 21 trading days) via EventBridge
- Dashboard uses minimum viable Fargate spec (0.25 vCPU / 0.5 GB RAM)
- SQLite on EFS instead of RDS — saves ~$15/month vs managed database
- VPC endpoints for ECR, S3, Secrets Manager, CloudWatch — reduces NAT Gateway data transfer costs
- CloudWatch log retention set to 30 days to limit storage costs
- Single NAT Gateway (not one per AZ) — sufficient for this workload

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

## Build Phases

### Phase 1 — Paper Trading Foundation
- Set up AWS infrastructure (VPC, subnets, NAT Gateway, ECS cluster, ECR, EFS, ALB, ACM, Route 53, EventBridge, Secrets Manager)
- Alpaca account setup + data feed integration
- Backtester: validate SMA crossover and ORB on 2 years of historical data
- Implement Risk Manager (non-negotiable before any orders)
- Deploy trading bot container to Fargate, paper trade all Tier 1 strategies

### Phase 2 — Monitoring & Alerts
- Streamlit dashboard deployed as always-on Fargate task behind ALB
- Twilio WhatsApp trade confirmations, commands, and end-of-day report
- Twilio webhook signature validation + phone number allowlist
- CloudWatch log monitoring + S3 daily SQLite database backup

### Phase 3 — Strategy Expansion
- Add Tier 2 strategies (momentum, options)
- Signal combining across strategies
- Performance analytics: Sharpe, max drawdown, win rate

### Phase 4 — Live Trading
- Switch 10% of capital to live after 3 months paper validation
- Scale up only if live results track paper results within acceptable variance
- Human approval gate (SMS YES/NO) for all orders

---

## Project Structure (Proposed)

```
auto-trading/
├── config/
│   └── settings.yaml              # Risk params, symbol universe (no secrets)
├── data/
│   └── market_data.py             # Alpaca/Polygon data fetching
├── strategies/
│   ├── base.py                    # Abstract strategy class
│   ├── sma_crossover.py
│   ├── orb.py
│   └── rsi_mean_reversion.py
├── risk/
│   └── risk_manager.py            # Order gating, kill-switch logic
├── execution/
│   └── alpaca_broker.py           # Order submission, position tracking
├── scheduler/
│   └── jobs.py                    # APScheduler job definitions
├── backtest/
│   └── engine.py                  # Historical simulation engine
├── dashboard/
│   └── app.py                     # Streamlit monitoring UI
├── alerts/
│   └── notifier.py                # Twilio SMS + reply polling
├── commands/
│   └── handler.py                 # Inbound SMS command parser + dispatcher
├── webhook/
│   └── server.py                  # Twilio webhook receiver (signature validation)
├── db/
│   └── models.py                  # SQLAlchemy models (trades, positions, logs) — SQLite backend
├── infra/
│   ├── Dockerfile.bot             # Trading bot container image
│   ├── Dockerfile.dashboard       # Streamlit dashboard container image
│   ├── docker-compose.yml         # Local development environment
│   ├── ecs-task-bot.json          # ECS task definition for trading bot
│   ├── ecs-task-dashboard.json    # ECS task definition for dashboard
│   ├── alb.tf                     # ALB + ACM + Route 53 (Terraform)
│   ├── vpc.tf                     # VPC, subnets, NAT Gateway, VPC endpoints
│   └── eventbridge-schedule.json  # Market hours start/stop schedule
└── main.py                        # Entry point
```
