# Debate, ratings and decision memory

Structured bull/bear and risk debates over one frozen paper ticket, a five-tier
rating, and a record of every rated call that is settled later on stored prices.
The shape follows multi-agent trading research; the safety model does not. A
model here can only refuse or downgrade. Code still sizes the position, sets the
stop and enforces every limit, and nothing in this file places an order.

Contents: [Flow](#flow), [Ratings](#ratings), [What a role cannot do](#what-a-role-cannot-do),
[Decision memory](#decision-memory), [Cost](#cost), [Configuration](#configuration),
[Not built](#not-built).

## Flow

```text
bull <-> bear (1-3 rounds)  ->  research manager  ->  rating
risk: aggressive / conservative / neutral (1-3)  ->  portfolio manager  ->  rating
```

Turns inside a round run at the same time and see every earlier round, so R
research and K risk rounds cost R + 1 + K + 1 sequential model steps. The debate
runs alongside the existing evidence reviews, inside the same 120-second
observation window.

Each role receives the frozen ticket, its digest, the supplied evidence, the
verified technical snapshot, stored history, the book's limits and any past
lessons already settled by this cutoff. Everything it receives is labelled
untrusted data.

## Ratings

The five-tier scale is **Buy, Overweight, Hold, Underweight, Sell**.

| Final rating | Pipeline outcome |
| --- | --- |
| Buy, Overweight | `PROCEED` — continues to the existing deterministic gates |
| Hold | `WAIT` |
| Underweight, Sell | `NO_TRADE` |
| no valid rating | `DATA_BLOCK` (recorded as `REVIEW`) |

A rating never creates an entry on its own: a `PROCEED` ticket still faces the
unanimous evidence reviews, the journal's caps and the engine's gates. A failed,
malformed or unbound reply is `REVIEW`, never a default Hold and never a retry.

## What a role cannot do

Every reply is validated before it is used. It is refused when it names another
role, changes the proposal digest, cites evidence that was not supplied, repeats
a citation, exceeds the length bound, or returns a rating outside the scale. A
Buy or Overweight with no cited evidence is refused. Quantity, entry, stop and
target are computed before the debate opens and are never read back from a model.

## Decision memory

Every rated call is logged once per symbol and session with the quote it was made
on. When that holding window has closed in `history.sqlite`, the call is settled:
raw return from the decision quote to the window's last close, alpha against
matched benchmark observations when supplied, and whether the rating's direction
held. Hold claims no direction and is never scored as a hit.

Lessons reach a later debate only when their outcome was already known at that
debate's cutoff, so a backtested or re-run decision cannot read its own future.
Settlement and scoring are deterministic; `memory.reflect` adds an optional model
sentence on top of the computed figures, and a failed reflection keeps the
computed lesson.

```bash
python3 SKILL_DIR/scripts/memory.py --db PROJECT/memory.sqlite scorecard
python3 SKILL_DIR/scripts/memory.py --db PROJECT/memory.sqlite lessons --symbol NSE:INFY
```

A scorecard describes recorded research calls, not executable returns. Fewer than
about 30 settled calls per rating is too small a sample to read.

## Cost

Per candidate: 6 evidence reviews (10 for `intraday_debate`) plus
`2R + 3K + 2` debate calls. At one round each that is 7 debate calls, so roughly
13-17 model calls per candidate. The daily budget in `max_model_calls_per_day` is
reserved before any call is made, and exhausting it blocks the candidate rather
than shrinking the review.

## Configuration

```json
{
  "debate": {"enabled": true, "research_rounds": 1, "risk_rounds": 1},
  "memory": {"enabled": true, "horizon_sessions": 1, "reflect": false},
  "model_provider": "local",
  "model": "qwen3:14b",
  "local_base_url": "http://127.0.0.1:11434/v1"
}
```

Rounds are 1-3 and the memory window 1-20 sessions. `local` sends the debate to
an OpenAI-compatible server on this computer only: the URL must resolve to
loopback, so a local model cannot silently become a remote one. Per-role routing
through `model_routes` still applies, and arguing roles default to the quick
model while judging roles default to the deep one.

## Not built

- No role can place, size or modify an order, in paper or anywhere else.
- Hit rate and alpha describe recorded calls; neither is a profitability claim.
- A short holding window is one observation, not evidence about a thesis.
- Debate quality depends entirely on the evidence supplied; thin evidence should
  produce Hold, and a model that reasons past missing evidence is a defect.
