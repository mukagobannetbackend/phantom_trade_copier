# Phantom Trade Copier — implementation plan

## Delivery scope

Deliver a runnable, local-first Flask application that presents the Phantom Trade Copier operations dashboard in **SIMULATION / DEMO mode**. The package mirrors the specified service boundaries while keeping MT5 execution behind an adapter seam. It provides durable SQLite state, seeded demo accounts/events, engine controls, risk checks, follower policies, trade/audit/alert visibility, CSV export, and a responsive dark UI.

Live trading is intentionally unavailable in this package. No broker order is submitted, no credential is collected, and all displayed execution data is explicitly simulated.

## Design

**Design movement:** industrial observability console with a restrained “night shift” feel.

**Core principles:** operational clarity over decoration; dangerous controls are deliberate; state is always labeled; dense information is grouped into readable surfaces.

**Color philosophy:** graphite and ink provide a low-glare base, violet is the product signature for active controls, mint communicates healthy/confirmed state, amber calls attention to review items, and red is reserved for stops/failures.

**Layout paradigm:** a fixed rail establishes the operator’s mental model, while the main canvas uses asymmetric metric strips and stacked monitoring surfaces instead of generic centered cards.

**Signature elements:** persistent SIMULATION/DEMO mode chips; violet “pulse rail” behind the engine state; monospaced operational metadata for IDs, timestamps, and tickets.

**Interaction philosophy:** actions should expose the next state immediately, with confirmations for emergency actions and inline feedback for all policy edits.

**Animation:** short 160–220ms transitions for panels, status changes, and modal entry; no looping motion except a subtle heartbeat dot in the connector status.

**Typography system:** system UI sans for labels and headings, with a compact monospace face for ticket IDs and telemetry.

**Brand essence:** a private execution-control room for safely validating account-to-account copying before live deployment. Personality: precise, calm, accountable.

**Brand voice:** direct and operational. Example lines: “Simulation is isolated. No broker orders are being sent.” / “Pause entries, keep the state legible.”

**Wordmark & logo:** a compact ghosted diamond mark made from two offset chevrons, suggesting a source event splitting into controlled follower routes.

**Signature brand color:** Phantom Violet `#8B7CFF`.

## Architecture

- `app.py` — Flask entry point and local-only server defaults.
- `phantom/app/__init__.py` — application factory, route registration, static/template wiring.
- `phantom/app/db.py` — SQLite schema, seed data, connection helpers, and row serialization.
- `phantom/app/services/risk.py` — deterministic volume normalization and preflight checks.
- `phantom/app/services/engine.py` — engine state transitions and deterministic demo event processing.
- `phantom/templates/index.html` — dashboard shell.
- `phantom/static/css/app.css` — responsive dark console styling.
- `phantom/static/js/app.js` — API-backed interaction layer, tables, modal, and toast feedback.
- `tests/` — unit/API tests for sizing, dedupe, controls, policy validation, and CSV export.

The MT5 integration point is represented by a connector status and simulation adapter. A future `mt5` adapter can replace the simulated event source without coupling Flask handlers to terminal calls.

## Persisted behavior

SQLite stores accounts, follower policies, source trades, copy executions, alerts, audit events, and settings. The database lives in `instance/` and is ignored by Git. On first boot, deterministic demo data is created; subsequent starts reuse the stored state.

## Safety boundaries

- Default mode is `SIMULATION` with `DEMO` dataset.
- Start is blocked while emergency stop is active.
- Pause blocks new entry copies in simulation.
- Emergency stop blocks new submissions and records an audit event; it never liquidates positions.
- Secrets are not accepted by the UI or written to logs.
- The service binds to `127.0.0.1` by default.
