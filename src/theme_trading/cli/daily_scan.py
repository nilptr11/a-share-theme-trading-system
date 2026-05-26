"""每日扫描命令行入口。"""

import argparse
import time as _time
from datetime import datetime

from theme_trading.scanner import daily_scan, format_score_report


def find_latest_trade_date() -> str:
    """获取最近的交易日（简化版：取今天或上周五）"""
    today = datetime.now()
    weekday = today.weekday()
    if weekday >= 5:
        today = today.replace(day=today.day - (weekday - 4))
    return today.strftime("%Y%m%d")


def main():
    parser = argparse.ArgumentParser(description="A股交易系统每日扫描")
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

    print(format_score_report(report["market_score"]))
    print()

    themes = report.get("themes")
    if themes and themes.get("candidates"):
        print(f"候选主线 ({len(themes['candidates'])} 个):")
        for t in themes["candidates"][:8]:
            print(f"  {t['name']:24s} {t['pct_chg']:+.2f}%  "
                  f"连续 {t['consecutive_days']}日强  "
                  f"量比 {t['vol_ratio']:.1f}  "
                  f"涨停 {t.get('up_in_sector', '?')}只  "
                  f"评分 {t['score']}")
        print()

    stocks = report.get("core_stocks")
    if stocks and stocks.get("candidates"):
        print(f"核心强势股候选 ({len(stocks['candidates'])} 只):")
        for s in stocks["candidates"][:12]:
            print(f"  {s['ts_code']:12s} {s['pct_chg']:+.2f}%  "
                  f"成交额排名 {s['amount_rank']}  "
                  f"换手 {s['turnover_rate']}%")
        print()

    scans = report.get("buy_scans", [])
    if scans:
        print(f"触发买点的个股 ({len(scans)} 只):")
        for bp in scans:
            print(f"  {bp['ts_code']}:")
            for name, info in bp["buy_points"].items():
                if info["triggered"]:
                    print(f"    {name}  止损 {info.get('stop_loss')}  {info.get('note', '')}")
        print()
    elif not args.no_buy_points:
        print("无标准买点触发")
        print()

    human = report.get("human_judgment", [])
    if human:
        print("─" * 60)
        print("需人工确认:")
        for h in human:
            print(f"  ? {h}")

    print()
    print(f"总耗时: {_time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
