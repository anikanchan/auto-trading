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

Using a business (entity) Alpaca account instead? Set `alpaca.account_type:
business` in `config/settings.yaml` and store the keys under the business
names instead:

```bash
python -m config.secrets set alpaca-business-api-key-id
python -m config.secrets set alpaca-business-api-secret-key
```

Both sets of keys can be stored side by side — the bot loads the pair
matching the configured account type at startup.

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

### 5. Store remaining secrets

```bash
python -m config.secrets set allowed-phone-number   # your iPhone's number/email registered with iMessage
```

(`alpaca-account-id`, `polygon-api-key`, and `dashboard-basic-auth-*` are
optional/used later — see `config/secrets.SECRET_KEYS` for the full list.)

### 6. Run the bot

```bash
source venv/bin/activate
python main.py
```

This initializes the database, starts the APScheduler jobs (strategy
scans, kill-switch checks, EOD report), sends a startup iMessage, and
polls for inbound commands (STATUS, PAUSE, BUY, etc.) every 10 seconds.
Press Ctrl+C to stop (sends a shutdown alert and exits cleanly).

### 7. Dashboard

```bash
streamlit run dashboard/app.py
```

### 8. Wake-on-LAN + auto-shutdown (Mac + Raspberry Pi)

To run unattended on a schedule (Pi wakes the Mac before market open, the
bot runs during market hours, and the Mac shuts down after the EOD report):

1. On the Mac, enable **Wake for network access** (System Settings >
   General > Sharing) and note the Mac's MAC address.
2. On the Raspberry Pi, run `pi/cron_setup.sh <mac-address>` to schedule a
   daily Wake-on-LAN packet at 9:00 AM ET (Mon-Fri).
3. On the Mac, install the launchd agents to start the bot after wake and
   shut down after the EOD report:

   ```bash
   cp scripts/com.autotrading.bot.plist scripts/com.autotrading.shutdown.plist ~/Library/LaunchAgents/
   # Edit the paths inside both plists if your checkout isn't at
   # ~/Workspace/auto-trading/app
   launchctl load ~/Library/LaunchAgents/com.autotrading.bot.plist
   launchctl load ~/Library/LaunchAgents/com.autotrading.shutdown.plist
   ```

4. `scripts/shutdown.sh` requires passwordless `sudo shutdown` — add a line
   like the following via `sudo visudo`:

   ```
   <your-username> ALL=(ALL) NOPASSWD: /sbin/shutdown
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
├── commands/       # inbound message command parser + handler
├── monitoring/     # transaction ledger (audit log)
├── webhook/        # Twilio webhook receiver (AWS only)
├── db/             # SQLAlchemy models
├── pi/             # Raspberry Pi Wake-on-LAN setup script
├── scripts/        # launchd plists + shutdown script
├── main.py         # entry point
└── tests/          # unit tests
```

## Running Tests

```bash
source venv/bin/activate
pytest
```
