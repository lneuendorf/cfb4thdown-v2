---
description: Audit the current diff against the night lights design spec
allowed-tools: Read, Grep, Glob, Bash(git diff:*), Bash(git status:*)
---

Audit the uncommitted changes against docs/design-spec.md.

Run `git diff` first. Then check every changed frontend file for:

- Hex literals or arbitrary Tailwind color values instead of tokens
- Numerals rendered in sans, or words rendered in mono
- Amber (`--bulb`) carrying more than one meaning on a single screen
- Red or green used for anything other than a model verdict
- Gradients, box-shadows, glow, or color transitions
- Fully rounded corners on left-accent cards
- Team logos without a fixed-size container and `--bg-inset` backing
- Missing empty, loading, or error states
- Font sizes below 11px
- Touch targets below 40px

Report only actual findings with file and line. If the diff is clean, say so in one line.
