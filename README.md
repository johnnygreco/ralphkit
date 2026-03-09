<p align="center">
  <img src="assets/ralphkit.png" alt="ralphkit" width="600">
</p>

# ralphkit

Agent pipes and loops for [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

Purpose-built subcommands for common developer workflows, plus generic `pipe` and `loop` primitives for custom configs.

- **Loop** — plan-driven iteration. Creates a structured plan, then iterates one item at a time until all are complete.
- **Pipe** — linear sequence. Each step runs once, passing context forward via handoff files.

Inspired by the [ralph loop](https://ghuntley.com/loop/).

## Install

```bash
pip install ralphkit
```

With [uv](https://docs.astral.sh/uv/):

```bash
uv tool install ralphkit
```

Or run directly without installing:

```bash
uvx ralphkit build "your task here"
```

## Quick Start

```bash
# Build a feature (plan-driven loop)
ralphkit build "Add unit tests for the auth module"

# Fix a bug (diagnose → fix → verify pipeline)
ralphkit fix "Login fails when email contains a plus sign"

# Research a topic (explore → synthesize → report pipeline)
ralphkit research "How does the caching layer work?"

# Plan an implementation (analyze → design document)
ralphkit plan "Add rate limiting to the API"

# Tackle something ambitious (research → plan → build → review → fix → verify)
ralphkit big-swing "Rewrite the database layer to use async"

# Generic primitives with custom YAML configs
ralphkit pipe "refactor auth" --config pipe.yaml
ralphkit loop "add tests" --config loop.yaml
```

## Subcommands

### `build` (loop)

Plan-driven iteration: plan → build → review, repeating until all items are complete.

```bash
ralphkit build "Add unit tests for the auth module"
ralphkit build task.md --plan-only                    # generate plan only
ralphkit build task.md --plan my-tickets.json         # skip planning
ralphkit build task.md --max-iterations 5 -f          # override iterations, skip prompt
ralphkit build task.md --plan-model sonnet             # cheaper planning model
```

| Option | Description | Default |
|--------|-------------|---------|
| `TASK` | Task description (string or path to `.md` file) | required |
| `--max-iterations N` | Override max iterations | 10 |
| `--default-model MODEL` | Override default model | opus |
| `--plan PATH` | Path to pre-made tickets.json (skips planning) | — |
| `--plan-only` | Generate plan and exit | off |
| `--plan-model MODEL` | Override model for planning step | default model |
| `--state-dir DIR` | Override state directory | .ralphkit |
| `-f` / `--force` | Skip confirmation prompt | off |

### `fix` (pipe, 3 steps)

Diagnose → fix → verify pipeline for bug fixes.

```bash
ralphkit fix "Login fails when email contains a plus sign"
```

### `research` (pipe, 3 steps)

Explore → synthesize → report pipeline for codebase research.

```bash
ralphkit research "How does the caching layer work?"
```

### `plan` (pipe, 2 steps)

Analyze → design document pipeline for implementation planning.

```bash
ralphkit plan "Add rate limiting to the API"
```

### `big-swing` (pipe, 6 steps)

Research → plan → build → review → fix → verify pipeline for ambitious tasks.

```bash
ralphkit big-swing "Rewrite the database layer to use async"
```

### `pipe` and `loop` (generic primitives)

Run custom workflows from YAML config files. `--config` is required.

```bash
ralphkit pipe "refactor auth" --config pipe.yaml
ralphkit loop "add tests" --config loop.yaml
ralphkit loop task.md --config loop.yaml --max-iterations 5
```

All pipe-based subcommands (`fix`, `research`, `plan`, `big-swing`) share: `--default-model`, `--state-dir`, `--host`, `-f/--force`.

## Background Jobs (`--host`)

Any workflow command accepts `--host` to run as a background job:

```bash
# Local tmux background
ralphkit build task.md --host local

# Remote host via SSH + tmux
ralphkit build task.md --host mini
ralphkit big-swing epic.md --host mini --working-dir /path/to/project
ralphkit fix bug.md --host mini --ralph-version 0.5.0
```

| Option | Description |
|--------|-------------|
| `--host local` | Run in a local detached tmux session |
| `--host NAME` | Run on a remote SSH host (from `~/.ssh/config`) |
| `--working-dir PATH` | Working directory for the job |
| `--ralph-version VER` | Pin ralphkit version for remote execution |

`--force` is auto-injected when `--host` is provided (background jobs always skip confirmation).

### Job Management

```bash
ralphkit jobs [--host NAME]            # List active jobs
ralphkit logs JOB_ID [--host NAME]     # View job logs (-F to follow)
ralphkit cancel JOB_ID [--host NAME]   # Cancel a running job
ralphkit runs                          # List past completed runs
```

## Config

The `--config` flag is **required** for the `pipe` and `loop` generic primitives. The named subcommands (`build`, `fix`, etc.) have built-in configs. The mode is determined by your config: include a `pipe:` section for pipe mode, otherwise it runs as a loop.

### Loop config

```yaml
# All top-level keys are optional
max_iterations: 10    # default: 10
default_model: opus   # default: opus
plan_model: sonnet    # optional: cheaper model for planning step

# Overrides the built-in worker loop
loop:
  - step_name: worker
    task_prompt: "Read {state_dir}/tickets.json, find the next incomplete item, and implement it."
    system_prompt: |
      You are a WORKER in a RALPH LOOP...
      (see configs/example.yaml for the full prompt)
    model: sonnet  # optional per-step model override

# Runs once before planning starts
setup:
  - step_name: init
    task_prompt: "Initialize the project."
    system_prompt: "Set up the project scaffolding."

# Runs once after the loop exits (always, even on failure)
cleanup:
  - step_name: finalize
    task_prompt: "Clean up temporary files."
    system_prompt: "Remove scratch files and finalize output."
```

### Pipe config

```yaml
default_model: opus

# Optional config-level handoff override for all steps
# handoff_prompt: "Custom handoff instructions..."

pipe:
  - step_name: analyze
    task_prompt: "Analyze the codebase: {task}"
    system_prompt: "Perform a thorough code analysis."

  - step_name: plan
    task_prompt: "Create an implementation plan based on the analysis."
    system_prompt: "Design a step-by-step plan for the changes."

  - step_name: implement
    task_prompt: "Implement the plan from the previous step."
    system_prompt: "Write the code described in the plan."
    model: sonnet
    # Optional per-step handoff override
    handoff_prompt: |
      Read {state_dir}/handoff__plan__to__implement.md for the implementation plan.
      This is the final step — no handoff file needed. Just do the work.
```

Pipe configs cannot have `setup:`, `cleanup:`, or `loop:` sections. A config with both `pipe:` and `loop:` is a validation error.

### Step fields

Each step requires `step_name`, `task_prompt`, and `system_prompt`. Optional fields:

| Field | Description |
|-------|-------------|
| `model` | Override `default_model` for this step |
| `handoff_prompt` | Per-step handoff override (pipe only) |

### Template variables

Prompt templates use `{variable_name}` for substitution. Unrecognized variables are left as-is.

Available in all modes:

| Variable | Description |
|----------|-------------|
| `{step_name}` | Current step's name |
| `{max_iterations}` | Configured max iterations |
| `{default_model}` | Default model |
| `{model}` | Resolved model for this step |
| `{state_dir}` | State directory path (`.ralphkit/current` symlink) |

Loop only:

| Variable | Description |
|----------|-------------|
| `{iteration}` | Current iteration number (1-based) |

Pipe only:

| Variable | Description |
|----------|-------------|
| `{task}` | Task content (empty string if not provided) |
| `{step_index}` | Current step index (1-based) |
| `{total_steps}` | Total number of pipe steps |
| `{prev_step_name}` | Previous step's name (empty for first step) |
| `{next_step_name}` | Next step's name (empty for last step) |

See [`configs/example.yaml`](configs/example.yaml) and [`configs/example-pipe.yaml`](configs/example-pipe.yaml) for complete examples.

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

The planner agent reads the task and breaks it into discrete items in `tickets.json`. Each loop iteration works on exactly one item, marks it done, and appends learnings to `progress.md`. The loop completes when all items are done. The cleanup phase runs after the loop exits regardless of outcome, like a `finally` block.

### Pipe

```
┌────────┐    ┌────────┐    ┌────────┐
│ step 1 │───>│ step 2 │───>│ step 3 │──> done
└────────┘    └────────┘    └────────┘
     │             │             │
     └── handoff ──┘── handoff ──┘
```

Each step runs once. Context flows forward through named handoff files:

```
.ralphkit/runs/001/
├── task.md                              # optional task input
├── handoff__analyze__to__plan.md        # written by analyze for plan
└── handoff__plan__to__implement.md      # written by plan for implement
```

By default, each step gets position-aware handoff instructions appended to its system prompt. The first step is told to write a handoff file, middle steps read the previous handoff and write the next, and the last step only reads. Override with `handoff_prompt:` at the step or config level, or set it to an empty string to disable handoff injection.

## Remote Execution

Submit jobs to remote machines via SSH + tmux. Useful for offloading long-running tasks to a remote machine (e.g., a Mac Mini).

### Setup

1. Ensure the remote host has `tmux` and `uv` installed.
2. Set up SSH access to the remote host (key-based auth recommended). Configure connection details in `~/.ssh/config`:
   ```
   Host mini
     HostName my-mac-mini.local
     User donnie
   ```

The `--host` flag takes an SSH config name directly — no additional ralphkit config needed. Remote jobs run via `uvx ralphkit@latest`, so ralphkit doesn't need to be pre-installed on the remote host.

## Run Reports

After each run, ralphkit prints a summary and saves `report.json` to the run directory. The report includes:

- Outcome (COMPLETE, MAX_ITERATIONS, PIPE_COMPLETE, ERROR, BLOCKED)
- Plan completion stats (items completed / total)
- Wall-clock and API duration per step
- Token usage broken down by model
- Lines added/deleted (from `git diff`)
- Turn count per step

```bash
ralphkit runs                         # list previous runs with plan progress
cat .ralphkit/runs/001/report.json # inspect a specific report
```

## State Files

Each run gets its own numbered directory under `.ralphkit/runs/`. A `current` symlink points to the active run, so prompt templates can use `{state_dir}` which resolves to `.ralphkit/current`.

```
.ralphkit/
  current -> runs/003        # symlink to active run
  runs/
    001/                     # first run (preserved)
      task.md, tickets.json, progress.md, report.json, ...
    002/                     # second run (preserved)
    003/                     # active run
```

Previous runs are preserved automatically. Use `ralphkit runs` to see them.

Loop state files:

| File | Purpose |
|------|---------|
| `task.md` | The task description |
| `tickets.json` | Structured plan: goal + items with done status |
| `progress.md` | Append-only log of iteration learnings |
| `iteration.txt` | Current iteration number |
| `RALPH-BLOCKED.md` | Created if a step cannot proceed |
| `report.json` | Run report with timing and token usage |

Pipe state files:

| File | Purpose |
|------|---------|
| `task.md` | The task description (if provided) |
| `handoff__X__to__Y.md` | Handoff from step X to step Y |
| `RALPH-BLOCKED.md` | Created if a step cannot proceed |
| `report.json` | Run report with timing and token usage |

## Requirements

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude` must be on your PATH)
- Python 3.10+
- [tmux](https://github.com/tmux/tmux) (required for `--host` background jobs — both locally and on remote hosts)
- SSH access to remote hosts (for remote execution only)
