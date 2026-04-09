# Architecture

## Overview

OpenClaude is a file-based, git-friendly framework. Everything is markdown, YAML, and Python scripts. No database required for the core framework (SQLite is used only by the dashboard).

```
┌─────────────────────────────────────────────────┐
│                    User (human)                  │
│                        │                         │
│                  Claude Code CLI                 │
│                        │                         │
│   ┌────────┬───────┬───────┬────────┬────────┐  │
│   │Clawdia │ Flux  │ Atlas │  Pulse  │ Pixel  │  │
│   │  (ops) │ (fin) │ (proj)│ (comm)  │ (soc)  │  │
│   └───┬────┴───┬───┴───┬───┴────┬───┴────┬───┘  │
│       │        │       │        │        │       │
│   ┌───┴────────┴───────┴────────┴────────┴───┐   │
│   │              Skills (~80)                 │   │
│   │   fin- / social- / int- / prod- / mkt-   │   │
│   └──────────────────────────────────────────┘   │
│                        │                         │
│   ┌──────────────────────────────────────────┐   │
│   │     Integrations (APIs + MCPs)           │   │
│   │  Gmail / Calendar / Discord / Stripe     │   │
│   └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘

        ┌───────────────────────┐
        │   Scheduler (cron)    │ ─── routines.yaml
        │   ADW Runner          │ ─── 4 core + ~23 custom examples
        │   JSONL Logs          │ ─── metrics + costs
        └───────────────────────┘

        ┌───────────────────────┐
        │   Dashboard (web)     │
        │   Flask + React       │
        │   SQLite (auth only)  │
        └───────────────────────┘
```

## Components

### Agents (`.claude/agents/`)

Each agent is a markdown file with a system prompt that defines its domain, responsibilities, and behavioral rules. Agents are invoked via slash commands (`/clawdia`, `/flux`, `/atlas`, etc.) or automatically by Claude based on the user's request.

### Skills (`.claude/skills/`)

Skills are domain-specific instructions that teach Claude how to perform specific tasks. Organized by prefix:

| Prefix | Domain | Count |
|--------|--------|-------|
| `social-` | Social media | 17 |
| `int-` | Integrations | 13 |
| `fin-` | Financial | 11 |
| `prod-` | Productivity | 9 |
| `mkt-` | Marketing | 8 |
| `gog-` | Google | 6 |
| `obs-` | Obsidian | 5 |
| `discord-` | Discord | 5 |
| `pulse-` | Community | 4 |
| `sage-` | Strategy | 3 |

> **Note:** `evo-` skills (~45) are maintained in the separate [EVO-METHOD](https://github.com/EvolutionAPI/EVO-METHOD) project. They are gitignored from this repo but work normally if installed locally. The repo ships ~80 non-evo skills.

### Routines (`ADWs/routines/`)

Automated workflows that run on a schedule. Each routine is a Python script that invokes Claude Code CLI with a specific agent and skill.

Routines are split into two tiers:
- **Core** (`ADWs/routines/`) — 4 routines shipped with the repo (good_morning, end_of_day, memory_sync, weekly_review).
- **Examples** (`ADWs/routines/examples/`) — ~23 example routines tracked with the repo (community, finance, social, licensing, etc.).
- **Custom** (`ADWs/routines/custom/`) — user-created routines (gitignored). Copy from examples or create your own.

**Runner** (`ADWs/runner.py`) — The execution engine that:
- Invokes Claude Code CLI with `--output-format json`
- Captures token usage and cost
- Logs to JSONL files
- Sends Telegram notifications
- Tracks metrics per routine

**Scheduler** (`scheduler.py`) — Reads `config/routines.yaml` and runs routines at configured times using the `schedule` library.

### Memory

Two-tier persistent memory:

1. **CLAUDE.md** — Hot cache loaded at every session start. Contains key context about the user, company, active projects, and preferences.
2. **memory/** — Global memory directory with typed files (people, projects, glossary, trends). Agents read these as needed.
3. **agent-memory/** — Per-agent memory that persists between sessions.

### Dashboard (`dashboard/`)

Web UI built with:
- **Backend**: Flask + SQLAlchemy + Flask-Login + WebSocket
- **Frontend**: React + TypeScript + Tailwind + Recharts + xterm.js
- **Auth**: SQLite with roles (admin/operator/viewer), customizable permissions, audit log
- **Terminal**: Real browser-based Claude Code terminal via WebSocket PTY

### Integrations

API clients in `.claude/skills/int-*/scripts/` that connect to external services. Each integration has a SKILL.md describing usage and a Python client script.
