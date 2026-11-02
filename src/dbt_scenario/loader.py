import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from importlib.resources import files
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from dbt_scenario.errors import ScenarioError

TYPE_PATTERN = re.compile(
    r"^(bigint|integer|text|boolean|date|timestamp|timestamptz|numeric\(([1-9]\d?),([0-9]\d?)\))$"
)


class StrictLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            mark = self.peek_event().start_mark
            raise ScenarioError(
                "YAML_ALIAS_UNSUPPORTED", line=mark.line + 1, column=mark.column + 1
            )
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        try:
            if len(set(keys)) != len(keys):
                seen = set()
                for key, (key_node, _) in zip(keys, node.value, strict=True):
                    if key in seen:
                        mark = key_node.start_mark
                        raise ScenarioError(
                            "DUPLICATE_YAML_KEY", line=mark.line + 1, column=mark.column + 1
                        )
                    seen.add(key)
        except TypeError:
            raise ScenarioError("INVALID_YAML_KEY") from None
        return super().construct_mapping(node, deep=deep)


StrictLoader.yaml_implicit_resolvers = {
    key: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def read_yaml(path: Path):
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ScenarioError("FILE_TOO_LARGE")
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=StrictLoader)
    except (yaml.YAMLError, UnicodeError, RecursionError) as error:
        mark = getattr(error, "problem_mark", None)
        raise ScenarioError(
            "INVALID_YAML",
            line=mark.line + 1 if mark else None,
            column=mark.column + 1 if mark else None,
        ) from None


def sql_type(value: str) -> str:
    match = TYPE_PATTERN.fullmatch(value)
    if not match or (value.startswith("numeric") and int(match[3]) > int(match[2])):
        raise ScenarioError("UNSUPPORTED_COLUMN_TYPE")
    return value


def converted(value, kind: str):
    if value is None:
        return None
    try:
        if kind in {"integer", "bigint"}:
            bound = 2 ** (31 if kind == "integer" else 63)
            if type(value) is int and -bound <= value < bound:
                return value
        elif kind == "boolean":
            if type(value) is bool:
                return value
        elif kind == "text":
            if isinstance(value, str) and "\x00" not in value:
                return value
        elif kind.startswith("numeric") and isinstance(value, str):
            number = Decimal(value)
            precision, scale = map(int, re.findall(r"\d+", kind))
            if number.is_finite():
                quantum = Decimal(1).scaleb(-scale)
                if number == number.quantize(quantum) and abs(number) < 10 ** (precision - scale):
                    return number
        elif isinstance(value, str):
            if kind == "date":
                return date.fromisoformat(value)
            parsed = datetime.fromisoformat(value)
            if (parsed.utcoffset() is not None) == (kind == "timestamptz"):
                return parsed
    except (ValueError, InvalidOperation, OverflowError):
        pass
    raise ScenarioError("INVALID_TYPED_VALUE")


def typed_rows(rows: list, columns: dict, location=()) -> list[tuple]:
    if not isinstance(rows, list) or len(rows) > 100_000:
        raise ScenarioError("INVALID_FIXTURE_SIZE", location=location)
    result = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.keys() != columns.keys():
            raise ScenarioError("FIXTURE_COLUMNS_MISMATCH", location=(*location, index))
        values = []
        for name, kind in columns.items():
            try:
                values.append(converted(row[name], kind))
            except ScenarioError as error:
                raise ScenarioError(error.code, location=(*location, index, name)) from None
        result.append(tuple(values))
    return result


@dataclass
class Scenario:
    data: dict
    path: Path
    fingerprint: str
    fixture_hashes: dict[str, str]


