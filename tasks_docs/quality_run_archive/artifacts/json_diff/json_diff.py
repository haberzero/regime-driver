MISSING = object()


def diff(a, b):
    changes = []
    _diff(a, b, "", changes)
    changes.sort(key=lambda change: change[0])
    return changes


def _diff(a, b, path, changes):
    if isinstance(a, dict) and isinstance(b, dict):
        _diff_dict(a, b, path, changes)
    elif isinstance(a, list) and isinstance(b, list):
        _diff_list(a, b, path, changes)
    else:
        _diff_scalar(a, b, path, changes)


def _diff_dict(a, b, path, changes):
    for key in sorted(set(a) | set(b)):
        child_path = _join(path, key)
        if key not in a:
            changes.append((child_path, "added", MISSING, b[key]))
        elif key not in b:
            changes.append((child_path, "removed", a[key], MISSING))
        else:
            _diff(a[key], b[key], child_path, changes)


def _diff_list(a, b, path, changes):
    common = min(len(a), len(b))
    for index in range(common):
        _diff(a[index], b[index], _join(path, index), changes)
    for index in range(common, len(b)):
        changes.append((_join(path, index), "added", MISSING, b[index]))
    for index in range(common, len(a)):
        changes.append((_join(path, index), "removed", a[index], MISSING))


def _diff_scalar(a, b, path, changes):
    if not _scalar_equal(a, b):
        changes.append((path, "changed", a, b))


def _scalar_equal(a, b):
    a_is_bool = isinstance(a, bool)
    b_is_bool = isinstance(b, bool)
    if a_is_bool or b_is_bool:
        return a_is_bool and b_is_bool and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-9
    return a == b


def _join(path, part):
    if not path:
        return str(part)
    return f"{path}.{part}"
