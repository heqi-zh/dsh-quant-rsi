from datetime import date
import math

from .candidate import Candidate
from .data import validate_rows
from .storage import number


def validate_config(config):
    for key in ("initial_cash", "min_trade", "candidate_timeout_seconds"):
        if number(config[key], key) <= 0:
            raise ValueError(key + " must be positive")
    for key in ("purchase_fee", "max_drawdown"):
        if number(config[key], key) >= 1:
            raise ValueError(key + " must be below one")
    for key in ("confirmation_sessions", "settlement_sessions", "max_trials_per_snapshot", "history_sessions"):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(key + " must be a positive integer")
    previous = 0
    for days, fee in config["redemption_fees"]:
        if type(days) is not int or days <= previous or number(fee, "redemption fee") >= 1:
            raise ValueError("invalid redemption fee schedule")
        previous = days
    if previous < 36500:
        raise ValueError("redemption fee schedule needs a final long-term tier")
    date.fromisoformat(config["validation_start"])
    date.fromisoformat(config["validation_end"])
    if config["validation_start"] >= config["validation_end"]:
        raise ValueError("invalid validation dates")


def panel(snapshot):
    validate_rows(snapshot["rows"], snapshot["funds"])
    by_date = {}
    for row in snapshot["rows"]:
        by_date.setdefault(row["date"], {})[row["code"]] = row
    shared = [day for day in sorted(by_date) if set(by_date[day]) == set(snapshot["funds"])]
    if not shared:
        raise ValueError("no common NAV sessions")
    if any(row.get("dividend", 0) for day, items in by_date.items()
           if shared[0] <= day <= shared[-1] and set(items) != set(snapshot["funds"]) for row in items.values()):
        raise ValueError("corporate action falls on an excluded common session")
    # Never backfill missing prices. Intersection limitation is explicit in results.
    return [{"date": day, "funds": by_date[day]} for day in sorted(by_date)
            if set(by_date[day]) == set(snapshot["funds"])]


def targets(value, funds):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - set(funds):
        raise ValueError("strategy must return None or known fund weights")
    weights = {code: number(value.get(code, 0), "weight") for code in funds}
    if sum(weights.values()) > 1 + 1e-9:
        raise ValueError("weights exceed one; leverage forbidden")
    return weights


