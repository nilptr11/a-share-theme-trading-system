"""一站式每日扫描。"""

from theme_trading.data.tushare_client import clear_cache

from .buy_points import scan_buy_points
from .core_stocks import filter_core_stocks
from .market_score import compute_market_score
from .pre_trade import pre_trade_checklist
from .themes import find_main_themes


def _append_observation(report: dict, category: str, items: list[dict]) -> None:
    for item in items:
        report["observation_pool"].append({"category": category, **item})


def daily_scan(
    trade_date: str,
    sector_codes: list[str] = None,
    theme_top_n: int = 15,
    include_buy_points: bool = True,
) -> dict:
    """执行完整的每日扫描流程。"""
    clear_cache()

    report = {
        "trade_date": trade_date,
        "market_score": None,
        "market_gate": None,
        "themes": None,
        "core_stocks": None,
        "buy_scans": [],
        "observation_pool": [],
        "pending_confirmations": [],
        "executable_plans": [],
        "blocked_reasons": [],
        "data_warnings": [],
        "human_judgment": [],
    }

    score = compute_market_score(trade_date)
    report["market_score"] = score
    report["market_gate"] = score.get("trade_permission")
    report["human_judgment"].extend(score.get("human_judgment", []))
    report["data_warnings"].extend(score.get("data_warnings", []))
    report["blocked_reasons"].extend(score.get("hard_rules", {}).get("violations", []))

    market_closed = score.get("trade_permission") == "closed"
    if market_closed:
        report["human_judgment"].append("市场开关关闭，后续只生成观察池，不生成可执行预案")

    if score.get("emotion_extreme"):
        report["risk_notes"] = report.get("risk_notes", [])
        report["risk_notes"].append(
            "情绪极端（上涨家数 > 3500 或板块高潮）：新开仓风险预算降至 0.5%，不追涨，只等分歧后的回踩确认"
        )

    themes = find_main_themes(trade_date, top_n=theme_top_n)
    report["themes"] = themes
    report["human_judgment"].extend(themes.get("human_judgment", []))
    report["data_warnings"].extend(themes.get("data_warnings", []))
    _append_observation(report, "watch_theme", themes.get("watch_themes", []))

    confirmed_themes = themes.get("confirmed_themes", [])
    if not confirmed_themes:
        report["blocked_reasons"].append("无确认主线，不生成核心股买点扫描")
        return report

    if sector_codes is None:
        sector_codes = [theme["ts_code"] for theme in confirmed_themes[:3]]

    stocks = filter_core_stocks(trade_date, sector_codes)
    report["core_stocks"] = stocks
    report["human_judgment"].extend(stocks.get("human_judgment", []))
    report["data_warnings"].extend(stocks.get("data_warnings", []))
    _append_observation(report, "watch_core_stock", stocks.get("watch_core_stocks", []))

    confirmed_core_stocks = stocks.get("confirmed_core_stocks", [])
    if not confirmed_core_stocks:
        report["blocked_reasons"].append("无确认核心强势股，不生成买点扫描")
        return report

    if not include_buy_points:
        report["human_judgment"].append("已跳过买点扫描")
        _append_observation(report, "confirmed_core_stock", confirmed_core_stocks[:20])
        return report

    theme_by_code = {theme["ts_code"]: theme for theme in confirmed_themes}
    for stock in confirmed_core_stocks[:10]:
        sector_context = theme_by_code.get(stock.get("sector_code"))
        bp = scan_buy_points(
            stock["ts_code"],
            trade_date,
            market_context=score,
            sector_context=sector_context,
            core_context=stock,
        )
        if not bp.get("ok", True):
            report["pending_confirmations"].append({
                "ts_code": stock["ts_code"],
                "reason": bp.get("error", "买点扫描失败"),
            })
            continue

        selected = bp.get("selected_buy_point")
        if selected:
            info = bp["buy_points"][selected]
            signal = {
                "ts_code": stock["ts_code"],
                "buy_point": selected,
                "status": info.get("status"),
                "close": bp.get("close"),
                "stop_loss": info.get("stop_loss"),
                "execution_check": info.get("execution_check"),
                "failure_signals": info.get("failure_signals", []),
                "manual_checks": info.get("manual_checks", []),
                "suppressed_by_priority": bp.get("suppressed_by_priority", []),
            }
            if selected == "买点四_趋势均线":
                signal["risk_budget_note"] = "买点四趋势成熟阶段，风险预算减半（强市 0.5%，中市 0.25%）"
            if score.get("emotion_extreme"):
                signal["risk_budget_note"] = signal.get("risk_budget_note", "情绪极端，风险预算降至 0.5%")

            report["buy_scans"].append(bp)
            if market_closed:
                signal["reason"] = "市场开关关闭，仅观察"
                report["blocked_reasons"].append(f"{stock['ts_code']} {selected} 因市场开关关闭不列入预案")
                report["observation_pool"].append({"category": "blocked_buy_setup", **signal})
            elif info.get("status") in {"executable_plan", "pending_next_open"}:
                report["executable_plans"].append(signal)
            elif info.get("status") in {"pending_next_day_strength", "watch"}:
                report["pending_confirmations"].append(signal)
            else:
                report["blocked_reasons"].append(f"{stock['ts_code']} {selected} 状态 {info.get('status')}，不生成预案")
        else:
            report["observation_pool"].append({"category": "confirmed_core_stock", **stock})

    if not report["buy_scans"]:
        report["human_judgment"].append("确认核心股中无买点 setup 触发")

    theme_by_name = {theme["ts_code"]: theme for theme in confirmed_themes}
    report["pre_trade_checks"] = []
    for plan in report.get("executable_plans", []):
        ts_code = plan["ts_code"]
        stock = next((s for s in confirmed_core_stocks[:10] if s["ts_code"] == ts_code), None)
        sector_ctx = theme_by_name.get(stock.get("sector_code")) if stock else None
        checklist = pre_trade_checklist(
            market_context=score,
            theme_context=sector_ctx,
            core_stock=stock,
            buy_point_info=plan,
        )
        report["pre_trade_checks"].append({
            "ts_code": ts_code,
            "all_passed": checklist["all_passed"],
            "checks": checklist["checks"],
            "three_questions": checklist["three_questions"],
            "block_reasons": checklist["block_reasons"],
        })

    return report
