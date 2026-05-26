"""一站式每日扫描。"""

from theme_trading.data.tushare_client import clear_cache

from .buy_points import scan_buy_points
from .core_stocks import filter_core_stocks
from .market_score import compute_market_score
from .themes import find_main_themes


def daily_scan(
    trade_date: str,
    sector_codes: list[str] = None,
    theme_top_n: int = 15,
    include_buy_points: bool = True,
) -> dict:
    """执行完整的每日扫描流程

    返回:
        { market_score, themes, core_stocks, buy_scans, human_judgment }
    """
    clear_cache()

    report = {
        "trade_date": trade_date,
        "market_score": None,
        "themes": None,
        "core_stocks": None,
        "buy_scans": [],
        "human_judgment": [],
    }

    # Step 1: 市场评分
    score = compute_market_score(trade_date)
    report["market_score"] = score
    report["human_judgment"].extend(score.get("human_judgment", []))

    if not score["ok"]:
        report["human_judgment"].append("市场开关关闭，停止后续扫描")
        return report

    # Step 2: 主线识别
    themes = find_main_themes(trade_date, top_n=theme_top_n)
    report["themes"] = themes
    report["human_judgment"].extend(themes.get("human_judgment", []))

    if not themes["ok"]:
        report["human_judgment"].append("无主线，停止选股")
        return report

    # 自动获取候选主线的板块代码
    if sector_codes is None and themes.get("candidates"):
        sector_codes = [t["ts_code"] for t in themes["candidates"][:3]]

    # Step 3: 核心强势股筛选
    stocks = filter_core_stocks(trade_date, sector_codes)
    report["core_stocks"] = stocks
    report["human_judgment"].extend(stocks.get("human_judgment", []))

    if not stocks["ok"]:
        return report

    # Step 4: 买点扫描
    if include_buy_points:
        for stock in stocks.get("candidates", [])[:10]:
            bp = scan_buy_points(stock["ts_code"], trade_date)
            if bp.get("any_triggered"):
                report["buy_scans"].append(bp)

        if not report["buy_scans"]:
            report["human_judgment"].append("候选核心股中无买点触发")

    return report
