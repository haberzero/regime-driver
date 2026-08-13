import pytest

from errors import (
    InsufficientStockError,
    InvalidCouponError,
    InvalidPriceError,
    InvalidQuantityError,
    InventoryError,
    UnknownSKUError,
)
from inventory import Inventory
from orders import Order, OrderLine, place_order
from pricing import PriceCatalog


@pytest.fixture
def catalog():
    c = PriceCatalog()
    c.set_price("A", 10.0)
    c.set_price("B", 5.5)
    c.set_price("C", 7.0)
    return c


@pytest.fixture
def inv():
    inv = Inventory()
    inv.add_item("A", "apple")
    inv.add_item("B", "banana")
    inv.add_item("C", "cherry")
    inv.restock("A", 10)
    inv.restock("B", 10)
    inv.restock("C", 2)
    return inv


# ---------- OrderLine ----------

def test_order_line_valid():
    line = OrderLine("A", 3, 10.0)
    assert line.sku == "A"
    assert line.qty == 3
    assert line.unit_price == 10.0
    assert line.total == 30.0


@pytest.mark.parametrize("bad", [0, -1, 1.5, "2", None, True])
def test_order_line_invalid_qty_raises(bad):
    with pytest.raises(InvalidQuantityError):
        OrderLine("A", bad, 10.0)


@pytest.mark.parametrize("bad", [0, -1, 0.0, "10", None, True])
def test_order_line_invalid_price_raises(bad):
    with pytest.raises(InvalidPriceError):
        OrderLine("A", 2, bad)


# ---------- Order ----------

def test_order_total_sums_lines():
    order = Order("alice", [OrderLine("A", 2, 10.0), OrderLine("B", 3, 5.5)])
    assert order.customer == "alice"
    assert len(order.lines) == 2
    assert order.total == 20.0 + 16.5


def test_order_total_is_pure_computation(catalog, inv):
    order = place_order(catalog, inv, [("A", 2)])
    before = inv.stock_level("A")
    _ = order.total
    _ = order.total
    assert inv.stock_level("A") == before


# ---------- place_order happy path ----------

def test_place_order_prices_and_deducts(catalog, inv):
    order = place_order(catalog, inv, [("A", 2), ("B", 4)], customer="alice")
    assert order.customer == "alice"
    assert [l.sku for l in order.lines] == ["A", "B"]
    assert order.lines[0].unit_price == 10.0
    assert order.lines[1].unit_price == 5.5
    assert order.total == 2 * 10.0 + 4 * 5.5
    assert inv.stock_level("A") == 8
    assert inv.stock_level("B") == 6


# ---------- place_order atomicity / failure paths ----------

def test_place_order_unknown_sku_does_not_deduct(catalog, inv):
    inv.restock("A", 100)
    before = inv.stock_level("A")
    with pytest.raises(UnknownSKUError) as exc:
        place_order(catalog, inv, [("A", 1), ("NOPE", 1)])
    assert exc.value.sku == "NOPE"
    assert inv.stock_level("A") == before


def test_place_order_priced_but_not_in_inventory_raises(catalog, inv):
    catalog.set_price("Z", 1.0)
    before = inv.stock_level("A")
    with pytest.raises(UnknownSKUError) as exc:
        place_order(catalog, inv, [("A", 1), ("Z", 1)])
    assert exc.value.sku == "Z"
    assert inv.stock_level("A") == before


def test_place_order_empty_lines_returns_empty_order(catalog, inv):
    order = place_order(catalog, inv, [], customer="bob")
    assert order.customer == "bob"
    assert order.lines == []
    assert order.total == 0.0
    assert inv.stock_level("A") == 10


def test_place_order_single_line(catalog, inv):
    order = place_order(catalog, inv, [("C", 2)])
    assert len(order.lines) == 1
    assert order.total == 14.0
    assert inv.stock_level("C") == 0


def test_place_order_sku_unpriced_does_not_deduct(catalog, inv):
    inv.add_item("Z", "zebra")
    inv.restock("Z", 50)
    before = inv.stock_level("A")
    with pytest.raises(UnknownSKUError):
        place_order(catalog, inv, [("A", 1), ("Z", 1)])
    assert inv.stock_level("A") == before
    assert inv.stock_level("Z") == 50


