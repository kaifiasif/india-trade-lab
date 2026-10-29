# Learning from mistakes, and smart model routing

Runtime: `scripts/learning.py` (grading, lessons, stock notes, fine-tune data) and
`scripts/model_router.py` (routing). Both write to `learning.sqlite` beside
`pipeline.json`.

## What gets graded

Each evening, after the history sync and the tournament, `learning.py settle`
reads that day's pre-market report and measures every stock's session from the
stored bars (open to close, the high and the low). It also reads closed paper
trades and computes each one's R multiple and how it ended.

| Agent | Right | Wrong | Missed |
| --- | --- | --- | --- |
| Six specialists | Positive and the stock rose, or negative and it fell | The opposite | Not used |
| Selection judge (pick) | The paper trade made money, or with no trade, the stock rose | The trade lost, or the stock fell | Not used |
| Selection judge (finalist passed) | Not used | Not used | The stock ran at least 1.5% and closed at least 1% up |
| Risk scout | "Low" and the stock never fell 1.5% and was not stopped | "Low" but it fell 1.5% or was stopped | Not used |
| Setup planner | Its strategy's paper trade made money | The trade lost | Said "none" on a stock that ran |

Moves under 0.3% open to close grade nobody, and neutral or "insufficient"
views are not graded. A call is graded once; reruns do not double count.

## What the agents learn

- **Lessons:** each wrong or missed call becomes a short lesson. It quotes what
  the agent said and what then happened. That agent sees its five newest
  lessons the next morning, with its track record (accuracy over its last 40
  graded calls).
- **Stock notes:** for each stock, how it moves (average daily range, average gap,
  share of up days over the last 60 sessions) and how the desk did on it (judge
  picks right, paper trades won, average R). Every agent sees the note.
- **Weights:** once a specialist has `min_graded` graded calls, finalists are
  ranked with its vote weighted by accuracy (twice the accuracy, clamped to
  0.5–1.5). A 50% specialist keeps a weight of 1.
- **Cooldown:** a stock sits out for seven days after its last two paper trades
  were stopped out, or after the judge's last three picks of it were wrong.
- **No look-ahead:** each lesson, note and grade carries the time its outcome
  became known, and an agent sees only what was known before its prompt.

Everything here is downgrade-only. A lesson is advice, a weight changes which
stocks the judge examines, and a cooldown removes a stock. Nothing changes risk
limits or sizing, or adds a trade. Lessons and notes are marked in every prompt
as data, never instructions.

The intraday debate keeps its own decision memory (`memory.py`), as before.

## Fine-tuning

Fine-tuning is usually not needed: lessons and stock notes change behaviour the
next day at no cost. `learning.py status` and the Learning page report, per role:

- **Not needed:** the role is right at least 55% of the time over 60 or more
  graded calls.
- **Worth trying:** there are at least 300 stored answers from sessions where
  every call by that role was right, and its accuracy stays low.
- **Collecting:** neither yet.

`learning.py --config … finetune-export --role ROLE|all` writes
`<role>-train.jsonl` and `<role>-eval.jsonl` in chat format
(`{"messages": [system, user, assistant]}`). Only right answers are kept, and
the latest fifth of sessions is held out for evaluation. The files contain
prompts built from market data only, never keys. Nothing is uploaded and no
paid job is started. You can tune a hosted model, or an open model with LoRA
and serve it locally, then point a routing tier at it. The Learning page then
compares its accuracy with the base model's on the same calls.

## Smart routing

Turn it on in Setup → Research model, or set `routing` in `pipeline.json`:

```json
"routing": {
  "enabled": true,
  "tiers": [
    {"name": "free", "provider": "gemini", "model": "<model ID>",
     "requests_per_day": 200, "requests_per_minute": 10,
     "reset_timezone": "America/Los_Angeles"},
    {"name": "strong", "provider": "anthropic", "model": "<model ID>",
     "requests_per_day": 30}
  ],
  "simple": ["free", "strong"],
  "complex": ["strong", "free"],
  "escalate": true, "cache": true, "store_prompts": true,
  "max_escalations_per_day": 10
}
```

The limits shown are examples. Enter the ones your provider shows for your key,
because free-tier limits change.

**Simple and complex jobs:**

- Simple: the six specialists, the two sub-agents, the debaters and the quick
  review roles.
- Complex: the selection judge, the managers and the reflector.

**For each call, the router:**

1. Answers a repeat of the same prompt on the same day from the cache, at no
   cost.
2. Skips a tier when:
   - its requests or tokens for the day are used up, counted in its reset
     timezone;
   - its per-minute limit is reached;
   - the provider returned HTTP 429 in the last minute, or three times today;
   - its key is missing;
   - it gave three invalid answers out of the last five for this role today.
3. Calls the first remaining tier. If the answer fails the role's validation or
   the call fails, it moves to the next tier. Each move is an escalation, and
   escalations are capped per day.
4. Logs every attempt: role, tier, model, outcome, tokens and latency. The
   Learning page shows today's use against your limits.

Routing is plain code, so it costs no tokens. With routing on, the
`model_provider`, `quick_model`, `deep_model` and `model_routes` settings are
not used. The daily `max_model_calls_per_day` budget still applies, and if
every tier fails the desk falls back to the deterministic ranking.

`store_prompts` keeps successful prompts and answers for 180 days, for the
fine-tune export. They hold market data only. Turn it off to keep none.

## OpenRouter: one key, and the desk picks the models

Runtime: `scripts/openrouter.py`. In Setup → Research model, choose
**OpenRouter**, paste one key from openrouter.ai, and set a daily dollar cap (or
choose free models only). In `pipeline.json` this is:

```json
"model_provider": "openrouter",
"openrouter": {"max_usd_per_day": 0.5, "max_input_usd_per_mtok": 1.0,
               "max_output_usd_per_mtok": 4.0, "min_context": 16000}
```

With routing off, this sets up two tiers by itself:

- `free` (`auto:free`): simple jobs;
- `strong` (`auto:paid`): the judge, and only when `max_usd_per_day` is above 0.

You can also put `auto:free` or `auto:paid` in your own routing tiers.

**How models are chosen, in plain code, at no token cost:**

1. Once a day, the desk reads OpenRouter's public model list.
2. It keeps models that:
   - take and return text;
   - support strict JSON output;
   - have a context of at least `min_context`;
   - have not passed their expiry date.
3. For `auto:paid`, it also drops models priced over the caps per million
   tokens. Once the day's spend reaches `max_usd_per_day`, paid models wait
   until the next day.
4. It ranks the rest. A starting prior by model family and context is replaced
   by the desk's own record:
   - valid-answer rate, after 5 calls;
   - graded accuracy of that model's views, after 10 graded views;
   - a penalty for repeated rate limits.
5. It skips a model that has failed this role three times today.
6. It tries the top three in order.

Simple jobs alternate between the two best free models by role and day. This
spreads OpenRouter's per-model free limits and gives both a comparable record.

Requests ask for `provider.require_parameters`, so only endpoints that honour
strict JSON answer. Every call logs the model actually used and its cost, and
the Learning page shows both.

**Free-tier limits** (OpenRouter's, at the time of writing):

- 20 requests a minute;
- 50 a day, or 1,000 a day once you have bought 10 credits.

A desk day uses about 30–60 requests. **Check key** in Setup shows what is left.
