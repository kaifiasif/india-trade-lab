# Indian specialist workflow

Contents: [Roles](#roles-and-ownership), [Delegation](#delegate-by-dependency), [Handoffs](#exchange-structured-handoffs), [Recording boundary](#keep-recording-separate).

## Roles and ownership

Use `day-trader-india` as the coordinator and runtime. Delegate bounded research
to these installed role skills, or run their procedures sequentially if the
host cannot launch subagents. Do not claim independent agents ran in that case.

The optional [daily service](daily-service.md) executes the intraday dependency
graph with six separately prompted, evidence-bound model calls. Its default
provider is disabled. Native host delegation and this Python runtime are
different invocation paths; both use the same role instructions and handoff
contract. Only persisted, valid provider responses count as model reviews.

| Role skill | Responsibility | Current implementation |
| --- | --- | --- |
| `india-data` | Instrument/data provenance, session and quote quality | Read-only Kite/Upstox historical adapter and local validation; current quotes supplied separately |
| `india-news` | Exchange/company announcements and events | Guided review of dated evidence |
| `india-analyst` | Reported financials and accounting context | Guided extraction and point-in-time review |
| `india-screener` | Completed-bar or fundamental candidate checks | Core ORB scan and CSV metric filter |
| `india-disclosures` | Indian shareholding/AMC disclosures and their lags | Guided review; no US 13F or congressional-trade substitution |
| `india-budget` | Whole shares, cost reserves and exposure | Guided sizing; journal enforces configured cash/risk limits |
| `india-risk` | Pre-trade evidence and deterministic-limit review | Core journal gates; specialist can veto |
| `india-paper-broker` | Exact virtual ticket and recording handoff | Coordinator invokes offline journal only after an explicit user request |
| `india-alerts` | On-demand price/level observations | Guided snapshot review; no background watcher |
| `india-cost-tax` | Estimated charges and dated Indian tax context | Guided review; no statutory calculator or tax filing |
| `india-rebalance` | Drift and proposed portfolio changes | Guided proposals; no automatic rebalance |
| `india-reviewer` | Independent challenge of evidence and proposal | Final veto; cannot authorize real orders |

The reference project `Jakeschincariol/trader-skill` packages eleven cooperating
skills. This project adds Indian role skills and optional native agent profiles;
it does not reuse US tax, SEC or Congress logic. Source reviewed at commit
`5189e79b9a480755a3733ac9713f5353981dbe18`.

## Delegate by dependency

Choose `intraday`, `fundamental`, `portfolio` or `alerts`. Generate a plan:

```bash
python3 CORE_DIR/scripts/agent_workflow.py plan --workflow intraday \
  --symbol NSE:VERIFIED_SYMBOL --as-of ISO_TIMESTAMP_WITH_OFFSET \
  --run-id UNIQUE_RESEARCH_RUN
```

Resolve `CORE_DIR` to the installed `day-trader-india` folder. The plan lists
dependencies, not running processes. Supply the same run ID, observation time,
symbol, current proposal and trusted task instructions to each role. Independent
first-stage roles can run in parallel. Give later roles the earlier handoffs.
The coordinator obtains data and runs Python tools; restricted specialist
profiles read supplied evidence and return findings without writing or executing.

For intraday review, data and news precede screening/budget, then risk, then
an independent reviewer. Fundamental research also uses financial analysis,
disclosures and costs. Portfolio research adds rebalancing. Alerts remain an
observation workflow and cannot authorize an entry.

Freeze the proposed virtual ticket before final reviews. Include every input
that can affect the fill: event ID, symbol, side, quantity, quote/time/source,
stop, fee, exit-fee reserve, slippage and book identity. Pass that JSON file
using `plan --proposal PROJECT/proposal.json` to get `proposal_sha256`.
If any input changes, recompute the digest and rerun affected reviews.

## Exchange structured handoffs

Each role returns:

```json
{
  "schema_version": 1,
  "run_id": "SAME_RUN_ID",
  "as_of": "ISO_TIMESTAMP_WITH_OFFSET",
  "symbol": "NSE:VERIFIED_SYMBOL",
  "role": "india-risk",
  "decision": "DATA_BLOCK",
  "summary": "Missing verified current evidence",
  "proposal_sha256": "DIGEST_FROM_PLAN_WHEN_AVAILABLE",
  "evidence": [],
  "blockers": ["Obtain the missing source before continuing"]
}
```

A PASS needs nonempty evidence entries with `source`, timezone-aware
`observed_at`, and `published_at` (or null when no publication time exists).
Publication must not follow observation, and observation must not follow the
packet's time. Document disclosure lag and source-specific freshness separately;
the validator cannot establish a source's truth or completeness.

Collect reports in a packet with `schema_version: 1`, `mode: paper_research`,
`workflow`, `run_id`, `symbol`, `as_of`, the exact `proposal` object and a
`reports` array. Every required PASS must carry the matching proposal digest.
Current paper-research packets must be no more than 120 seconds old and no
more than five seconds in the future. Refresh reviews before acting on stale
packets. Use `mode: synthetic` only for labelled offline examples.

```bash
python3 CORE_DIR/scripts/agent_workflow.py review --packet PROJECT/review-packet.json
```

The validator rejects unknown/duplicate roles, missing reports, conflicting
runs, mismatched times, future evidence and changed proposals. Any BLOCK
vetoes the result; a majority cannot override it. Missing evidence produces
DATA_BLOCK. The bundled `assets/review-packet.synthetic.json` deliberately
fails these gates and can be used to demonstrate refusal.

`REVIEW_COMPLETE` means report consistency passed. The output always keeps
`paper_entry_allowed: false`: it does not send an order or write a journal.
Synthetic completion is labelled separately. Agent identities and signatures
are not authenticated by these JSON files; an owner can fabricate them.

## Keep recording separate

Show the proposal, review results, costs and remaining uncertainty. Only record
a virtual fill when the user has explicitly requested that action, and rerun
the journal's independent [pre-trade guardrails](guardrails.md). A review packet
is not the version-1 pre-trade evidence file. PASS never grants broker-tool
permission, weakens a limit or starts a live mode. Never hide a failed role,
reroll it until it agrees or substitute a fabricated report.

Native Claude profiles allow only Read/Grep/Glob. Codex profiles disable the
documented shell/app/plugin/memory/permission-request capabilities and inherit
the parent's other permissions and MCP servers. Do not expose real-order MCP
tools in the parent research session. Host restrictions and prompt rules are
not a universal security boundary. If a required capability is unavailable,
return DATA_BLOCK or continue a clearly labelled sequential review.
