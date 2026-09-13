---
description: Scaffold one of the six pages from the sitemap, end to end
argument-hint: [page-slug]
---

Build the page `$1` from docs/sitemap.md.

Work in this order and stop for confirmation after step 2:

1. Read the entry for `$1` in docs/sitemap.md. Restate in three or four lines: what the page is for, what's on it, what data it needs.
2. Read docs/api-contract.md and confirm the endpoints exist. If something the page needs isn't in the contract, stop and say what's missing rather than inventing a response shape.
3. Read docs/design-spec.md. List which existing components in frontend/src/components/ you'll reuse and which are new.
4. Build the route, the page component, and any new shared components.
5. Handle loading, empty, and error states.
6. Run `npm run typecheck`.
7. Report what you built and what still needs real data.

Don't build anything not described in the sitemap entry. If the entry seems to be missing something obvious, say so instead of adding it.
