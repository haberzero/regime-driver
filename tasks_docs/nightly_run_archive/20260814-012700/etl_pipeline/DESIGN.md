# ETL Pipeline Framework — Design Decisions

This document finalizes the three design decisions for the pipeline framework
(design node deliverable), including the rejected options.

## A) Rate-limiting semantics — CHOSEN: token bucket

- **Token bucket (chosen).** `RateLimitStage(per_sec, burst)` replenishes
  `per_sec` tokens per second up to a capacity of `burst` (default = one
  second's worth). It allows a bounded burst (≤ `burst` tokens pass
  immediately) while enforcing the long-run average throughput at `per_sec`.
  When the bucket is empty the stage waits for the next token, or raises
  `RateLimitExceeded` if `raise_on_limit=True`. The clock is injectable so the
  throttle is verified deterministically in tests.
- **Rejected: fixed window.** Trivially simple (count events per second) but
  has no memory between windows and admits up to 2× the configured rate in a
  burst straddling a window boundary. Worse for a framework where the rate
  limit is a hard contract.

## B) Failure strategy — CHOSEN: default `fail_fast=False` (isolation)

- **Isolation (chosen).** A failing batch is recorded per-stage in
  `stage_stats[name]["failed"]`, later stages still run, and the run returns
  `{processed, failed, stage_stats}` so callers can inspect and reprocess only
  the failed batches. This composes with the idempotent `BatchSink.flush()`
  (repeated flush never duplicates), so partial results are safe and
  observable. `fail_fast=True` remains available for callers who want fail-now
  semantics, in which case a `StageFailure(stage_name, cause)` is raised.
- **Rejected: full-chain fail_fast as the default.** Simpler to reason about
  but aborts the remaining rows and couples unrelated stages; a single transient
  failure silently discards the rest of the batch. Fail-fast is opt-in.

## C) Concurrency — CHOSEN: single-threaded sequential by default

- **Sequential (chosen).** Stages run in insertion order on the caller's
  thread. This keeps ordering, failure-isolation, and rate-limiting semantics
  deterministic, and it guarantees the token-bucket limiter and the idempotent
  sink behave predictably. Suitable for batch pipelines where correctness
  precedes peak throughput.
- **Rejected: stage-level parallelism as the default.** Requires bounded queues
  between stages, reordering/failure semantics become subtle, and interaction
  with an in-process token bucket gets nondeterministic. If parallelism is
  needed later it should be an opt-in option (e.g. a per-stage `executor`) —
  tracked in the tech-debt section of the implementation report, not in the
  default path.
