# analysis/ — exploratory scripts

Read-only companions to the pipeline. They read from `data/`, write into
`analysis/` or `exports/`, and never touch a pipeline module. Like the core,
they are **stdlib only** — no pandas, no plotly, no install step.

Several of them need `data/predictions.json`, which is generated, not tracked.
Run the pipeline first:

```bash
PYTHONPATH=src python3 -m wm_tipps.cli refresh-fixtures
PYTHONPATH=src python3 -m wm_tipps.cli build-predictions
```

Scripts that need it will tell you so instead of failing with a stack trace.

## The tournament page (`wm_journey.py`)

```bash
python3 analysis/wm_journey.py     # writes analysis/site/index.html
open analysis/site/index.html      # no server needed
```

A self-contained tournament dashboard: group tables, a knockout bracket you
play yourself, and the fixture list. Data is embedded, JavaScript is vanilla,
fonts are system fonts — one file, no external requests.

Deliberately **no predictions on this page**: no win probabilities, no model
tips, no title odds. It is the tournament, not the model.

Four tabs: **Overview** (counts, headlines, group grid), **Groups** (tables and
fixtures per group, qualification cut-off), **Road to the title** (a bracket
where a tap picks a winner and a long-press swaps a team; only the round of 32
is pre-filled from the current standings, later rounds stay open until you pick
— your picks live in localStorage, nothing is sent anywhere), and **Schedule**
(results and upcoming kick-offs in UTC).

Qualification status comes from brute-forcing the remaining group fixtures on
points — clinched / possible / eliminated — not from the model.

### Making it yours

Branding is configurable — nothing about the page identity is baked into the
markup. Either edit the constants at the top of `wm_journey.py` or set
environment variables:

```bash
WM_SITE_BRAND="Cup Run" \
WM_SITE_HEADLINE="Road to the title" \
WM_SITE_ACCENT="#007aff" \
python3 analysis/wm_journey.py
```

| Variable | Default | Effect |
|---|---|---|
| `WM_SITE_BRAND` | `Pokalkurs` | Name in the top bar and the iOS home-screen title |
| `WM_SITE_TITLE` | `<brand> · WM 2026` | Browser tab title |
| `WM_SITE_HEADLINE` | `Der Weg zum Titel` | Headline above the bracket |
| `WM_SITE_DESCRIPTION` | derived from brand | `<meta name="description">` |
| `WM_SITE_ACCENT` | `#34c759` | Accent colour (CSS `--acc`) |

The page's own strings are German — it was built for a German-speaking
audience. Translating it means editing `wm_journey.py`; there is no i18n layer,
and pretending otherwise would be more work than the strings are worth.

Publishing: see `deploy-site.sh` in this directory and `netlify.toml` in the
repository root.

## The other scripts

| Script | What it does | Needs |
|---|---|---|
| `cv_backtest.py` | Leave-one-tournament-out cross-validation over the seven backtested tournaments — checks whether a parameter is overfitted | `data/backtest_*.json` |
| `wm_form.py` | Team form as the residual between goals scored and model xG, shrunk toward zero | `predictions.json` |
| `wm_distributions.py` | Distribution of goals, assists and clean sheets across the tournament | `fixtures.json` — **see note** |
| `wm_player_ratings.py` | Player impact board — empirical-Bayes goals+assists per 90, plus a goals-prevented proxy for keepers | `predictions.json` |
| `keeper_shotstopping.py` | Goals-prevented proxy for tournament goalkeepers from shot-stopping counts | nothing (data inline) |
| `odds_check.py` | Sanity-checks freshly imported odds against the model and against plausible bookmaker margins | `predictions.json` |

`wm_player_ratings.py` writes `analysis/wm_player_board.html` and
`exports/player_watch.md`. Everything here is advisory: nothing in this
directory feeds back into the tips.

**Note on `wm_distributions.py`:** its player-level numbers are a hard-coded
snapshot taken from Wikipedia during the tournament, and the tournament has
since finished. The script notices this itself and exits with a staleness
message rather than printing numbers it knows are wrong. Refresh the embedded
table at the top of the file to use it. This is deliberate — it is the only
script here that carries pasted data instead of reading it.
