import inspect
import math
from pathlib import Path
import sys
import unittest

import numpy as np
import polars as pl
import talib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
from dqr.operators import Interpreter, REGISTRY, catalogue, evaluate_program, provenance_hash, frame_from_bars
from dqr.storage import read


def market_frame(count=180):
    rows = []
    for fund, offset in [("A", 0), ("B", 3)]:
        for i in range(count):
            close = 20 + offset + i * .03 + math.sin(i * .31)
            rows.append({"datetime": f"{i:04d}", "vt_symbol": fund, "close": close,
                         "high": close + .7, "low": close - .6, "open": close - .1,
                         "volume": 100.0 + i % 9, "total_return_index": close, "return_1": .01 + math.sin(i) * .02})
    return pl.DataFrame(rows).sort(["datetime", "vt_symbol"])


def example(name):
    args = []
    for p in REGISTRY[name]["signature"].parameters.values():
        if p.name in {"open", "high", "low", "close", "volume"}:
            args.append(p.name)
        elif p.name in {"feature", "feature1", "base"}:
            args.append("close")
        elif p.name in {"feature2", "feature3"}:
            args.append("high" if p.name == "feature2" else "low")
        elif p.name == "exponent":
            args.append("close / close * 2" if name == "pow2" else "2")
        elif p.name == "threshold":
            args.append("low" if name == "quesval2" else "20")
        elif p.name == "quantile":
            args.append("0.5")
        elif p.name in {"matype", "slowk_matype", "slowd_matype"}:
            args.append("0")
        elif p.name in {"dev", "nbdev"}:
            args.append("2")
        elif p.name == "acceleration":
            args.append("0.02")
        elif p.name == "maximum":
            args.append("0.2")
        elif p.name in {"slow_period", "time_period2"}:
            args.append("10")
        elif p.name == "time_period3":
            args.append("20")
        else:
            args.append("5")
    return name + "(" + ", ".join(args) + ")"


class OperatorTests(unittest.TestCase):
    def test_all_86_real_operators_run_and_are_prefix_causal(self):
        self.assertEqual(catalogue()["count"], 86)
        full = market_frame()
        prefix = full.filter(pl.col("datetime") < "0140")
        for name in REGISTRY:
            with self.subTest(operator=name):
                expr = example(name)
                a = Interpreter(full).expression(expr).df
                b = Interpreter(prefix).expression(expr).df
                self.assertEqual(a.height, full.height)
                self.assertTrue(a["data"].drop_nulls().is_finite().any(), expr)
                np.testing.assert_allclose(a.filter(pl.col("datetime") < "0140")["data"].to_numpy(),
                                           b["data"].to_numpy(), equal_nan=True, rtol=1e-10)

    def test_math_reference_and_symbol_isolation(self):
        frame = market_frame()
        mean = Interpreter(frame).expression("ts_mean(close, 5)").df
        for fund in ["A", "B"]:
            expected = frame.filter(pl.col("vt_symbol") == fund)["close"].to_numpy()
            actual = mean.filter(pl.col("vt_symbol") == fund)["data"].to_numpy()
            self.assertAlmostEqual(actual[-1], float(np.mean(expected[-5:])))
        rsi = Interpreter(frame).expression("am_rsi(close, 14)").df
        macd = Interpreter(frame).expression("am_macd_hist(close, 5, 10, 5)").df
        for fund in ["A", "B"]:
            values = frame.filter(pl.col("vt_symbol") == fund)["close"].to_numpy()
            np.testing.assert_allclose(rsi.filter(pl.col("vt_symbol") == fund)["data"].to_numpy(), talib.RSI(values, 14), equal_nan=True)
            np.testing.assert_allclose(macd.filter(pl.col("vt_symbol") == fund)["data"].to_numpy(), talib.MACD(values, 5, 10, 5)[2], equal_nan=True)
        rank = Interpreter(frame).expression("cs_rank(close)").df.tail(2)["data"].to_list()
        self.assertEqual(rank, [.5, 1.0])

    def test_expression_boundaries_and_missing_market_fields(self):
        frame = market_frame().drop("high", "low", "open", "volume")
        for expr in ["ts_delay(close, -1)", "ts_mean(close, 9999)", "close.__class__", "__import__('os')", "[x for x in close]", "ta_atr(high, low, close, 14)", "close ** 999999"]:
            with self.subTest(expression=expr), self.assertRaises((ValueError, SyntaxError)):
                Interpreter(frame).expression(expr)

    def test_custom_operator_and_parameter_changes_affect_results(self):
        program = read(ROOT / "strategies/operators-current.json")
        a, traces = evaluate_program(market_frame(), program)
        self.assertIn("momentum", traces["return_20"])
        self.assertIn("ts_delay", traces["return_20"])
        program["features"][0]["expression"] = "momentum(total_return_index, 10)"
        b, _ = evaluate_program(market_frame(), program)
        self.assertNotEqual(a["return_20"][-1], b["return_20"][-1])
        self.assertEqual(a["return_60"][-1], b["return_60"][-1])

    def test_dividend_adapter_and_provenance(self):
        frame = frame_from_bars([{"date": "2026-01-01", "funds": {"A": {"nav": 1.0}}},
                                {"date": "2026-01-02", "funds": {"A": {"nav": .9, "dividend": .1}}}])
        self.assertAlmostEqual(frame["return_1"][-1], 0)
        self.assertAlmostEqual(frame["total_return_index"][-1], 1)
        self.assertEqual(len(provenance_hash()), 64)


if __name__ == "__main__":
    unittest.main()
