"""Transformation pipeline DSL used by import template columns (spec §12.4).

A column's `transformation` is a `|`-separated list of steps applied left to
right, e.g.::

    trim|upper|normalize_vehicle
    remove_currency|remove_commas|decimal
    replace(Rs.,)|trim|default(0)
    split(/,0)|trim
    concat( ,C,D)                      -> this value + " " + column C + " " + column D
    if(eq:CR,$value,)                  -> keep value only if it equals CR
    if(col:E=CR,$value,0)              -> keep value when column E is CR, else 0
    map(FUEL_TYPE)                     -> value_mappings lookup for this provider
    date(%d-%b-%Y) / datetime(%d/%m/%Y %H:%M)
    regex(\\d+,0) / left(4) / right(4) / abs / negate / prefix(X) / suffix(X)

Arguments are comma separated; use `\\,` for a literal comma.  Unknown steps
raise a clear error when the template is saved (see `validate_pipeline`).
"""
from __future__ import annotations

import re
from typing import Any, Callable

from app.core.utils import normalize_text, normalize_vehicle_number, parse_date, parse_datetime, to_decimal

_STEP_RE = re.compile(r"^\s*([a-z_]+)\s*(?:\((.*)\))?\s*$", re.S)


def _split_args(s: str | None) -> list[str]:
    if s is None or s == "":
        return []
    out, cur, esc = [], "", False
    for ch in s:
        if esc:
            cur += ch if ch in ",\\" else "\\" + ch  # only \, and \\ are escapes; keep regex escapes intact
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ",":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def split_pipeline(expr: str | None) -> list[tuple[str, list[str]]]:
    if not expr:
        return []
    steps, depth, cur = [], 0, ""
    for ch in expr:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "|" and depth == 0:
            steps.append(cur)
            cur = ""
        else:
            cur += ch
    steps.append(cur)
    out = []
    for s in steps:
        if not s.strip():
            continue
        m = _STEP_RE.match(s)
        if not m:
            raise ValueError(f"Invalid transformation step '{s}'")
        out.append((m.group(1), _split_args(m.group(2))))
    return out


class TContext:
    """What a transformation step may consult: the whole source row and value mappings."""

    def __init__(self, row: dict[str, Any], mapper: Callable[[str, str], str | None] | None = None,
                 date_format: str | None = None, datetime_format: str | None = None):
        self.row = row  # keys: column letters (A, B...) and header texts (upper-cased)
        self.mapper = mapper
        self.date_format = date_format
        self.datetime_format = datetime_format

    def col(self, ref: str) -> Any:
        ref = ref.strip()
        return self.row.get(ref.upper(), self.row.get(normalize_text(ref)))


def _cond(ctx: TContext, value: Any, cond: str) -> bool:
    if cond.startswith("col:"):
        ref, _, rest = cond[4:].partition("=")
        return normalize_text(ctx.col(ref)) == normalize_text(rest)
    op, _, arg = cond.partition(":")
    sv = normalize_text(value)
    if op == "eq":
        return sv == normalize_text(arg)
    if op == "ne":
        return sv != normalize_text(arg)
    if op == "contains":
        return normalize_text(arg) in sv
    if op == "empty":
        return sv == ""
    if op == "notempty":
        return sv != ""
    if op in ("gt", "lt"):
        d = to_decimal(value) or 0
        return d > to_decimal(arg) if op == "gt" else d < to_decimal(arg)
    raise ValueError(f"Unknown condition '{cond}'")


def _resolve(ctx: TContext, token: str, value: Any) -> Any:
    if token == "$value":
        return value
    if token.startswith("$col:"):
        return ctx.col(token[5:])
    return token


