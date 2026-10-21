# Indian connections and paper execution

Contents: [Testing modes](#three-different-tests), [Upstox](#upstox), [Zerodha](#zerodha), [Dhan](#dhan), [OpenAlgo](#optional-openalgo-route), [Future live work](#live-execution-is-a-separate-future-project).

Reviewed 21 October 2026. Recheck official documentation at setup time.

## Three different tests

1. Backtest/replay: historical or synthetic data. Useful for debugging and
   out-of-sample evaluation; not a forward paper record.
2. Broker sandbox: validates credentials, schemas, order lifecycle and errors.
   Fill behaviour and available endpoints can be limited or artificial.
3. Forward paper practice: current authorized market observations, simulated
   fills, virtual cash, charges and a journal. It still cannot reproduce real
   liquidity, exchange matching or the psychology of risking money.

## Upstox

- Official account MCP: https://upstox.com/developer/api-documentation/mcp-integration/
- Hosted endpoint: `https://mcp.upstox.com/mcp`. Upstox describes this as read-only;
  it does not place trades. Authenticate on Upstox, never in chat.
- API docs: https://upstox.com/developer/api-documentation/open-api
- OAuth: https://upstox.com/developer/api-documentation/authentication/
- Sandbox: https://upstox.com/developer/api-documentation/sandbox/
- Official Python SDK: https://github.com/upstox/upstox-python

For integration tests, log into the Developer Apps portal, create a **Sandbox
App**, and generate its sandbox token. Docs currently state 30-day validity
and sandbox-only use. Use only documented sandbox-enabled endpoints. Currently
the list focuses on place/modify/cancel orders; do not assume a realistic
virtual portfolio or market matching engine. No token has been created here.

For forward paper practice, authorize historical/live data separately; map
Upstox instrument keys into normalized exchange-qualified symbols. Feed the
manual journal or implement an isolated paper adapter. MCP connection alone
does not port the upstream strategy or supply every data entitlement.

## Zerodha

- Connect API: https://kite.trade/docs/connect/v3/
- Sandbox: https://kite.trade/docs/connect/v3/sandbox/
- Official Python SDK: https://github.com/zerodha/pykiteconnect
- Official MCP implementation: https://github.com/zerodha/kite-mcp-server
- Pricing: https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/what-are-the-charges-for-kite-apis
- Static IP: https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/static-ip

Current official API documentation describes `https://sandbox.kite.trade`, demo
credentials, limit-only API orders and sandbox-specific SDK routing. Historical
data availability can vary. Older official support/forum messages say no sandbox;
use the current dedicated documentation and verify access rather than assuming
old answers or promising equivalent exchange fills. Never send demo credentials
to the production API. This installation has not contacted the sandbox.

Current data plan lists ₹500/month per app for live WebSocket and historical
candles. The free Personal plan excludes that data. Check eligibility, taxes,
promotions and current terms before paying. Treat hosted/self-hosted MCP tools
individually: the hosted server excludes many destructive tools, while a local
build can expose order APIs. Inspect GTT tools too; do not equate the name MCP
with a guarantee that all available actions are read-only.

## Dhan

- API docs: https://dhanhq.co/docs/v2/
- API products/pricing: https://dhanhq.co/
- Official Python SDK: https://github.com/dhan-oss/DhanHQ-py
- Sandbox limitation: https://dhan.co/support/platforms/dhanhq-api/can-i-use-dhanhq-sandbox-for-paper-trading-with-virtual-money-and-live-market-data/

Dhan explicitly says its sandbox is **not** live-market paper trading with
virtual funds. Use it to validate API workflows, not measure strategy returns.
Use entitled broker data plus a separate paper execution/journal layer for
forward practice. Do not open a new account solely on a third-party claim that
the sandbox gives realistic paper fills.

## Optional OpenAlgo route

- Project: https://github.com/marketcalls/openalgo
- Current guide: https://github.com/marketcalls/openalgo/blob/main/docs/userguide/15-analyzer-mode/README.md
- Analyzer status: https://docs.openalgo.in/api-documentation/v1/accounts-api/analyzer-status
- General docs: https://docs.openalgo.in/

OpenAlgo Analyzer routes supported trading/account operations to a local sandbox;
market prices still come from the active broker data services. Entitlements may
therefore be required. It is not an exchange emulator or a backtesting engine.
Connection and adapter work are still required; it is not installed here.

Suggested connection sequence:

1. Install a reviewed/pinned OpenAlgo release on a user-controlled machine.
2. Authenticate the existing supported broker through its official flow.
3. Verify the instrument master, data plan and source timestamps.
4. Enable Analyzer Mode in the UI and confirm the status response says
   `data.analyze_mode: true`; the mode is application-wide, not per API key.
5. Use a dedicated paper instance. Restrict execution server-side so a UI mode
   toggle cannot silently turn a paper integration into a live integration.
6. Implement and test the India adapter: quote normalization, simulated order
   submission, response validation, duplicate IDs, rejects, positions and P&L.
7. Confirm a virtual order appears in sandbox records and no broker order exists.
8. Freeze the strategy and begin a separate forward paper record.

Never pass Alpaca JSON directly to OpenAlgo or another Indian broker. Do not
assume bracket/OCO order support or atomically protected exits across providers.

## Live execution is a separate future project

Nothing here authorizes real-money trading. When explicitly requested later,
verify the broker's current retail algo onboarding, API/IP rules and order types,
then implement deterministic risk checks, idempotency, reconciliation, stale-data
blocking and a kill switch outside the language model. Zerodha currently states
static-IP requirements for API order placement from 1 April 2026; its WebSocket
and read-only APIs can continue from any IP. Do not apply order-placement rules
to an offline journal or claim this cloud chat supplies a compliant execution IP.
