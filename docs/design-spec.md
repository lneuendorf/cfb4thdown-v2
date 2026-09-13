# Design spec — "night lights"

The look is a stadium scoreboard at night. Black field, amber bulbs, monospaced numerals, verdicts in red and green. Nothing decorative.

## Why this direction

Three things follow from it, and they're the reason the palette was chosen:

1. **Amber is the bulb.** It marks the thing you're meant to look at — the leading score, the current rank, the active nav item. One meaning per screen. The moment amber marks three different concepts it stops reading as a scoreboard and becomes decoration.
2. **Red and green are verdicts only.** They mean the model disagreed or agreed. Never use them for anything else — not for team colors, not for "new", not for status chips.
3. **Numerals are monospaced, words are not.** That contrast is most of the aesthetic. A score in proportional type immediately stops looking like a scoreboard.

---

## Tokens

Define once, in `frontend/src/styles/tokens.css`, exposed to Tailwind via `tailwind.config.ts`. No hex in components.

### Surface

| Token | Value | Use |
|---|---|---|
| `--bg-field` | `#0a0a0a` | Page background |
| `--bg-panel` | `#111111` | Cards, raised rows |
| `--bg-deep` | `#000000` | Ticker bar, sticky header |
| `--bg-inset` | `#1a1a1a` | Progress bar track, logo backing |
| `--line` | `#242424` | Default hairline |
| `--line-dashed` | `#2e2e2e` | Dashed divider inside cards |

### Bulb (amber)

| Token | Value | Use |
|---|---|---|
| `--bulb` | `#f0b429` | Live accent, leading score, rank, active nav |
| `--bulb-dim` | `#8a6a1c` | Light bank, half-lit state |
| `--bulb-dark` | `#4a3a14` | Light bank, off state |

### Text

| Token | Value | Use |
|---|---|---|
| `--text` | `#faf7ef` | Primary. Warm white, not pure white |
| `--text-muted` | `#7a7a6e` | Labels, metadata, trailing score |

`--text-muted` is warm gray, not blue-gray. Cool gray against amber looks wrong.

### Verdict

| Token | Value | Use |
|---|---|---|
| `--good` | `#4ade80` | Model agreed, WP gained, correct call |
| `--bad` | `#e5484d` | Model disagreed, WP lost |
| `--mid` | `#f0b429` | Marginal — under 5% WP swing. Same hex as bulb, different token so it can diverge later |

---

## Type

| Role | Family | Size / weight |
|---|---|---|
| Page title | sans | 32px / 500, tracking -0.5px, uppercase |
| Section title | sans | 26px / 500 |
| Card title | sans | 17px / 400 |
| Body | sans | 14px / 400, line-height 1.6 |
| Team name | sans | 15px / 400, tracking 0.5px |
| **Score** | **mono** | 32px / 400 |
| **Stat value** | **mono** | 21px / 400 |
| **WP delta** | **mono** | 16-17px / 400 |
| Eyebrow / label | mono | 11px, tracking 1.5-2px, uppercase, muted |
| Metadata line | mono | 11-12px, muted |

Sans is Inter. Mono is JetBrains Mono. Both self-hosted via `@fontsource` — no Google Fonts request on the critical path.

Two weights only: 400 and 500. Never 600 or 700.

Uppercase is for page titles, eyebrows, and labels. Never for body copy or team names.

---

## Components

### Light bank

The signature element. A row of small circles at the top of a page header, playing on the site name.

```tsx
<LightBank lit={8} total={12} />
```

- 9px circles, 7px gap
- Lit = `--bulb`, half = `--bulb-dim`, off = `--bulb-dark`
- **It encodes something.** Number of live games, or games processed this week. It is never random and never purely decorative. If there's nothing to encode on a page, leave it out.
- No animation. It's a readout, not a loading spinner.

### Ticker

