<p align="center">
  <img src="assets/ralphkit.png" alt="ralphkit" width="600">
</p>

# ralphkit

Agent pipes and loops for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). 

Run `ralph` with two modes:

- **Loop** — iterative work/review cycle. Steps repeat until the reviewer says SHIP or max iterations are reached.
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
uvx ralphkit ralph "your task here" --config ralph.yaml
```

## Quick Start

### Loop (default)

```bash
# Run with built-in defaults (no config needed)
ralph "Add unit tests for the auth module"

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
| `--state-dir DIR` | Override state directory | .ralphkit |
| `-f` / `--force` | Skip confirmation prompt | off |

```bash
# No config — uses built-in worker/reviewer loop
ralph "Add unit tests for the auth module"

# Task from a markdown file
ralph task.md --config ralph.yaml

# Override max iterations and skip confirmation
ralph "Fix the flaky CI tests" --max-iterations 5 -f

# Pipe with no task
ralph --config pipe.yaml -f

# Pipe with a task
ralph "analyze auth" --config pipe.yaml
```

### Background Jobs

```
ralph submit TASK [OPTIONS]
```

Submit a task to run in a detached tmux session (locally or on a remote host).

| Option | Description |
|--------|-------------|
| `--host NAME` / `-H` | Run on a remote host (from hosts config) |
| `--working-dir PATH` | Working directory for the job |
| `--attach` | Attach to the tmux session after submitting |
| All `run` options | `--config`, `--max-iterations`, `--default-model`, `--state-dir` |

### Job Management

```bash
ralph jobs [--host NAME]            # List active jobs
ralph logs JOB_ID [--host NAME]     # View job logs (-F to follow)
ralph cancel JOB_ID [--host NAME]   # Cancel a running job
ralph attach JOB_ID [--host NAME]   # Attach to a job's tmux session
ralph runs                          # List past completed runs
ralph hosts                         # List configured remote hosts
```

## Config

The config file is optional. Without one, ralphkit uses a built-in loop with a worker and reviewer step. The mode is determined by your config: include a `pipe:` section for pipe mode, otherwise it runs as a loop.

### Loop config

```yaml
# All top-level keys are optional
max_iterations: 10    # default: 10
default_model: opus   # default: opus

# Runs once before the loop starts
setup:
  - step_name: init
    task_prompt: "Initialize the project."
    system_prompt: "Set up the project scaffolding."

# Overrides the built-in worker/reviewer loop
loop:
  - step_name: worker
    task_prompt: "Read {state_dir}/task.md and begin working. This is iteration {iteration} of {max_iterations}."
    system_prompt: "Work on the task incrementally..."
  - step_name: reviewer
    task_prompt: "Review the work done for the task in {state_dir}/task.md."
    system_prompt: "Review the code changes and write your verdict..."
    model: sonnet  # optional per-step model override

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
Setup (once)         Loop (iterate)           Cleanup (once)
┌──────────┐    ┌───────────────────────┐    ┌──────────────┐
│ step 1   │    │ step 1 (e.g. worker)  │    │ step 1       │
│ step 2   │    │ step 2 (e.g. reviewer)│    │ ...          │
│ ...      │    │ ...                   │    └──────────────┘
└──────────┘    │ SHIP? → done          │
                │ REVISE? → loop again  │
                └───────────────────────┘
```

Each iteration runs all loop steps in order, then checks `.ralphkit/current/review-result.md` for a verdict. On SHIP, the run exits successfully. On REVISE, feedback is preserved and the loop continues. The cleanup phase runs after the loop exits regardless of outcome, like a `finally` block.

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

1. Ensure the remote host has `tmux` and `ralph` (ralphkit) installed.
2. Set up SSH access to the remote host (key-based auth recommended). Configure connection details in `~/.ssh/config` as usual:
   ```
   Host mini
     HostName my-mac-mini.local
     User donnie
   ```
3. Create `~/.config/ralphkit/hosts.yaml`:

```yaml
default: mini  # optional, shown in `ralph hosts` output

hosts:
  mini:
    hostname: mini                          # SSH host (matches ~/.ssh/config)
    working_dir: /Users/donnie/project      # optional
    ralph_command: ralph                    # optional, defaults to "ralph"
    env:                                    # optional environment variables
      CLAUDE_MODEL: opus
```

The `hostname` field is passed directly to `ssh`, so it can be an SSH config alias, a hostname, or an IP address. All SSH config options (user, port, identity file, proxy, etc.) are handled by your SSH config.

### Submitting Remote Jobs

```bash
# Submit to a configured host
ralph submit "Add unit tests for auth" --host mini

# Override working directory
ralph submit "Fix the build" --host mini --working-dir /path/to/project

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

- Outcome (SHIP, REVISE, MAX_ITERATIONS, PIPE_COMPLETE, ERROR, BLOCKED)
- Wall-clock and API duration per step
- Token usage broken down by model
- Lines added/deleted (from `git diff`)
- Turn count per step

```bash
ralph runs                         # list previous runs
cat .ralphkit/runs/001/report.json # inspect a specific report
```

## State Files

Each run gets its own numbered directory under `.ralphkit/runs/`. A `current` symlink points to the active run, so prompt templates can use `{state_dir}` which resolves to `.ralphkit/current`.

```
.ralphkit/
  current -> runs/003        # symlink to active run
  runs/
    001/                     # first run (preserved)
      task.md, iteration.md, work-summary.md, report.json, ...
    002/                     # second run (preserved)
    003/                     # active run
```

Previous runs are preserved automatically. Use `ralph runs` to see them.

Loop state files:

| File | Purpose |
|------|---------|
| `task.md` | The task description |
| `iteration.md` | Current iteration number |
| `work-summary.md` | What the worker did this iteration |
| `work-complete.md` | Created when the worker thinks it's done |
| `review-result.md` | SHIP or REVISE |
| `review-feedback.md` | Feedback from the reviewer |
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
