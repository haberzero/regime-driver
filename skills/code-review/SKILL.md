---
name: code-review
description: Review recent code changes for correctness, quality, and security before marking work complete. Use at every milestone/phase boundary.
---

# Code Review

Load this skill at every milestone/phase boundary to audit the work done before continuing or reporting completion.

## Procedure

1. **Scope** — Identify the changes since the last checkpoint (git diff / git status / recent file edits).
2. **Read, don't guess** — Open the actual changed files. Verify logic against real code, not memory.
3. **Checklist**:
   - Correctness: does it do what the task requires? Edge cases/error paths handled?
   - Regressions: run the relevant tests/build; zero regressions required.
   - Security: secrets, input validation, injection, unsafe patterns.
   - Maintainability: dead code, duplicate channels / dual-write truth sources, fallbacks masking architecture problems.
   - Contract: no unapproved external API / contract / destructive changes.
4. **Severity** — Classify findings:
   - `blocker` (must fix before proceeding)
   - `warning` (should fix, can defer with a recorded reason)
   - `nit` (cosmetic)
5. **Output** — Write a short review summary to the task control document:
   - `[REVIEW] <path/scope> | <count> issues | blockers: <n> | warnings: <n>`
   - If any `blocker`, do NOT mark complete; fix the root cause first.