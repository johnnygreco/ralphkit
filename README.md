# ralphkit

An iterative work → review loop for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). One model does the work, a different model reviews it. The loop continues until the reviewer says **SHIP** or max iterations are reached.

Inspired by [Goose's Ralph pattern](https://block.github.io/goose/docs/tutorials/ralph-loop).

## Install

```bash
uv tool install -e path/to/ralphkit
```

Or run directly:

```bash
uvx --from path/to/ralphkit ralph "your task here"
```

## Quick Start

```bash
ralph "Create a Python function in prime.py that checks if a number is prime. Include unit tests in test_prime.py."
```

Pass a markdown file:

```bash
ralph task.md
```

Or put the task in your config:

```yaml
# ralph.yaml
worker_model: opus
reviewer_model: sonnet
max_iterations: 10
task: |
  Create a Python function in prime.py that checks if a number is prime.
  Include unit tests in test_prime.py.
```

Then just run:

```bash
ralph
```

## Task Input

Tasks can come from three sources (in priority order):

1. **CLI string**: `ralph "Build a REST API"` — ad-hoc, one-off tasks
2. **CLI markdown file**: `ralph task.md` — reusable task files, detected by `.md` extension + file exists
3. **In config YAML**: `task` field in `ralph.yaml` — best for reproducibility, keeps task + config together

CLI arg always wins over config.

## Configuration

Create a `ralph.yaml` in your working directory:

```yaml
worker_model: opus        # Model for work phase (default: opus)
reviewer_model: sonnet    # Model for review phase (default: sonnet)
max_iterations: 10        # Max work/review cycles (default: 10)
```

All fields are optional — sensible defaults are used for anything omitted. If no `ralph.yaml` exists, all defaults apply.

To use a config file in a different location:

```bash
ralph --config path/to/config.yaml "Build a REST API in Go"
```

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

State is persisted in a `.ralph/` directory so each stateless `claude -p` invocation can pick up where the last left off.

## State Files

All state lives in `.ralph/` in the current working directory:

| File | Purpose |
|------|---------|
| `task.md` | The task description |
| `iteration.txt` | Current iteration number |
| `work-summary.txt` | What the worker did this iteration |
| `work-complete.txt` | Created when the worker thinks it's done |
| `review-result.txt` | `SHIP` or `REVISE` |
| `review-feedback.txt` | Specific feedback from the reviewer |

## Uninstall

```bash
uv tool uninstall ralphkit
```

## Requirements

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude` must be on your PATH)
- Python 3.11+
