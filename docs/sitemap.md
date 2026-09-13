# Sitemap

Six pages. Each one has a single job. If a feature doesn't clearly belong to one of these jobs, it doesn't get built yet.

---

## 1. Live scoreboard — `/`

**Job:** during a Saturday slate, show what just happened, ranked by how much it mattered.

The home page in season. Out of season it falls back to the most recent completed week with a banner saying so.

**Contents, top to bottom:**
- Ticker — live scores with WP deltas
- Light bank — lit dots = games currently live
- Title and tagline
- Stat strip — games live, fourth downs today, total WP lost, % followed model
- **Pending decision card**, if any game is sitting on a fourth down right now. Shows the recommendation *before* the coach acts. This is the most valuable moment on the whole site and it only exists for a few seconds at a time — build for it deliberately.
- Ranked feed of today's fourth downs, sorted by absolute WP impact
- Filters: all / mistakes only / by conference / top 25

**Key behavior:** polls every 20-30s while any game is live, stops polling entirely when none are. Never poll the upstream API from the browser — poll our own cached endpoint.

**Empty state:** no games today → show last week's worst call and a link to Week in Review.

---

## 2. Game page — `/game/:gameId`

**Job:** be the thing people link to after a game ends.

Single game, every fourth down, in sequence.

**Contents:**
- Final or live score with team marks
- Win probability line chart across the game, with fourth-down decisions marked as points — red ring for mistakes, green for correct
- Chronological list of decision cards, most impactful highlighted
- Game total: net WP surrendered

**Requirements:**
- Every decision needs a stable anchor (`/game/:gameId#play-:playId`) so a single call can be linked directly
- Open Graph image generated per game — the score plus the worst decision. This is what makes it shareable.

---

## 3. Week in review — `/week/:season/:week`

**Job:** give people a reason to come back on Sunday, and give you something to post.

Auto-generated from data already in the database. No manual writing required, though it should be possible to add a paragraph of commentary.

**Contents:**
- Headline number — total WP surrendered league-wide
- Worst call of the week, as a full decision card
- Best call of the week
- WP lost by conference, as a ranked bar list
- Biggest movers on The Punt Index
- Every fourth down from the week, collapsed behind a "show all"

**Requirements:**
- Generated automatically once the week's games are all final
- Permanent URL per week, browsable back through history
- Designed so a screenshot of the top section stands alone on social

---

## 4. The Punt Index — `/punt-index`

**Job:** be argued about.

Every coach ranked by win probability surrendered through conservative fourth-down decisions. This is the site's named metric — the thing that gets cited.

**Contents:**
- Explanation in one sentence, with a link to Methodology
- Toggle: WP lost / go-for-it rate when recommended
- Filters: season range, conference, all coaches vs. returning coaches
- Ranked rows with team mark, coach name, proportional bar, value
- Toggle to rank teams instead of coaches

**Requirements:**
- Deep-linkable filter state in the URL, so a specific ranking can be shared
- Clicking a coach goes to their detail page with a season-over-season trend
- Be careful with sample size. A coach with three games should not top the list. Either require a minimum or show sample size next to the value.

---

## 5. Decision simulator — `/simulator`

**Job:** turn the model from something you read about into something you play with.

Set up any situation and see what the model says.

**Inputs:** down (fixed at 4), distance, yard line, score differential, time remaining, quarter, optionally team quality.

**Outputs:**
- Recommendation, stated plainly
- Win probability for each of go / punt / field goal
- How close the call is — a marginal 1% edge should look different from a clear 15% one
- Nearest real plays: "this has come up 47 times since 2013; coaches went for it 22% of the time"

**Requirements:**
- Runs client-side off a precomputed lookup table if feasible, so it's instant and costs nothing. Falls back to an API call if the table is too large.
- Every state is URL-encodable and shareable
- Sensible defaults that produce an interesting answer immediately — never open on an empty form

---

## 6. Methodology — `/methodology`

**Job:** answer the skeptic. Give the site credibility.

**Contents:**
- How win probability is estimated
- How the four component models fit together
- What the model doesn't account for — injuries, weather, momentum, whatever. **Be honest about limitations.** This section is what earns trust.
- Data sources and update cadence
- Known issues and how to report one
- Link to the source repo

**Requirements:**
- Written for someone who's skeptical but not hostile
- Includes at least one worked example of a single decision, end to end
- Every other page links here from its metric explanations

---

## Navigation

Live · Games · Week · Punt Index · Simulator · Methodology

Out of season, "Live" is labeled "Scoreboard".

Mobile: five items is too many. Collapse Simulator and Methodology behind a menu, keep Live / Games / Week / Punt Index visible.

---

## What is deliberately not being built

Carried over from the old site but cut for now, to avoid rebuilding everything at once:

- The filter-heavy Plays explorer. The live feed and game pages cover the same ground with less friction. Reconsider once the six pages ship.
- Team and coach detail pages beyond what Punt Index links to.
- The Analysis article index. Articles live on Substack; link out.
- Light mode.
- Accounts, favorites, notifications.

---

## Build order

Moved to `docs/roadmap.md`.
