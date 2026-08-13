import re


def camel_to_snake(name):
    """Convert camelCase to snake_case.

    Digit boundary convention (approved decision, 2026-08-12): digits attach
    to the preceding token; a split only occurs at a digit-to-uppercase
    boundary. Thus "version2Update" -> "version2_update" (not
    "version_2_update"). Round-trip safe: snake_to_camel of the result is
    idempotent under this function.
    """
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def snake_to_camel(name, upper_first=False):
    parts = name.split("_")
    if upper_first:
        return "".join(p.capitalize() for p in parts)
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def truncate(s, width, ellipsis="…"):
    if width <= 0:
        raise ValueError(f"width must be positive, got {width}")
    if len(s) <= width:
        return s
    if len(ellipsis) >= width:
        return s[:width]
    return s[: width - len(ellipsis)] + ellipsis


def word_wrap(text, width):
    if width <= 0:
        raise ValueError(f"width must be positive, got {width}")
    if text == "":
        return []
    words = text.split()
    lines = []
    current = ""
    for word in words:
        if len(word) > width:
            if current:
                lines.append(current)
                current = ""
            while len(word) > width:
                lines.append(word[:width])
                word = word[width:]
            current = word
        elif current and len(current) + 1 + len(word) <= width:
            current = current + " " + word
        elif current:
            lines.append(current)
            current = word
        else:
            current = word
    if current:
        lines.append(current)
    return lines


_PUNCT_RE = re.compile(r"[\W_]+", re.UNICODE)


def is_palindrome(s):
    cleaned = _PUNCT_RE.sub("", s).lower()
    return cleaned == cleaned[::-1]
