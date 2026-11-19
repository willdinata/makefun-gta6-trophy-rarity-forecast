import json
import math
import os
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import median


Z_SCORES = (-1.645, -0.674, 0.0, 0.674, 1.645)
FOUR_PLACES = Decimal("0.0001")


def parse_time(value):
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def clamp(value, low, high):
    return min(max(value, low), high)


def percent_logit(percent):
    probability = clamp(percent, 0.01, 99.99) / 100.0
    return math.log(probability / (1.0 - probability))


def inverse_logit(value):
    return 100.0 / (1.0 + math.exp(-value))


def round_half_up_4(value):
    return float(Decimal(str(value)).quantize(FOUR_PLACES, rounding=ROUND_HALF_UP))


def normalized_rates(read, trophy_count):
    rates = read.get("rates") or []
    return tuple(rates[index] if index < len(rates) else None for index in range(trophy_count))


def collect_snapshots(history, trophy_count):
    snapshots = []
    previous_pair = None

    for read in history:
        rates = normalized_rates(read, trophy_count)
        pair = (read["players_tracked"], rates)
        if pair != previous_pair:
            snapshots.append(
                {
                    "time": parse_time(read["slot"]),
                    "players": float(read["players_tracked"]),
                    "total": float(read["trophies_earned"]),
                    "rates": rates,
                }
            )
        previous_pair = pair

    if snapshots:
        origin = snapshots[0]["time"]
        for snapshot in snapshots:
            snapshot["hour"] = (snapshot["time"] - origin).total_seconds() / 3600.0

    return snapshots


def build_player_path(snapshots):
    players = [snapshot["players"] for snapshot in snapshots]
    last_players = players[-1]

    if len(set(players)) < 2:
        return lambda _hour: last_players

    xs = [math.log1p(snapshot["hour"]) for snapshot in snapshots]
    ys = [math.log(snapshot["players"]) for snapshot in snapshots]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denominator = sum((value - x_mean) ** 2 for value in xs)
    if denominator == 0.0:
        return lambda _hour: last_players

    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator
    intercept = y_mean - slope * x_mean
    slope = clamp(slope, 0.0, 1.2)

    def player_path(hour):
        return math.exp(intercept + slope * math.log1p(hour))

    return player_path


def calculate_hazards(snapshots, earned, trophy_count):
    numerators = [0.0] * trophy_count
    denominators = [0.0] * trophy_count
    pooled_numerator = 0.0
    pooled_denominator = 0.0

    for index in range(1, len(snapshots)):
        previous = snapshots[index - 1]
        current = snapshots[index]
        gap_days = (current["hour"] - previous["hour"]) / 24.0
        if gap_days <= 0.0:
            continue

        for trophy_index in range(trophy_count):
            previous_earned = earned[index - 1][trophy_index]
            current_earned = earned[index][trophy_index]
            if previous_earned is None or current_earned is None:
                continue
            delta_earned = max(current_earned - previous_earned, 0.0)
            pool_average = max(
                (
                    previous["players"]
                    - previous_earned
                    + current["players"]
                    - current_earned
                )
                / 2.0,
                0.0,
            )
            numerators[trophy_index] += delta_earned
            denominators[trophy_index] += pool_average * gap_days

        previous_pool = trophy_count * previous["players"] - previous["total"]
        current_pool = trophy_count * current["players"] - current["total"]
        pooled_numerator += max(current["total"] - previous["total"], 0.0)
        pooled_denominator += max((previous_pool + current_pool) / 2.0, 0.0) * gap_days

    pooled_hazard = pooled_numerator / pooled_denominator if pooled_denominator > 0.0 else 0.0
    return [
        (numerators[index] + 5000.0 * pooled_hazard) / (denominators[index] + 5000.0)
        if denominators[index] > 0.0
        else pooled_hazard
        for index in range(trophy_count)
    ]


