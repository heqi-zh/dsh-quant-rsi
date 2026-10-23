"""Real vn.py operators behind a bounded expression interpreter (never Python eval)."""
import ast
import hashlib
import inspect
import math
import operator
from pathlib import Path

import numpy as np
import polars as pl

from .vendor.vnpy import ts_function, cs_function, math_function, ta_function
from .vendor.vnpy.utility import DataProxy
from .vendor.vnpy.array_manager import ArrayManager
from .storage import read, digest

KEYS = ["datetime", "vt_symbol"]
NAV_FIELDS = {"nav", "dividend", "return_1", "total_return_index"}
BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.Pow: operator.pow}
CMP = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
       ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}
REGISTRY = {}


def register(name, function, signature, source, description, required=()):
    REGISTRY[name] = {"function": function, "signature": signature, "source": source,
                      "description": description, "required_fields": list(required)}


for module in (ts_function, cs_function, math_function, ta_function):
    for name, function in inspect.getmembers(module, inspect.isfunction):
        if function.__module__ == module.__name__ and not name.startswith("_") and name != "to_feature_df":
            register(name, function, inspect.signature(function), "vnpy/alpha/dataset/" + module.__name__.split(".")[-1] + ".py",
                     inspect.getdoc(function) or name)


def array_wrapper(method, fields, component):
    original = getattr(ArrayManager, method)
    params = [p for p in inspect.signature(original).parameters.values() if p.name not in {"self", "array"}]
    signature = inspect.Signature([inspect.Parameter(f, inspect.Parameter.POSITIONAL_OR_KEYWORD) for f in fields] + params)

    def calculate(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        series = {f: bound.arguments.pop(f) for f in fields}
        if not all(isinstance(s, DataProxy) for s in series.values()):
            raise ValueError("technical indicator inputs must be feature series")
        base = next(iter(series.values())).df.select(KEYS)
        for f, s in series.items():
            base = base.join(s.df.rename({"data": f}), on=KEYS, how="left", maintain_order="left")
        outputs = []
        for frame in base.partition_by("vt_symbol", maintain_order=True):
            am = ArrayManager(frame.height)
            for f in fields:
                setattr(am, f + "_array", frame[f].cast(pl.Float64).to_numpy())
            values = original(am, **bound.arguments, array=True)
            if component is not None:
                values = values[component]
            outputs.append(frame.select(KEYS).with_columns(pl.Series("data", values, nan_to_null=True)))
        return DataProxy(pl.concat(outputs).sort(KEYS))
    return calculate, signature


# Derive field requirements from actual upstream method bodies, including delegated calls.
_tree = ast.parse(Path(inspect.getfile(ArrayManager)).read_text())
_class = next(n for n in _tree.body if isinstance(n, ast.ClassDef))
_methods = {n.name: n for n in _class.body if isinstance(n, ast.FunctionDef) and not n.decorator_list}
_fields = {"open", "high", "low", "close", "volume", "turnover", "open_interest"}


def required_fields(method):
    attrs = {n.attr for n in ast.walk(_methods[method]) if isinstance(n, ast.Attribute)
             and isinstance(n.value, ast.Name) and n.value.id == "self"}
    result = attrs & _fields
    for name in attrs - _fields:
        if name in _methods and name != method:
            result |= set(required_fields(name))
    return sorted(result)


MULTI = {"macd": ["line", "signal", "hist"], "boll": ["upper", "lower"],
         "keltner": ["upper", "lower"], "donchian": ["upper", "lower"],
         "aroon": ["up", "down"], "stoch": ["k", "d"]}
for method in _methods:
    if method in {"__init__", "update_bar"}:
        continue
    fields = required_fields(method)
    for component, suffix in enumerate(MULTI.get(method, [""])):
        name = "am_" + method + ("_" + suffix if suffix else "")
        function, signature = array_wrapper(method, fields, component if suffix else None)
        register(name, function, signature, "vnpy/trader/utility.py:ArrayManager." + method,
                 inspect.getdoc(getattr(ArrayManager, method)) or method, fields)


def catalogue():
    return {"vendor": read(Path(__file__).with_name("vendor") / "vnpy/provenance.json"),
            "operators": [{"name": name, "signature": str(info["signature"]),
                           "description": info["description"], "source": info["source"],
                           "required_fields": info["required_fields"],
                           "fund_nav_usage": "requires real OHLC/volume inputs" if set(info["required_fields"]) - {"close"}
                           or name == "ta_atr" else "usable with NAV-derived series; pass total_return_index explicitly for close"}
                          for name, info in sorted(REGISTRY.items())],
            "count": len(REGISTRY), "available_fund_fields": sorted(NAV_FIELDS),
            "semantics": "Upstream null/window semantics retained. All series aligned by date and symbol. Negative lags forbidden. No synthetic OHLCV."}


def frame_from_bars(bars):
    """No forward/backfill; daily total return includes the day's cash dividend."""
    rows, previous, indexes = [], {}, {}
    for bar in bars:
        for fund, item in sorted(bar["funds"].items()):
            nav, dividend = item["nav"], item.get("dividend", 0)
            ret = (nav + dividend) / previous[fund] - 1 if fund in previous else None
            indexes[fund] = indexes.get(fund, 1.0) * (1 + ret if ret is not None else 1)
            rows.append({"datetime": bar["date"], "vt_symbol": fund, "nav": nav,
                         "dividend": dividend, "return_1": ret, "total_return_index": indexes[fund]})
            previous[fund] = nav
    return pl.DataFrame(rows, schema_overrides={name: pl.Float64 for name in NAV_FIELDS}).sort(KEYS)


class Interpreter:
    def __init__(self, frame, custom=None):
        if frame.select(KEYS).is_duplicated().any():
            raise ValueError("duplicate date/symbol input")
        self.frame = frame.sort(KEYS)
        self.keys = self.frame.select(KEYS)
        self.env = {f: DataProxy(self.frame.select(KEYS + [f])) for f in frame.columns if f not in KEYS}
        self.custom = custom or {}
        self.trace = []
        self.calls = 0

    def align(self, value):
        if isinstance(value, DataProxy):
            if value.df.height != self.keys.height or value.df.select(KEYS).is_duplicated().any():
                raise ValueError("operator changed input key cardinality")
            return DataProxy(self.keys.join(value.df, on=KEYS, how="left", maintain_order="left"))
        return value

    def expression(self, text, env=None, stack=()):
        if not isinstance(text, str) or len(text) > 4000:
            raise ValueError("expression must be at most 4000 characters")
        tree = ast.parse(text, mode="eval")
        if len(list(ast.walk(tree))) > 256:
            raise ValueError("expression too complex")
        return self.visit(tree.body, self.env if env is None else env, stack)

    def visit(self, node, env, stack):
        if len(stack) > 8:
            raise ValueError("custom operator nesting limit")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float) and math.isfinite(node.value) and abs(node.value) <= 1e6:
            return node.value
        if isinstance(node, ast.Name) and node.id in env:
            return env[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = self.visit(node.operand, env, stack)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp) and type(node.op) in BIN:
            a, b = self.visit(node.left, env, stack), self.visit(node.right, env, stack)
            if isinstance(node.op, ast.Pow) and (not isinstance(b, (int, float)) or abs(b) > 8):
                raise ValueError("power exponent must be a small scalar; use pow2 for feature powers")
            return self.align(BIN[type(node.op)](a, b))
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in CMP:
            return self.align(CMP[type(node.ops[0])](self.visit(node.left, env, stack), self.visit(node.comparators[0], env, stack)))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            args = [self.visit(a, env, stack) for a in node.args]
            if any(k.arg is None for k in node.keywords):
                raise ValueError("keyword expansion forbidden")
            kwargs = {k.arg: self.visit(k.value, env, stack) for k in node.keywords}
            self.calls += 1
            if self.calls > 2048:
                raise ValueError("program call budget exceeded")
            if name in self.custom:
                if name in stack:
                    raise ValueError("recursive operator forbidden")
                definition = self.custom[name]
                sig = inspect.Signature([inspect.Parameter(p, inspect.Parameter.POSITIONAL_OR_KEYWORD) for p in definition["parameters"]])
                bound = sig.bind(*args, **kwargs)
                value = self.expression(definition["expression"], dict(bound.arguments), stack + (name,))
            elif name in REGISTRY:
                info = REGISTRY[name]
                bound = info["signature"].bind(*args, **kwargs)
                bound.apply_defaults()
                for key, value in bound.arguments.items():
                    if key in {"window", "n", "fast_period", "slow_period", "signal_period", "time_period1", "time_period2", "time_period3", "fastk_period", "slowk_period", "slowd_period"}:
                        if type(value) is not int or not 1 <= value <= 252:
                            raise ValueError("periods must be integers between 1 and 252; future lags forbidden")
                    if key == "quantile" and (not isinstance(value, (int, float)) or not 0 <= value <= 1):
                        raise ValueError("quantile outside [0,1]")
                value = info["function"](*args, **kwargs)
            else:
                raise ValueError("unregistered operator: " + name)
            self.trace.append(name)
            return self.align(value)
        raise ValueError("unsupported expression syntax or unknown input: " + ast.dump(node)[:120])


