def strategy(history, portfolio):
    # Called with yesterday-or-earlier observations. Return target weights.
    # Rebalance on the first visible session of a new month.
    if sum(portfolio["units"][code] for code in portfolio["units"]) > 0 and len(history) > 1 and history[-1]["date"][:7] == history[-2]["date"][:7]:
        return None
    codes = sorted(portfolio["units"])
    return {code: 1.0 / len(codes) for code in codes}