def forecast_case(case):
    trophies = case["trophies"]
    trophy_count = len(trophies)
    history = case.get("history") or []
    snapshots = collect_snapshots(history, trophy_count)
    horizon_days = float(case["horizon_minutes"]) / 1440.0

    if not snapshots:
        medians = [5.0] * trophy_count
        sigmas = [1.6] * trophy_count
    else:
        origin = snapshots[0]["time"]
        checkpoint_time = parse_time(case["at"])
        target_time = parse_time(case["target"])
        checkpoint_hour = (checkpoint_time - origin).total_seconds() / 3600.0
        target_hour = (target_time - origin).total_seconds() / 3600.0
        snapshot_count = len(snapshots)
        last_snapshot = snapshots[-1]
        last_players = last_snapshot["players"]

        earned = [
            [
                None if rate is None else float(rate) * snapshot["players"] / 100.0
                for rate in snapshot["rates"]
            ]
            for snapshot in snapshots
        ]

        recent_rates = []
        for trophy_index in range(trophy_count):
            recent_rate = None
            for snapshot in reversed(snapshots):
                if snapshot["rates"][trophy_index] is not None:
                    recent_rate = float(snapshot["rates"][trophy_index])
                    break
            recent_rates.append(recent_rate)

        known_rates = [rate for rate in recent_rates if rate is not None]
        fallback_rate = float(median(known_rates)) if known_rates else 1.0
        last_rates = [rate if rate is not None else fallback_rate for rate in recent_rates]
        last_earned = [rate * last_players / 100.0 for rate in last_rates]
        universal = [value >= last_players - 0.5 for value in last_earned]

        if snapshot_count >= 2:
            player_path = build_player_path(snapshots)
            target_players = clamp(player_path(target_hour), last_players, 60.0 * last_players)
            hazards = calculate_hazards(snapshots, earned, trophy_count)
            medians = []

            for trophy_index in range(trophy_count):
                if universal[trophy_index]:
                    medians.append(99.9)
                    continue

                projected_earned = last_earned[trophy_index]
                step_start = last_snapshot["hour"]
                while step_start < target_hour:
                    step_end = min(step_start + 12.0, target_hour)
                    step_days = (step_end - step_start) / 24.0
                    midpoint = (step_start + step_end) / 2.0
                    pool = max(player_path(midpoint) - projected_earned, 0.0)
                    days_since_last = (step_start - last_snapshot["hour"]) / 24.0
                    projected_earned += (
                        hazards[trophy_index]
                        * (0.92**days_since_last)
                        * pool
                        * step_days
                    )
                    projected_earned = min(projected_earned, player_path(step_end))
                    step_start = step_end

                raw_rate = 100.0 * projected_earned / target_players
                last_logit = percent_logit(last_rates[trophy_index])
                blended_logit = (
                    0.75 * percent_logit(raw_rate) + 0.25 * last_logit
                )
                blended_logit = clamp(
                    blended_logit, last_logit - 2.75, last_logit + 2.75
                )
                medians.append(clamp(inverse_logit(blended_logit), 0.01, 99.99))
        else:
            release_time = datetime.fromisoformat(case["game"]["release_date"]).replace(
                tzinfo=timezone.utc
            )
            days_after_release = (checkpoint_time - release_time).total_seconds() / 86400.0
            launch_refresh = 0.0 <= days_after_release <= 3.0
            growth = min(1.3 + 0.35 * max(0.0, horizon_days - 0.0625), 3.0)
            refreshed_players = 5.0 * last_players
            medians = []

            for trophy_index in range(trophy_count):
                if universal[trophy_index]:
                    medians.append(99.9)
                elif launch_refresh:
                    refreshed_earned = min(
                        last_earned[trophy_index] * growth, refreshed_players
                    )
                    medians.append(100.0 * refreshed_earned / refreshed_players)
                else:
                    medians.append(last_rates[trophy_index])

        base_spread = 0.5 * math.sqrt(horizon_days)
        stale_spread = (
            0.60
            if snapshot_count == 1
            else 0.25
            if checkpoint_hour - last_snapshot["hour"] > 6.0
            else 0.0
        )
        model_spread = 0.35 / math.sqrt(snapshot_count)
        sigmas = []
        for value in last_earned:
            small_spread = 0.20 if value < 10.0 else 0.0
            sigma = math.sqrt(
                base_spread**2
                + stale_spread**2
                + model_spread**2
                + small_spread**2
            )
            sigmas.append(clamp(sigma, 0.15, 1.6))

    rows = []
    for trophy, forecast_median, sigma in zip(trophies, medians, sigmas):
        center = percent_logit(forecast_median)
        quantiles = [
            round_half_up_4(inverse_logit(center + z_score * sigma))
            for z_score in Z_SCORES
        ]
        for index in range(1, len(quantiles)):
            quantiles[index] = max(quantiles[index], quantiles[index - 1])
        rows.append({"id": trophy["id"], "q": quantiles})

    return {"trophies": rows}


def main():
    input_directory = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
    output_directory = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))
    output_directory.mkdir(parents=True, exist_ok=True)

    for input_path in sorted(input_directory.glob("*.in"), key=lambda path: path.name):
        with input_path.open("r", encoding="utf-8") as input_file:
            case = json.load(input_file)
        output = forecast_case(case)
        output_path = output_directory / f"{input_path.stem}.out"
        with output_path.open("w", encoding="utf-8", newline="\n") as output_file:
            json.dump(output, output_file, separators=(",", ":"), allow_nan=False)


if __name__ == "__main__":
    main()
