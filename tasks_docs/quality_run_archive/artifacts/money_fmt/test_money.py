import pytest
from decimal import Decimal, ROUND_HALF_DOWN, ROUND_HALF_UP

from money import fmt


def test_thousands_grouping():
    assert fmt(1234.56) == "1,234.56"
    assert fmt(1234567) == "1,234,567.00"
    assert fmt(1234567890123) == "1,234,567,890,123.00"


def test_custom_thousands_separator():
    assert fmt(1234567.89, thousands=".") == "1.234.567.89"
    assert fmt(1234567890123, thousands=" ") == "1 234 567 890 123.00"


def test_negative_minus_prefix():
    assert fmt(-1234.56) == "-1,234.56"
    assert fmt(-1) == "-1.00"


def test_negative_parens():
    assert fmt(-1234.56, negative="parens") == "(1,234.56)"
    assert fmt(-1, negative="parens") == "(1.00)"


def test_half_up_default():
    assert fmt(2.675) == "2.68"
    assert fmt(1.005) == "1.01"


def test_half_down_rounding():
    assert fmt(2.675, rounding=ROUND_HALF_DOWN) == "2.67"
    assert fmt(1.005, rounding=ROUND_HALF_DOWN) == "1.00"


def test_negative_half_rounding():
    assert fmt(-2.675) == "-2.68"
    assert fmt(-2.675, rounding=ROUND_HALF_DOWN) == "-2.67"
    assert fmt(-2.675, negative="parens", rounding=ROUND_HALF_DOWN) == "(2.67)"


def test_rounding_modes_are_decimal_constants():
    assert fmt(2.675, rounding="ROUND_HALF_UP") == "2.68"


def test_large_numbers():
    assert fmt(10**18) == "1,000,000,000,000,000,000.00"
    assert fmt(12345678901234567890) == "12,345,678,901,234,567,890.00"
    assert (
        fmt(-10**18, negative="parens") == "(1,000,000,000,000,000,000.00)"
    )


def test_large_float_uses_decimal_str_no_binary_error():
    assert fmt(12345678901234567890.0) == "12,345,678,901,234,567,000.00"
    assert fmt(0.1 + 0.2) == "0.30"


def test_zero_and_negative_zero():
    assert fmt(0) == "0.00"
    assert fmt(0.0) == "0.00"
    assert fmt(-0.0) == "0.00"
    assert fmt(-0.0, negative="parens") == "0.00"


def test_tiny_negative_values_round_to_zero():
    assert fmt(-0.004) == "0.00"
    assert fmt(-1e-300) == "0.00"
    assert fmt(-0.005) == "-0.01"
    assert fmt(-0.005, rounding=ROUND_HALF_DOWN) == "0.00"


def test_zero_decimals():
    assert fmt(1234.56, decimals=0) == "1,235"
    assert fmt(999.6, decimals=0) == "1,000"


def test_three_decimals():
    assert fmt(1.2345, decimals=3) == "1.235"
    assert fmt(1.2345, decimals=3, rounding=ROUND_HALF_DOWN) == "1.234"


def test_negative_decimals_raises():
    with pytest.raises(ValueError):
        fmt(1.0, decimals=-1)
    with pytest.raises(ValueError):
        fmt(1.0, decimals=-5)


def test_non_finite_amounts_raise():
    with pytest.raises(ValueError):
        fmt(float("inf"))
    with pytest.raises(ValueError):
        fmt(float("-inf"))
    with pytest.raises(ValueError):
        fmt(float("nan"))
    with pytest.raises(ValueError):
        fmt(Decimal("Infinity"))


def test_invalid_negative_mode_raises():
    with pytest.raises(ValueError):
        fmt(1.0, negative="brackets")


def test_input_types():
    assert fmt("1234.56") == "1,234.56"
    assert fmt(1234) == "1,234.00"
    assert fmt(Decimal("1234.56")) == "1,234.56"
    assert fmt(Decimal("-1234.56")) == "-1,234.56"
