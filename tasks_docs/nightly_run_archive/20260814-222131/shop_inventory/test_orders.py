from decimal import Decimal

import pytest

from errors import (
    InsufficientStockError,
    InvalidCouponError,
    InvalidQuantityError,
    UnknownSKUError,
)
from inventory import Inventory
from orders import Order, OrderLine, place_order
from pricing import PriceCatalog, make_full_reduction, make_percent_off


@pytest.fixture
def catalog():
    c = PriceCatalog()
    c.set_price("A1", "1.50")
    c.set_price("B2", "3.00")
    c.set_price("C3", "10.00")
    return c


@pytest.fixture
def inventory():
    inv = Inventory()
    inv.add_item("A1", "apple", "1.50")
    inv.add_item("B2", "banana", "3.00")
    inv.add_item("C3", "cherry", "10.00")
    inv.restock("A1", 10)
    inv.restock("B2", 10)
    inv.restock("C3", 10)
    return inv


def test_price_catalog_basic(catalog):
    assert catalog.price_of("A1") == Decimal("1.50")


def test_price_of_unknown_sku_raises(catalog):
    with pytest.raises(UnknownSKUError):
        catalog.price_of("NOPE")


def test_set_price_invalid_raises():
    c = PriceCatalog()
    with pytest.raises(Exception) as exc:
        c.set_price("A1", 0)
    assert exc.value.fields["price"] == 0
    with pytest.raises(Exception):
        c.set_price("A1", -5)
    with pytest.raises(Exception):
        c.set_price("A1", "free")


def test_place_order_success(catalog, inventory):
    order = place_order(catalog, inventory, [("A1", 2), ("B2", 3)])
    assert isinstance(order, Order)
    assert order.customer is None
    assert len(order.lines) == 2
    line = order.lines[0]
    assert isinstance(line, OrderLine)
    assert line.sku == "A1"
    assert line.qty == 2
    assert line.unit_price == Decimal("1.50")
    assert line.amount == Decimal("3.00")
    assert order.total() == Decimal("12.00")
    assert inventory.stock_level("A1") == 8
    assert inventory.stock_level("B2") == 7


def test_place_order_unknown_sku_does_not_deduct(catalog, inventory):
    with pytest.raises(UnknownSKUError):
        place_order(catalog, inventory, [("A1", 1), ("NOPE", 1)])
    assert inventory.stock_level("A1") == 10


def test_place_order_insufficient_stock_does_not_deduct(catalog, inventory):
    with pytest.raises(InsufficientStockError) as exc:
        place_order(catalog, inventory, [("A1", 1), ("B2", 99)])
    assert exc.value.fields["sku"] == "B2"
    assert exc.value.fields["requested"] == 99
    assert exc.value.fields["available"] == 10
    assert inventory.stock_level("A1") == 10
    assert inventory.stock_level("B2") == 10


def test_place_order_invalid_quantity(catalog, inventory):
    with pytest.raises(InvalidQuantityError):
        place_order(catalog, inventory, [("A1", 0)])
    with pytest.raises(InvalidQuantityError):
        place_order(catalog, inventory, [("A1", -2)])
    with pytest.raises(InvalidQuantityError):
        place_order(catalog, inventory, [("A1", 1.5)])
    assert inventory.stock_level("A1") == 10


def test_place_order_invalid_coupon_rolls_back(catalog, inventory):
    catalog.set_discount_strategy(make_full_reduction(5, 1))
    with pytest.raises(InvalidCouponError):
        place_order(catalog, inventory, [("A1", 1)], coupon_code="SAVE10")
    assert inventory.stock_level("A1") == 10


def test_full_reduction_strategy(catalog, inventory):
    catalog.set_discount_strategy(make_full_reduction(5, 1))
    order = place_order(catalog, inventory, [("A1", 4)])  # 6.00 >= 5 -> 5.00
    assert order.total() == Decimal("5.00")
    order2 = place_order(catalog, inventory, [("A1", 1)])  # 1.50 < 5 -> no discount
    assert order2.total() == Decimal("1.50")


def test_percent_off_strategy(catalog, inventory):
    catalog.set_discount_strategy(make_percent_off(50))
    order = place_order(catalog, inventory, [("B2", 2)])  # 6.00 * 0.5 = 3.00
    assert order.total() == Decimal("3.00")


def test_percent_off_requires_coupon(catalog, inventory):
    catalog.set_discount_strategy(make_percent_off(20, required_coupon="SAVE20"))
    order = place_order(catalog, inventory, [("C3", 1)], coupon_code="SAVE20")
    assert order.total() == Decimal("8.00")
    with pytest.raises(InvalidCouponError):
        place_order(catalog, inventory, [("C3", 1)], coupon_code="WRONG")


def test_total_is_pure_no_catalog_dependency(catalog, inventory):
    order = place_order(catalog, inventory, [("A1", 2)])
    assert order.total() == Decimal("3.00")
    catalog.set_price("A1", "99.99")
    assert order.total() == Decimal("3.00")


def test_concurrent_place_orders_no_oversell(catalog, inventory):
    import threading

    n_threads = 8
    barrier = threading.Barrier(n_threads)
    success = []

    def worker():
        barrier.wait()
        while True:
            try:
                place_order(catalog, inventory, [("C3", 1)])
                success.append(1)
            except InsufficientStockError:
                break

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(success) == 10
    assert inventory.stock_level("C3") == 0
