"""每日扫描命令行入口。"""

import argparse
import time as _time
from datetime import datetime, timedelta

from theme_trading.data.market_data import fetch_trade_cal
from theme_trading.scanner import daily_scan, format_score_report


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


def _print_conditions(conditions: dict) -> str:
    passed = [key for key, value in conditions.items() if value]
    return ", ".join(passed) if passed else "无"


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

    print(format_score_report(report["market_score"]))
    print()

    themes = report.get("themes") or {}
    confirmed_themes = themes.get("confirmed_themes", [])
    watch_themes = themes.get("watch_themes", [])
    if confirmed_themes:
        print(f"确认主线 ({len(confirmed_themes)} 个):")
        for t in confirmed_themes[:8]:
            print(f"  {t['name']:24s} {t['pct_chg']:+.2f}%  "
                  f"满足 {t['condition_count']}/5  连续强 {t['consecutive_days']}日  "
                  f"量比 {t['amount_ratio']:.1f}  涨停 {t.get('up_in_sector', '?')}只")
            missing = t.get("missing_conditions", [])
            if missing:
                print(f"    缺: {', '.join(missing)}")
        print()
    if watch_themes:
        print(f"观察主线 ({len(watch_themes)} 个):")
        for t in watch_themes[:5]:
            print(f"  {t['name']:24s} {t['pct_chg']:+.2f}%  满足 {t['condition_count']}/5  "
                  f"缺: {', '.join(t.get('missing_conditions', []))}")
        print()

    stocks = report.get("core_stocks") or {}
    confirmed_stocks = stocks.get("confirmed_core_stocks", [])
    watch_stocks = stocks.get("watch_core_stocks", [])
    if confirmed_stocks:
        print(f"确认核心强势股 ({len(confirmed_stocks)} 只):")
        for s in confirmed_stocks[:12]:
            leader = s.get("leader_effect")
            leader_str = "带动" if leader is True else ("未带动" if leader is False else "带动?")
            print(f"  {s['ts_code']:12s} {s.get('name') or '':8s} {s['pct_chg']:+.2f}%  "
                  f"满足 {s['condition_count']}/5  成交额排名 {s['amount_rank']}  "
                  f"板块排名 {s.get('sector_amount_rank')}  换手 {s['turnover_rate']}%  "
                  f"带动性: {leader_str}")
        print()
    if watch_stocks:
        print(f"观察核心股 ({len(watch_stocks)} 只):")
        for s in watch_stocks[:8]:
            leader = s.get("leader_effect")
            leader_str = "带动" if leader is True else ("未带动" if leader is False else "带动?")
            print(f"  {s['ts_code']:12s} {s.get('name') or '':8s} {s['pct_chg']:+.2f}%  "
                  f"满足 {s['condition_count']}/5  缺: {', '.join(s.get('missing_conditions', []))}  "
                  f"带动性: {leader_str}")
        print()

    pending = report.get("pending_confirmations", [])
    if pending:
        print(f"待确认 ({len(pending)} 项):")
        for item in pending[:12]:
            if "buy_point" in item:
                print(f"  {item['ts_code']} {item['buy_point']}  状态 {item['status']}  止损参考 {item.get('stop_loss')}")
                for check in item.get("manual_checks", [])[:2]:
                    print(f"    ? {check}")
            else:
                print(f"  {item.get('ts_code', '-')}: {item.get('reason', item)}")
        print()

    plans = report.get("executable_plans", [])
    if plans:
        print(f"可执行预案 ({len(plans)} 只):")
        for item in plans:
            execution = item.get("execution_check", {})
            dates = f"信号日 {item.get('setup_date') or '-'}  →  确认日 {item.get('confirm_date') or '-'}  →  计划买入日 {item.get('execution_date') or '-'}"
            print(f"  {item['ts_code']}  {item['buy_point']}  状态 {item['status']}")
            print(f"    {dates}")
            print(f"    确认收盘 {item.get('close')}  止损参考 {item.get('stop_loss')}  "
                  f"执行条件: {execution.get('rule', '次日开盘 ±3% 内')}")
            if item.get("risk_budget_label"):
                print(f"    风险预算: {item['risk_budget_label']}（{item.get('risk_budget_reason', '')}）")
            failures = item.get("failure_signals", [])
            if failures:
                print(f"    失败信号: {' / '.join(failures[:3])}")
        print()

    trial_plans = report.get("trial_plans", [])
    if trial_plans:
        print(f"试错预案 ({len(trial_plans)} 只) — 主线未确认，仅买点一:")
        for item in trial_plans:
            execution = item.get("execution_check", {})
            dates = f"信号日 {item.get('setup_date') or '-'}  →  确认日 {item.get('confirm_date') or '-'}  →  计划买入日 {item.get('execution_date') or '-'}"
            print(f"  {item['ts_code']}  {item['buy_point']}  状态 {item['status']}")
            print(f"    {dates}")
            print(f"    确认收盘 {item.get('close')}  止损参考 {item.get('stop_loss')}  "
                  f"执行条件: {execution.get('rule', '次日开盘 ±3% 内')}")
            if item.get("risk_budget_label"):
                print(f"    风险预算: {item['risk_budget_label']}（{item.get('risk_budget_reason', '')}）")
            failures = item.get("failure_signals", [])
            if failures:
                print(f"    失败信号: {' / '.join(failures[:3])}")
        print()

    pre_trade = report.get("pre_trade_checks", [])
    if pre_trade:
        print(f"买入前检查清单 ({len(pre_trade)} 项):")
        for check in pre_trade:
            passed_str = "通过" if check["all_passed"] else "未通过"
            questions = check.get("three_questions", {})
            print(f"  {check['ts_code']}: {passed_str}")
            if questions.get("answered"):
                print(f"    为什么是它: {questions['why_this']}")
                print(f"    为什么是现在: {questions['why_now']}")
                print(f"    错了在哪里走: {questions['where_exit']}")
            for reason in check.get("block_reasons", []):
                print(f"    ✗ {reason}")
        print()

    blocked = report.get("blocked_reasons", [])
    if blocked:
        print("阻断原因:")
        for reason in blocked[:12]:
            print(f"  - {reason}")
        print()

    warnings = report.get("data_warnings", [])
    if warnings:
        print("数据提示:")
        for warning in dict.fromkeys(warnings):
            print(f"  ? {warning}")
        print()

    human = report.get("human_judgment", [])
    if human:
        print("─" * 60)
        print("需人工确认:")
        for h in human:
            print(f"  ? {h}")

    risk_notes = report.get("risk_notes", [])
    if risk_notes:
        print()
        print("风险提示:")
        for note in risk_notes:
            print(f"  ⚠ {note}")

    print()
    print(f"总耗时: {_time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