def load_scenario(path: Path, project_dir: Path) -> Scenario:
    path = path.resolve()
    root = project_dir.resolve()
    if not path.is_relative_to(root):
        raise ScenarioError("SCENARIO_OUTSIDE_PROJECT")
    data = read_yaml(path)
    schema = json.loads(files("dbt_scenario").joinpath("scenario.schema.json").read_text())
    error = next(Draft202012Validator(schema).iter_errors(data), None)
    if error:
        location = tuple(error.absolute_path)
        if error.validator == "required" and isinstance(error.instance, dict):
            missing = next(key for key in error.validator_value if key not in error.instance)
            location = (*location, missing)
        raise ScenarioError("INVALID_SCENARIO_SCHEMA", location=location)
    hashes = {}

    def resolve_fixture(fixture):
        if "fixture" not in fixture:
            return
        target = (path.parent / fixture["fixture"]).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise ScenarioError("INVALID_FIXTURE_PATH")
        payload = read_yaml(target)
        if not isinstance(payload, dict) or set(payload) != {"rows"}:
            raise ScenarioError("INVALID_FIXTURE_FILE")
        hashes[str(target.relative_to(root))] = hashlib.sha256(target.read_bytes()).hexdigest()
        fixture["rows"] = payload["rows"]
        del fixture["fixture"]

    definitions = [("inputs", name, definition) for name, definition in data["inputs"].items()]
    definitions.append(("output", data["output"]))
    for *prefix, definition in definitions:
        for name, kind in definition["columns"].items():
            if not name or "\x00" in name or len(name.encode()) > 63:
                raise ScenarioError("INVALID_COLUMN_NAME")
            try:
                sql_type(kind)
            except ScenarioError as error:
                raise ScenarioError(error.code, location=(*prefix, "columns", name)) from None
    keys = data["output"]["primary_key"]
    columns = data["output"]["columns"]
    if len(set(keys)) != len(keys) or not set(keys) <= columns.keys():
        raise ScenarioError("INVALID_PRIMARY_KEY")
    seen = set()
    initialized = set()
    nodes = [item["node"] for item in data["inputs"].values()]
    if len(set(nodes)) != len(nodes):
        raise ScenarioError("DUPLICATE_INPUT_NODE")
    for index, step in enumerate(data["steps"]):
        try:
            json.dumps(step["run"].get("vars", {}), allow_nan=False)
        except (TypeError, ValueError):
            raise ScenarioError(
                "INVALID_RUN_VARS", location=("steps", index, "run", "vars")
            ) from None
        if step["name"] in seen:
            raise ScenarioError("DUPLICATE_STEP_NAME")
        if step["run"]["mode"] != ("initial" if index == 0 else "incremental"):
            raise ScenarioError("INVALID_STEP_ORDER", location=("steps", index, "run", "mode"))
        for name, update in step.get("inputs", {}).items():
            if name not in data["inputs"]:
                raise ScenarioError("UNKNOWN_INPUT")
            fixture = update["replace"]
            resolve_fixture(fixture)
            typed_rows(
                fixture["rows"],
                data["inputs"][name]["columns"],
                ("steps", index, "inputs", name, "replace", "rows"),
            )
            initialized.add(name)
        if initialized != data["inputs"].keys():
            raise ScenarioError("UNINITIALIZED_INPUT", location=("steps", index, "inputs"))
        expected = step["expect"]
        if "same_as" in expected:
            if expected["same_as"] not in seen:
                raise ScenarioError(
                    "INVALID_SAME_AS_REFERENCE", location=("steps", index, "expect", "same_as")
                )
        else:
            resolve_fixture(expected)
            rows = typed_rows(expected["rows"], columns, ("steps", index, "expect", "rows"))
            key_indexes = [list(columns).index(key) for key in keys]
            identities = [tuple(row[i] for i in key_indexes) for row in rows]
            if any(None in key for key in identities) or len(set(identities)) != len(identities):
                raise ScenarioError(
                    "INVALID_EXPECTED_KEY", location=("steps", index, "expect", "rows")
                )
        seen.add(step["name"])
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return Scenario(data, path, hashlib.sha256(canonical.encode()).hexdigest(), hashes)
