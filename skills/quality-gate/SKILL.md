---
name: quality-gate
description: Checkpoint progress into the task control document and verify the current milestone passes before continuing.
---

# Quality Gate

Use this at each milestone boundary and before ending a work segment. It keeps the run verifiable and self-auditing.

## Procedure

1. **Read the task control doc** (e.g. TASK.md / tasks.md / plan.md). Confirm the current milestone and its checklist.
2. **Verify, don't claim** — Re-run the actual checks (tests, build, lint). Record real counts, not estimates.
3. **Update the control doc**:
   - Mark completed items `[x]`.
   - Record results: `[DONE] <item> | verified: <test count> | files: <paths>`.
   - Move incomplete items to "next" / blockers with a reason.
4. **Self-question** — Challenge anything unclear: is this actually verified? Any assumption I'm making?
5. **Decide**:
   - Milestone met → write a short summary, then continue to next item.
   - Blocked → record the blocker and stop (do not silently work around).
   - If a decision needs a human (architecture/contract/destructive) → stop and report.
6. **Commit** — At each milestone, commit with a descriptive message (what + verification result). Keep the worktree clean for the next session.