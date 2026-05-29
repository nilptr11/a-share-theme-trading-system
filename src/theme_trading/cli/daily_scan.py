"""每日扫描命令行入口。"""

import argparse
import time as _time
from datetime import datetime, timedelta

from theme_trading.cli.render_daily_scan import render_daily_scan_report, render_execution_confirmation
from theme_trading.data.market_data import fetch_trade_cal
from theme_trading.scanner import confirm_open_from_plan, daily_scan, save_decision_plan


def find_latest_trade_date() -> str:
    """获取最近已收盘并预留落库时间的完整交易日。"""
    now = datetime.now()
    today_str = now.strftime("%Y%m%d")
    start = (now - timedelta(days=20)).strftime("%Y%m%d")
    end = today_str
    cal = fetch_trade_cal(start_date=start, end_date=end)
    if cal is not None and len(cal) > 0 and "is_open" in cal.columns:
        open_days = cal[cal["is_open"].astype(str) == "1"].sort_values("cal_date")
        if len(open_days) > 0:
            latest = str(open_days.iloc[-1]["cal_date"])
            if latest == today_str and now.hour < 18 and len(open_days) > 1:
                return str(open_days.iloc[-2]["cal_date"])
            return latest

    fallback = now
    weekday = fallback.weekday()
    if weekday >= 5:
        fallback = fallback - timedelta(days=weekday - 4)
    elif now.hour < 18:
        fallback = fallback - timedelta(days=1)
        while fallback.weekday() >= 5:
            fallback = fallback - timedelta(days=1)
    return fallback.strftime("%Y%m%d")


def main():
    parser = argparse.ArgumentParser(description="A股主题选股每日扫描")
    parser.add_argument("date", nargs="?", default=None,
                        help="收盘决策日期 YYYYMMDD，默认最近已收盘完整交易日")
    parser.add_argument("--sectors", type=int, default=15,
                        help="候选板块数 (默认 15)")
    parser.add_argument("--no-buy-points", action="store_true",
                        help="跳过买点扫描（快速模式）")
    parser.add_argument("--save-plan", action="store_true",
                        help="保存收盘决策人工执行预案 JSON，默认 plans/<decision_date>.json")
    parser.add_argument("--plan-output", default=None,
                        help="指定预案 JSON 输出路径")
    parser.add_argument("--confirm-open", action="store_true",
                        help="读取预案 JSON 并执行次日开盘人工执行确认")
    parser.add_argument("--plan", default=None,
                        help="用于 --confirm-open 的预案 JSON 路径")
    parser.add_argument("--execution-date", default=None,
                        help="执行确认日期 YYYYMMDD，默认使用预案 planned_execution_date")
    parser.add_argument("--confirmation-output", default=None,
                        help="指定确认 JSON 输出路径，默认 confirmations/<execution_date>.json")
    args = parser.parse_args()

    if args.confirm_open:
        if not args.plan:
            parser.error("--confirm-open 需要同时指定 --plan <plan.json>")
        t0 = _time.time()
        confirmation, output_path = confirm_open_from_plan(
            args.plan,
            execution_date=args.execution_date,
            output_path=args.confirmation_output,
        )
        print(render_execution_confirmation(confirmation))
        print()
        print(f"确认结果已保存: {output_path}")
        print(f"总耗时: {_time.time() - t0:.0f}s")
        return

    trade_date = args.date or find_latest_trade_date()
    print(f"收盘决策日期 / latest_complete_trade_date: {trade_date}")
    print()

    t0 = _time.time()
    report = daily_scan(
        trade_date,
        sector_codes=None,
        theme_top_n=args.sectors,
        include_buy_points=not args.no_buy_points,
    )
    print(render_daily_scan_report(report, elapsed_seconds=_time.time() - t0))
    if args.save_plan:
        plan, output_path = save_decision_plan(report, args.plan_output)
        print()
        print(f"人工执行预案已保存: {output_path}")
        print(f"预案状态: 待次日开盘人工执行确认；计划数: {len(plan.get('plans', []))}")


if __name__ == "__main__":
    main()
