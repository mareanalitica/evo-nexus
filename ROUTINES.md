# OpenClaude — Routines

Routines are automated workflows that run on a schedule via the ADW Runner.

## Core vs Custom

| Type | Location | Tracked | Description |
|------|----------|---------|-------------|
| **Core** | `ADWs/routines/` | Yes | Essential system routines shipped with the repo |
| **Custom** | `ADWs/routines/custom/` | No (gitignored) | User-created, workspace-specific routines |

## Core Routines

| Routine | Script | Agent | Schedule |
|---------|--------|-------|----------|
| Good Morning | `good_morning.py` | @clawdia | Daily 07:00 |
| End of Day | `end_of_day.py` | @clawdia | Daily 21:00 |
| Memory Sync | `memory_sync.py` | @clawdia | Daily 21:15 |
| Weekly Review | `weekly_review.py` | @clawdia | Friday 08:00 |

## Custom Routines

Custom routines live in `ADWs/routines/custom/` (gitignored) and are scheduled via `config/routines.yaml` (also gitignored).

To create a custom routine, say **"create a routine"** and the `create-routine` skill will guide you.

### config/routines.yaml

```yaml
daily:
  - name: "My Routine"
    script: my_routine.py
    time: "19:00"
    enabled: true

weekly:
  - name: "Weekly Report"
    script: weekly_report.py
    day: friday
    time: "09:00"
    enabled: true

monthly:
  - name: "Monthly Close"
    script: monthly_close.py
    day: 1
    time: "08:00"
    enabled: true
```

## How It Works

1. Scheduler runs embedded in the dashboard (`make dashboard-app`)
2. Core routines are hardcoded in `scheduler.py`
3. Custom routines are loaded from `config/routines.yaml`
4. Each routine invokes Claude Code CLI via the ADW Runner (`ADWs/runner.py`)
5. Runner logs to `ADWs/logs/` (JSONL + metrics)
6. Reports saved to `workspace/` folders

## Manual Execution

```bash
make morning    # Good Morning
make eod        # End of Day
make memory     # Memory Sync
make weekly     # Weekly Review
make help       # All commands
```
