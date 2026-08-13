import json


class ConfigError(Exception):
    def __init__(self, path, reason):
        self.path = path
        self.reason = reason
        super().__init__("config error at '%s': %s" % (path, reason))


def load_config(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        raise ConfigError(path, "file not found")
    except json.JSONDecodeError as e:
        raise ConfigError(path, "invalid JSON: %s" % e)
    except OSError as e:
        raise ConfigError(path, "unable to read file: %s" % e)


def validate(config, schema, path=""):
    if not isinstance(config, dict):
        raise ConfigError(path or "<root>", "expected a dict")

    specs = {}
    for raw_key, spec in schema.items():
        optional = False
        key = raw_key
        if key.startswith("optional:"):
            optional = True
            key = key[len("optional:"):]
        if isinstance(spec, str) and spec.startswith("optional:"):
            optional = True
            spec = spec[len("optional:"):]
        specs[key] = (optional, spec)

    for key in config:
        if key not in specs:
            full = "%s.%s" % (path, key) if path else key
            raise ConfigError(full, "unknown key")

    for key, (optional, spec) in specs.items():
        full = "%s.%s" % (path, key) if path else key
        if key not in config:
            if not optional:
                raise ConfigError(full, "missing required key")
            continue

        value = config[key]

        if isinstance(spec, dict):
            if not isinstance(value, dict):
                raise ConfigError(
                    full, "expected dict, got %s" % type(value).__name__
                )
            validate(value, spec, full)
            continue

        if not _type_matches(value, spec):
            raise ConfigError(
                full,
                "type mismatch: expected %s, got %s"
                % (spec, type(value).__name__),
            )


def _type_matches(value, expected):
    if expected == "str":
        return isinstance(value, str)
    if expected == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "float":
        return (
            isinstance(value, float)
            or (isinstance(value, int) and not isinstance(value, bool))
        )
    if expected == "bool":
        return isinstance(value, bool)
    if expected == "list":
        return isinstance(value, list)
    if expected == "dict":
        return isinstance(value, dict)
    return False
