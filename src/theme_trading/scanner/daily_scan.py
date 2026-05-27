"""一站式每日扫描。"""

from theme_trading.data.tushare_client import clear_cache

from .buy_points import scan_buy_points
from .core_stocks import filter_core_stocks
from .market_score import check_sector_climax, compute_market_score
from .pending import review_pending_setups
from .report import add_messages, add_risk_note, append_observation, new_daily_report
from .routing import route_signal
from .signals import build_signal_from_buy_scan
from .themes import find_main_themes


def daily_scan(
    trade_date: str,
    sector_codes: list[str] = None,
    theme_top_n: int = 15,
    include_buy_points: bool = True,
    pending_setups: list[dict] | None = None,
) -> dict:
    """执行完整的每日扫描流程。"""
    clear_cache()
    report = new_daily_report(trade_date)

    score = compute_market_score(trade_date)
    report["market_score"] = score
    report["market_gate"] = score.get("trade_permission")
    add_messages(report, score)
    report["blocked_reasons"].extend(score.get("hard_rules", {}).get("violations", []))

    market_closed = score.get("trade_permission") == "closed"
    if market_closed:
        report["human_judgment"].append("市场开关关闭，后续只生成观察池，不生成可执行预案")

    breadth_extreme = score.get("emotion_extreme", False)

    themes = find_main_themes(trade_date, top_n=theme_top_n)
    report["themes"] = themes
    add_messages(report, themes)
    append_observation(report, "watch_theme", themes.get("watch_themes", []))

    confirmed_themes = themes.get("confirmed_themes", [])
    watch_themes = themes.get("watch_themes", [])
    _append_sector_climax_notes(report, confirmed_themes + watch_themes)

    score["emotion_extreme"] = breadth_extreme
    if breadth_extreme:
        report.setdefault("risk_notes", [])
        add_risk_note(report, "情绪极端（上涨家数 > 3500）：不追涨，只等分歧后的回踩确认")

    trial_mode = not confirmed_themes and bool(watch_themes)
    if not confirmed_themes and not trial_mode:
        report["blocked_reasons"].append("无确认主线且无观察主线，不生成核心股买点扫描")
        return report

    if trial_mode and watch_themes:
        report["human_judgment"].append("主线仅处于观察状态，仅允许买点一试错预案")

    active_themes = confirmed_themes if confirmed_themes else watch_themes
    if sector_codes is None:
        sector_codes = [theme["ts_code"] for theme in active_themes[:3]]

    stocks = filter_core_stocks(trade_date, sector_codes)
    report["core_stocks"] = stocks
    add_messages(report, stocks)
    append_observation(report, "watch_core_stock", stocks.get("watch_core_stocks", []))

    confirmed_core_stocks = stocks.get("confirmed_core_stocks", [])
    watch_core = stocks.get("watch_core_stocks", [])
    core_universe = confirmed_core_stocks[:10] if confirmed_core_stocks else watch_core[:5]

    if not core_universe:
        if watch_core:
            report["blocked_reasons"].append("无确认核心强势股，仅保留观察核心股，不生成买点扫描")
        else:
            report["blocked_reasons"].append("无确认核心强势股，不生成买点扫描")
        return report

    if not include_buy_points:
        report["human_judgment"].append("已跳过买点扫描")
        append_observation(report, "confirmed_core_stock", confirmed_core_stocks[:20])
        return report

    theme_by_code = {theme["ts_code"]: theme for theme in active_themes}
    stock_by_code = {stock["ts_code"]: stock for stock in core_universe}

    review_pending_setups(
        report,
        pending_setups,
        trade_date=trade_date,
        score=score,
        theme_by_code=theme_by_code,
        stock_by_code=stock_by_code,
        market_closed=market_closed,
    )

    _scan_current_buy_points(
        report,
        core_universe,
        trade_date=trade_date,
        score=score,
        theme_by_code=theme_by_code,
        trial_mode=trial_mode,
        market_closed=market_closed,
    )

    if not report["buy_scans"]:
        report["human_judgment"].append("核心股中无买点 setup 触发")

    return report


def _append_sector_climax_notes(report: dict, sectors: list[dict]) -> None:
    for sector in sectors[:3]:
        sc = check_sector_climax(sector)
        if sc["climax"]:
            add_risk_note(
                report,
                f"板块 {sector.get('name', sector.get('ts_code', ''))} 高潮信号: {'; '.join(sc['reasons'])}",
            )
            report["human_judgment"].extend(sc["action_notes"])


def _score_for_stock(score: dict, sector_context: dict | None) -> dict:
    if sector_context and check_sector_climax(sector_context)["climax"]:
        stock_score = dict(score)
        stock_score["emotion_extreme"] = True
        return stock_score
    return score


def _scan_current_buy_points(
    report: dict,
    core_universe: list[dict],
    *,
    trade_date: str,
    score: dict,
    theme_by_code: dict[str, dict],
    trial_mode: bool,
    market_closed: bool,
) -> None:
    for stock in core_universe:
        sector_context = theme_by_code.get(stock.get("sector_code"))
        stock_score = _score_for_stock(score, sector_context)
        bp = scan_buy_points(
            stock["ts_code"],
            trade_date,
            market_context=stock_score,
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
        if not selected:
            report["observation_pool"].append({"category": "core_no_buy_point", **stock})
            continue

        if trial_mode and selected != "买点一_放量突破":
            report["blocked_reasons"].append(
                f"{stock['ts_code']} {selected} 主线未确认，仅买点一允许试错预案"
            )
            report["observation_pool"].append({
                "category": "blocked_trial_mode",
                "ts_code": stock["ts_code"],
                "buy_point": selected,
                "reason": "主线未确认，仅买点一允许试错预案",
            })
            continue

        signal = build_signal_from_buy_scan(
            stock,
            bp,
            selected,
            market_context=stock_score,
            theme_context=sector_context,
            trial_mode=trial_mode,
        )
        report["buy_scans"].append(bp)
        route_signal(
            report,
            signal,
            market_closed=market_closed,
            trial_mode=trial_mode,
            blocked_message=f"{stock['ts_code']} {selected} 状态 {signal.get('status')}，不生成预案",
            market_closed_message=f"{stock['ts_code']} {selected} 因市场开关关闭不列入预案",
        )
