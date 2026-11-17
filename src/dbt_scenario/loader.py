import copy
import dataclasses
import datetime
import decimal
import hashlib
import json
import math
import pathlib
import re
from importlib import resources
from typing import Any

import jsonschema
import yaml

from dbt_scenario import errors

TYPE_PATTERN = re.compile(
    r"^(bigint|integer|text|boolean|date|timestamp|timestamptz|double "
    r"precision|"
    r"numeric(?:\(([1-9]\d?),([0-9]\d?)\))?)$"
)
DECIMAL_PATTERN = re.compile(
    r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
)
YAML_BASE = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class StrictLoader(YAML_BASE):
    def compose_node(
        self,
        parent: yaml.nodes.Node | None,
        index: int | yaml.nodes.Node | None,
    ) -> yaml.nodes.Node:
        if self.check_event(yaml.AliasEvent):
            mark = self.peek_event().start_mark
            raise errors.ScenarioError(
                "YAML_ALIAS_UNSUPPORTED",
                line=mark.line + 1,
                column=mark.column + 1,
            )
        return super().compose_node(parent, index)

    def construct_mapping(
        self, node: yaml.nodes.MappingNode, deep: bool = False
    ) -> dict:
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        try:
            if len(set(keys)) != len(keys):
                seen = set()
                for key, (key_node, _) in zip(keys, node.value, strict=True):
                    if key in seen:
                        mark = key_node.start_mark
                        raise errors.ScenarioError(
                            "DUPLICATE_YAML_KEY",
                            line=mark.line + 1,
                            column=mark.column + 1,
                        )
                    seen.add(key)
        except TypeError:
            raise errors.ScenarioError("INVALID_YAML_KEY") from None
        return super().construct_mapping(node, deep=deep)


StrictLoader.yaml_implicit_resolvers = {
    key: [
        (tag, rx)
        for tag, rx in resolvers
        if tag != "tag:yaml.org,2002:timestamp"
    ]
    for key, resolvers in YAML_BASE.yaml_implicit_resolvers.items()
}


def read_yaml_document(path: pathlib.Path) -> tuple[Any, str]:
    limit = 10 * 1024 * 1024
    with path.open("rb") as source:
        content = source.read(limit + 1)
    if len(content) > limit:
        raise errors.ScenarioError("FILE_TOO_LARGE")
    try:
        text = content.decode("utf-8")
        depth = 0
        for event in yaml.parse(text, Loader=YAML_BASE):
            if isinstance(event, yaml.AliasEvent):
                mark = event.start_mark
                raise errors.ScenarioError(
                    "YAML_ALIAS_UNSUPPORTED",
                    line=mark.line + 1,
                    column=mark.column + 1,
                )
            if isinstance(
                event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)
            ):
                depth += 1
                if depth > 128:
                    raise errors.ScenarioError("YAML_NESTING_LIMIT")
            elif isinstance(
                event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)
            ):
                depth -= 1
        payload = yaml.load(text, Loader=StrictLoader)
    except (yaml.YAMLError, UnicodeError, RecursionError) as error:
        mark = getattr(error, "problem_mark", None)
        raise errors.ScenarioError(
            "INVALID_YAML",
            line=mark.line + 1 if mark else None,
            column=mark.column + 1 if mark else None,
        ) from None
    return payload, hashlib.sha256(content).hexdigest()


def read_yaml(path: pathlib.Path) -> Any:
    return read_yaml_document(path)[0]


def sql_type(value: str) -> str:
    match = TYPE_PATTERN.fullmatch(value)
    if not match or (match[2] is not None and int(match[3]) > int(match[2])):
        raise errors.ScenarioError("UNSUPPORTED_COLUMN_TYPE")
    return value


def converted(
    value: object, kind: str
) -> bool | int | float | str | decimal.Decimal | datetime.date | None:
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
        elif kind == "double precision" and isinstance(value, str):
            if DECIMAL_PATTERN.fullmatch(value):
                number = decimal.Decimal(value)
                floating = float(value)
                if math.isfinite(floating) and (
                    floating != 0.0 or number.is_zero()
                ):
                    return floating
        elif kind == "numeric" and isinstance(value, str):
            if DECIMAL_PATTERN.fullmatch(value):
                number = decimal.Decimal(value)
                if (
                    number.is_finite()
                    and number.as_tuple().exponent >= -16383
                    and (number.is_zero() or number.adjusted() < 131072)
                ):
                    return decimal.Decimal(0) if number.is_zero() else number
        elif kind.startswith("numeric") and isinstance(value, str):
            number = decimal.Decimal(value)
            precision, scale = map(int, re.findall(r"\d+", kind))
            if number.is_finite() and number.copy_abs() < 10 ** (
                precision - scale
            ):
                with decimal.localcontext(decimal.Context(prec=precision + 2)):
                    quantum = decimal.Decimal(1).scaleb(-scale)
                    if number == number.quantize(quantum):
                        return number
        elif isinstance(value, str):
            if kind == "date":
                return datetime.date.fromisoformat(value)
            if re.search(r"[.,]\d{7,}", value):
                raise ValueError
            parsed = datetime.datetime.fromisoformat(value)
            if (parsed.utcoffset() is not None) == (kind == "timestamptz"):
                return parsed
    except (ValueError, decimal.InvalidOperation, OverflowError):
        pass
    raise errors.ScenarioError("INVALID_TYPED_VALUE")


