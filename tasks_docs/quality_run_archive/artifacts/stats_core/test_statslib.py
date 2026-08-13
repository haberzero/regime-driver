import pytest

from statslib import mean, median, mode, pearson, percentile, variance


def test_mean_basic():
    assert mean([1, 2, 3, 4]) == 2.5
    assert mean([5]) == 5


def test_mean_empty_raises():
    with pytest.raises(ValueError, match="at least one"):
        mean([])


def test_median_odd_length():
    assert median([3, 1, 2]) == 2
    assert median([10, 5, 1, 8, 3]) == 5


def test_median_even_length():
    assert median([1, 2, 3, 4]) == 2.5
    assert median([4, 1, 3, 2]) == 2.5


def test_median_single_element():
    assert median([7]) == 7


def test_median_empty_raises():
    with pytest.raises(ValueError, match="at least one"):
        median([])


def test_mode_single():
    assert mode([1, 2, 2, 3]) == [2]


def test_mode_multiple_first_occurrence_order():
    assert mode([1, 2, 1, 2, 3]) == [1, 2]
    assert mode([3, 1, 3, 1]) == [3, 1]


def test_mode_all_distinct():
    assert mode([1, 2, 3]) == [1, 2, 3]


def test_mode_empty_raises():
    with pytest.raises(ValueError, match="at least one"):
        mode([])


def test_variance_population():
    assert variance([1, 2, 3, 4]) == 1.25
    assert variance([2, 2, 2]) == 0


def test_variance_sample():
    assert variance([1, 2, 3, 4], population=False) == pytest.approx(5 / 3)
    assert variance([1, 2, 3, 4, 5], population=False) == pytest.approx(2.5)


def test_variance_single_element():
    assert variance([7]) == 0
    assert variance([7], population=False) == 0


def test_variance_empty_raises():
    with pytest.raises(ValueError, match="at least one"):
        variance([])


def test_percentile_linear_interpolation():
    data = [1, 2, 3, 4]
    assert percentile(data, 0) == 1
    assert percentile(data, 100) == 4
    assert percentile(data, 50) == 2.5
    assert percentile(data, 25) == 1.75
    assert percentile(data, 75) == 3.25


def test_percentile_boundaries_and_single():
    assert percentile([5], 0) == 5
    assert percentile([5], 100) == 5
    assert percentile([5], 50) == 5


def test_percentile_unsorted_input():
    data = [4, 1, 3, 2]
    assert percentile(data, 50) == 2.5
    assert percentile(data, 0) == 1


def test_percentile_empty_raises():
    with pytest.raises(ValueError, match="at least one"):
        percentile([], 50)


def test_percentile_out_of_range_raises():
    with pytest.raises(ValueError):
        percentile([1, 2, 3], -1)
    with pytest.raises(ValueError):
        percentile([1, 2, 3], 101)


def test_pearson_positive_correlation():
    assert pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)


def test_pearson_negative_correlation():
    assert pearson([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)


def test_pearson_no_correlation():
    assert pearson([1, 2, 3, 4], [1, 1, 1, 1]) == pytest.approx(0.0)


def test_pearson_constant_vectors():
    assert pearson([5, 5, 5], [1, 2, 3]) == 0.0
    assert pearson([1, 2, 3], [7, 7, 7]) == 0.0
    assert pearson([4, 4, 4], [9, 9, 9]) == 0.0


def test_pearson_empty_raises():
    with pytest.raises(ValueError, match="at least two"):
        pearson([], [])


def test_pearson_single_element_raises():
    with pytest.raises(ValueError, match="at least two"):
        pearson([1], [2])


def test_pearson_unequal_lengths_raises():
    with pytest.raises(ValueError):
        pearson([1, 2, 3], [1, 2])
