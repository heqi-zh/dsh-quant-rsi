from datetime import date, datetime, timezone
import json
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .storage import digest, number, write


def validate_rows(rows, funds):
    if not rows or not funds or len(set(funds)) != len(funds):
        raise ValueError("nonempty unique funds and NAV rows required")
    seen = set()
    for row in rows:
        date.fromisoformat(row["date"])
        code = row["code"]
        key = (row["date"], code)
        if code not in funds or key in seen:
            raise ValueError("unknown fund or duplicate NAV")
        seen.add(key)
        if number(row["nav"], "nav") <= 0:
            raise ValueError("NAV must be positive")
        number(row.get("dividend", 0), "dividend")
    for code in funds:
        if not any(row["code"] == code for row in rows):
            raise ValueError("missing fund " + code)


def fetch_fund(code, start_date=None):
    """Read public Eastmoney history. Never access a personal account."""
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("fund code must have six digits")
    rows, raw_pages = [], []
    page, count = 1, None
    while count is None or len(rows) < count:
        query = urlencode({"fundCode": code, "pageIndex": page, "pageSize": 20})
        request = Request("https://api.fund.eastmoney.com/f10/lsjz?" + query,
                          headers={"Referer": "https://fundf10.eastmoney.com/", "User-Agent": "Mozilla/5.0 DQR/0.1"})
        with urlopen(request, timeout=20) as response:
            raw = json.load(response)
        raw_pages.append(raw)
        data = raw["Data"]["LSJZList"]
        count = int(raw["TotalCount"])
        if raw.get("ErrCode") != 0 or int(raw["PageIndex"]) != page or count > 100000 or not data:
            raise ValueError("unexpected NAV pagination")
        for item in data:
            # Corporate actions must be explicit. Do not silently ignore source text.
            action = (item.get("FHSP") or "").strip()
            dividend = 0.0
            if action and action not in ("--", "暂无分红信息"):
                match = re.fullmatch(r"每([0-9.]+)?份派现金([0-9.]+)元", action)
                if not match:
                    raise ValueError("unsupported corporate action for %s: %s" % (code, action))
                denominator = float(match.group(1) or "1")
                if denominator <= 0:
                    raise ValueError("invalid dividend denominator")
                dividend = float(match.group(2)) / denominator
            rows.append({"date": item["FSRQ"], "code": code, "nav": float(item["DWJZ"]), "dividend": dividend})
        page += 1
        if start_date and min(item["FSRQ"] for item in data) <= start_date:
            break
        if page > 1000:
            raise ValueError("NAV pagination limit exceeded")
    if start_date:
        rows = [row for row in rows if row["date"] >= start_date]
    return rows, raw_pages


def save_snapshot(directory, funds, rows, source, raw=None):
    validate_rows(rows, funds)
    payload = {"schema": "dqr.snapshot.v1", "funds": sorted(funds),
               "rows": sorted(rows, key=lambda row: (row["date"], row["code"])),
               "source": source, "retrieved_at": datetime.now(timezone.utc).isoformat()}
    if raw is not None:
        payload["raw"] = raw
    identity = digest(payload)
    write(directory / "snapshots" / (identity + ".json"), payload)
    return identity
