<p align="center">
  <img src="assets/ralphkit.png" alt="ralphkit" width="600">
</p>

# ralphkit

Agent pipes and loops for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Two modes:

- **Loop** — iterative work/review cycle. Steps repeat until the reviewer says **SHIP** or max iterations are reached.
- **Pipe** — linear sequence. Each step runs once, output flows forward via handoff files, and execution stops at the end.

No subcommands — the mode is auto-detected from your config.

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
ralph "Create a Python function in prime.py that checks if a number is prime. Include unit tests."

# With a custom config
ralph "Build a REST API" --config configs/example.yaml
```

### Pipe

```bash
# Run a pipe config (task is optional for pipe)
ralph --config configs/example-pipe.yaml

# Pipe with a task input (available as {task} in prompts)
ralph "refactor auth module" --config configs/example-pipe.yaml
```

## Usage

```
ralph [TASK] [OPTIONS]
```

**Arguments:**

| Argument | Description | Default |
|----------|-------------|---------|
| `TASK` | Task description (string or path to `.md` file) | required for loop, optional for pipe |
| `--config PATH` | Path to YAML config file | built-in loop defaults |
| `--max-iterations N` | Override max iterations (loop only) | 10 |
| `--default-model MODEL` | Override default model from config | opus |
| `--state-dir DIR` | Override state directory | .ralphkit |
| `-f` / `--force` | Skip confirmation prompt | off |
| `--list-runs` | List previous runs and exit | off |

**Examples:**

```bash
# No config — uses built-in worker/reviewer loop
ralph "Build a REST API"

# With a custom loop config
ralph "Build a REST API" --config ralph.yaml

# Task from a markdown file
ralph task.md --config ralph.yaml

# Override max iterations
ralph "Build a REST API" --max-iterations 5

# Skip confirmation
ralph "Build a REST API" -f

# Pipe with no task
ralph --config pipe.yaml -f

# Pipe with a task
ralph "analyze auth" --config pipe.yaml
```

## Config

The config file is optional. Without one, ralphkit uses a built-in default loop with a worker and reviewer step. The config determines the mode: a `pipe:` section means pipe mode, otherwise it's loop mode.

### Loop config

```yaml
# All top-level keys are optional
max_iterations: 10    # default: 10
default_model: opus   # default: opus

# Optional: runs once before the loop
setup:
  - step_name: init
    task_prompt: "Initialize the project."
    system_prompt: "You are a setup agent."

# Optional: overrides the built-in worker/reviewer loop
loop:
  - step_name: worker
    task_prompt: "Read {state_dir}/task.md and begin working. This is iteration {iteration} of {max_iterations}."
    system_prompt: "You are a worker in a RALPH LOOP..."
  - step_name: reviewer
    task_prompt: "Review the work done for the task in {state_dir}/task.md."
    system_prompt: "You are a code reviewer in a RALPH LOOP..."
    model: sonnet  # optional: override default_model for this step

# Optional: runs once after the loop (always, even on failure)
cleanup:
  - step_name: finalize
    task_prompt: "Clean up temporary files."
    system_prompt: "You are a cleanup agent."
```

### Pipe config

```yaml
default_model: opus

# Optional: override default handoff instructions for all steps
# handoff_prompt: "Custom handoff instructions..."

pipe:
  - step_name: analyze
    task_prompt: "Analyze the codebase: {task}"
    system_prompt: "You are an expert code analyst."

  - step_name: plan
    task_prompt: "Create an implementation plan based on the analysis."
    system_prompt: "You are a technical architect."

  - step_name: implement
    task_prompt: "Implement the plan from the previous step."
    system_prompt: "You are a senior developer."
    model: sonnet
    # Optional: override handoff instructions for this step
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
| `handoff_prompt` | Override handoff instructions for this pipe step (pipe only) |

### Template variables

Both `task_prompt` and `system_prompt` support template variables via `{variable_name}`. Unrecognized variables are left as-is.

**All modes:**

