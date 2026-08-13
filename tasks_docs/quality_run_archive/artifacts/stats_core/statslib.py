import math


def mean(data):
    if not data:
        raise ValueError("mean requires at least one value")
    return sum(data) / len(data)


def median(data):
    if not data:
        raise ValueError("median requires at least one value")
    ordered = sorted(data)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def mode(data):
    if not data:
        raise ValueError("mode requires at least one value")
    counts = {}
    order = []
    for value in data:
        if value not in counts:
            counts[value] = 0
            order.append(value)
        counts[value] += 1
    max_count = max(counts.values())
    return [value for value in order if counts[value] == max_count]


def variance(data, population=True):
    if not data:
        raise ValueError("variance requires at least one value")
    n = len(data)
    mu = sum(data) / n
    total = sum((x - mu) ** 2 for x in data)
    denominator = n if population else n - 1
    if denominator == 0:
        return 0.0
    return total / denominator


def percentile(data, p):
    if not data:
        raise ValueError("percentile requires at least one value")
    if not 0 <= p <= 100:
        raise ValueError(f"percentile must be between 0 and 100, got {p}")
    ordered = sorted(data)
    n = len(ordered)
    rank = (n - 1) * (p / 100)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def pearson(x, y):
    if len(x) < 2 or len(y) < 2:
        raise ValueError("pearson requires at least two paired values")
    if len(x) != len(y):
        raise ValueError("pearson requires x and y of equal length")
    n = len(x)
    mu_x = sum(x) / n
    mu_y = sum(y) / n
    sum_xy = sum((xi - mu_x) * (yi - mu_y) for xi, yi in zip(x, y))
    sum_xx = sum((xi - mu_x) ** 2 for xi in x)
    sum_yy = sum((yi - mu_y) ** 2 for yi in y)
    denominator = math.sqrt(sum_xx * sum_yy)
    if denominator == 0:
        return 0.0
    return sum_xy / denominator
