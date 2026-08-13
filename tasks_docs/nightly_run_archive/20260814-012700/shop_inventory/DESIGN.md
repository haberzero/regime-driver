# DESIGN — inventory/pricing/orders refactor

## Module layout (one responsibility per file)

| Module       | Responsibility                                                       |
|--------------|----------------------------------------------------------------------|
| `inventory.py` | SKU registry (name), thread-safe stock ledger, atomic `restock`/`take`, `stock_level`. |
| `pricing.py`   | `PriceCatalog` (unit prices), `set_price`, `price_of`, discount engine `discounted_price`. |
| `orders.py`    | `OrderLine`, `Order`, `place_order` (validate -> deduct -> price, rollback on failure). |
| `errors.py`    | Unified domain exceptions with structured fields.                    |

Layering: `orders -> {inventory, pricing}`; `{inventory, pricing} -> errors`.
Inventory and pricing are independent (stock vs. price are separate concerns).

## Design decision: discount system

**Chosen: strategy-function injection.**

- `PriceCatalog.register_discount(coupon_code, strategy)` binds a coupon to a
  caller-supplied `strategy(unit_price, qty) -> discounted_total`.
- The library ships two factories — `percent_discount` (打折) and `amount_off`
  (满减) — but the caller may inject any other policy without touching the lib.

Rationale:

1. **Composable with the layered design.** Pricing stays a thin, stateless
   engine; business rules live with the caller, who already owns the domain.
2. **No coupling to data shape.** A rule table forces a fixed rule schema
   (threshold/percent columns); strategies can express non-linear rules
   (quantity tiers, bundles) the table cannot represent.
3. **Explicit unit pricing.** `OrderLine.unit_price` is the (possibly
   discounted) effective unit price, so `Order.total()` stays a pure sum.
4. **Testability.** Each strategy is a pure function — trivially unit-tested.

**Rejected: data-driven rule table** (e.g. a list of
`{"coupon", "kind", "threshold", "value"}` rows).

- The task mandates the *caller* registers policy functions; a table would
  drag pricing back into the legacy "config + logic in one place" shape.
- Interpretation (满减 vs 打折 vs threshold rounding) leaks into the library
  and hard-codes the two known rules, making future rules a library change.
- Validation of arbitrary rules needs a mini schema/compiler — over-engineering.

## Defect fixes (root cause, no symptom patches)

1. **add_item drops name updates** — `Inventory.add_item(sku, name)` now always
   writes the name; price no longer lives here (moved to `PriceCatalog`).
2. **make_order deducted before pricing, no rollback** — `place_order` wraps
   deduction+pricing in try/except and `restock`s all deducted lines on any
   failure (incl. `InvalidCouponError` surfaced mid-pricing).
3. **restock accepted negatives** — `restock` rejects `n <= 0` (and
   non-`int`, incl. `bool`) with `InvalidQuantityError`; same guard on `take`
   and on quantities everywhere.
4. **price/qty unvalidated** — `set_price` rejects `<= 0`, non-numeric, and
   `bool`; quantity guards applied in inventory, pricing, and orders.
5. **double deduction / double computation** — `take` happens exactly once in
   `place_order`; `Order.total()` sums captured line prices only, never
   re-reads inventory.

## API mapping (legacy -> new, observable semantics preserved)

- `Inventory.add_item(sku, name, price)` -> `add_item(sku, name)`; prices are
  now set via `PriceCatalog.set_price(sku, price)`.
- `Inventory.restock/take` — same names, plus validation; unknown-SKU ops now
  raise `UnknownSKUError` instead of silently creating garbage entries.
- `Inventory.price_of` -> `PriceCatalog.price_of`.
- `make_order(inv, customer, lines)` -> `orders.place_order(catalog, inventory,
  lines, customer, coupon_code=None)`.
- `Order.add_line`/`Order.total(inv)` -> immutable `Order` with line objects;
  `total()` needs no arguments.

## Known technical debt (accepted)

- Per-SKU lock granularity (single global lock) is simplest and correct; a
  striped/fine-grained lock is premature.
- Discounts apply per line (one coupon across the order). Order-level
  aggregation (e.g. minimum order total for a coupon) is a future extension.
- Float arithmetic for prices; decimal money handling deferred.
