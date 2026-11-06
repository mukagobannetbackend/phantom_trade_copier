# Phantom Trade Copier — TODO

## Delivered outcomes

- [x] **Local-first demo dashboard:** The application starts locally and serves a responsive dark dashboard with persistent `SIMULATION` and `DEMO` badges; live execution is not exposed.
- [x] **Account onboarding and status:** The UI shows one masked master and two follower demo accounts with role, enabled state, connector state, heartbeat, terminal readiness, balance/equity, margin, floating P/L, and active positions.
- [x] **Follower policy editing:** Each follower exposes sizing mode, multiplier/fixed lot, max lot, max risk, symbol allowlist, direction filter, SL/TP sync, pending-order copy, and copy toggle; values are validated and persisted.
- [x] **Engine controls:** Start, pause, resume, stop, follower disable, emergency stop, and emergency reset are available with visible resulting state and audit records.
- [x] **Risk and duplicate protection:** Simulation events use stable event IDs, are processed once, normalize volumes down to a valid step, and apply follower max lot, max risk, max open positions, allowed-symbol, and direction checks.
- [x] **Trade lifecycle visibility:** The dashboard shows source tickets, follower tickets, symbol, side, requested/filled volume, requested/filled price, slippage, status, timestamps, and failure/rejection reasons.
- [x] **Alerts and audit:** Disconnections, risk blocks, sync failures, emergency actions, and operator actions appear in dedicated panels and durable audit history.
- [x] **Recovery/export seam:** SQLite persists settings, policies, trades, executions, and mappings; CSV export is available for non-secret trade records; restart reuses the database without replaying old IDs.
- [x] **Validation coverage:** Tests cover sizing, policy validation, idempotent simulation events, engine state transitions, and CSV export.
- [x] **Dormant live execution layer:** The package includes a lazy MetaTrader5 adapter for master monitoring, account snapshots, market execution, and SL/TP modification, plus persisted preflight acknowledgements and activation/disable endpoints. Live mode remains locked by default.

## Intentionally gated / future work

- [ ] Implement and validate a real MT5 connector on a Windows host with demo terminals.
- [ ] Add local authentication/unlock and OS-protected secret storage before any remote access.
- [ ] Add broker-specific contract metadata, pending order lifecycle, hedging/netting reconciliation, and production worker process.
- [ ] Complete demo-account end-to-end validation before considering any live-mode review.
