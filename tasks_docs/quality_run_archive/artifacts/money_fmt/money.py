from decimal import Decimal, ROUND_HALF_UP, localcontext


def _to_decimal(amount):
    if isinstance(amount, float):
        return Decimal(str(amount))
    if isinstance(amount, str):
        return Decimal(amount)
    return Decimal(amount)


def _needed_precision(d, decimals):
    integer_digits = max(d.as_tuple().exponent + len(d.as_tuple().digits), 0)
    return max(28, integer_digits + decimals + 4)


def _group(integer, sep):
    parts = []
    while integer:
        parts.append(integer[-3:])
        integer = integer[:-3]
    return sep.join(reversed(parts))


def fmt(
    amount,
    decimals=2,
    thousands=",",
    negative="minus",
    rounding=ROUND_HALF_UP,
):
    if decimals < 0:
        raise ValueError(f"decimals must be >= 0, got {decimals}")
    if negative not in ("minus", "parens"):
        raise ValueError(
            f"negative must be 'minus' or 'parens', got {negative!r}"
        )

    d = _to_decimal(amount)
    if not d.is_finite():
        raise ValueError(f"amount must be finite, got {amount!r}")

    with localcontext() as ctx:
        ctx.prec = _needed_precision(d, decimals)
        q = d.quantize(Decimal(1).scaleb(-decimals), rounding=rounding)

    s = format(q, "f")
    is_neg = s.startswith("-") and not q.is_zero()
    s = s.lstrip("-")
    int_part, dot, frac_part = s.partition(".")
    if thousands:
        int_part = _group(int_part, thousands)
    body = int_part + dot + frac_part
    if is_neg:
        if negative == "parens":
            return f"({body})"
        return f"-{body}"
    return body
