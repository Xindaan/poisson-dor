# Changelog

All notable changes to this project are documented here.

This repository is published as a **squashed snapshot**: `main` is a single
commit, rebuilt on every update. That keeps the public tree clean, but it means
the commit log carries no history — so this file, plus the release tags, are
where the project's evolution is visible. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/) and versioning follows
[Semantic Versioning](https://semver.org/); newest release first.

The version is recorded in `pyproject.toml` and `wm_tipps.__version__`.

**Older releases stay available as tags**, even though `main` is rebuilt:

```bash
git checkout v0.1.1
```

One consequence of the rebuild worth knowing: a tag is not an ancestor of
`main`, so range syntax like `git log v0.1.1..main` does not do anything useful
here. Compare releases by checking one out, or read this file.

## 0.1.1 — 2026-08-09

### Added

- This changelog. Because the public history is a single squashed commit, it is
  the only place where changes are visible at all.
- Release versioning. Until now the version had stood at `0.1.0` since the
  project was first scaffolded; from here on it tracks published changes.

### Fixed

- The Quickstart is now cross-platform (2026-07-27). The page-build step ended
  in a macOS-only command; it no longer does, so the getting-started sequence
  runs the same way on Linux and Windows.

## 0.1.0 — 2026-07-23 — Initial public release

The public repository was **re-created from a fresh root commit** on this date;
any earlier git history was reset. The published content is what the entries
below describe.

### Added

- **Prediction engine.** Poisson scoring rates with a Dixon-Coles low-score
  correction, blended with a modest weight of the no-vig market consensus.
- **Context modifiers.** Heat stress, altitude and travel/time-zone load are
  applied per fixture — asymmetrically, because a sea-level side loses more at
  altitude than the reverse.
- **Backtest harness.** Validation across seven completed tournaments (405
  matches), reported honestly — including the tournaments where the model
  loses to a plain odds-derived tip.
- **Expected-points tip selection.** For a configurable scoring table, the
  scoreline that maximises expected points rather than the single most likely
  result. Round rules are configurable; two generic profiles ship built in.
- **Tournament page generator.** A self-contained static dashboard — group
  tables, a playable knockout bracket, the full schedule — in one HTML file
  with no external requests.
- **Local analysis dashboard** with a light design system, an integrated
  player-impact board, watchlist and panel filters.
- **Opponent-modelling commands** — tip profiles, a variance/aggression dial,
  and a field-relative tip policy. These read the standings of your own
  prediction round; since that data is personal, the repository ships
  documented example files instead, and the commands explain what to supply.
- **Zero runtime dependencies.** Python standard library only — no install
  step, no virtualenv, no lockfile.
- **MIT license.**
