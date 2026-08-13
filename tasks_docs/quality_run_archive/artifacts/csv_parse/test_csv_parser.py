import pytest

from csv_parser import parse


def test_empty_input():
    assert parse("") == []


def test_bom_only_input():
    assert parse("\ufeff") == []


def test_single_row():
    assert parse("a,b,c") == [["a", "b", "c"]]


def test_header_only():
    assert parse("name,age,city\n") == [["name", "age", "city"]]


def test_header_only_no_trailing_newline():
    assert parse("name,age") == [["name", "age"]]


def test_basic_rows():
    assert parse("a,b\nc,d\n") == [["a", "b"], ["c", "d"]]


def test_empty_lines_ignored():
    assert parse("a,b\n\nc,d\n\n") == [["a", "b"], ["c", "d"]]


def test_leading_and_trailing_blank_lines():
    assert parse("\na,b\n\n") == [["a", "b"]]


def test_trailing_delimiter():
    assert parse("a,b,\n") == [["a", "b", ""]]


def test_escaped_quotes():
    assert parse('"say ""hi""",x') == [['say "hi"', "x"]]


def test_escaped_quotes_adjacent():
    assert parse('""""') == [['"']]
    assert parse('"a""b"') == [["a\"b"]]


def test_quoted_field_with_delimiter():
    assert parse('"a,b",c') == [["a,b", "c"]]


def test_multiline_field_lf():
    assert parse('"line1\nline2",x') == [["line1\nline2", "x"]]


def test_multiline_field_crlf():
    assert parse('"line1\r\nline2",x') == [["line1\nline2", "x"]]


def test_multiline_field_in_middle_row():
    assert parse('a,b\n"x\n\nz",w\nc,d') == [
        ["a", "b"],
        ["x\n\nz", "w"],
        ["c", "d"],
    ]


def test_quoted_empty_field():
    assert parse('a,"",b') == [["a", "", "b"]]


def test_quote_in_unquoted_field_literal():
    assert parse('a"b,c') == [['a"b', "c"]]
    assert parse('x"y"z,q') == [['x"y"z', "q"]]


def test_crlf_rows():
    assert parse("a,b\r\nc,d\r\n") == [["a", "b"], ["c", "d"]]


def test_crlf_and_lf_mixed():
    assert parse("a,b\r\nc,d\ne,f\rg,h") == [
        ["a", "b"],
        ["c", "d"],
        ["e", "f"],
        ["g", "h"],
    ]


def test_bom_stripped():
    assert parse("\ufeffa,b\nc,d") == [["a", "b"], ["c", "d"]]


def test_bom_with_crlf():
    assert parse("\ufeffa,b\r\nc,d\r\n") == [["a", "b"], ["c", "d"]]


def test_comments_disabled_by_default():
    assert parse("# comment\na,b\n") == [["# comment"], ["a", "b"]]


def test_comments_enabled():
    assert parse("# comment\na,b\n# another\nc,d\n", comments=True) == [
        ["a", "b"],
        ["c", "d"],
    ]


def test_comment_not_at_line_start():
    assert parse("a,#b\n", comments=True) == [["a", "#b"]]


def test_comment_inside_quotes_kept():
    assert parse('# a\n"#b",c\n', comments=True) == [["#b", "c"]]


def test_comment_crlf_and_no_trailing_newline():
    assert parse("# c\r\na,b", comments=True) == [["a", "b"]]
    assert parse("# only", comments=True) == []


def test_custom_delimiter():
    assert parse('a;b;"x;y"', delimiter=";") == [["a", "b", "x;y"]]


def test_unclosed_quote_raises():
    with pytest.raises(ValueError, match="line 1"):
        parse('"abc,x')


def test_unclosed_quote_line_number():
    with pytest.raises(ValueError, match="line 2"):
        parse("a,b\n\"oops,x")


def test_unclosed_quote_line_number_multiline_field():
    with pytest.raises(ValueError, match="line 3"):
        parse('a,b\nc,d\n"oops\nx')
