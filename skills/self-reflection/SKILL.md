---
name: self-reflection
description: Retrospective on the current work segment. Load periodically to assess progress, quality, and next steps.
---

# Self-Reflection

Load this periodically (e.g. on a stall, or every N minutes) to assess the run and decide next actions.

## Prompt

Answer the following concisely and write the result to the task control document:

1. **Progress** — What have I actually accomplished since the last checkpoint? (verified, not claimed)
2. **Quality** — Any unverified work, debt, or fallbacks hiding a problem? What's the riskiest unverified assumption?
3. **Stall check** — Am I making progress, or repeating the same action? Is the last turn a "talk-only" turn?
4. **Next step** — The single most valuable next action, and whether it's autonomous or needs a human decision.
5. **Structural problems** — Any architecture/contract/destructive issue that must be escalated?

## Output format

Append to the task control doc:

```
[REFLECT] <datetime> | progress: <summary> | risk: <n> | next: <action> | escalate: <yes/no> <reason>
```

- If `escalate: yes`, stop and report; do not continue autonomously.
- If progress is stuck (3+ turns with no meaningful change), stop and report the stall.