def _step(name: str, args: list[str], value: Any, ctx: TContext) -> Any:
    s = "" if value is None else value
    if name == "trim":
        return str(s).strip() if isinstance(s, str) else s
    if name == "upper":
        return str(s).upper() if s != "" else s
    if name == "lower":
        return str(s).lower() if s != "" else s
    if name == "collapse_spaces":
        return re.sub(r"\s+", " ", str(s)).strip()
    if name == "remove_commas":
        return str(s).replace(",", "") if isinstance(s, str) else s
    if name == "remove_currency":
        return re.sub(r"[₹$€£]|INR|Rs\.?", "", str(s), flags=re.I).strip() if isinstance(s, str) else s
    if name == "replace":
        return str(s).replace(args[0], args[1] if len(args) > 1 else "")
    if name == "regex":
        m = re.search(args[0], str(s))
        return (m.group(int(args[1]) if len(args) > 1 else 0) if m else "")
    if name == "default":
        return args[0] if s in ("", None) else s
    if name == "concat":
        sep = args[0] if args else ""
        parts = [str(s)] if str(s) != "" else []
        parts += [str(ctx.col(a) or "") for a in args[1:] if str(ctx.col(a) or "") != ""]
        return sep.join(parts)
    if name == "split":
        sep, idx = args[0], int(args[1]) if len(args) > 1 else 0
        bits = str(s).split(sep)
        return bits[idx].strip() if -len(bits) <= idx < len(bits) else ""
    if name == "left":
        return str(s)[: int(args[0])]
    if name == "right":
        return str(s)[-int(args[0]):]
    if name == "prefix":
        return f"{args[0]}{s}" if s != "" else s
    if name == "suffix":
        return f"{s}{args[0]}" if s != "" else s
    if name == "if":
        return _resolve(ctx, args[1], value) if _cond(ctx, value, args[0]) else _resolve(
            ctx, args[2] if len(args) > 2 else "", value)
    if name == "decimal":
        return to_decimal(s) if s != "" else None
    if name == "int":
        d = to_decimal(s)
        return int(d) if d is not None else None
    if name == "abs":
        d = to_decimal(s)
        return abs(d) if d is not None else None
    if name == "negate":
        d = to_decimal(s)
        return -d if d is not None else None
    if name == "date":
        return parse_date(s, args[0] if args else ctx.date_format) if s != "" else None
    if name == "datetime":
        v = parse_datetime(s, args[0] if args else ctx.datetime_format) if s != "" else None
        if s != "" and v is None:
            raise ValueError(f"Invalid date/time '{s}'")
        return v
    if name == "normalize_vehicle":
        return normalize_vehicle_number(s)
    if name == "map":
        if s == "" or ctx.mapper is None:
            return s
        mapped = ctx.mapper(args[0] if args else "GENERIC", str(s))
        return mapped if mapped is not None else s
    raise ValueError(f"Unknown transformation '{name}'")


KNOWN_STEPS = {"trim", "upper", "lower", "collapse_spaces", "remove_commas", "remove_currency", "replace", "regex",
               "default", "concat", "split", "left", "right", "prefix", "suffix", "if", "decimal", "int", "abs",
               "negate", "date", "datetime", "normalize_vehicle", "map"}


def validate_pipeline(expr: str | None) -> None:
    for name, _ in split_pipeline(expr):
        if name not in KNOWN_STEPS:
            raise ValueError(f"Unknown transformation '{name}'. Allowed: {', '.join(sorted(KNOWN_STEPS))}")


def apply_pipeline(expr: str | None, value: Any, ctx: TContext) -> Any:
    for name, args in split_pipeline(expr):
        value = _step(name, args, value, ctx)
    return value


def check_validation(rule_expr: str | None, value: Any) -> str | None:
    """Return an error message or None. Rules: regex:..., min:n, max:n, len:n, in:A;B;C"""
    if not rule_expr or value in (None, ""):
        return None
    for part in rule_expr.split("&&"):
        kind, _, arg = part.strip().partition(":")
        if kind == "regex" and not re.fullmatch(arg, str(value)):
            return f"does not match pattern {arg}"
        if kind in ("min", "max"):
            d = to_decimal(value)
            if d is not None and (d < to_decimal(arg) if kind == "min" else d > to_decimal(arg)):
                return f"must be {'≥' if kind == 'min' else '≤'} {arg}"
        if kind == "len" and len(str(value)) != int(arg):
            return f"must be {arg} characters"
        if kind == "maxlen" and len(str(value)) > int(arg):
            return f"must be at most {arg} characters"
        if kind == "in" and normalize_text(value) not in [normalize_text(x) for x in arg.split(";")]:
            return f"must be one of {arg}"
    return None
