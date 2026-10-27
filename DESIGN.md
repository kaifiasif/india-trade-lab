# India Trade Lab design system

The dashboard in `web/` follows these rules. The tokens live in
`web/src/index.css`; the components are shadcn-style wrappers around Radix
primitives in `web/src/components/ui/`. See [PRODUCT.md](PRODUCT.md) for who
it is for.

## Direction

A clean, modern trading dashboard. The page should read like a broker's
back-office tool: calm surfaces, dense where it matters (numbers, logs), and
no decoration that competes with the data. Personality comes from the mascot
family, not from the chrome.

## Colour

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `primary` | `hsl(254 52% 56%)` | `hsl(254 82% 74%)` | Actions, current step, the price line |
| `success` | `hsl(161 46% 33%)` | `hsl(158 52% 52%)` | Done, profit, buy |
| `warning` | `hsl(34 86% 40%)` | `hsl(38 92% 60%)` | Needs attention, sitting out |
| `destructive` | `hsl(352 50% 48%)` | `hsl(352 78% 68%)` | Loss, block, stop, halt |
| `muted-foreground` | `hsl(247 9% 40%)` | `hsl(248 12% 66%)` | Secondary text (AA on card) |

- Background and cards carry a faint purple tint (hue 248–254), so the two
  themes feel like one product.
- Profit and loss are never shown by colour alone: values are signed (`+₹…`,
  `-₹…`) and badges carry words.
- Badges use a 10–15% tint of their colour, never a solid fill, except `solid`
  for chosen items (picked stocks).

## Type

- **Inter Variable** for the interface and **JetBrains Mono Variable** for
  identifiers, keys, URLs and logs. Both are self-hosted, Latin subset only.
- Inter is a deliberate category choice: the detector flags it as common, but
  its tabular figures and small-size legibility suit a numbers-first
  dashboard. Every number uses the `.num` class (`tabular-nums`) so columns
  line up as values tick.
- Sizes: page titles `text-xl`–`3xl` semibold with tight tracking; card titles
  `text-base` semibold; body `text-sm`; hints `text-xs` muted.

## Layout

- A 256px sidebar on large screens; a dialog menu below `lg`.
- Content max width `7xl`, 16px gutters on phones, 24px from `sm`.
- Cards with a 0.75rem radius and a hairline shadow. Every card is `min-w-0`
  so tables scroll inside it instead of widening the page.
- Checked at 390px wide with no horizontal page scroll.

## Mascots and motion

Sixteen SVG robots (generated from `docs/guide/mascots.py` into
`web/src/mascots/data.ts`), animated with GSAP.

| Layer | Behaviour |
| --- | --- |
| Ambient | Breathing, blinking at random intervals, antenna sway |
| Mood | `idle`, `thinking` (dots, eyes scanning), `happy` (hop and sparkle), `alert` (shake), `sleep` (closed eyes, rising z's), `wave` |
| Reaction | A hop whenever the `react` value changes: a new pick, a new stage count, a fill |
| Entrance | `walk` on from the side or `pop` up, with an optional stagger delay |
| Celebration | Paper confetti on a target exit and when Setup completes |

Moods always follow recorded state (the judge sleeps when the desk sits out;
a replay stage is alert when blocked). Motion never carries information that
is not also in text. With `prefers-reduced-motion`, every mascot holds its
final pose and confetti is skipped.

## Content rules

- Plain words; sentence case; no jargon without the plain version next to it.
- Empty states say what will appear and when ("Picks appear here after the
  08:40 report"), never placeholder data.
- Errors say what happened and what to do next. Server replies are shown as
  given by the API, which never includes secrets.
- "Paper only" is visible on every page.

## Security constraints that shape the UI

- Content-Security-Policy `script-src 'self'; style-src 'self'`: no inline
  scripts, no injected `<style>` tags (hence the in-house toast), no CDNs.
- Secrets are write-only fields: the page sends a value once and afterwards
  shows only "Saved · ends 1234".
