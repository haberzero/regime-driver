# Design Decisions — Payment Ledger

## 1. Money representation: integer cents (`int`) — CHOSEN

**Chosen: amounts are stored and returned as integer cents.**

Every amount is normalized to whole cents at the API boundary by an *exact*
decimal conversion: floats are routed through `Decimal(str(x))` and multiplied
by 100; `int`/`Decimal` inputs are converted arithmetically. Values with
sub-cent precision raise `ValueError` instead of being silently rounded. All
internal arithmetic (post, transfer legs, balance sums, reconcile comparison)
is integer arithmetic.

Rationale for choosing `int` cents:

- **Correctness.** There is no floating-point drift by construction:
  `post(a,0.1) ; post(a,0.2)` stores `10 + 20 = 30` cents exactly, so
  `balance(a) == 0.3` and `reconcile(..., {"a": 0.3})` matches exactly.
  The legacy `balance` accumulated binary floats, producing
  `0.30000000000000004`, and the old `1e-9` tolerance masked such drift —
  the root cause of the float defect.
- **Determinism.** No Decimal context/scale/precision state to manage; two
  identical operations always produce identical results, which also keeps
  reconcile comparison trivially exact (`==` on ints).
- **Performance.** Integer arithmetic avoids Decimal's per-operation overhead
  and allocation, relevant under heavy concurrent posting.
- **Thread-safety.** Reading a single int is atomic; combined with one lock
  for compound read-modify-write, no special-casing is needed.

Rejected alternatives and the unacceptable points that eliminated them:

- **`float` accumulation (status quo).** *Root cause of defect #1*: binary
  floats cannot represent `0.1`, `0.2` exactly, so sums drift and equality
  checks fail; the `1e-9` reconcile tolerance hides these errors instead of
  surfacing them.
- **`Decimal` as the internal type.** Correct in principle, but (a) float
  inputs still drift unless routed through `str()` — `Decimal(0.1)+Decimal(0.2)
  != Decimal(0.3)` reproduces the bug; (b) equality is scale-sensitive, so
  `Decimal('0.1')+Decimal('0.2') == Decimal('0.3')` only holds if every operand
  is quantized to the same exponent — easy to get wrong; (c) higher per-op
  cost for no concurrency or atomicity benefit (a lock is still required).

## 2. Atomicity of `transfer`

Legacy behavior wrote `post(src, -amount)` then `post(dst, amount)` as two
independent appends; a failure between them left the source debited and the
destination un-credited — an unbalanced ledger.

Fix: **validate up-front, then write both legs under one lock.** The amount is
converted (and any `TypeError`/`ValueError` raised) *before* taking the lock;
capacity for 2 entries is checked *before* any append. No exception can fire
between the two appends, so a transfer is all-or-nothing. This satisfies the
"pre-validation or transactional rollback" requirement with no compensating
writes.

## 3. Idempotency key: `(account, ref)`

- `post(account, amount, ref)` returns `True` when a new entry is recorded and
  `False` when an entry with the same `(account, ref)` already exists — no
  duplicate entry is written.
- `transfer(src, dst, amount, ref)` and `idempotent_transfer(...)` (alias) are
  idempotent per `ref`: if `(src, ref)` already exists the transfer is a no-op
  returning `False`. Because a transfer is atomic, `(src, ref)` exists iff both
  legs exist, so retries (e.g. network retries) apply at most once.
- Same `ref` on *different* accounts is still a distinct key (allowed).

## 4. Capacity

`Ledger(max_entries=None)` accepts an optional capacity. Every mutation
checks remaining room up-front and raises `StorageFullError` before writing
anything, so a failed write leaves the ledger untouched. Duplicate postings
return `False` (idempotency) even when the ledger is full. Default `None`
means unbounded, preserving the legacy contract.

## 5. Concurrency

A single `threading.Lock` guards every mutation and every read. `post`,
`transfer`, `balance`, `count`, and `last_refs` take the lock, so
readers observe a consistent snapshot and read-modify-write operations
(idempotency check + append, both transfer legs) are atomic. The GIL makes
int reads safe; the lock makes compound operations safe.
