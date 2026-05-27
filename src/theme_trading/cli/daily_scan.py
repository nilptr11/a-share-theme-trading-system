"""每日扫描命令行入口。"""

import argparse
import time as _time
from datetime import datetime, timedelta

from theme_trading.cli.render_daily_scan import render_daily_scan_report
from theme_trading.data.market_data import fetch_trade_cal
from theme_trading.scanner import daily_scan


def find_latest_trade_date() -> str:
    """获取最近交易日。"""
    today = datetime.now()
    start = (today - timedelta(days=20)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    cal = fetch_trade_cal(start_date=start, end_date=end)
    if cal is not None and len(cal) > 0 and "is_open" in cal.columns:
        open_days = cal[cal["is_open"].astype(str) == "1"].sort_values("cal_date")
        if len(open_days) > 0:
            return str(open_days.iloc[-1]["cal_date"])

    weekday = today.weekday()
    if weekday >= 5:
        today = today - timedelta(days=weekday - 4)
    return today.strftime("%Y%m%d")


def main():
    parser = argparse.ArgumentParser(description="A股主题选股每日扫描")
    parser.add_argument("date", nargs="?", default=None,
                        help="交易日期 YYYYMMDD，默认最近交易日")
    parser.add_argument("--sectors", type=int, default=15,
                        help="候选板块数 (默认 15)")
    parser.add_argument("--no-buy-points", action="store_true",
                        help="跳过买点扫描（快速模式）")
    args = parser.parse_args()

    trade_date = args.date or find_latest_trade_date()
    print(f"扫描日期: {trade_date}")
    print()

    t0 = _time.time()
    report = daily_scan(
        trade_date,
        sector_codes=None,
        theme_top_n=args.sectors,
        include_buy_points=not args.no_buy_points,
    )
    print(render_daily_scan_report(report, elapsed_seconds=_time.time() - t0))


if __name__ == "__main__":
    main()
