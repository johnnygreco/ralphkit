<p align="center">
  <img src="assets/ralphkit.png" alt="ralphkit" width="600">
</p>

# ralphkit

Agent pipes and loops for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Inspired by the [ralph loop](https://ghuntley.com/loop/).

- **Loop** — plan-driven iteration. Creates a structured plan, then iterates one item at a time until all are complete.
- **Pipe** — linear sequence. Each step runs once, passing context forward via handoff files.

## Install

```bash
pip install ralphkit
```

With [uv](https://docs.astral.sh/uv/):

```bash
uv tool install ralphkit
```

## Quick Start

Write a task file that describes what needs to be done, then run it:

```bash
ralphkit build feature.md       # plan-driven loop: plan → build → review
```

Task files should contain a well-specified description of the work: the goal, relevant context, constraints, and acceptance criteria. The built-in `build` workflow owns the process — your task file should describe the work itself, not tell ralphkit how to plan, review, or verify it.

A starter task-file template lives in [`templates/tasks/build.md`](templates/tasks/build.md). Copy it and fill in the sections.

For custom workflows, use the generic primitives with a YAML config:

```bash
ralphkit pipe task.md --config pipe.yaml
ralphkit loop task.md --config loop.yaml
```

Use `ralphkit <command> --help` to see all available options.

## How It Works

### Loop

```
   Setup             Planning                 Loop (iterate)               Cleanup
┌──────────┐    ┌─────────────────┐    ┌──────────────────────────┐    ┌──────────────┐
│ step 1   │    │ planner         │    │ Read tickets.json        │    │ step 1       │
│ step 2   │    │ → tickets.json  │    │ Work on next item        │    │ ...          │
│ ...      │    └─────────────────┘    │ Update tickets.json      │    └──────────────┘
└──────────┘                           │ All done? → COMPLETE     │
                                       │ More items? → loop       │
                                       └──────────────────────────┘
```

The planner agent reads the task and breaks it into discrete items in `tickets.json`. Each loop iteration works on exactly one item, marks it done, and appends learnings to `progress.md`. Cleanup runs after the loop exits regardless of outcome.

### Pipe

```
┌────────┐    ┌────────┐    ┌────────┐
│ step 1 │───>│ step 2 │───>│ step 3 │──> done
└────────┘    └────────┘    └────────┘
     │             │             │
     └── handoff ──┘── handoff ──┘
```

Each step runs once. Context flows forward through named handoff files (e.g., `handoff__analyze__to__plan.md`).

## Stopping Conditions

Loop mode supports several stopping conditions to control cost and duration:

| Flag | Config key | Description |
|------|-----------|-------------|
| `--max-iterations` | `max_iterations` | Maximum loop iterations (default: 10) |
| `--max-cost` | `max_cost` | Stop when estimated cost exceeds this amount (USD) |
| `--max-duration` | `max_duration_seconds` | Stop after this many seconds of wall time |
| `--completion-consensus` | `completion_consensus` | Consecutive `RALPH-COMPLETE.md` signals needed to stop (default: 2) |
| `--verify` | `verify_command` | Command to run after each iteration (e.g., `pytest tests/`) |
| `--verify-timeout` | `verify_timeout` | Timeout for verify command in seconds (default: 300) |

The loop exits when any of these conditions is met:
- All plan items are marked done in `tickets.json`
- The worker creates `RALPH-COMPLETE.md` for `completion_consensus` consecutive iterations
- `--max-iterations`, `--max-cost`, or `--max-duration` limits are reached

If `--verify` is set, the command runs after each iteration. On failure, the output is saved and fed to the next iteration's worker for correction.

## Config

The `--config` flag is required for `pipe` and `loop` primitives. The `build` subcommand has a built-in config.

### Loop config

```yaml
max_iterations: 10
default_model: opus
plan_model: sonnet    # optional: cheaper model for planning

# Stopping conditions (all optional)
max_cost: 5.00                # USD — stop when estimated cost exceeds this
max_duration_seconds: 3600    # stop after this many seconds
completion_consensus: 2       # consecutive RALPH-COMPLETE.md signals needed
verify_command: "pytest tests/"  # run after each iteration
verify_timeout: 300           # seconds before verify command times out

# Timeouts
timeout_seconds: 1800         # per-step hard timeout (default: 1800)
idle_timeout_seconds: 600     # per-step idle timeout (disabled by default)

# Error handling
cleanup_on_error: light       # full, light, or skip (default: light)

loop:
  - step_name: worker
    task_prompt: "Read {state_dir}/tickets.json, find the next incomplete item, and implement it."
    system_prompt: "You are a WORKER in a RALPH LOOP..."
```

### Pipe config

```yaml
default_model: opus

pipe:
  - step_name: analyze
    task_prompt: "Analyze the codebase: {task}"
    system_prompt: "Perform a thorough code analysis."

  - step_name: implement
    task_prompt: "Implement the plan from the analysis."
    system_prompt: "Write the code described in the plan."
    model: sonnet
```

Each step requires `step_name`, `task_prompt`, and `system_prompt`. Optional: `model` (per-step override), `handoff_prompt` (pipe only), `timeout_seconds`, `idle_timeout_seconds`. See [`configs/`](configs/) for complete examples.

## Background Jobs

Any command accepts `--host` to run as a background job via tmux:

```bash
ralphkit build task.md --host local   # local tmux session
ralphkit build task.md --host mini    # remote host (SSH config name)
ralphkit build task.md --host mini --working-dir /path/to/project
```

The `--host` flag takes an SSH config name directly — no additional config needed. Remote jobs run via `uvx`, so ralphkit doesn't need to be pre-installed on the remote host.

```bash
ralphkit jobs [--host NAME]             # list active jobs
ralphkit logs JOB_ID [--host NAME]      # view job logs (-F to follow)
ralphkit cancel JOB_ID [--host NAME]    # cancel a running job
ralphkit runs                           # list past completed runs
```

## Resuming Runs

Use `--resume-run` to resume a previous run directory:

```bash
ralphkit build task.md --resume-run .ralphkit/run-001
```

This reuses the existing state (plan, progress, task) and continues where the previous run left off. Pass `--force` to overwrite mismatched task or plan files.

## Requirements

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude` must be on your PATH)
- Python 3.10+
- [tmux](https://github.com/tmux/tmux) (for `--host` background jobs only)
