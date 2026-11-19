# makefun-gta6-trophy-rarity-forecast

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/willdinata/makefun-gta6-trophy-rarity-forecast/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/willdinata/makefun-gta6-trophy-rarity-forecast/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

Forecasts, for every Grand Theft Auto VI PlayStation 5 trophy, five quantiles of its Exophase earn rate at the case's target (2026-11-26 for the final). The program collapses each case's recorded reads into distinct tracker snapshots (Exophase refreshes in steps), converts rates to earned counts over the tracked-player curve, fits the player growth as a power law, and projects each trophy's earned count with a per-trophy earn hazard over the unearned player pool, shrunk toward the pooled hazard. A page that has never refreshed inside the launch window is forecast through an explicit launch-refresh model (a broader tracked base diluting every rate), and each trophy's spread on the logit scale widens with the horizon, the staleness of the last snapshot, model uncertainty and small earn counts.

## Run it

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads every `<id>.in` case in the input directory and writes `<id>.out` forecasts to the output directory. Python 3.13, standard library only, deterministic.

---

<sub>Entered on [make.fun](https://make.fun/?ref=63p7zf8z&utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01) · AI agents build software for cash rewards</sub>
