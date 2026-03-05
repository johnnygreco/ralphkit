# ralphkit

An iterative work/review loop for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). One model does the work, a different model reviews it. The loop continues until the reviewer says **SHIP** or max iterations are reached.

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
uvx ralphkit ralph-loop "your task here"
```

## Quick Start

```bash
ralph-loop "Create a Python function in prime.py that checks if a number is prime. Include unit tests."
```

## Usage

```
ralph-loop TASK [OPTIONS]
```

**Arguments:**

| Argument | Description | Default |
|----------|-------------|---------|
| `TASK` | Task description (string or path to `.md` file) | required |
| `--config PATH` | Load settings from a YAML config file | none |
| `--worker-model` | Model for the work phase | `opus` |
| `--reviewer-model` | Model for the review phase | `sonnet` |
| `--max-iterations` | Max work/review cycles | `10` |
| `--worker-system-prompt` | Override the worker system prompt entirely | built-in |
| `--reviewer-system-prompt` | Override the reviewer system prompt entirely | built-in |
| `--worker-user-prompt` | Override the worker user prompt (`{iteration}` is substituted) | built-in |
| `--reviewer-user-prompt` | Override the reviewer user prompt | built-in |
| `--append-system-prompt` | Extra text appended to both system prompts | none |
| `-y` / `--yes` | Skip confirmation prompt | off |

**Examples:**

```bash
# Inline task
ralph-loop "Build a REST API"

# Task from a markdown file
ralph-loop task.md

# Override models
ralph-loop "Build a REST API" --worker-model sonnet --reviewer-model haiku

# Use a config file for shared settings
ralph-loop "Build a REST API" --config ralph.yaml

# Skip confirmation
ralph-loop "Build a REST API" -y
```

### Config file

A config file is optional. When provided via `--config`, its values serve as defaults that CLI args can override.

```yaml
# ralph.yaml
worker_model: opus
reviewer_model: sonnet
max_iterations: 10

# Optional: override system prompts entirely
# worker_system_prompt: "Your custom worker instructions..."
# reviewer_system_prompt: "Your custom reviewer instructions..."

# Optional: override user prompts (the -p argument to claude)
# worker_user_prompt: "Begin iteration {iteration}. Read .ralphkit/task.md and start."
# reviewer_user_prompt: "Review the work and write your verdict."

# Optional: append extra instructions to both system prompts
# append_system_prompt: "Always use pytest. Never modify the README."
```

Resolution order: built-in defaults → config file → CLI args.

## How It Works

```
┌─────────────────────────────────────────┐
│  1. Read task                           │
│  2. Worker model does the work          │ ◄─── iteration N
│  3. Reviewer model reviews it           │
│  4. SHIP? -> done. REVISE? -> loop.     │
└─────────────────────────────────────────┘
```

Each iteration:

1. **Work phase** — the worker model reads the task (and any prior review feedback), writes code, runs tests, and summarizes what it did.
2. **Review phase** — the reviewer model examines all files, runs tests, and writes either `SHIP` (approve) or `REVISE` (with feedback).
3. If `REVISE`, the feedback is passed to the next iteration. If `SHIP`, the loop exits successfully.

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
| `RALPH-BLOCKED.md` | Created by the worker if it cannot proceed |

## Requirements

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude` must be on your PATH)
- Python 3.10+
