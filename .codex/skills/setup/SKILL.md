---
name: setup
description: Set up this Flight_search repository after cloning, pulling, or switching machines. Use when Codex needs to configure local Seats.aero credentials, create local traveler scoring preferences, check or create the Python environment, install module requirements, or prepare Playwright without overwriting tracked project defaults.
---

# Setup

## Overview

Use this skill to make a fresh or recently pulled Flight_search checkout runnable on a contributor's machine. Keep secrets and personal scoring preferences local; do not edit tracked defaults for machine-specific setup.

## Workflow

Run the setup script from the workspace root:

```bash
python3 .codex/skills/setup/scripts/setup_repo.py
```

The script performs the setup in this order:

1. Prompt for the Seats.aero API key and write it to `seat_aero/.env`, preserving existing non-key settings and filling missing defaults from `seat_aero/.env.example`.
2. Ask whether to customize cents-per-point values. Show the current effective default for the global CPP and each configured program.
3. Ask whether to customize duration and early/late time penalties. Show the current effective defaults from `config/search_preferences.yaml` plus any local overlay.
4. Write personal preference changes to `config/search_preferences.local.yaml`; never write personal setup values into `config/search_preferences.yaml`.
5. Check Python `>=3.10` and required imports for Seats.aero, cash search, award-web, and Playwright.
6. If dependencies are missing, default to creating or updating `.venv`, installing `seat_aero/requirements.txt`, `cash/requirements.txt`, and `award_web/requirements.txt`, then running `python -m playwright install chromium`.

## Local Files

- `seat_aero/.env` stores the local Seats.aero key and is ignored by git.
- `config/search_preferences.local.yaml` stores local scoring overrides and is ignored by git.
- `.venv/` stores the local Python environment and is ignored by git.

## Notes

- Use `--skip-dependencies` for a no-network setup pass that only writes local env and preference files.
- Use `--repo-root <path>` only when testing the setup script against a temporary checkout.
- If no Python `>=3.10` executable is available, stop after local file setup and tell the user to install Python before dependency setup.