def unfinished_rows(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"replace_with_[A-Za-z0-9_]+_rows", value) is not None
    )


def unfinished_rows_error(
    error: jsonschema.exceptions.ValidationError,
) -> tuple[str | int, ...] | None:
    location = tuple(error.absolute_path)
    if (
        error.validator == "type"
        and error.validator_value == "array"
        and location[-1:] == ("rows",)
        and unfinished_rows(error.instance)
    ):
        return location
    for child in error.context:
        found = unfinished_rows_error(child)
        if found is not None:
            return found
    return None


def typed_rows(
    rows: list, columns: dict, location: tuple[str | int, ...] = ()
) -> list[tuple]:
    if unfinished_rows(rows):
        raise errors.ScenarioError("UNFILLED_TEMPLATE_ROWS", location=location)
    if not isinstance(rows, list) or len(rows) > 100_000:
        raise errors.ScenarioError("INVALID_FIXTURE_SIZE", location=location)
    result = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.keys() != columns.keys():
            raise errors.ScenarioError(
                "FIXTURE_COLUMNS_MISMATCH", location=(*location, index)
            )
        values = []
        for name, kind in columns.items():
            try:
                values.append(converted(row[name], kind))
            except errors.ScenarioError as error:
                raise errors.ScenarioError(
                    error.code, location=(*location, index, name)
                ) from None
        result.append(tuple(values))
    return result


@dataclasses.dataclass
class PreparedRows:
    columns: tuple[tuple[str, str], ...]
    source: list[tuple] = dataclasses.field(repr=False)
    values: list[tuple] = dataclasses.field(repr=False)

    def batch(
        self,
        rows: list,
        offset: int,
        columns: dict[str, str],
    ) -> list[tuple] | None:
        if not isinstance(rows, list) or self.columns != tuple(columns.items()):
            return None
        end = offset + len(rows)
        original = self.source[offset:end]
        if len(rows) != len(original):
            return None
        for row, prior in zip(rows, original, strict=True):
            if not isinstance(row, dict) or row.keys() != columns.keys():
                return None
            for name, value in zip(columns, prior, strict=True):
                if type(row[name]) is not type(value) or row[name] != value:
                    return None
        return self.values[offset:end]


@dataclasses.dataclass
class Scenario:
    data: dict
    path: pathlib.Path
    fingerprint: str
    fixture_hashes: dict[str, str]
    prepared: dict[tuple, PreparedRows] = dataclasses.field(
        default_factory=dict,
        repr=False,
        compare=False,
    )


def validate_scenario_schema(data: object) -> None:
    schema = json.loads(
        resources.files("dbt_scenario")
        .joinpath("scenario.schema.json")
        .read_text()
    )
    error = next(
        jsonschema.Draft202012Validator(schema).iter_errors(data), None
    )
    if error:
        unfinished = unfinished_rows_error(error)
        if unfinished is not None:
            raise errors.ScenarioError(
                "UNFILLED_TEMPLATE_ROWS", location=unfinished
            )
        location = tuple(error.absolute_path)
        if error.validator == "required" and isinstance(error.instance, dict):
            missing = next(
                key
                for key in error.validator_value
                if key not in error.instance
            )
            location = (*location, missing)
        raise errors.ScenarioError("INVALID_SCENARIO_SCHEMA", location=location)


