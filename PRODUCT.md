# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

React, Vite, Tailwind CSS and shadcn/21st.dev components with GSAP for motion, built to static files that are committed so the Python standard-library server can serve them without Node (user decision, 2026-10-27). The backend stays the standard-library Python observatory, loopback only.

## Users

Kaifi, the owner: an Indian retail trader and frontend engineer who runs the desk on an Oracle Cloud server and checks it from a phone and a laptop. Secondary: Indian retail traders and developers who clone the open-source repo to test an AI-assisted intraday process honestly before risking money (inferred from the README audience; not yet observed users).

## Product Purpose

A paper-trading research desk for NSE cash equity. Before the open, specialist agents and a judge pick up to ten stocks; during the session proven strategies trade a virtual book under hard loss limits; every evening a tournament re-tests the strategies at double costs. Success: the owner can set up, run and understand the desk entirely from the UI, and trusts what it shows.

## Positioning

Agents can only narrow or veto; code sizes every trade and caps every loss; a strategy trades only after earning money at double costs on the user's own history, otherwise the desk sits out. Paper only, with no real-order path.

## Operating Context

- Morning ritual (about 08:30 IST): Kite 2FA login and two human attestations (NSE surveillance lists, announcements), then the 08:40 pre-market report by email.
- Market hours 09:15 to 15:30 IST: the worker polls quotes each minute; the owner glances at picks, open paper positions and exits, often from a phone through an SSH tunnel.
- Evenings: history sync and tournament; Fridays: weekly paper track record.
- Setup once: Kite Connect app keys, stock universe from NSE EQUITY_L.csv, 180 days of history, email delivery, model provider.

## Capabilities and Constraints

- Everything must be configurable from the UI: profile, Kite keys and daily login, email, model provider, pipeline settings, stock universe, attestations, and running jobs (preflight, report, tournament, history sync).
- Secrets never in JSON config or the repository; the UI writes them but never reads them back (user requirement). Email goes over SMTP with an app password kept in the owner-only store; no Google sign-in (user decision).
- Paper only. No control may place or imply a real order.
- Served on loopback; reached remotely through an SSH tunnel.
- Undecided: whether more than one person will ever use one server.

## Brand Commitments

- Name: India Trade Lab ("trade lab" wordmark in the current UI).
- Mascots: a family of 16 original robot characters (white shell, dark visor, glowing eyes, one prop each), one per agent, in `docs/guide/mascots/`. Mascot motion must be both purposeful (reacting to real events) and expressive (user decision).
- Light purple identity from the existing UI (user preference, October 2026); both light and dark themes with a toggle (user decision).

## Evidence on Hand

- Real: the agent roles, strategies, guardrails, tournament rules and the Meet the Desk guide (`docs/guide/agents-guide.pdf`).
- Synthetic only: the bundled NSE:DEMO session and the sample pre-market report (`docs/examples/`). There is no real track record, no users, no testimonials and no performance figures; none may be invented.

## Product Principles

1. Honest by construction: show what is proven, what is not, and why the desk sits out.
2. Code decides limits; agents explain and veto. The UI must make that hierarchy visible.
3. Setup without a terminal: every step a user would type, they can do on screen.
4. Calm in market hours: the right number, at a glance, from a phone.
5. Never fabricate: empty states say what is missing and how to fix it.

## Accessibility & Inclusion

WCAG 2.2 AA contrast in both themes, full keyboard operation, visible focus, and reduced-motion support for every mascot animation.
