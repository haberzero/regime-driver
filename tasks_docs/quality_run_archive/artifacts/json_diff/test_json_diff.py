from json_diff import MISSING, diff


def test_deeply_nested():
    a = {"a": {"b": {"c": {"d": 1}}}}
    b = {"a": {"b": {"c": {"d": 2}}}}
    assert diff(a, b) == [("a.b.c.d", "changed", 1, 2)]


def test_deeply_nested_added_and_removed():
    a = {"a": {"b": {"x": 1}}}
    b = {"a": {"b": {"y": 2}}}
    assert diff(a, b) == [
        ("a.b.x", "removed", 1, MISSING),
        ("a.b.y", "added", MISSING, 2),
    ]


def test_list_by_index():
    a = {"items": [10, 20, 30]}
    b = {"items": [10, 99, 30]}
    assert diff(a, b) == [("items.1", "changed", 20, 99)]


def test_list_index_path_with_dict():
    a = {"rows": [{"id": 1}, {"id": 2}]}
    b = {"rows": [{"id": 1}, {"id": 3}]}
    assert diff(a, b) == [("rows.1.id", "changed", 2, 3)]


def test_list_length_difference():
    a = {"items": [1, 2, 3]}
    b = {"items": [1, 2]}
    assert diff(a, b) == [("items.2", "removed", 3, MISSING)]


def test_list_length_difference_grows():
    a = {"items": [1, 2]}
    b = {"items": [1, 2, 3, 4]}
    assert diff(a, b) == [
        ("items.2", "added", MISSING, 3),
        ("items.3", "added", MISSING, 4),
    ]


def test_scalar_type_change():
    assert diff({"v": 1}, {"v": "1"}) == [("v", "changed", 1, "1")]
    assert diff({"v": "x"}, {"v": 1}) == [("v", "changed", "x", 1)]
    assert diff({"v": 1}, {"v": 2.5}) == [("v", "changed", 1, 2.5)]


def test_container_type_change():
    a = {"v": {"x": 1}}
    b = {"v": [1]}
    assert diff(a, b) == [("v", "changed", {"x": 1}, [1])]


def test_float_approximation():
    assert diff({"v": 0.1 + 0.2}, {"v": 0.3}) == []
    assert diff({"v": 0.30000000000000004}, {"v": 0.3}) == []


def test_float_change_beyond_tolerance():
    assert diff({"v": 0.1}, {"v": 0.2}) == [("v", "changed", 0.1, 0.2)]


def test_int_float_equivalence():
    assert diff({"v": 1}, {"v": 1.0}) == []


def test_identical_inputs_empty():
    a = {"a": 1, "b": [1, 2, {"c": 0.1 + 0.2}], "c": None}
    assert diff(a, dict(a)) == []
    assert diff(a, a) == []


def test_none_participates():
    assert diff({"v": None}, {"v": 1}) == [("v", "changed", None, 1)]
    assert diff({"v": 1}, {"v": None}) == [("v", "changed", 1, None)]
    assert diff({"v": None}, {"v": None}) == []
    assert diff({}, {"v": None}) == [("v", "added", MISSING, None)]


def test_bool_participates():
    assert diff({"v": True}, {"v": False}) == [("v", "changed", True, False)]
    assert diff({"v": True}, {"v": 1}) == [("v", "changed", True, 1)]
    assert diff({"v": 0}, {"v": False}) == [("v", "changed", 0, False)]


def test_stability_sorted_by_path():
    a = {"z": 1, "m": 1, "a": 1}
    b = {"z": 2, "m": 2, "a": 2}
    assert diff(a, b) == [
        ("a", "changed", 1, 2),
        ("m", "changed", 1, 2),
        ("z", "changed", 1, 2),
    ]


def test_stability_numeric_index_lexicographic():
    a = {"list": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]}
    b = {"list": [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]}
    paths = [change[0] for change in diff(a, b)]
    assert paths == sorted(paths)


def test_root_container_difference():
    assert diff({"a": 1}, [1]) == [("", "changed", {"a": 1}, [1])]