@dataclasses.dataclass
class FixtureReader:
    path: pathlib.Path
    root: pathlib.Path
    hashes: dict[str, str] = dataclasses.field(default_factory=dict)
    cache: dict[pathlib.Path, dict] = dataclasses.field(default_factory=dict)
    prepared: dict[tuple, PreparedRows] = dataclasses.field(
        default_factory=dict
    )

    def prepare(
        self,
        fixture: dict,
        columns: dict[str, str],
        location: tuple,
    ) -> list[tuple]:
        if "fixture" in fixture:
            target = (self.path.parent / fixture["fixture"]).resolve()
            if not target.is_relative_to(self.root) or not target.is_file():
                raise errors.ScenarioError("INVALID_FIXTURE_PATH")
            if target not in self.cache:
                payload, fingerprint = read_yaml_document(target)
                if not isinstance(payload, dict) or set(payload) != {"rows"}:
                    raise errors.ScenarioError("INVALID_FIXTURE_FILE")
                self.cache[target] = payload
                self.hashes[target.relative_to(self.root).as_posix()] = (
                    fingerprint
                )
            fixture["rows"] = copy.deepcopy(self.cache[target]["rows"])
            del fixture["fixture"]
        rows = fixture["rows"]
        values = typed_rows(rows, columns, location)
        source = [tuple(row[name] for name in columns) for row in rows]
        self.prepared[location] = PreparedRows(
            tuple(columns.items()),
            source,
            values,
        )
        return values


def validate_columns(data: dict) -> None:
    definitions = [
        ("inputs", name, definition)
        for name, definition in data["inputs"].items()
    ]
    definitions.append(("output", data["output"]))
    for *prefix, definition in definitions:
        for name, kind in definition["columns"].items():
            if (
                not isinstance(name, str)
                or not name
                or "\x00" in name
                or len(name.encode()) > 63
            ):
                raise errors.ScenarioError(
                    "INVALID_COLUMN_NAME", location=(*prefix, "columns")
                )
            try:
                sql_type(kind)
            except errors.ScenarioError as error:
                raise errors.ScenarioError(
                    error.code, location=(*prefix, "columns", name)
                ) from None


def validate_steps(data: dict, fixtures: FixtureReader) -> None:
    nodes = [item["node"] for item in data["inputs"].values()]
    if len(set(nodes)) != len(nodes):
        raise errors.ScenarioError("DUPLICATE_INPUT_NODE")
    columns = data["output"]["columns"]
    keys = data["output"]["primary_key"]
    key_indexes = [list(columns).index(key) for key in keys]
    seen = set()
    initialized = set()
    for index, step in enumerate(data["steps"]):
        try:
            json.dumps(step["run"].get("vars", {}), allow_nan=False)
        except (TypeError, ValueError):
            raise errors.ScenarioError(
                "INVALID_RUN_VARS", location=("steps", index, "run", "vars")
            ) from None
        if step["name"] in seen:
            raise errors.ScenarioError("DUPLICATE_STEP_NAME")
        if step["run"]["mode"] != ("initial" if index == 0 else "incremental"):
            raise errors.ScenarioError(
                "INVALID_STEP_ORDER", location=("steps", index, "run", "mode")
            )
        for name, update in step.get("inputs", {}).items():
            if name not in data["inputs"]:
                raise errors.ScenarioError("UNKNOWN_INPUT")
            fixtures.prepare(
                update["replace"],
                data["inputs"][name]["columns"],
                ("steps", index, "inputs", name, "replace", "rows"),
            )
            initialized.add(name)
        if initialized != data["inputs"].keys():
            raise errors.ScenarioError(
                "UNINITIALIZED_INPUT", location=("steps", index, "inputs")
            )
        expected = step["expect"]
        if "same_as" in expected:
            if expected["same_as"] not in seen:
                raise errors.ScenarioError(
                    "INVALID_SAME_AS_REFERENCE",
                    location=("steps", index, "expect", "same_as"),
                )
        else:
            rows = fixtures.prepare(
                expected,
                columns,
                ("steps", index, "expect", "rows"),
            )
            identities = [tuple(row[i] for i in key_indexes) for row in rows]
            if any(None in key for key in identities) or len(
                set(identities)
            ) != len(identities):
                raise errors.ScenarioError(
                    "INVALID_EXPECTED_KEY",
                    location=("steps", index, "expect", "rows"),
                )
        seen.add(step["name"])


def load_scenario(path: pathlib.Path, project_dir: pathlib.Path) -> Scenario:
    path = path.resolve()
    root = project_dir.resolve()
    if not path.is_relative_to(root):
        raise errors.ScenarioError("SCENARIO_OUTSIDE_PROJECT")
    data = read_yaml(path)
    validate_scenario_schema(data)
    validate_columns(data)
    keys = data["output"]["primary_key"]
    columns = data["output"]["columns"]
    if len(set(keys)) != len(keys) or not set(keys) <= columns.keys():
        raise errors.ScenarioError("INVALID_PRIMARY_KEY")
    fixtures = FixtureReader(path, root)
    validate_steps(data, fixtures)
    canonical = json.dumps(
        data, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return Scenario(
        data,
        path,
        hashlib.sha256(canonical.encode()).hexdigest(),
        fixtures.hashes,
        fixtures.prepared,
    )
