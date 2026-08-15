import threading
from decimal import Decimal

import pytest

from errors import (
    InsufficientStockError,
    InvalidCouponError,
    InvalidPriceError,
    InvalidQuantityError,
    ShopError,
    UnknownSKUError,
)
from inventory import Inventory
from pricing import PriceCatalog


@pytest.fixture
def inventory():
    inv = Inventory()
    inv.add_item("SKU-A", "widget")
    return inv


def test_add_item_registers_new_sku():
    inv = Inventory()
    inv.add_item("SKU-A", "widget")
    assert inv.stock_level("SKU-A") == 0
    assert inv.name_of("SKU-A") == "widget"


def test_add_item_updates_name_for_existing_sku(inventory):
    inventory.add_item("SKU-A", "deluxe widget")
    assert inventory.name_of("SKU-A") == "deluxe widget"


def test_add_item_update_keeps_stock(inventory):
    inventory.restock("SKU-A", 5)
    inventory.add_item("SKU-A", "deluxe widget")
    assert inventory.stock_level("SKU-A") == 5


def test_add_item_invalid_sku_raises():
    inv = Inventory()
    with pytest.raises(TypeError):
        inv.add_item("", "widget")
    with pytest.raises(TypeError):
        inv.add_item("SKU-A", "")


def test_restock_increases_stock(inventory):
    inventory.restock("SKU-A", 5)
    assert inventory.stock_level("SKU-A") == 5


def test_restock_negative_raises(inventory):
    with pytest.raises(InvalidQuantityError) as exc:
        inventory.restock("SKU-A", -1)
    assert exc.value.sku == "SKU-A"
    assert exc.value.qty == -1
    assert "invalid quantity" in exc.value.message


def test_restock_zero_raises(inventory):
    with pytest.raises(InvalidQuantityError):
        inventory.restock("SKU-A", 0)


def test_restock_invalid_qty_type_raises(inventory):
    for bad in ("5", 2.5, True, None):
        with pytest.raises(InvalidQuantityError):
            inventory.restock("SKU-A", bad)


def test_restock_unknown_sku_raises(inventory):
    with pytest.raises(UnknownSKUError) as exc:
        inventory.restock("GHOST", 1)
    assert exc.value.sku == "GHOST"


def test_take_decreases_stock(inventory):
    inventory.restock("SKU-A", 5)
    inventory.take("SKU-A", 2)
    assert inventory.stock_level("SKU-A") == 3


def test_take_insufficient_raises_and_does_not_deduct(inventory):
    inventory.restock("SKU-A", 2)
    with pytest.raises(InsufficientStockError) as exc:
        inventory.take("SKU-A", 3)
    assert exc.value.sku == "SKU-A"
    assert exc.value.requested == 3
    assert exc.value.available == 2
    assert inventory.stock_level("SKU-A") == 2


def test_take_unknown_sku_raises(inventory):
    with pytest.raises(UnknownSKUError):
        inventory.take("GHOST", 1)


def test_take_invalid_qty_raises(inventory):
    for bad in (-1, 0, "2", 2.5, True):
        with pytest.raises(InvalidQuantityError):
            inventory.take("SKU-A", bad)


def test_stock_level_unknown_sku_raises(inventory):
    with pytest.raises(UnknownSKUError):
        inventory.stock_level("GHOST")


def test_set_price_accepts_valid_inputs():
    catalog = PriceCatalog()
    catalog.set_price("SKU-A", 10)
    catalog.set_price("SKU-B", "19.99")
    catalog.set_price("SKU-C", 4.5)
    assert catalog.price_of("SKU-A") == Decimal("10")
    assert catalog.price_of("SKU-B") == Decimal("19.99")
    assert catalog.price_of("SKU-C") == Decimal("4.5")


def test_set_price_invalid_raises():
    catalog = PriceCatalog()
    for bad in (0, -5, "abc", True, None, float("inf")):
        with pytest.raises(InvalidPriceError) as exc:
            catalog.set_price("SKU-A", bad)
        assert exc.value.sku == "SKU-A"


def test_price_of_unknown_sku_raises():
    catalog = PriceCatalog()
    with pytest.raises(UnknownSKUError):
        catalog.price_of("GHOST")


def test_error_contracts():
    err = UnknownSKUError("X")
    assert err.sku == "X"
    assert "X" in err.message
    assert isinstance(err, ShopError)

    err = InsufficientStockError("X", 5, 2)
    assert (err.sku, err.requested, err.available) == ("X", 5, 2)

    err = InvalidQuantityError("X", -1)
    assert (err.sku, err.qty) == ("X", -1)

    err = InvalidPriceError("X", 0)
    assert (err.sku, err.price) == ("X", 0)

    err = InvalidCouponError("NOPE")
    assert err.coupon_code == "NOPE"
    assert "NOPE" in err.message

    assert str(UnknownSKUError("Y")) == "unknown sku: 'Y'"


def test_concurrent_restock_take_no_lost_stock():
    inv = Inventory()
    inv.add_item("SKU-C", "gadget")
    n_workers = 8
    per_thread = 10
    barrier = threading.Barrier(n_workers + 1)

    def worker():
        inv.restock("SKU-C", per_thread)
        barrier.wait()

    threads = [threading.Thread(target=worker) for _ in range(n_workers)]
    for t in threads:
        t.start()
    barrier.wait()
    for t in threads:
        t.join()

    assert inv.stock_level("SKU-C") == n_workers * per_thread

    take_barrier = threading.Barrier(n_workers + 1)

    def taker():
        take_barrier.wait()
        inv.take("SKU-C", per_thread)

    threads = [threading.Thread(target=taker) for _ in range(n_workers)]
    for t in threads:
        t.start()
    take_barrier.wait()
    for t in threads:
        t.join()

    assert inv.stock_level("SKU-C") == 0


def test_concurrent_restock_storm():
    inv = Inventory()
    inv.add_item("SKU-D", "thing")
    n = 50
    barrier = threading.Barrier(n)

    def worker():
        barrier.wait()
        inv.restock("SKU-D", 1)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert inv.stock_level("SKU-D") == n
