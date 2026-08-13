import pytest

from errors import (
    InsufficientStockError,
    InvalidCouponError,
    InvalidPriceError,
    InvalidQuantityError,
    UnknownSKUError,
)
from inventory import Inventory
from orders import Order, OrderLine, place_order
from pricing import PriceCatalog, amount_off, percent_discount


@pytest.fixture
def shop():
    inv = Inventory()
    catalog = PriceCatalog()
    inv.add_item("A", "Apple")
    inv.restock("A", 10)
    catalog.set_price("A", 5.0)
    inv.add_item("B", "Banana")
    inv.restock("B", 5)
    catalog.set_price("B", 2.0)
    return inv, catalog


# --- PriceCatalog: set_price / price_of (defect 4 regression) ---

@pytest.mark.parametrize("bad", [0, -1, -0.01, "5", None, True, []])
def test_set_price_rejects_invalid_price(bad):
    catalog = PriceCatalog()
    with pytest.raises(InvalidPriceError):
        catalog.set_price("A", bad)
    assert not catalog.has_sku("A")


def test_set_price_overwrites():
    catalog = PriceCatalog()
    catalog.set_price("A", 9.99)
    catalog.set_price("A", 7.5)
    assert catalog.price_of("A") == pytest.approx(7.5)


def test_price_of_unknown_sku():
    catalog = PriceCatalog()
    with pytest.raises(UnknownSKUError):
        catalog.price_of("NOPE")


# --- discounts: strategy injection ---

def test_discounted_price_no_coupon():
    catalog = PriceCatalog()
    catalog.set_price("A", 5.0)
    assert catalog.discounted_price("A", 3) == pytest.approx(15.0)


def test_discounted_price_percent_off():
    catalog = PriceCatalog()
    catalog.set_price("A", 5.0)
    catalog.register_discount("SAVE10", percent_discount(10))
    assert catalog.discounted_price("A", 3, "SAVE10") == pytest.approx(13.5)


def test_discounted_price_amount_off():
    catalog = PriceCatalog()
    catalog.set_price("A", 5.0)
    catalog.register_discount("FULL100", amount_off(100, 20))
    assert catalog.discounted_price("A", 21, "FULL100") == pytest.approx(85.0)
    assert catalog.discounted_price("A", 19, "FULL100") == pytest.approx(95.0)


def test_discounted_price_unknown_sku():
    catalog = PriceCatalog()
    catalog.set_price("A", 5.0)
    with pytest.raises(UnknownSKUError):
        catalog.discounted_price("NOPE", 1)


@pytest.mark.parametrize("bad", [0, -2, 1.5, "3", None, True])
def test_discounted_price_rejects_bad_qty(bad):
    catalog = PriceCatalog()
    catalog.set_price("A", 5.0)
    with pytest.raises(InvalidQuantityError):
        catalog.discounted_price("A", bad)


def test_discounted_price_unknown_coupon():
    catalog = PriceCatalog()
    catalog.set_price("A", 5.0)
    with pytest.raises(InvalidCouponError):
        catalog.discounted_price("A", 1, "NOPE")


# --- Order / OrderLine ---

def test_order_lines_and_total_is_pure():
    order = Order("Cust", [OrderLine("A", 2, 5.0), OrderLine("B", 3, 2.0)])
    assert order.lines[0].total == pytest.approx(10.0)
    assert order.total() == pytest.approx(16.0)


# --- place_order happy path ---

def test_place_order_deducts_stock_and_prices(shop):
    inv, catalog = shop
    order = place_order(catalog, inv, [("A", 2), ("B", 3)], customer="Alice")
    assert order.customer == "Alice"
    assert order.lines == [OrderLine("A", 2, 5.0), OrderLine("B", 3, 2.0)]
    assert order.total() == pytest.approx(16.0)
    assert inv.stock_level("A") == 8
    assert inv.stock_level("B") == 2


def test_place_order_exact_stock(shop):
    inv, catalog = shop
    place_order(catalog, inv, [("A", 10)], customer="Bob")
    assert inv.stock_level("A") == 0


def test_place_order_with_discount(shop):
    inv, catalog = shop
    catalog.register_discount("SAVE10", percent_discount(10))
    order = place_order(
        catalog, inv, [("A", 2), ("B", 3)], customer="Alice", coupon_code="SAVE10"
    )
    assert order.total() == pytest.approx(14.4)
    assert inv.stock_level("A") == 8
    assert inv.stock_level("B") == 2


# --- atomicity: failures must never deduct stock (defects 2 & 5 regressions) ---

def test_place_order_insufficient_stock_does_not_deduct(shop):
    inv, catalog = shop
    with pytest.raises(InsufficientStockError):
        place_order(catalog, inv, [("A", 11)], customer="Bob")
    assert inv.stock_level("A") == 10


def test_place_order_insufficient_in_later_line_does_not_deduct(shop):
    inv, catalog = shop
    with pytest.raises(InsufficientStockError):
        place_order(catalog, inv, [("A", 1), ("B", 99)], customer="Bob")
    assert inv.stock_level("A") == 10
    assert inv.stock_level("B") == 5


def test_place_order_unknown_sku_does_not_deduct(shop):
    inv, catalog = shop
    with pytest.raises(UnknownSKUError):
        place_order(catalog, inv, [("A", 1), ("NOPE", 1)], customer="Bob")
    assert inv.stock_level("A") == 10


def test_place_order_unpriced_sku_does_not_deduct(shop):
    inv, catalog = shop
    inv.add_item("C", "Cherry")
    inv.restock("C", 3)
    with pytest.raises(UnknownSKUError):
        place_order(catalog, inv, [("A", 1), ("C", 1)], customer="Bob")
    assert inv.stock_level("A") == 10
    assert inv.stock_level("C") == 3


@pytest.mark.parametrize("bad", [0, -1, 2.5, "3", None, True])
def test_place_order_invalid_qty_does_not_deduct(shop, bad):
    inv, catalog = shop
    with pytest.raises(InvalidQuantityError):
        place_order(catalog, inv, [("A", bad)], customer="Bob")
    assert inv.stock_level("A") == 10


def test_place_order_invalid_coupon_rolls_back_deducted_stock(shop):
    # Regression for defect 2: stock is deducted, THEN pricing/discount
    # resolution fails -> stock must be restored.
    inv, catalog = shop
    with pytest.raises(InvalidCouponError):
        place_order(
            catalog, inv, [("A", 2), ("B", 3)], customer="Bob", coupon_code="NOPE"
        )
    assert inv.stock_level("A") == 10
    assert inv.stock_level("B") == 5


# --- defect 5 regression: exactly one deduction, total independent of ledger ---

def test_order_total_does_not_require_inventory(shop):
    inv, catalog = shop
    order = place_order(catalog, inv, [("A", 2)], customer="Alice")
    assert order.total() == pytest.approx(10.0)


def test_place_order_deducts_stock_exactly_once(shop):
    inv, catalog = shop
    order = place_order(catalog, inv, [("A", 2), ("B", 3)], customer="Alice")
    assert inv.stock_level("A") == 8
    assert inv.stock_level("B") == 2
    assert order.total() == pytest.approx(16.0)
