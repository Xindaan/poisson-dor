"""Template for your own tip rounds -- copy to `rounds_local.py` to activate.

    cp src/wm_tipps/rounds_local.example.py src/wm_tipps/rounds_local.py

If `rounds_local.py` exists, it fully replaces the neutral defaults shipped in
`scoring.py` (`classic` and `escalating`). If it does not exist, those defaults
apply. Nothing else needs changing -- every module reads the round registry
through `wm_tipps.scoring`.

`rounds_local.py` is gitignored on purpose: a round id usually identifies a
real Kicktipp group.

Field reference
---------------
id                  Round key. Used in filenames, exports and payloads.
name                Display name.
group_points        Points for group-stage tips: tendency / difference / exact.
knockout_points     Points for knockout tips, unless overridden per stage.
stage_points        Optional per-stage override, e.g. escalating late rounds.
                    Stage keys: round_of_32, round_of_16, quarter, semi,
                    third_place, final.
bonus_questions     Side bets your round offers.
bonus_points        Points per bonus question; None = unknown/not scored here.
result_scope        Free text, but two markers are parsed: if it contains
                    "penalt" or "elfmeter", knockout results are scored
                    INCLUDING the shootout tally. Otherwise the score after
                    extra time counts. This decides whether a knockout tie can
                    ever be scored as a draw.
non_tippable_stages Stages your round does not offer a tip line for
                    (e.g. frozenset({"third_place"})).
"""
from __future__ import annotations

from .round_rules import GROUP_POINTS, KNOCKOUT_POINTS, TipRound


DEFAULT_ROUND_ID = "my-main-round"
SECONDARY_ROUND_ID = "my-second-round"

TIP_ROUNDS: dict[str, TipRound] = {
    DEFAULT_ROUND_ID: TipRound(
        id=DEFAULT_ROUND_ID,
        name="My Main Round",
        group_points=GROUP_POINTS,                 # 2 / 3 / 4
        knockout_points=KNOCKOUT_POINTS,           # 3 / 4 / 6
        bonus_questions=("world_champion",),
        bonus_points={"world_champion": 10},
        result_scope="including extra time and penalties",
    ),
    SECONDARY_ROUND_ID: TipRound(
        id=SECONDARY_ROUND_ID,
        name="My Second Round",
        group_points={"tendency": 2, "difference": 3, "exact": 4},
        knockout_points={"tendency": 3, "difference": 4, "exact": 6},
        stage_points={
            "semi": {"tendency": 4, "difference": 6, "exact": 8},
            "final": {"tendency": 4, "difference": 6, "exact": 8},
        },
        bonus_questions=("world_champion",),
        bonus_points={"world_champion": 10},
        result_scope="after extra time",
        non_tippable_stages=frozenset({"third_place"}),
    ),
}
