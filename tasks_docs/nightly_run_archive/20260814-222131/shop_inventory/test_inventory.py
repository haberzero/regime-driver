import threading

import pytest

from errors import (
    InsufficientStockError,
    InvalidPriceError,
    InvalidQuantityError,
    UnknownSKUError,
)
from inventory import Inventory


@pytest.fixture
def inv():
    return Inventory()


def test_add_item_registers_sku(inv):
    inv.add_item("A1", "apple", 1.5)
    assert inv.name_of("A1") == "apple"
    assert inv.stock_level("A1") == 0


def test_add_item_updates_name_and_price_for_existing_sku(inv):
    inv.add_item("A1", "apple", 1.5)
    inv.add_item("A1", "red apple", 2.0)
    assert inv.name_of("A1") == "red apple"
    assert inv.stock_level("A1") == 0


def test_rename(inv):
    inv.add_item("A1", "apple", 1.5)
    inv.rename("A1", "fresh apple")
    assert inv.name_of("A1") == "fresh apple"


def test_restock_and_stock_level(inv):
    inv.add_item("A1", "apple", 1.5)
    inv.restock("A1", 5)
    inv.restock("A1", 3)
    assert inv.stock_level("A1") == 8


def test_restock_negative_raises(inv):
    inv.add_item("A1", "apple", 1.5)
    with pytest.raises(InvalidQuantityError) as exc:
        inv.restock("A1", -3)
    assert exc.value.fields["sku"] == "A1"
    assert exc.value.fields["quantity"] == -3
    assert inv.stock_level("A1") == 0


def test_restock_zero_raises(inv):
    inv.add_item("A1", "apple", 1.5)
    with pytest.raises(InvalidQuantityError):
        inv.restock("A1", 0)


def test_restock_non_integer_raises(inv):
    inv.add_item("A1", "apple", 1.5)
    with pytest.raises(InvalidQuantityError):
        inv.restock("A1", 1.5)


def test_restock_unknown_sku_raises(inv):
    with pytest.raises(UnknownSKUError) as exc:
        inv.restock("NOPE", 1)
    assert exc.value.fields["sku"] == "NOPE"


def test_take_success(inv):
    inv.add_item("A1", "apple", 1.5)
    inv.restock("A1", 5)
    inv.take("A1", 2)
    assert inv.stock_level("A1") == 3


def test_take_insufficient_raises(inv):
    inv.add_item("A1", "apple", 1.5)
    inv.restock("A1", 2)
    with pytest.raises(InsufficientStockError) as exc:
        inv.take("A1", 5)
    assert exc.value.fields["sku"] == "A1"
    assert exc.value.fields["requested"] == 5
    assert exc.value.fields["available"] == 2
    assert inv.stock_level("A1") == 2


def test_take_unknown_sku_raises(inv):
    with pytest.raises(UnknownSKUError):
        inv.take("NOPE", 1)


def test_take_invalid_quantity_raises(inv):
    inv.add_item("A1", "apple", 1.5)
    inv.restock("A1", 5)
    with pytest.raises(InvalidQuantityError):
        inv.take("A1", 0)
    with pytest.raises(InvalidQuantityError):
        inv.take("A1", -1)


def test_add_item_invalid_price_raises(inv):
    with pytest.raises(InvalidPriceError):
        inv.add_item("A1", "apple", 0)
    with pytest.raises(InvalidPriceError):
        inv.add_item("A1", "apple", -1)
    with pytest.raises(InvalidPriceError):
        inv.add_item("A1", "apple", "one")


def test_stock_level_unknown_sku_raises(inv):
    with pytest.raises(UnknownSKUError):
        inv.stock_level("NOPE")


def test_name_of_unknown_sku_raises(inv):
    with pytest.raises(UnknownSKUError):
        inv.name_of("NOPE")


def test_concurrent_restock_take_no_lost_updates():
    inv = Inventory()
    inv.add_item("A1", "apple", 1.5)
    initial = 200
    inv.restock("A1", initial)

    rounds = 50
    n_threads = 8
    barrier = threading.Barrier(n_threads)

    def restock_worker():
        barrier.wait()
        for _ in range(rounds):
            inv.restock("A1", 1)

    def take_worker():
        barrier.wait()
        for _ in range(rounds):
            inv.take("A1", 1)

    threads = []
    for i in range(n_threads):
        target = restock_worker if i % 2 == 0 else take_worker
        t = threading.Thread(target=target)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    assert inv.stock_level("A1") == initial
