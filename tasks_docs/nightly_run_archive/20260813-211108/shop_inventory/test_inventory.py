import threading

import pytest

from errors import (
    InsufficientStockError,
    InvalidQuantityError,
    UnknownSKUError,
)
from inventory import Inventory


@pytest.fixture
def inv():
    inv = Inventory()
    inv.add_item("A", "apple")
    return inv


def test_add_item_new_sku_has_zero_stock(inv):
    assert inv.stock_level("A") == 0
    assert inv.name_of("A") == "apple"


def test_add_item_existing_sku_updates_name(inv):
    inv.add_item("A", "red apple")
    assert inv.name_of("A") == "red apple"


def test_name_of_unknown_sku_raises(inv):
    with pytest.raises(UnknownSKUError) as exc:
        inv.name_of("NOPE")
    assert exc.value.sku == "NOPE"


def test_stock_level_unknown_sku_raises(inv):
    with pytest.raises(UnknownSKUError) as exc:
        inv.stock_level("NOPE")
    assert exc.value.sku == "NOPE"


def test_restock_and_stock_level(inv):
    inv.restock("A", 5)
    inv.restock("A", 3)
    assert inv.stock_level("A") == 8


def test_restock_zero_is_allowed(inv):
    inv.restock("A", 0)
    assert inv.stock_level("A") == 0


@pytest.mark.parametrize("bad", [-1, -100, 1.5, "5", None, True])
def test_restock_negative_or_non_int_raises(inv, bad):
    with pytest.raises(InvalidQuantityError) as exc:
        inv.restock("A", bad)
    assert exc.value.sku == "A"
    assert exc.value.quantity is bad
    assert inv.stock_level("A") == 0


def test_restock_unknown_sku_raises(inv):
    with pytest.raises(UnknownSKUError):
        inv.restock("NOPE", 5)


def test_take_deducts(inv):
    inv.restock("A", 10)
    inv.take("A", 3)
    assert inv.stock_level("A") == 7


def test_take_exactly_available_succeeds_and_depletes(inv):
    inv.restock("A", 5)
    inv.take("A", 5)
    assert inv.stock_level("A") == 0


def test_take_from_empty_stock_raises(inv):
    with pytest.raises(InsufficientStockError):
        inv.take("A", 1)
    assert inv.stock_level("A") == 0


def test_take_insufficient_stock_leaves_stock_untouched(inv):
    inv.restock("A", 2)
    with pytest.raises(InsufficientStockError) as exc:
        inv.take("A", 5)
    assert exc.value.sku == "A"
    assert exc.value.requested == 5
    assert exc.value.available == 2
    assert inv.stock_level("A") == 2


@pytest.mark.parametrize("bad", [-1, 0, 1.5, "5", None, True])
def test_take_invalid_quantity_raises(inv, bad):
    inv.restock("A", 10)
    with pytest.raises(InvalidQuantityError):
        inv.take("A", bad)
    assert inv.stock_level("A") == 10


def test_take_unknown_sku_raises(inv):
    with pytest.raises(UnknownSKUError):
        inv.take("NOPE", 1)


def test_concurrent_restock_take_no_lost_updates():
    inv = Inventory()
    inv.add_item("T", "thread item")
    inv.restock("T", 1000)

    n_threads = 32
    iterations = 50
    barrier = threading.Barrier(n_threads)
    errors = []

    def worker():
        try:
            barrier.wait()
            for _ in range(iterations):
                inv.restock("T", 1)
                inv.take("T", 1)
        except Exception as exc:  # pragma: no cover - unexpected
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert inv.stock_level("T") == 1000