def validate_program(program):
    if not isinstance(program, dict) or program.get("schema") != "dqr.operator-program.v1":
        raise ValueError("operator program schema required")
    features = program.get("features")
    if not isinstance(features, list) or not 1 <= len(features) <= 32:
        raise ValueError("program requires 1 to 32 ordered features")
    custom = program.get("operators", {})
    if not isinstance(custom, dict) or len(custom) > 16:
        raise ValueError("at most 16 custom expression operators")
    used = set(REGISTRY) | NAV_FIELDS | set(KEYS) | {"score"}
    for name, definition in custom.items():
        if not name.isidentifier() or name.startswith("_") or name in used:
            raise ValueError("invalid or reserved operator name")
        params = definition.get("parameters", [])
        if not 1 <= len(params) <= 8 or len(set(params)) != len(params) or any(not p.isidentifier() or p.startswith("_") for p in params):
            raise ValueError("invalid operator parameters")
        used.add(name)
    for feature in features:
        name = feature.get("name", "")
        if not name.isidentifier() or name.startswith("_") or name in used:
            raise ValueError("invalid or duplicate feature name")
        used.add(name)
    if program.get("purpose") == "fund_screening":
        slots = program.get("selection", {}).get("slots", {})
        if not slots or any(type(v) is not int or not 1 <= v <= 5 for v in slots.values()) or sum(slots.values()) > 20:
            raise ValueError("screening requires bounded per-category slots")
        return program
    portfolio = program.get("portfolio", {})
    if portfolio.get("rebalance") != "weekly" or type(portfolio.get("top_k")) is not int or not 1 <= portfolio["top_k"] <= 20:
        raise ValueError("weekly portfolio with top_k 1..20 required")
    if type(portfolio.get("exposure")) not in (float, int) or not 0 < portfolio["exposure"] <= 1:
        raise ValueError("exposure must be in (0,1]")
    return program