def test_place_order_insufficient_stock_does_not_deduct(catalog, inv):
    with pytest.raises(InsufficientStockError) as exc:
        place_order(catalog, inv, [("A", 2), ("C", 5)])
    assert exc.value.sku == "C"
    assert inv.stock_level("A") == 10
    assert inv.stock_level("C") == 2


def test_place_order_partial_failure_rolls_back_everything(catalog, inv):
    inv.restock("A", 0)
    with pytest.raises(InsufficientStockError):
        place_order(catalog, inv, [("A", 1), ("B", 999)])
    assert inv.stock_level("A") == 10
    assert inv.stock_level("B") == 10


def test_place_order_invalid_qty_does_not_deduct(catalog, inv):
    with pytest.raises(InvalidQuantityError):
        place_order(catalog, inv, [("A", -2)])
    assert inv.stock_level("A") == 10


def test_place_order_success_consumes_stock_once(catalog, inv):
    before_a = inv.stock_level("A")
    order = place_order(catalog, inv, [("A", 3)])
    assert inv.stock_level("A") == before_a - 3
    assert order.total == 30.0


# ---------- PriceCatalog ----------

def test_price_of_and_set_price(catalog):
    assert catalog.price_of("A") == 10.0
    catalog.set_price("A", 12.0)
    assert catalog.price_of("A") == 12.0


def test_price_of_unknown_sku_raises(catalog):
    with pytest.raises(UnknownSKUError):
        catalog.price_of("NOPE")


@pytest.mark.parametrize("bad", [0, -1, 0.0, "10", None, True])
def test_set_price_invalid_raises(catalog, bad):
    with pytest.raises(InvalidPriceError) as exc:
        catalog.set_price("A", bad)
    assert exc.value.sku == "A"
    assert exc.value.price is bad
    assert catalog.price_of("A") == 10.0


# ---------- discounts (strategy injection) ----------

def test_discount_percentage(catalog):
    catalog.register_coupon("PCT10", lambda base: base * 0.9)
    assert catalog.discounted_price("A", 2, "PCT10") == 18.0
    assert catalog.discounted_price("B", 1, "PCT10") == round(5.5 * 0.9, 2)


def test_discount_threshold_amount_off(catalog):
    def min_spend_off(base):
        return base - 20.0 if base >= 100 else base

    catalog.register_coupon("OFF20", min_spend_off)
    assert catalog.discounted_price("A", 5, "OFF20") == 50.0
    assert catalog.discounted_price("A", 15, "OFF20") == 130.0


def test_discount_replacing_coupon_overrides(catalog):
    catalog.register_coupon("PCT10", lambda base: base * 0.9)
    catalog.register_coupon("PCT10", lambda base: base * 0.5)
    assert catalog.discounted_price("A", 2, "PCT10") == 10.0


def test_discount_removed_coupon_raises(catalog):
    catalog.register_coupon("X", lambda base: base)
    catalog.remove_coupon("X")
    with pytest.raises(InvalidCouponError):
        catalog.discounted_price("A", 1, "X")


def test_discount_unknown_coupon_raises(catalog):
    with pytest.raises(InvalidCouponError) as exc:
        catalog.discounted_price("A", 1, "NOPE")
    assert exc.value.coupon_code == "NOPE"


def test_discount_unknown_sku_raises(catalog):
    catalog.register_coupon("PCT10", lambda base: base * 0.9)
    with pytest.raises(UnknownSKUError):
        catalog.discounted_price("NOPE", 1, "PCT10")


@pytest.mark.parametrize("bad", [0, -1, 1.5, "2", None, True])
def test_discount_invalid_qty_raises(catalog, bad):
    catalog.register_coupon("PCT10", lambda base: base * 0.9)
    with pytest.raises(InvalidQuantityError):
        catalog.discounted_price("A", bad, "PCT10")


def test_register_coupon_rejects_bad_strategy(catalog):
    with pytest.raises(InvalidCouponError):
        catalog.register_coupon("BAD", "not callable")
    with pytest.raises(InvalidCouponError):
        catalog.register_coupon("", lambda base: base)


# ---------- unified error hierarchy ----------

def test_all_errors_share_base(catalog, inv):
    errors = [
        InvalidCouponError("X"),
        InvalidQuantityError("A", 0),
        InvalidPriceError("A", -1),
        UnknownSKUError("NOPE"),
        InsufficientStockError("A", 5, 2),
    ]
    for err in errors:
        assert isinstance(err, InventoryError)
        assert err.message
