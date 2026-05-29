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
        report["human_judgment"].append("市场开关关闭，后续只生成观察池，不生成人工执行预案")

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
        return _finalize_no_plan_diagnostics(report)

    if trial_mode and watch_themes:
        report["human_judgment"].append("主线仅处于观察状态，仅允许买点一试错预案")

    active_themes = confirmed_themes if confirmed_themes else watch_themes
    requested_sector_codes = set(sector_codes) if sector_codes is not None else None
    if sector_codes is None:
        sector_codes = [theme["ts_code"] for theme in active_themes[:3]]

    stocks = filter_core_stocks(trade_date, sector_codes)
    report["core_stocks"] = stocks
    add_messages(report, stocks)
    append_observation(report, "watch_core_stock", stocks.get("watch_core_stocks", []))

    confirmed_core_stocks = stocks.get("confirmed_core_stocks", [])
    watch_core = stocks.get("watch_core_stocks", [])
    core_universe = confirmed_core_stocks[:10] if confirmed_core_stocks else watch_core[:5]

    watch_shape_themes = watch_themes
    if requested_sector_codes is not None:
        watch_shape_themes = [theme for theme in watch_themes if theme["ts_code"] in requested_sector_codes]
    should_scan_watch_shapes = include_buy_points and bool(confirmed_themes) and bool(watch_shape_themes)
    if should_scan_watch_shapes:
        _scan_watch_theme_buy_shapes(
            report,
            watch_shape_themes,
            trade_date=trade_date,
            score=score,
        )

    if not core_universe:
        if watch_core:
            report["blocked_reasons"].append("无确认核心强势股，仅保留观察核心股，不生成买点扫描")
        else:
            report["blocked_reasons"].append("无确认核心强势股，不生成买点扫描")
        return _finalize_no_plan_diagnostics(report)

    if not include_buy_points:
        report["human_judgment"].append("已跳过买点扫描")
        append_observation(report, "confirmed_core_stock", confirmed_core_stocks[:20])
        return _finalize_no_plan_diagnostics(report)

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

    return _finalize_no_plan_diagnostics(report)


def _finalize_no_plan_diagnostics(report: dict) -> dict:
    themes = report.get("themes") or {}
    stocks = report.get("core_stocks") or {}
    observation_pool = report.get("observation_pool") or []
    pending_confirmations = report.get("pending_confirmations") or []
    pending_open_plans = report.get("pending_open_plans") or []
    trial_plans = report.get("trial_plans") or []

    confirmed_theme_count = len(themes.get("confirmed_themes", []) or [])
    watch_theme_count = len(themes.get("watch_themes", []) or [])
    confirmed_core_count = len(stocks.get("confirmed_core_stocks", []) or [])
    watch_core_count = len(stocks.get("watch_core_stocks", []) or [])
    scan_failure_count = len([item for item in pending_confirmations if item.get("category") == "buy_point_scan_failure"])
    invalid_setup_count = len([item for item in observation_pool if item.get("category") == "invalid_buy_setup"])
    no_buy_point_count = len([item for item in observation_pool if item.get("category") == "core_no_buy_point"])
    pending_confirmation_count = len([item for item in pending_confirmations if item.get("category") != "buy_point_scan_failure"])
    risk_notes_count = len(report.get("risk_notes", []) or [])
    has_plan = bool(pending_open_plans or trial_plans)

    reason_codes: list[str] = []
    main_reasons: list[str] = []

    def add_reason(code: str, text: str) -> None:
        if code not in reason_codes:
            reason_codes.append(code)
            main_reasons.append(text)

    market_gate = report.get("market_gate")
    if market_gate == "closed":
        add_reason("market_closed", "市场开关关闭，收盘决策只保留观察，不生成人工执行预案")
    elif market_gate == "restricted":
        add_reason("market_restricted", "市场权限受限，需严格过滤买点与风险检查")

    if confirmed_theme_count == 0:
        if watch_theme_count == 0:
            add_reason("no_theme", "无确认主线且无观察主线，未进入核心股买点扫描")
        else:
            add_reason("only_watch_theme", "主线未确认，仅允许买点一试错预案；未形成正式待开盘确认预案")

    if confirmed_theme_count > 0 and confirmed_core_count == 0:
        if watch_core_count > 0:
            add_reason("no_confirmed_core", "无确认核心强势股，仅保留观察核心股，不生成正式买点预案")
        else:
            add_reason("no_core", "无确认核心强势股，未进入买点扫描")

    if scan_failure_count:
        add_reason("buy_point_scan_failed", f"{scan_failure_count} 只核心股买点扫描失败，常见原因是行情或历史窗口数据不足")
    if invalid_setup_count:
        add_reason("invalid_setup", f"{invalid_setup_count} 个买点形态已失效，未通过确认/执行条件")
    if no_buy_point_count:
        add_reason("no_buy_point", f"{no_buy_point_count} 只核心股未触发买点 setup")
    if pending_confirmation_count:
        add_reason("pending_confirmation", f"{pending_confirmation_count} 项仍待收盘转强/人工确认，不是待开盘执行预案")
    if risk_notes_count:
        add_reason("risk_notes", f"存在 {risk_notes_count} 条风险提示，需人工复核；风险提示不会放宽买点规则")
    if report.get("pre_trade_checks") and not has_plan:
        add_reason("pre_trade_blocked", "买入前检查未通过，信号进入观察或阻断，不生成预案")
    if not has_plan and not reason_codes:
        add_reason("no_eligible_plan", "市场、主线、核心股、买点与风险检查后没有符合规则的人工执行预案")

    report["no_plan_diagnostics"] = {
        "has_plan": has_plan,
        "market_gate": market_gate,
        "confirmed_theme_count": confirmed_theme_count,
        "watch_theme_count": watch_theme_count,
        "confirmed_core_count": confirmed_core_count,
        "watch_core_count": watch_core_count,
        "scan_failure_count": scan_failure_count,
        "invalid_setup_count": invalid_setup_count,
        "no_buy_point_count": no_buy_point_count,
        "pending_confirmation_count": pending_confirmation_count,
        "risk_notes_count": risk_notes_count,
        "reason_codes": reason_codes,
        "main_reasons": main_reasons,
    }
    return report