def evaluate_program(frame, program):
    validate_program(program)
    interpreter = Interpreter(frame, program.get("operators"))
    output = interpreter.keys
    traces = {}
    for feature in program["features"] + [{"name": "score", "expression": program["score"]}]:
        start = len(interpreter.trace)
        value = interpreter.expression(feature["expression"])
        if not isinstance(value, DataProxy):
            raise ValueError("feature must produce a series")
        name = feature["name"]
        # Keep invalid warmup/domain values explicit, never invent a score.
        value = DataProxy(value.df.with_columns(pl.when(pl.col("data").cast(pl.Float64).is_finite()).then(pl.col("data")).otherwise(None).alias("data")))
        interpreter.env[name] = value
        output = output.join(value.df.rename({"data": name}), on=KEYS, how="left", maintain_order="left")
        traces[name] = interpreter.trace[start:]
    return output, traces


def provenance_hash():
    folder = Path(__file__).with_name("vendor") / "vnpy"
    metadata = read(folder / "provenance.json")
    for name, item in metadata["files"].items():
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != item["vendored_sha256"]:
            raise ValueError("vendored vn.py source hash mismatch: " + name)
    return digest({"source": metadata, "adapter": Path(__file__).read_text()})


def target_weights(scores, portfolio):
    available = [f for f, row in scores.items() if row.get("score") is not None and math.isfinite(row["score"])]
    if not available:
        return {f: 0.0 for f in scores}
    ranked = sorted(available, key=lambda f: (-scores[f]["score"], f))[:portfolio["top_k"]]
    return {f: portfolio["exposure"] / len(ranked) if f in ranked else 0.0 for f in scores}