Full-width bar at the very top, `--bg-deep`, 1px `--bulb` bottom border, mono 12px amber, letter-spacing 1px.

Content is scores separated by ` · ` with ` | ` between games. **Include the WP delta, not just scores** — that's the thing no other site's ticker has.

Horizontal scroll on overflow, no wrap. Auto-scrolls during live games; static otherwise.

### Team mark

```tsx
<TeamMark team={team} size={30} />
```

Fixed square, 6px radius, containing the logo from the CFBD API. Falls back to a 3-4 letter abbreviation in mono when no logo exists.

**Always a fixed-size container with `--bg-inset` behind the logo.** Several schools have mostly-white marks that disappear or blow out on black. The backing is non-negotiable.

Sizes: 30px in lists and live cards, 34px on game pages, 44px on team pages.

### Score row

Team mark, team name (flex-1), score (mono, right).

**Leading team's score is `--bulb`. Trailing team's is `--text-muted`.** Tied, both are `--text`. This is how the eye finds the state of the game in under a second, and it's why amber can't be spent elsewhere on the same card.

### Decision chip

Small bordered pill, 11-12px, 4px radius. Border and text share a color, background stays transparent.

| Meaning | Border + text |
|---|---|
| Model recommendation | `--good` if go, `--bulb` if kick, `--text-muted` if punt |
| Actual — matched model | `--good` |
| Actual — didn't match | `--bad` |
| Actual — marginal miss | `--mid` |

Pattern is always `RECOMMENDATION → ACTUAL`, with a muted mono arrow between.

### Decision card

Live and completed fourth downs. Left border 2-3px carrying the verdict color, `--bg-panel`, `border-radius: 0 8px 8px 0`.

**Never round the corners on the border side.** A left-accent card with full rounding looks broken.

Contents, in order: situation line, WP delta (right, large mono), metadata (mono muted), chip row.

### Stat strip

Grid of 2-4 metrics under a page header. `gap: 1px` with `--line` as the grid background, so the cells are separated by hairlines rather than borders.

Label is mono 10-11px muted uppercase. Value is mono 21px, colored by meaning.

### Ranked row

Rank number (mono, amber for top 3, muted below), team mark, name with a thin bar underneath, value on the right.

Bar is 5px tall, `--bg-inset` track, 3px radius, filled proportionally in the verdict color.

---

## Rules

- **No gradients, no shadows, no glow.** Borders and flat fills only. This includes "subtle" ones.
- **No transitions on color.** State changes are instant. It's a scoreboard; scoreboards don't fade.
- **The only animation permitted** is the ticker scroll during live games.
- **6px radius on controls and marks, 8px on cards.** Nothing larger. Nothing fully round except light-bank dots.
- **Sentence case for prose, uppercase for labels.** Never title case.
- **Tables scroll horizontally on mobile.** Never wrap columns, never collapse to cards — people compare rows, and a stacked card kills that.
- **Sticky first column** on any table wider than the viewport, so the team name stays visible while scrolling.
- Minimum touch target 40px.
- Minimum font size 11px.

---

## Copy

- The model **recommends**; it does not **know**. "Model said go", not "correct play was go".
- Deltas are signed and carry a unit: `−9.4%`, `+5.2%`. Use a true minus sign (−), not a hyphen.
- Round WP to one decimal. Round rates to whole percents.
- Name the metric, don't describe it. "The Punt Index", not "Win Probability Lost Per Season". A named metric gets cited.
- Never editorialize about a coach in generated copy.

---

## Checklist before a page is done

- [ ] Amber appears with exactly one meaning
- [ ] All numerals are mono, all words are sans
- [ ] Every color came from a token
- [ ] Logos sit on `--bg-inset` backing at fixed size
- [ ] Verified at 390px wide
- [ ] Tables scroll, first column sticky
- [ ] Empty state exists and says something useful
- [ ] Loading state doesn't shift layout when data arrives
- [ ] No hex literal anywhere in the diff
