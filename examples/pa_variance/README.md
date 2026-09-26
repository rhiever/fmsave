# How much does PA change between fresh FM26 saves?

Many young players have a potential-ability (PA) range in the game database instead of a
fixed PA, and FM picks a number inside that range each time you start a new game. This
script measures how much that moves. Start two or more fresh saves on the same database
and it compares every young player's PA across them. It produces two phone-friendly
PNGs and a metrics file. No save data or output is included in this example.

**Hidden-data spoilers:** the results show exact PA. Do not use them to gain an advantage
in an online career. The tool reads the saves; it does not modify them. Never upload a
save file for troubleshooting.

From the repository root, with Python 3.12 or newer:

```sh
python -m pip install 'fmsave[pandas]' matplotlib
python examples/pa_variance/analyze.py \
  --save '/absolute/path/to/first-fresh-save.fm' \
  --save '/absolute/path/to/second-fresh-save.fm'
```

For a source checkout using uv:

```sh
uv run --with matplotlib examples/pa_variance/analyze.py \
  --save '/absolute/path/to/first-fresh-save.fm' \
  --save '/absolute/path/to/second-fresh-save.fm'
```

Instead of `--save`, you can set `SAVE_PATHS` to the saves separated by `:` (`;` on
Windows). Add `--players 'Name One;Name Two'` for a second chart showing each named young
player's PA in every save. The default output is `.local/pa_variance/`. `--output` can
choose another directory underneath `.local/`, but cannot write save-derived results
outside it. Keep generated images, metrics and saves out of Git.

## Method

- **Saves:** use saves started separately, each on the same database. Two saves loaded
  from one game start share the same PA values.
- **Matching:** players are matched across saves by name, birth date and nationality.
  Player uids are not stable between separately started games, so a uid join would pair
  different people. People who share all three fields within a save are left out.
- **Population:** players aged `--max-age` or under (default 21) in the first save of
  each pair, with a positive PA in both.
- **Comparisons:** every pair of saves is compared once for the change distribution.
- **Threshold question:** "PA 150+ in one save, below 150 in another" (`--threshold`) is
  counted in both directions of every pair.

Reading the results:

- **Rises and falls balance** across all young players, so the change is a fresh draw,
  not a systematic cut.
- **Selected groups drift back.** Players chosen because they are high in one save (such
  as PA 150+) tend to be lower in another. Being high in one save partly reflects a
  favourable draw, and the next draw regresses toward the middle of the player's range.
  The same happens in reverse for players chosen because they are low.

`metrics.json` holds every number the charts use, recomputed from the supplied saves.
Nothing save-specific is hardcoded.
