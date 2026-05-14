# Loom

Loom is a local activity monitor and router for subscription-backed agent CLIs.

The first MVP tracks usable capacity across Codex, Claude, and Gemini command
line tools. It records Loom-launched usage, parses provider feedback for quota
and auth failures, computes availability scores, and recommends the next agent
for coding work.

## Commands

```bash
loom status
loom monitor --once
loom usage
loom probe --dry-run
loom route "task description"
loom log
loom run "goal"
loom spawn --agent codex "task"
loom sessions
loom attach loom:project:task-id
loom stop loom:project:task-id
```

Monitor state is stored under `knowledge/logs/loom/` in the enclosing
meta-learning-system checkout by default.

`loom run` routes work to the highest scoring available agent. `loom spawn`
uses a specific agent. Both create a caveman task packet with `TASK`, `REPO`,
`STATE`, `FILES`, `CONSTRAINTS`, `ASK`, and `OUTPUT` sections, then launch the
selected CLI in a tmux session named `loom:<project>:<task-id>`. If tmux is not
available, Loom falls back to a local subprocess and writes output to the task
log under `knowledge/logs/loom/tasks/`.