def _append_sector_climax_notes(report: dict, sectors: list[dict]) -> None:
    climax_names = []
    for sector in sectors[:3]:
        sc = check_sector_climax(sector)
        if sc["climax"]:
            name = sector.get("name", sector.get("ts_code", ""))
            climax_names.append(name)
            add_risk_note(
                report,
                f"板块 {name} 高潮信号: {'; '.join(sc['reasons'])}",
            )

    if climax_names:
        report["human_judgment"].append(
            f"板块高潮：{', '.join(climax_names)}；优先检查卖点/止盈预案，不追涨"
        )


def _score_for_stock(score: dict, sector_context: dict | None) -> dict:
    if sector_context and check_sector_climax(sector_context)["climax"]:
        stock_score = dict(score)
        stock_score["emotion_extreme"] = True
        return stock_score
    return score


def _scan_watch_theme_buy_shapes(
    report: dict,
    watch_themes: list[dict],
    *,
    trade_date: str,
    score: dict,
) -> None:
    observable_statuses = {"pending_next_day_strength", "pending_next_open", "watch"}
    seen: set[tuple[str, str]] = set()
    scan_cache: dict[tuple[str, str], dict] = {}

    for theme in watch_themes[:3]:
        stocks = filter_core_stocks(trade_date, [theme["ts_code"]])
        candidates = (stocks.get("confirmed_core_stocks", []) + stocks.get("watch_core_stocks", []))[:5]
        for stock in candidates:
            cache_key = (theme["ts_code"], stock["ts_code"])
            if cache_key in scan_cache:
                bp = scan_cache[cache_key]
            else:
                stock_score = _score_for_stock(score, theme)
                bp = scan_buy_points(
                    stock["ts_code"],
                    trade_date,
                    market_context=stock_score,
                    sector_context=theme,
                    core_context=stock,
                )
                scan_cache[cache_key] = bp
            if not bp.get("ok", True):
                continue
            observable = [
                (name, info)
                for name, info in bp.get("buy_points", {}).items()
                if info.get("status") in observable_statuses
            ]
            if not observable:
                continue
            selected, info = sorted(observable, key=lambda item: item[1].get("priority", 99))[0]
            key = (stock["ts_code"], selected)
            if key in seen:
                continue
            seen.add(key)
            report["watch_buy_shapes"].append({
                "category": "watch_theme_buy_shape",
                "theme_code": theme["ts_code"],
                "theme_name": theme.get("name"),
                "theme_condition_count": theme.get("condition_count"),
                "theme_missing_conditions": theme.get("missing_conditions", []),
                "ts_code": stock["ts_code"],
                "name": stock.get("name"),
                "buy_point": selected,
                "status": info.get("status"),
                "confirm_date": info.get("confirm_date", bp.get("confirm_date")),
                "execution_date": info.get("execution_date", bp.get("execution_date")),
                "stop_loss": info.get("stop_loss"),
                "execution_check": info.get("execution_check"),
                "failure_signals": info.get("failure_signals", []),
                "setup_triggered": info.get("setup_triggered"),
                "triggered": info.get("triggered"),
                "strength_score": info.get("strength_score"),
                "strength_level": info.get("strength_level"),
                "strength_reasons": info.get("strength_reasons", []),
                "theme_human_judgment": stocks.get("human_judgment", []),
                "theme_data_warnings": stocks.get("data_warnings", []),
                "reason": "观察主线尚未确认，仅提示即将确认/观察买点形态，不生成正式预案",
                "actionable": False,
            })


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
                "category": "buy_point_scan_failure",
                "ts_code": stock["ts_code"],
                "name": stock.get("name"),
                "sector_code": stock.get("sector_code"),
                "reason": bp.get("error", "买点扫描失败"),
            })
            continue

        selected = bp.get("selected_buy_point")
        if not selected:
            invalid_setups = [
                {"buy_point": name, **info}
                for name, info in bp.get("buy_points", {}).items()
                if info.get("setup_triggered") and info.get("status") == "invalid"
            ]
            if invalid_setups:
                for item in invalid_setups:
                    report["observation_pool"].append({
                        "category": "invalid_buy_setup",
                        "ts_code": stock["ts_code"],
                        "name": stock.get("name"),
                        "buy_point": item["buy_point"],
                        "status": item.get("status"),
                        "stop_loss": item.get("stop_loss"),
                        "execution_check": item.get("execution_check"),
                        "failure_signals": item.get("failure_signals", []),
                        "manual_checks": item.get("manual_checks", []),
                        "strength_score": item.get("strength_score"),
                        "strength_level": item.get("strength_level"),
                        "strength_reasons": item.get("strength_reasons", []),
                        "reason": "买点形态出现但执行条件已失效，不生成人工执行预案",
                    })
            else:
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
            blocked_message=f"{stock['ts_code']} {selected} 状态 {signal.get('status')}，不生成人工执行预案",
            market_closed_message=f"{stock['ts_code']} {selected} 因市场开关关闭不列入预案",
        )
