from __future__ import annotations

import re
from typing import Any


HHMM_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})")


def append_flag(flags: str, flag: str) -> str:
    values = [value.strip() for value in flags.split(",") if value.strip()]
    if flag not in values:
        values.append(flag)
    return ", ".join(values)


def extend_flags(flags: list[str], additions: list[str]) -> list[str]:
    for flag in additions:
        if flag not in flags:
            flags.append(flag)
    return flags


def minutes_from_hhmm(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def extract_hhmm(value: Any) -> str:
    text = str(value or "")
    match = HHMM_RE.search(text)
    if not match:
        return ""
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def time_in_window(value: Any, start: str, end: str) -> bool:
    label = extract_hhmm(value)
    if not label:
        return False
    time_value = minutes_from_hhmm(label)
    start_value = minutes_from_hhmm(start)
    end_value = minutes_from_hhmm(end)
    if start_value <= end_value:
        return start_value <= time_value <= end_value
    return time_value >= start_value or time_value <= end_value


def configured_time_penalty(value: Any, rules: list[dict[str, Any]]) -> tuple[float, list[str]]:
    penalty = 0.0
    labels = []
    for rule in rules:
        if time_in_window(value, str(rule["start"]), str(rule["end"])):
            penalty += float(rule.get("penalty_usd", 0))
            labels.append(str(rule.get("label", "time penalty")))
    return penalty, labels


def has_next_day_marker(value: Any) -> bool:
    return bool(re.search(r"\+\d+", str(value or "")))


def score_cash_itinerary(
    *,
    effective_usd: float | int | str | None,
    stops: int | str,
    duration_minutes: int | str,
    depart_time: str,
    arrive_time: str,
    preferences: dict[str, Any],
) -> dict[str, Any]:
    if effective_usd in (None, ""):
        return {
            "stop_penalty_usd": "",
            "duration_penalty_usd": "",
            "time_penalty_usd": "",
            "next_day_penalty_usd": "",
            "score": "",
            "flags": [],
        }

    ranking = preferences.get("ranking", {})
    time_rules = ranking.get("time_penalties", {})
    stop_penalty = float(ranking.get("stop_penalty_usd", 50))
    duration_penalty_per_hour = float(ranking.get("duration_penalty_usd_per_hour", 5))
    next_day_penalty = float(ranking.get("next_day_arrival_penalty_usd", 75))

    flags: list[str] = []
    stop_count = stops if isinstance(stops, int) else 0
    if not isinstance(stops, int):
        flags.append("missing_stops")

    duration = duration_minutes if isinstance(duration_minutes, int) else 0
    if not isinstance(duration_minutes, int):
        flags.append("missing_duration")

    depart_penalty, depart_flags = configured_time_penalty(depart_time, time_rules.get("departure", []))
    arrive_penalty, arrive_flags = configured_time_penalty(arrive_time, time_rules.get("arrival", []))
    flags = extend_flags(flags, depart_flags)
    flags = extend_flags(flags, arrive_flags)

    next_day = has_next_day_marker(arrive_time)
    if next_day:
        flags.append("next_day_arrival")

    stop_penalty_amount = stop_count * stop_penalty
    duration_penalty_amount = duration / 60 * duration_penalty_per_hour
    time_penalty_amount = depart_penalty + arrive_penalty
    next_day_penalty_amount = next_day_penalty if next_day else 0.0
    score = (
        float(effective_usd)
        + stop_penalty_amount
        + duration_penalty_amount
        + time_penalty_amount
        + next_day_penalty_amount
    )

    return {
        "stop_penalty_usd": round(stop_penalty_amount, 2),
        "duration_penalty_usd": round(duration_penalty_amount, 2),
        "time_penalty_usd": round(time_penalty_amount, 2),
        "next_day_penalty_usd": round(next_day_penalty_amount, 2),
        "score": round(score, 2),
        "flags": flags,
    }
