# ralphkit

A step-based pipeline for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Define setup, loop, and cleanup phases in a YAML config. The loop iterates until the reviewer says **SHIP** or max iterations are reached.

Inspired by [Goose's Ralph pattern](https://block.github.io/goose/docs/tutorials/ralph-loop).

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
uvx ralphkit ralph-loop "your task here" --config ralph.yaml
```

## Quick Start

```bash
ralph-loop "Create a Python function in prime.py that checks if a number is prime. Include unit tests." --config configs/example.yaml
```

## Usage

```
ralph-loop TASK --config PATH [OPTIONS]
```

**Arguments:**

| Argument | Description | Default |
|----------|-------------|---------|
| `TASK` | Task description (string or path to `.md` file) | required |
| `--config PATH` | Path to YAML config file | required |
| `--max-iterations N` | Override max iterations from config | from config |
| `-f` / `--force` | Skip confirmation prompt | off |

**Examples:**

```bash
# Inline task
ralph-loop "Build a REST API" --config ralph.yaml

# Task from a markdown file
ralph-loop task.md --config ralph.yaml

# Override max iterations
ralph-loop "Build a REST API" --config ralph.yaml --max-iterations 5

# Skip confirmation
ralph-loop "Build a REST API" --config ralph.yaml -f
```

### Config file

A YAML config file is required. It defines three phases — **setup**, **loop**, and **cleanup** — each containing a list of steps. Only `loop` is required.

```yaml
max_iterations: 10
default_model: opus

# Optional: runs once before the loop
setup:
  - step_name: init
    task_prompt: "Initialize the project."
    system_prompt: "You are a setup agent."

# Required: iterated until SHIP or max iterations
loop:
  - step_name: worker
    task_prompt: "Read .ralphkit/task.md and begin working. This is iteration {iteration}."
    system_prompt: "You are a worker in a RALPH LOOP..."
    model: opus
  - step_name: reviewer
    task_prompt: "Review the work done for the task in .ralphkit/task.md."
    system_prompt: "You are a code reviewer..."
    model: sonnet

# Optional: runs once after the loop (always, even on failure)
cleanup:
  - step_name: finalize
    task_prompt: "Clean up temporary files."
    system_prompt: "You are a cleanup agent."
```

**Required top-level keys:** `max_iterations`, `default_model`, `loop`

Each step requires `step_name`, `task_prompt`, and `system_prompt`. The optional `model` field overrides `default_model` for that step.

### Template variables

Both `task_prompt` and `system_prompt` support template variables via `{variable_name}`. Unrecognized variables are left as-is.

**All phases:**

| Variable | Description |
|----------|-------------|
| `{step_name}` | Current step's name |
| `{max_iterations}` | Configured max iterations |
| `{default_model}` | Pipeline's default model |
| `{model}` | Resolved model for this step |
| `{state_dir}` | State directory path (`.ralphkit`) |

**Loop phase only:**

| Variable | Description |
|----------|-------------|
| `{iteration}` | Current iteration number (1-based) |

See [`configs/example.yaml`](configs/example.yaml) for a complete working config.

## How It Works

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
2. After all steps, the verdict is read from `.ralphkit/review-result.md`.
3. **SHIP** → exit successfully. **REVISE** → feedback is preserved for the next iteration.

The cleanup phase always runs (even if the loop exits with an error), similar to a `finally` block.

## State Files

State is persisted in `.ralphkit/` in the current working directory so each stateless `claude -p` invocation can pick up where the last left off.

| File | Purpose |
|------|---------|
| `task.md` | The task description |
| `iteration.md` | Current iteration number |
| `work-summary.md` | What the worker did this iteration |
| `work-complete.md` | Created when the worker thinks it's done |
| `review-result.md` | `SHIP` or `REVISE` |
| `review-feedback.md` | Specific feedback from the reviewer |
| `RALPH-BLOCKED.md` | Created by a step if it cannot proceed |

## Requirements

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude` must be on your PATH)
- Python 3.10+
