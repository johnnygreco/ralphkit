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

Write a task file that clearly specifies what needs to be done, then run it:

```bash
ralphkit build feature.md       # plan-driven loop: plan → build → review
ralphkit fix bug.md             # diagnose → fix → verify
ralphkit research question.md   # explore → synthesize → report
ralphkit plan feature.md        # analyze → design document
ralphkit big-swing epic.md      # research → plan → build → review → fix → verify
```

Task files should contain a well-specified description of the work to be done: the goal, relevant context, constraints, and acceptance criteria.

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

## Config

The `--config` flag is required for `pipe` and `loop` primitives. The named subcommands (`build`, `fix`, etc.) have built-in configs.

### Loop config

```yaml
max_iterations: 10
default_model: opus
plan_model: sonnet

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

Each step requires `step_name`, `task_prompt`, and `system_prompt`. Optional: `model` (per-step override), `handoff_prompt` (pipe only). See [`configs/`](configs/) for complete examples.

## Background Jobs

Any command accepts `--host` to run as a background job via tmux:

```bash
ralphkit build task.md --host local   # local tmux session
ralphkit build task.md --host mini    # remote host (SSH config name)
ralphkit big-swing epic.md --host mini --working-dir /path/to/project
```

The `--host` flag takes an SSH config name directly — no additional config needed. Remote jobs run via `uvx`, so ralphkit doesn't need to be pre-installed on the remote host.

```bash
ralphkit jobs [--host NAME]             # list active jobs
ralphkit logs JOB_ID [--host NAME]      # view job logs (-F to follow)
ralphkit cancel JOB_ID [--host NAME]    # cancel a running job
ralphkit runs                           # list past completed runs
```

## Requirements

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude` must be on your PATH)
- Python 3.10+
- [tmux](https://github.com/tmux/tmux) (for `--host` background jobs only)