| Variable | Description |
|----------|-------------|
| `{step_name}` | Current step's name |
| `{max_iterations}` | Configured max iterations |
| `{default_model}` | Default model |
| `{model}` | Resolved model for this step |
| `{state_dir}` | State directory path (`.ralphkit/current` symlink) |

**Loop only:**

| Variable | Description |
|----------|-------------|
| `{iteration}` | Current iteration number (1-based) |

**Pipe only:**

| Variable | Description |
|----------|-------------|
| `{task}` | Task content (empty string if not provided) |
| `{step_index}` | Current step index (1-based) |
| `{total_steps}` | Total number of pipe steps |
| `{prev_step_name}` | Previous step's name (empty string for first step) |
| `{next_step_name}` | Next step's name (empty string for last step) |

See [`configs/example.yaml`](configs/example.yaml) for a loop config and [`configs/example-pipe.yaml`](configs/example-pipe.yaml) for a pipe config.

## How It Works

### Loop

```
 Setup (once)          Loop (iterate)              Cleanup (once, always)
┌──────────┐    ┌───────────────────────┐    ┌──────────────┐
│ step 1   │    │ step 1 (e.g. worker)  │    │ step 1       │
│ step 2   │    │ step 2 (e.g. reviewer)│    │ ...          │
│ ...      │    │ ...                   │    └──────────────┘
└──────────┘    │ SHIP? → done          │
                │ REVISE? → loop again  │
                └───────────────────────┘
```

Each loop iteration runs all loop steps in order, then checks the review result:

1. **Loop steps** — each step runs `claude` with its configured prompts and model.
2. After all steps, the verdict is read from `.ralphkit/current/review-result.md`.
3. **SHIP** → exit successfully. **REVISE** → feedback is preserved for the next iteration.

The cleanup phase always runs (even if the loop exits with an error), similar to a `finally` block.

### Pipe

```
┌────────┐    ┌────────┐    ┌────────┐
│ step 1 │───>│ step 2 │───>│ step 3 │──> done
└────────┘    └────────┘    └────────┘
     │             │             │
     └── handoff ──┘── handoff ──┘
```

Each step runs once. Output flows forward via **named handoff files**:

```
.ralphkit/runs/001/
├── task.md                              # optional task input
├── handoff__analyze__to__plan.md        # analyze's output for plan
└── handoff__plan__to__implement.md      # plan's output for implement
```

By default, each step gets position-aware handoff instructions appended to its system prompt:
- **First step**: write handoff file for the next step
- **Middle steps**: read previous handoff, write next handoff
- **Last step**: read previous handoff, no write

Override the default handoff with `handoff_prompt:` at the step level or config level. Set to empty string to disable handoff injection entirely.

## State Files

Each run gets its own numbered directory under `.ralphkit/runs/`. A `current` symlink always points to the active run, so prompt templates use `{state_dir}` which resolves to `.ralphkit/current`.

```
.ralphkit/
  current -> runs/003        # symlink to active run
  runs/
    001/                     # first run (preserved)
      task.md, iteration.md, work-summary.md, ...
    002/                     # second run (preserved)
    003/                     # active run
```

Previous runs are preserved automatically. Use `--list-runs` to see them:

```bash
ralph --list-runs
```

**Loop state files:**

| File | Purpose |
|------|---------|
| `task.md` | The task description |
| `iteration.md` | Current iteration number |
| `work-summary.md` | What the worker did this iteration |
| `work-complete.md` | Created when the worker thinks it's done |
| `review-result.md` | `SHIP` or `REVISE` |
| `review-feedback.md` | Specific feedback from the reviewer |
| `RALPH-BLOCKED.md` | Created by a step if it cannot proceed |

**Pipe state files:**

| File | Purpose |
|------|---------|
| `task.md` | The task description (if provided) |
| `handoff__X__to__Y.md` | Handoff from step X to step Y |
| `RALPH-BLOCKED.md` | Created by a step if it cannot proceed |

## Requirements

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude` must be on your PATH)
- Python 3.10+
