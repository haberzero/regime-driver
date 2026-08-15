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
from pricing import PriceCatalog


@pytest.fixture
def shop():
    inv = Inventory()
    catalog = PriceCatalog()
    for sku, name, price in (
        ("APPLE", "apple", 5),
        ("BANANA", "banana", 3),
        ("CHERRY", "cherry", 7),
    ):
        inv.add_item(sku, name)
        catalog.set_price(sku, price)
        inv.restock(sku, 10)
    return inv, catalog


def test_place_order_happy_path(shop):
    inv, catalog = shop
    order = place_order(catalog, inv, [("APPLE", 2), ("BANANA", 3)])
    assert order.customer is None
    assert [line.sku for line in order.lines] == ["APPLE", "BANANA"]
    assert order.lines[0].unit_price == Decimal("5")
    assert order.lines[1].unit_price == Decimal("3")
    assert order.total == Decimal("19")
    assert inv.stock_level("APPLE") == 8
    assert inv.stock_level("BANANA") == 7
    assert inv.stock_level("CHERRY") == 10


def test_place_order_customer(shop):
    inv, catalog = shop
    order = place_order(catalog, inv, [("APPLE", 1)], customer="alice")
    assert order.customer == "alice"


def test_order_total_is_snapshot(shop):
    inv, catalog = shop
    order = place_order(catalog, inv, [("APPLE", 2)])
    assert order.total == Decimal("10")
    catalog.set_price("APPLE", 100)
    assert order.total == Decimal("10")


def test_order_total_from_lines():
    order = Order(
        "customer",
        [OrderLine("A", 2, Decimal("5")), OrderLine("B", 1, Decimal("3"))],
    )
    assert order.total == Decimal("13")


def test_stock_deducted_exactly_once(shop):
    inv, catalog = shop
    before = inv.stock_level("APPLE")
    place_order(catalog, inv, [("APPLE", 4)])
    assert inv.stock_level("APPLE") == before - 4


def test_place_order_unknown_sku_no_stock_change(shop):
    inv, catalog = shop
    before = {sku: inv.stock_level(sku) for sku in ("APPLE", "BANANA", "CHERRY")}
    with pytest.raises(UnknownSKUError):
        place_order(catalog, inv, [("APPLE", 1), ("GHOST", 1)])
    for sku, level in before.items():
        assert inv.stock_level(sku) == level


def test_place_order_sku_not_in_catalog_rolls_back(shop):
    inv, catalog = shop
    inv.add_item("GHOST", "ghost")
    inv.restock("GHOST", 5)
    before = inv.stock_level("GHOST")
    with pytest.raises(UnknownSKUError):
        place_order(catalog, inv, [("GHOST", 1)])
    assert inv.stock_level("GHOST") == before


def test_place_order_insufficient_rolls_back_first_line(shop):
    inv, catalog = shop
    before_apple = inv.stock_level("APPLE")
    with pytest.raises(InsufficientStockError):
        place_order(catalog, inv, [("APPLE", 2), ("CHERRY", 999)])
    assert inv.stock_level("APPLE") == before_apple
    assert inv.stock_level("CHERRY") == 10


def test_place_order_empty_allowed(shop):
    inv, catalog = shop
    order = place_order(catalog, inv, [])
    assert order.lines == ()
    assert order.total == Decimal("0")


def test_place_order_invalid_qty_no_deduction(shop):
    inv, catalog = shop
    before = inv.stock_level("APPLE")
    for bad in (0, -2, True, 2.5, "3"):
        with pytest.raises(InvalidQuantityError):
            place_order(catalog, inv, [("APPLE", bad)])
        assert inv.stock_level("APPLE") == before


def test_threshold_discount_strategy():
    catalog = PriceCatalog()
    catalog.set_price("BOOK", 40)

    def threshold_discount(base, qty, coupon_code):
        total = base * qty
        if total >= 100:
            total -= 30
        return total

    catalog.set_discount_strategy(threshold_discount)
    assert catalog.discounted_price("BOOK", 2, None) == Decimal("80")
    assert catalog.discounted_price("BOOK", 3, None) == Decimal("90")


def test_percent_discount_strategy():
    catalog = PriceCatalog()
    catalog.set_price("GADGET", 20)

    def percent_discount(base, qty, coupon_code):
        if coupon_code != "SAVE10":
            raise InvalidCouponError(coupon_code)
        return base * qty * Decimal("0.9")

    catalog.set_discount_strategy(percent_discount)
    assert catalog.discounted_price("GADGET", 2, "SAVE10") == Decimal("36")
    with pytest.raises(InvalidCouponError):
        catalog.discounted_price("GADGET", 2, "NOPE")


def test_discount_no_strategy_no_coupon():
    catalog = PriceCatalog()
    catalog.set_price("ITEM", 4)
    assert catalog.discounted_price("ITEM", 3) == Decimal("12")


def test_discount_no_strategy_with_coupon_raises():
    catalog = PriceCatalog()
    catalog.set_price("ITEM", 4)
    with pytest.raises(InvalidCouponError):
        catalog.discounted_price("ITEM", 3, "SAVE")


def test_discount_strategy_receives_expected_args():
    catalog = PriceCatalog()
    catalog.set_price("ITEM", 4)
    calls = []

    def spy(base, qty, coupon_code):
        calls.append((base, qty, coupon_code))
        return base * qty

    catalog.set_discount_strategy(spy)
    catalog.discounted_price("ITEM", 2, "COUP")
    assert calls == [(Decimal("4"), 2, "COUP")]


def test_discounted_price_unknown_sku_raises():
    catalog = PriceCatalog()
    with pytest.raises(UnknownSKUError):
        catalog.discounted_price("GHOST", 1)


def test_discounted_price_invalid_qty_raises():
    catalog = PriceCatalog()
    catalog.set_price("ITEM", 4)
    for bad in (0, -1, True, "2", 2.5):
        with pytest.raises(InvalidQuantityError):
            catalog.discounted_price("ITEM", bad, None)