def simulate(snapshot, config, code, runner=None):
    validate_config(config)
    if sorted(snapshot["funds"]) != sorted(config["funds"]):
        raise ValueError("snapshot fund pool differs from fixed evaluation")
    bars = panel(snapshot)
    if bars[0]["date"] >= config["validation_start"]:
        raise ValueError("snapshot lacks pre-validation observations")
    if bars[-1]["date"] < config["validation_end"]:
        raise ValueError("snapshot does not cover validation end; refresh or explicitly revise the host evaluation config")
    active = [i for i, bar in enumerate(bars) if config["validation_start"] <= bar["date"] <= config["validation_end"] and i > 0]
    if len(active) < 2:
        raise ValueError("at least two evaluable sessions and one prior observation required")
    funds = sorted(snapshot["funds"])
    cash = float(config["initial_cash"])
    lots = {fund: [] for fund in funds}
    pending_cash, fills, curve = [], [], []
    total_fees = 0.0
    runner = runner if runner is not None else Candidate(code, config["candidate_timeout_seconds"])
    last_target = None
    try:
        for i in active:
            bar = bars[i]
            prices = {fund: bar["funds"][fund]["nav"] for fund in funds}
            # Corporate actions on held units, before that day's new subscriptions.
            dividend_cash = sum(sum(lot["units"] for lot in lots[fund]) * bar["funds"][fund].get("dividend", 0) for fund in funds)
            cash += sum(item[1] for item in pending_cash if item[0] <= i)
            pending_cash = [item for item in pending_cash if item[0] > i]
            units = {fund: sum(lot["units"] for lot in lots[fund]) for fund in funds}
            # Decisions see only prior NAV and marked values using prior NAV.
            visible_prices = {fund: bars[i - 1]["funds"][fund]["nav"] for fund in funds}
            portfolio = {"cash": cash, "units": units, "prices": visible_prices,
                         "pending_cash": sum(item[1] for item in pending_cash)}
            history = [{"date": old["date"], "nav": {f: old["funds"][f]["nav"] for f in funds},
                        "dividend": {f: old["funds"][f].get("dividend", 0) for f in funds}}
                       for old in bars[max(0, i - config["history_sessions"]):i]]
            weights = targets(runner.decide(history, portfolio), funds)
            if weights is not None:
                last_target = weights
                # Quantity sizing uses visible NAV; actual fill uses current unknown NAV.
                equity_visible = cash + portfolio["pending_cash"] + sum(units[f] * visible_prices[f] for f in funds)
                desired = {f: equity_visible * weights[f] for f in funds}
                for fund in funds:
                    sell_units = max(0, units[fund] - desired[fund] / visible_prices[fund])
                    if sell_units * visible_prices[fund] < config["min_trade"]:
                        continue
                    gross, fees, sold = 0.0, 0.0, 0.0
                    for lot in lots[fund]:
                        if lot["confirmed"] > i:
                            continue
                        quantity = min(lot["units"], sell_units - sold)
                        age = (date.fromisoformat(bar["date"]) - date.fromisoformat(lot["confirmed_date"])).days
                        rate = next((fee for days, fee in config["redemption_fees"] if age < days), None)
                        if rate is None:
                            raise ValueError("holding period outside configured fee schedule")
                        gross += quantity * prices[fund]
                        fees += quantity * prices[fund] * rate
                        lot["units"] -= quantity
                        sold += quantity
                        if sold >= sell_units - 1e-10:
                            break
                    if sold:
                        pending_cash.append((i + config["settlement_sessions"], gross - fees))
                        fills.append({"date": bar["date"], "code": fund, "side": "redeem", "units": sold, "gross": gross, "fee": fees})
                        total_fees += fees
                wants = {f: max(0, desired[f] - units[f] * visible_prices[f]) for f in funds}
                scale = min(1, cash / sum(wants.values())) if sum(wants.values()) else 0
                for fund in funds:
                    amount = wants[fund] * scale
                    if amount < config["min_trade"]:
                        continue
                    net = amount / (1 + config["purchase_fee"])
                    quantity = math.floor(net / prices[fund] * 100 + 1e-9) / 100
                    if quantity <= 0:
                        continue
                    confirmed = i + config["confirmation_sessions"]
                    # Confirmation date beyond the data range remains unresolved, never fabricated.
                    confirmed_date = bars[confirmed]["date"] if confirmed < len(bars) else "9999-12-31"
                    fee = amount - net
                    lots[fund].append({"units": quantity, "confirmed": confirmed, "confirmed_date": confirmed_date})
                    cash -= amount
                    fills.append({"date": bar["date"], "code": fund, "side": "purchase", "units": quantity, "gross": amount, "fee": fee,
                                  "rounding_loss": net - quantity * prices[fund]})
                    total_fees += fee
            cash += dividend_cash
            equity = cash + sum(item[1] for item in pending_cash) + sum(sum(lot["units"] for lot in lots[f]) * prices[f] for f in funds)
            curve.append({"date": bar["date"], "equity": equity, "cash": cash,
                          "pending_cash": sum(item[1] for item in pending_cash),
                          "units": {f: sum(lot["units"] for lot in lots[f]) for f in funds},
                          "last_target": last_target, "decision_input_date": history[-1]["date"],
                          "fees_to_date": total_fees})
    finally:
        runner.close()
    peak, max_dd = config["initial_cash"], 0.0
    for point in curve:
        peak = max(peak, point["equity"])
        max_dd = max(max_dd, 1 - point["equity"] / peak)
    return {"metrics": {"total_return": curve[-1]["equity"] / config["initial_cash"] - 1,
                         "max_drawdown": max_dd, "fees": total_fees, "trade_count": len(fills)},
            "curve": curve, "fills": fills, "cash": cash, "lots": lots,
            "pending_cash": sum(item[1] for item in pending_cash), "last_target": last_target,
            "simulation_as_of": curve[-1]["date"], "common_sessions": len(bars),
            "discarded_rows": len(snapshot["rows"]) - len(bars) * len(funds),
            "assumptions": config["assumptions"]}
