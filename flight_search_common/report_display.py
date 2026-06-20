from __future__ import annotations

from typing import Any


def friendly_flag_notes(value: Any) -> str:
    tokens = []
    seen = set()
    for raw in str(value or "").split(","):
        token = raw.strip()
        if not token or token.lower().startswith("evidence:"):
            continue
        if ":" in token:
            key, detail = token.split(":", 1)
            label = f"{key.replace('_', ' ')}: {detail.replace('_', ' ')}"
        else:
            label = token.replace("_", " ")
        label = " ".join(label.split())
        if not label or label in seen:
            continue
        seen.add(label)
        tokens.append(label)
    return ", ".join(tokens)
