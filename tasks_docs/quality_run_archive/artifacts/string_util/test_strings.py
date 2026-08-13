import pytest

from strings import (
    camel_to_snake,
    is_palindrome,
    snake_to_camel,
    truncate,
    word_wrap,
)


class TestCamelToSnake:
    def test_simple_camel(self):
        assert camel_to_snake("camelCase") == "camel_case"

    def test_continuous_uppercase(self):
        assert camel_to_snake("XMLHttp") == "xml_http"
        assert camel_to_snake("HTTPServer") == "http_server"
        assert camel_to_snake("ABCTest") == "abc_test"

    def test_digits(self):
        assert camel_to_snake("version2") == "version2"
        assert camel_to_snake("version2Update") == "version2_update"
        assert camel_to_snake("MIME2Text") == "mime2_text"
        assert camel_to_snake("build2x") == "build2x"

    def test_snake_input_unchanged(self):
        assert camel_to_snake("already_snake") == "already_snake"

    def test_empty_string(self):
        assert camel_to_snake("") == ""

    def test_single_lowercase(self):
        assert camel_to_snake("a") == "a"

    def test_single_uppercase(self):
        assert camel_to_snake("A") == "a"


class TestSnakeToCamel:
    def test_simple_snake(self):
        assert snake_to_camel("snake_case") == "snakeCase"

    def test_multiple_parts(self):
        assert snake_to_camel("foo_bar_baz") == "fooBarBaz"

    def test_upper_first(self):
        assert snake_to_camel("foo_bar", upper_first=True) == "FooBar"

    def test_empty_string(self):
        assert snake_to_camel("") == ""

    def test_single_word(self):
        assert snake_to_camel("word") == "word"
        assert snake_to_camel("word", upper_first=True) == "Word"


class TestTruncate:
    def test_short_string_unchanged(self):
        assert truncate("hello", 10) == "hello"

    def test_exact_width_no_ellipsis(self):
        assert truncate("hello", 5) == "hello"

    def test_basic_truncation(self):
        assert truncate("hello world", 8) == "hello w…"

    def test_ellipsis_custom(self):
        assert truncate("hello world", 8, ellipsis="...") == "hello..."

    def test_total_length_not_exceeding_width(self):
        result = truncate("a" * 100, 10)
        assert len(result) == 10
        assert result.endswith("…")

    def test_width_equal_ellipsis_length(self):
        assert truncate("abcdef", 1) == "a"
        assert truncate("abcdef", 2, ellipsis="..") == "ab"

    def test_width_less_than_ellipsis_length(self):
        assert truncate("abcdef", 2) == "a…"

    def test_ellipsis_longer_than_width(self):
        assert truncate("abcdef", 3, ellipsis="....") == "abc"

    def test_width_one(self):
        assert truncate("ab", 1) == "a"

    def test_non_positive_width_raises(self):
        with pytest.raises(ValueError):
            truncate("abc", 0)
        with pytest.raises(ValueError):
            truncate("abc", -5)

    def test_empty_string(self):
        assert truncate("", 5) == ""


class TestWordWrap:
    def test_simple_wrap(self):
        assert word_wrap("the quick brown fox", 10) == ["the quick", "brown fox"]

    def test_exact_fit(self):
        assert word_wrap("aa bb", 5) == ["aa bb"]

    def test_long_word_forced_break(self):
        assert word_wrap("aaaaaaa bb", 4) == ["aaaa", "aaa", "bb"]

    def test_word_longer_than_width(self):
        assert word_wrap("abcdef", 3) == ["abc", "def"]

    def test_single_word_fits(self):
        assert word_wrap("hello", 10) == ["hello"]

    def test_empty_string_returns_empty_list(self):
        assert word_wrap("", 10) == []

    def test_whitespace_only(self):
        assert word_wrap("   ", 10) == []

    def test_newlines_and_multiple_spaces(self):
        assert word_wrap("a  b\nc d", 5) == ["a b c", "d"]
        assert word_wrap("a b c", 3) == ["a b", "c"]

    def test_non_positive_width_raises(self):
        with pytest.raises(ValueError):
            word_wrap("abc", 0)
        with pytest.raises(ValueError):
            word_wrap("abc", -1)


class TestIsPalindrome:
    def test_ignores_case(self):
        assert is_palindrome("RaceCar") is True

    def test_ignores_spaces(self):
        assert is_palindrome("never odd or even") is True

    def test_ignores_punctuation(self):
        assert is_palindrome("A man, a plan, a canal: Panama") is True
        assert is_palindrome("Was it a car or a cat I saw?") is True

    def test_ignores_underscores(self):
        assert is_palindrome("_ab_a_") is True

    def test_non_palindrome(self):
        assert is_palindrome("hello") is False

    def test_empty_string(self):
        assert is_palindrome("") is True

    def test_single_char(self):
        assert is_palindrome("a") is True
        assert is_palindrome("!") is True

    def test_unicode(self):
        assert is_palindrome("Ännä") is True
