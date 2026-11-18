# Scouting scores

Research preview. Rank players at the same natural position by expected future league
match rating. The full score uses visible attributes, current ability, and up to 5 hidden
attributes, including Consistency. The visible-only score uses the attributes shown on the
player profile.

## Build a shortlist

1. In the web app, open `All players`, then `Scouting`, and choose a position.
2. Set maximum transfer value and weekly wage filters. These are the game's valuation and
   the player's current wage.
3. Sort by `Full` or `Visible only`. Under `Download CSV`, choose `This list as shown`
   to keep the shortlist, scores, and scouting position together.

## Export the scores

```console
fmsave export career.fm players --all --scouting-position CB -o scouting.csv
```

The export adds `scouting_position`, `scouting_score_full`, and `scouting_score_visible`.
Use `--columns` to choose which to keep. Scores are blank for players outside the selected
position or with missing inputs.

```python
import fmsave

with fmsave.open("career.fm") as save:
    scouting = fmsave.scout_players(save.players(), "CB")

scouting.write_csv("scouting.csv")
```

Use `to_pandas()` or `to_polars()` on the same table. To score a player directly, call
`fmsave.scouting_score(player, "CB", model="full")`. The 8 options are `GK`, `CB`, `FB/WB`,
`DM`, `CM`, `AM`, `WIDE`, and `ST`. For a player with several natural positions, score
each position separately.

## How the scores were tested

Each position has a weighted sum of attributes. The weights were fit to future league ratings
and checked by holding out each of 5 FM26 careers in turn. Across 2 seasons of 1 FM27 career, the
full score reached a rank correlation of 0.570 within league and position, compared with
0.504 for current ability. Center backs showed the largest gain.
