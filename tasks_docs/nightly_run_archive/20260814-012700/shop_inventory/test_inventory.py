import threading

import pytest

from errors import (
    InsufficientStockError,
    InvalidQuantityError,
    UnknownSKUError,
)
from inventory import Inventory


def make_inventory():
    inv = Inventory()
    inv.add_item("A", "Apple")
    return inv


# --- add_item / SKU + name management (defect 1 regression) ---

def test_add_item_registers_sku_with_zero_stock():
    inv = make_inventory()
    assert inv.has_sku("A")
    assert inv.stock_level("A") == 0
    assert inv.name_of("A") == "Apple"


def test_add_item_updates_existing_name():
    inv = make_inventory()
    inv.add_item("A", "Granny Smith Apple")
    assert inv.name_of("A") == "Granny Smith Apple"
    assert inv.stock_level("A") == 0


def test_add_item_preserves_existing_stock():
    inv = make_inventory()
    inv.restock("A", 3)
    inv.add_item("A", "Renamed Apple")
    assert inv.stock_level("A") == 3


def test_add_item_unknown_skus():
    inv = Inventory()
    with pytest.raises(UnknownSKUError):
        inv.add_item("", "Empty")
    with pytest.raises(UnknownSKUError):
        inv.add_item(None, "None")


# --- restock (defect 3 regression) ---

def test_restock_increases_stock():
    inv = make_inventory()
    inv.restock("A", 5)
    assert inv.stock_level("A") == 5
    inv.restock("A", 2)
    assert inv.stock_level("A") == 7


@pytest.mark.parametrize("bad", [0, -1, -100, 1.5, "3", None, True])
def test_restock_rejects_bad_quantity(bad):
    inv = make_inventory()
    inv.restock("A", 5)
    with pytest.raises(InvalidQuantityError):
        inv.restock("A", bad)
    assert inv.stock_level("A") == 5


def test_restock_unknown_sku():
    inv = Inventory()
    with pytest.raises(UnknownSKUError):
        inv.restock("NOPE", 1)


# --- take ---

def test_take_decrements_stock():
    inv = make_inventory()
    inv.restock("A", 10)
    inv.take("A", 3)
    assert inv.stock_level("A") == 7


def test_take_exact_amount_leaves_zero():
    inv = make_inventory()
    inv.restock("A", 4)
    inv.take("A", 4)
    assert inv.stock_level("A") == 0


def test_take_insufficient_stock_raises_with_fields():
    inv = make_inventory()
    inv.restock("A", 2)
    with pytest.raises(InsufficientStockError) as exc:
        inv.take("A", 3)
    assert exc.value.sku == "A"
    assert exc.value.requested == 3
    assert exc.value.available == 2
    assert inv.stock_level("A") == 2


def test_take_unknown_sku():
    inv = Inventory()
    with pytest.raises(UnknownSKUError):
        inv.take("NOPE", 1)


@pytest.mark.parametrize("bad", [0, -5, 1.5, "2", None, True])
def test_take_rejects_bad_quantity(bad):
    inv = make_inventory()
    inv.restock("A", 5)
    with pytest.raises(InvalidQuantityError):
        inv.take("A", bad)
    assert inv.stock_level("A") == 5


# --- stock_level / name_of ---

def test_stock_level_unknown_sku():
    inv = Inventory()
    with pytest.raises(UnknownSKUError):
        inv.stock_level("NOPE")


def test_name_of_unknown_sku():
    inv = Inventory()
    with pytest.raises(UnknownSKUError):
        inv.name_of("NOPE")


# --- concurrency: barrier race, no lost updates ---

def test_concurrent_restock_take_no_lost_updates():
    inv = make_inventory()
    initial = 2000
    inv.restock("A", initial)

    n_threads = 8
    per_thread = 250
    barrier = threading.Barrier(n_threads * 2)

    def restock_worker():
        barrier.wait()
        for _ in range(per_thread):
            inv.restock("A", 1)

    def take_worker():
        barrier.wait()
        for _ in range(per_thread):
            inv.take("A", 1)

    threads = [threading.Thread(target=restock_worker) for _ in range(n_threads)]
    threads += [threading.Thread(target=take_worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert inv.stock_level("A") == initial
