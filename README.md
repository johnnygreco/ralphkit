<p align="center">
  <img src="assets/ralphkit.png" alt="ralphkit" width="600">
</p>

# ralphkit

Agent pipes and loops for [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

Run `ralph` with two modes:

- **Loop** — plan-driven iteration. Creates a structured plan, then iterates one item at a time until all are complete.
- **Pipe** — linear sequence. Each step runs once, passing context forward via handoff files.

The mode is auto-detected from your config. Just `ralph "your task"` to get started.

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
uvx --from ralphkit ralph "your task here" --config ralph.yaml
```

## Quick Start

### Loop (default)

```bash
# Run with built-in defaults (no config needed)
ralph "Add unit tests for the auth module"

# Generate plan only — review/edit before committing to a full run
ralph "Add unit tests for the auth module" --plan-only

# Skip planning — provide your own plan.json
ralph "Add unit tests for the auth module" --plan my-plan.json

# With a custom config
ralph "Refactor the database layer" --config configs/example.yaml
```

### Pipe

```bash
# Run a pipe config (task is optional)
ralph --config configs/example-pipe.yaml

# Pipe with a task input (available as {task} in prompts)
ralph "refactor auth module" --config configs/example-pipe.yaml
```

## Usage

### Foreground (default)

```
ralph [run] TASK [OPTIONS]
```

The `run` subcommand is implicit — `ralph "your task"` is equivalent to `ralph run "your task"`.

| Option | Description | Default |
|--------|-------------|---------|
| `TASK` | Task description (string or path to `.md` file) | required for loop, optional for pipe |
| `--config PATH` / `-c` | Path to YAML config file | built-in loop defaults |
| `--max-iterations N` | Override max iterations (loop only) | 10 |
| `--default-model MODEL` | Override default model | opus |
| `--plan PATH` | Path to pre-made plan.json (skips planning step) | — |
| `--plan-only` | Generate plan and exit without running the loop | off |
| `--plan-model MODEL` | Override model for the planning step | default model |
| `--state-dir DIR` | Override state directory | .ralphkit |
| `-f` / `--force` | Skip confirmation prompt | off |

```bash
# No config — uses built-in plan-driven loop
ralph "Add unit tests for the auth module"

# Task from a markdown file
ralph task.md --config ralph.yaml

# Generate plan only, review it, then run
ralph "Add auth" --plan-only -f
# ... edit .ralphkit/runs/001/plan.json ...
ralph "Add auth" --plan .ralphkit/runs/001/plan.json -f

# Use a cheaper model for planning
ralph "Add auth" --plan-model sonnet

# Override max iterations and skip confirmation
ralph "Fix the flaky CI tests" --max-iterations 5 -f

# Pipe with no task
ralph --config pipe.yaml -f

# Pipe with a task
ralph "analyze auth" --config pipe.yaml

# Combinations
ralph task.md --plan-model sonnet --max-iterations 8 --default-model sonnet -f
```

### Background Jobs

```
ralph submit TASK [OPTIONS]
```

Submit a task to run in a detached tmux session (locally or on a remote host).

| Option | Description |
|--------|-------------|
| `--host NAME` / `-H` | Run on a remote SSH host (from `~/.ssh/config`) |
| `--working-dir PATH` | Working directory for the job |
| `--attach` | Attach to the tmux session after submitting |
| `--ralph-version VER` | Pin ralphkit version for remote execution |
| `--allow-prerelease` | Allow prerelease versions for remote uvx |
| All `run` options | `--config`, `--max-iterations`, `--default-model`, `--state-dir` |

### Job Management

```bash
ralph jobs [--host NAME]            # List active jobs
ralph logs JOB_ID [--host NAME]     # View job logs (-F to follow)
ralph cancel JOB_ID [--host NAME]   # Cancel a running job
ralph attach JOB_ID [--host NAME]   # Attach to a job's tmux session
ralph runs                          # List past completed runs
```

## Config

The config file is optional. Without one, ralphkit uses a built-in loop with a single worker step driven by a plan. The mode is determined by your config: include a `pipe:` section for pipe mode, otherwise it runs as a loop.

### Loop config

```yaml
# All top-level keys are optional
max_iterations: 10    # default: 10
default_model: opus   # default: opus
plan_model: sonnet    # optional: cheaper model for planning step

# Overrides the built-in worker loop
loop:
  - step_name: worker
    task_prompt: "Read {state_dir}/plan.json, find the next incomplete item, and implement it."
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
Setup (once)         Planning          Loop (iterate)           Cleanup (once)
┌──────────┐    ┌──────────────┐    ┌───────────────────────┐    ┌──────────────┐
│ step 1   │    │ planner      │    │ Read plan.json        │    │ step 1       │
│ step 2   │    │ → plan.json  │    │ Work on next item     │    │ ...          │
│ ...      │    └──────────────┘    │ Update plan.json      │    └──────────────┘
└──────────┘                        │ All done? → COMPLETE  │
                                    │ More items? → loop    │
                                    └───────────────────────┘
```

The planner agent reads the task and breaks it into discrete items in `plan.json`. Each loop iteration works on exactly one item, marks it done, and appends learnings to `progress.md`. The loop completes when all items are done. The cleanup phase runs after the loop exits regardless of outcome, like a `finally` block.

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

Submit jobs to remote machines via SSH + tmux. Useful for offloading long-running tasks to a more remote machine (e.g., a Mac Mini).

### Setup

1. Ensure the remote host has `tmux` and `uv` installed.
2. Set up SSH access to the remote host (key-based auth recommended). Configure connection details in `~/.ssh/config`:
   ```
   Host mini
     HostName my-mac-mini.local
     User donnie
   ```

The `--host` flag takes an SSH config name directly — no additional ralphkit config needed. Remote jobs run via `uvx --from ralphkit@latest ralph`, so ralphkit doesn't need to be pre-installed on the remote host.

### Submitting Remote Jobs

```bash
# Submit to a remote host
ralph submit "Add unit tests for auth" --host mini

# Override working directory
ralph submit "Fix the build" --host mini --working-dir /path/to/project

# Pin a specific version
ralph submit "Fix the build" --host mini --ralph-version 0.5.0

# Use a prerelease version
ralph submit "Fix the build" --host mini --allow-prerelease

# Submit and immediately attach
ralph submit "Refactor database layer" --host mini --attach

# Check status
ralph jobs --host mini

# Stream logs
ralph logs rk-add-unit-tests-0307-1430-a1b2 --host mini -F

# Attach to the tmux session
ralph attach rk-add-unit-tests-0307-1430-a1b2 --host mini
```

Remote jobs persist in tmux sessions on the remote host. If your SSH connection drops, the job continues running — reconnect with `ralph attach`.

## Run Reports

After each run, ralphkit prints a summary and saves `report.json` to the run directory. The report includes:

- Outcome (COMPLETE, MAX_ITERATIONS, PIPE_COMPLETE, ERROR, BLOCKED)
- Plan completion stats (items completed / total)
- Wall-clock and API duration per step
- Token usage broken down by model
- Lines added/deleted (from `git diff`)
- Turn count per step

```bash
ralph runs                         # list previous runs with plan progress
cat .ralphkit/runs/001/report.json # inspect a specific report
```

## State Files

Each run gets its own numbered directory under `.ralphkit/runs/`. A `current` symlink points to the active run, so prompt templates can use `{state_dir}` which resolves to `.ralphkit/current`.

```
.ralphkit/
  current -> runs/003        # symlink to active run
  runs/
    001/                     # first run (preserved)
      task.md, plan.json, progress.md, report.json, ...
    002/                     # second run (preserved)
    003/                     # active run
```

Previous runs are preserved automatically. Use `ralph runs` to see them.

Loop state files:

| File | Purpose |
|------|---------|
| `task.md` | The task description |
| `plan.json` | Structured plan: goal + items with done status |
| `progress.md` | Append-only log of iteration learnings |
| `iteration.md` | Current iteration number |
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
- [tmux](https://github.com/tmux/tmux) (required for `submit` — both locally and on remote hosts)
- SSH access to remote hosts (for remote execution only)
