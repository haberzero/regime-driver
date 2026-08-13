import pytest

from anagram import group_anagrams, is_anagram


def test_basic_anagrams():
    assert is_anagram("listen", "silent")
    assert is_anagram("anagram", "nagaram")
    assert is_anagram("abc", "cba")


def test_non_anagrams():
    assert not is_anagram("listen", "listens")
    assert not is_anagram("abc", "abd")
    assert not is_anagram("cat", "car")


def test_ignore_case_default_true():
    assert is_anagram("Tea", "ate")
    assert is_anagram("Listen", "SILENT")
    assert not is_anagram("Tea", "ate", ignore_case=False)


def test_case_sensitive_mode():
    assert is_anagram("Tea", "ate", ignore_case=False) is False
    assert is_anagram("cat", "cat", ignore_case=False)
    assert not is_anagram("CAT", "cat", ignore_case=False)


def test_ignore_punct():
    assert is_anagram("a b c", "abc", ignore_punct=True)
    assert is_anagram("a.b,c!", "abc", ignore_punct=True)
    assert not is_anagram("a b c", "abc")
    assert is_anagram("hello world", "droll woe hl", ignore_punct=True)


def test_ignore_unicode_whitespace():
    assert is_anagram("a\tb\nc", "abc", ignore_punct=True)
    assert is_anagram("a\u00a0b", "ab", ignore_punct=True)


def test_unicode_chinese():
    assert is_anagram("你好", "好你")
    assert is_anagram("研究", "究研")
    assert not is_anagram("你好", "研究")


def test_unicode_accents():
    assert is_anagram("café", "éfac")
    assert is_anagram("déjà vu", "vu déjà", ignore_punct=True)


def test_unicode_casefold():
    assert is_anagram("Straße", "STRASSE")
    assert is_anagram("Äpfel", "läpfe", ignore_punct=True)


def test_empty_strings():
    assert is_anagram("", "")
    assert not is_anagram("", "a")
    assert not is_anagram("a", "")


def test_empty_with_punct():
    assert is_anagram("!!!", "", ignore_punct=True)
    assert is_anagram("  ", "", ignore_punct=True)
    assert not is_anagram("!!!", "", ignore_punct=False)


def test_group_basic():
    assert group_anagrams(["eat", "tea", "tan", "ate", "nat", "bat"]) == [
        ["eat", "tea", "ate"],
        ["tan", "nat"],
        ["bat"],
    ]


def test_group_keeps_relative_order():
    assert group_anagrams(["tea", "eat", "ate"]) == [["tea", "eat", "ate"]]


def test_group_orders_by_first_occurrence():
    assert group_anagrams(["cat", "dog", "tac", "god"]) == [
        ["cat", "tac"],
        ["dog", "god"],
    ]


def test_group_empty_list():
    assert group_anagrams([]) == []


def test_group_single_word():
    assert group_anagrams(["hello"]) == [["hello"]]


def test_group_ignore_case():
    assert group_anagrams(["Eat", "ate", "Tea"], ignore_case=True) == [
        ["Eat", "ate", "Tea"]
    ]
    assert group_anagrams(["Eat", "ate"], ignore_case=False) == [["Eat"], ["ate"]]


def test_group_ignore_punct():
    assert group_anagrams(
        ["a.b", "ab", "c a"], ignore_punct=True
    ) == [["a.b", "ab"], ["c a"]]


def test_group_empty_strings():
    assert group_anagrams(["", "a", "!"], ignore_punct=True) == [
        ["", "!"],
        ["a"],
    ]
    assert group_anagrams(["", "", "a"]) == [["", ""], ["a"]]


def test_group_unicode():
    assert group_anagrams(["你好", "好你", "研究"]) == [
        ["你好", "好你"],
        ["研究"],
    ]
