import json

import pytest

from config_loader import ConfigError, load_config, validate


def write_json(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path


def test_load_config_missing_file(tmp_path):
    path = tmp_path / "nope.json"
    with pytest.raises(ConfigError) as exc:
        load_config(str(path))
    assert exc.value.path == str(path)
    assert "not found" in exc.value.reason


def test_load_config_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json")
    with pytest.raises(ConfigError) as exc:
        load_config(str(path))
    assert exc.value.path == str(path)
    assert "invalid JSON" in exc.value.reason


def test_load_config_valid(tmp_path):
    path = write_json(tmp_path, "good.json", {"name": "x"})
    assert load_config(str(path)) == {"name": "x"}


def test_validate_ok():
    config = {
        "name": "x",
        "count": 3,
        "ratio": 1.5,
        "flag": True,
        "items": [1, 2],
        "nested": {"a": 1},
    }
    schema = {
        "name": "str",
        "count": "int",
        "ratio": "float",
        "flag": "bool",
        "items": "list",
        "nested": {"a": "int"},
    }
    assert validate(config, schema) is None


def test_validate_missing_required_key():
    schema = {"name": "str", "count": "int"}
    with pytest.raises(ConfigError) as exc:
        validate({"name": "x"}, schema)
    assert exc.value.path == "count"
    assert "missing required key" in exc.value.reason


def test_validate_type_mismatch():
    schema = {"count": "int"}
    with pytest.raises(ConfigError) as exc:
        validate({"count": "3"}, schema)
    assert exc.value.path == "count"
    assert "expected int" in exc.value.reason


def test_validate_bool_not_accepted_as_int():
    schema = {"count": "int"}
    with pytest.raises(ConfigError):
        validate({"count": True}, schema)


def test_validate_int_accepted_for_float():
    schema = {"ratio": "float"}
    assert validate({"ratio": 2}, schema) is None


def test_validate_unknown_key():
    schema = {"name": "str"}
    with pytest.raises(ConfigError) as exc:
        validate({"name": "x", "extra": 1}, schema)
    assert exc.value.path == "extra"
    assert "unknown key" in exc.value.reason


def test_validate_nested_path_in_error():
    schema = {"a": {"b": {"c": "int"}}}
    with pytest.raises(ConfigError) as exc:
        validate({"a": {"b": {"c": "not-int"}}}, schema)
    assert exc.value.path == "a.b.c"
    assert "a.b.c" in str(exc.value)


def test_validate_nested_missing_required_key():
    schema = {"a": {"b": "int"}}
    with pytest.raises(ConfigError) as exc:
        validate({"a": {}}, schema)
    assert exc.value.path == "a.b"


def test_validate_nested_unknown_key():
    schema = {"a": {"b": "int"}}
    with pytest.raises(ConfigError) as exc:
        validate({"a": {"b": 1, "c": 2}}, schema)
    assert exc.value.path == "a.c"


def test_validate_nested_not_a_dict():
    schema = {"a": {"b": "int"}}
    with pytest.raises(ConfigError) as exc:
        validate({"a": 5}, schema)
    assert exc.value.path == "a"
    assert "expected dict" in exc.value.reason


def test_validate_optional_present_matches():
    schema = {"name": "str", "optional:count": "int"}
    assert validate({"name": "x", "count": 3}, schema) is None


def test_validate_optional_missing_ok():
    schema = {"name": "str", "optional:count": "int"}
    assert validate({"name": "x"}, schema) is None


def test_validate_optional_present_wrong_type():
    schema = {"optional:count": "int"}
    with pytest.raises(ConfigError) as exc:
        validate({"count": "3"}, schema)
    assert exc.value.path == "count"
    assert "type mismatch" in exc.value.reason
