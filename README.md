# Auto-Trading App

Automated stock trading bot — see `../auto-trading-specs.md` (Mac setup) and
`../auto-trading-specs-aws.md` (AWS setup) for full specs.

## Setup

### 1. Create virtual environment & install dependencies

```bash
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Get Alpaca paper trading API keys

1. Sign up at https://alpaca.markets (free)
2. Go to your Paper Trading dashboard
3. Generate an API key + secret

### 3. Store credentials in macOS Keychain

```bash
source venv/bin/activate
python -m config.secrets set alpaca-api-key-id
python -m config.secrets set alpaca-api-secret-key
```

You'll be prompted to paste each value (input is hidden). These are stored
securely in the macOS Keychain under the `auto-trading` service — never in
plaintext files.

### 4. Verify connectivity

```bash
python -m execution.alpaca_broker
```

Expected output:

```
Mode: paper
Account ID: <your-account-id>
Status: ACTIVE
Cash: $100,000.00
Portfolio value: $100,000.00
Buying power: $200,000.00
Market open: True/False
Positions: []
```

## Project Structure

```
app/
├── config/         # settings.yaml (non-sensitive config) + secrets.py (Keychain)
├── data/           # market data fetching
├── strategies/     # trading strategy implementations
├── risk/           # risk manager (position sizing, kill switches)
├── execution/      # Alpaca broker client
├── scheduler/      # APScheduler job definitions
├── backtest/       # historical simulation engine
├── dashboard/      # Streamlit monitoring UI
├── alerts/         # iMessage / WhatsApp notifications
├── commands/       # inbound message command parser
├── webhook/        # Twilio webhook receiver (AWS only)
├── db/             # SQLAlchemy models
└── tests/          # unit tests
```

## Running Tests

```bash
source venv/bin/activate
pytest
```
