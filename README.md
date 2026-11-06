# Phantom Trade Copier

Phantom Trade Copier is a local-first, simulation-first Flask dashboard for validating the operational workflow around copying MT5 trades from a master account to follower accounts. It is an execution workflow utility, not a strategy, signal provider, profit guarantee, or risk-free trading system.

## Current delivery

This package implements the dashboard and API foundation described in the supplied specification. It includes durable SQLite persistence, seeded demo accounts, a simulated source-event processor, per-follower policy validation, sizing normalization, duplicate protection, engine controls, alerts, audit records, account/trade endpoints, and CSV export. The UI is intentionally labeled `SIMULATION` and `DEMO DATASET`; it cannot submit broker orders and it does not request MT5 passwords.

The dormant live layer is now integrated behind `phantom/app/services/mt5_connector.py` and `phantom/app/services/live_gate.py`. It contains a lazy MetaTrader5 Python adapter for master monitoring, account snapshots, market execution, and SL/TP modification, plus explicit preflight gates for demo validation, broker-rule review, risk limits, emergency-stop testing, connected terminals, and the application switch `PHANTOM_LIVE_ENABLED=1`. The adapter is not imported or initialized until it is used, and the current sandbox remains blocked because the optional package is not installed and the acknowledgements are unset.

## Run locally

```bash
cd /home/ubuntu/phantom-trade-copier
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open `http://127.0.0.1:5000`. The application binds to localhost by default. Runtime state is stored in `instance/phantom.db`, which is ignored by Git.

## Key API routes

`GET /api/v1/dashboard` aggregates the dashboard state. `GET /api/v1/status` returns engine and account status. `POST /api/v1/engine/start`, `/pause`, `/resume`, `/stop`, `/emergency-stop`, and `/reset-emergency` manage the engine state. `POST /api/v1/simulation/tick` processes one deterministic demo event with stable event IDs and persisted follower execution records. `GET /api/v1/accounts`, `POST /api/v1/accounts`, and `PATCH /api/v1/accounts/{id}` manage account metadata without secrets. `GET` and `PUT /api/v1/followers/{id}/policy` read and validate follower policies. `GET /api/v1/trades`, `/trades/{id}`, `/alerts`, and `/audit` expose operational records. `GET /api/v1/export/trades.csv` downloads a non-secret trade/copy ledger.

The live preparation endpoints are `GET /api/v1/live/preflight`, `POST /api/v1/live/acknowledgements`, `POST /api/v1/live/activate`, and `POST /api/v1/live/disable`. Activation returns `409` until every gate passes; a JSON body of `{"confirm":true}` is required even after preflight passes. Disabling always returns the application to `SIMULATION` mode.

## Safety behavior

Pause blocks new simulated entry copies. Emergency stop blocks new submissions, cancels no real orders because none can be sent, records the action, and does not liquidate existing positions. Reset returns the engine to paused state and requires a deliberate subsequent start. Follower policies reject disallowed symbols, direction mismatches, stale or disconnected followers, position caps, invalid sizing, and below-minimum normalized volume.

Before considering any real connector, validate broker and prop-firm rules, hedging/netting behavior, symbol contract metadata, terminal topology, credentials storage, authentication, CSRF protection, worker lifecycle, bounded retries, reconciliation, and a controlled demo-account end-to-end test.

## Optional Windows live dependency

The current `requirements.txt` intentionally stays platform-neutral. On the Windows MT5 host, install the optional dependency from `requirements-live.txt`, set `PHANTOM_LIVE_ENABLED=1` only after the owner has reviewed the preflight checklist, and keep the application behind local authentication and a firewall. This package does not contain or collect account passwords.

## Test

```bash
pytest -q
```

The tests cover volume normalization, sizing modes, policy validation, idempotent source event processing, engine safety transitions, and CSV export.
