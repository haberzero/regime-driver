def _normalize(s, ignore_case, ignore_punct):
    if ignore_punct:
        s = "".join(ch for ch in s if ch.isalnum())
    if ignore_case:
        s = s.casefold()
    return s


def _anagram_key(s, ignore_case, ignore_punct):
    return "".join(sorted(_normalize(s, ignore_case, ignore_punct)))


def is_anagram(a, b, ignore_case=True, ignore_punct=False):
    """Return True if a and b are anagrams (same character multiset).

    Args:
        a, b: strings to compare.
        ignore_case: if True (default), fold case so "Tea" == "ate".
        ignore_punct: if True, drop non-alphanumeric characters
            (punctuation, spaces, Unicode whitespace) before comparing.
    """
    return _anagram_key(a, ignore_case, ignore_punct) == _anagram_key(
        b, ignore_case, ignore_punct
    )


def group_anagrams(words, ignore_case=True, ignore_punct=False):
    """Group words into anagram groups.

    Each group preserves the relative order of its words as they appear in
    the input. Groups are emitted ordered by the position of their first word
    in the original list. An empty input yields [].
    """
    groups = {}
    for word in words:
        key = _anagram_key(word, ignore_case, ignore_punct)
        groups.setdefault(key, []).append(word)
    return list(groups.values())
