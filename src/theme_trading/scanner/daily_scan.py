"""一站式每日扫描。"""

from theme_trading.data.tushare_client import clear_cache

from .buy_points import confirm_pending_buy_point, scan_buy_points
from .core_stocks import filter_core_stocks
from .market_score import check_sector_climax, compute_market_score
from .pre_trade import pre_trade_checklist
from .risk_budget import risk_budget_for_plan
from .themes import find_main_themes


def _append_observation(report: dict, category: str, items: list[dict]) -> None:
    for item in items:
        report["observation_pool"].append({"category": category, **item})


def _routing_status(bp_status: str) -> str:
    """将买点状态映射到路由分类。"""
    if bp_status in ("executable_plan", "pending_next_open"):
        return "ready"
    if bp_status in ("pending_next_day_strength", "watch"):
        return "pending"
    return "blocked"


def daily_scan(
    trade_date: str,
    sector_codes: list[str] = None,
    theme_top_n: int = 15,
    include_buy_points: bool = True,
    pending_setups: list[dict] | None = None,
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
        "trial_plans": [],
        "pending_reviews": [],
        "pre_trade_checks": [],
        "blocked_reasons": [],
        "data_warnings": [],
        "human_judgment": [],
    }

    # ═══ 1. 市场评分 ═══
    score = compute_market_score(trade_date)
    report["market_score"] = score
    report["market_gate"] = score.get("trade_permission")
    report["human_judgment"].extend(score.get("human_judgment", []))
    report["data_warnings"].extend(score.get("data_warnings", []))
    report["blocked_reasons"].extend(score.get("hard_rules", {}).get("violations", []))

    market_closed = score.get("trade_permission") == "closed"
    if market_closed:
        report["human_judgment"].append("市场开关关闭，后续只生成观察池，不生成可执行预案")

    breadth_extreme = score.get("emotion_extreme", False)

    # ═══ 2. 主线识别 ═══
    themes = find_main_themes(trade_date, top_n=theme_top_n)
    report["themes"] = themes
    report["human_judgment"].extend(themes.get("human_judgment", []))
    report["data_warnings"].extend(themes.get("data_warnings", []))
    _append_observation(report, "watch_theme", themes.get("watch_themes", []))

    confirmed_themes = themes.get("confirmed_themes", [])
    watch_themes = themes.get("watch_themes", [])

    # ── 板块高潮检测（仅用于风险提示，不做全局阻断）──
    all_sectors = confirmed_themes + watch_themes
    for sector in all_sectors[:3]:
        sc = check_sector_climax(sector)
        if sc["climax"]:
            report.setdefault("risk_notes", []).append(
                f"板块 {sector.get('name', sector.get('ts_code', ''))} 高潮信号: {'; '.join(sc['reasons'])}"
            )
            report["human_judgment"].extend(sc["action_notes"])

    emotion_extreme = breadth_extreme
    score["emotion_extreme"] = emotion_extreme
    if emotion_extreme and not report.get("risk_notes"):
        report["risk_notes"] = []
    if breadth_extreme:
        report.setdefault("risk_notes", []).append(
            "情绪极端（上涨家数 > 3500）：不追涨，只等分歧后的回踩确认"
        )

    # ═══ 3. 主线开关 — 决定是否继续 ═══
    trial_mode = not confirmed_themes and bool(watch_themes)
    if not confirmed_themes and not trial_mode:
        report["blocked_reasons"].append("无确认主线且无观察主线，不生成核心股买点扫描")
        return report

    if trial_mode:
        if watch_themes:
            report["human_judgment"].append("主线仅处于观察状态，仅允许买点一试错预案")

    active_themes = confirmed_themes if confirmed_themes else watch_themes

    if sector_codes is None:
        sector_codes = [theme["ts_code"] for theme in active_themes[:3]]

    # ═══ 4. 核心强势股筛选 ═══
    stocks = filter_core_stocks(trade_date, sector_codes)
    report["core_stocks"] = stocks
    report["human_judgment"].extend(stocks.get("human_judgment", []))
    report["data_warnings"].extend(stocks.get("data_warnings", []))
    _append_observation(report, "watch_core_stock", stocks.get("watch_core_stocks", []))

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
        _append_observation(report, "confirmed_core_stock", confirmed_core_stocks[:20])
        return report

    # ═══ 5. 买点扫描 + 买入前检查 ═══
    theme_by_code = {theme["ts_code"]: theme for theme in active_themes}
    stock_by_code = {stock["ts_code"]: stock for stock in core_universe}

    # ── 5a. 昨日 pending 回看确认 ──
    for pending in pending_setups or []:
        buy_point_name = pending.get("buy_point")
        if buy_point_name not in ("买点二_主升回踩", "买点三_突破确认", "买点四_趋势均线"):
            continue

        ts_code = pending.get("ts_code")
        setup_date = pending.get("setup_date")
        if not ts_code or not setup_date:
            report["pending_reviews"].append({
                "status": "invalid",
                "reason": "pending setup 缺少 ts_code 或 setup_date",
                "source": pending,
            })
            continue

        stock = stock_by_code.get(ts_code) or {
            "ts_code": ts_code,
            "name": pending.get("name"),
            "sector_code": pending.get("sector_code"),
            "status": pending.get("core_status"),
            "amount_rank": pending.get("amount_rank"),
            "conditions": pending.get("conditions", {}),
        }
        sector_context = theme_by_code.get(pending.get("sector_code") or stock.get("sector_code"))
        stock_score = score
        if sector_context and check_sector_climax(sector_context)["climax"]:
            # pending 回看也继承板块高潮约束，仅影响该板块内追涨风险判断。
            stock_score = dict(score)
            stock_score["emotion_extreme"] = True

        review = confirm_pending_buy_point(
            ts_code,
            setup_date,
            trade_date,
            buy_point_name,
            market_context=stock_score,
            sector_context=sector_context,
            core_context=stock,
        )
        report["pending_reviews"].append(review)
        if not review.get("ok"):
            report["blocked_reasons"].append(f"{ts_code} {buy_point_name} pending 回看失败: {review.get('reason')}")
            continue

        info = review.get("buy_point_info")
        bp = review.get("buy_scan")
        if not info or not bp:
            report["pending_confirmations"].append({
                "ts_code": ts_code,
                "buy_point": buy_point_name,
                "status": review.get("status", "pending_next_day_strength"),
                "reason": review.get("reason", "等待确认日数据"),
                "setup_date": setup_date,
            })
            continue

        plan_type = pending.get("plan_type", "standard")
        signal = {
            "ts_code": ts_code,
            "plan_type": plan_type,
            "buy_point": buy_point_name,
            "status": info.get("status"),
            "setup_date": bp.get("setup_date"),
            "confirm_date": bp.get("confirm_date"),
            "execution_date": bp.get("execution_date"),
            "close": info.get("execution_check", {}).get("confirm_close", bp.get("close")),
            "stop_loss": info.get("stop_loss"),
            "execution_check": info.get("execution_check"),
            "failure_signals": info.get("failure_signals", []),
            "manual_checks": info.get("manual_checks", []),
            "suppressed_by_priority": bp.get("suppressed_by_priority", []),
            "source": "pending_setup_review",
        }
        signal.update(risk_budget_for_plan(
            stock_score,
            buy_point_name,
            plan_type=plan_type,
            emotion_extreme=bool(stock_score.get("emotion_extreme")),
        ))

        checklist = pre_trade_checklist(
            market_context=score,
            theme_context=sector_context,
            core_stock=stock,
            buy_point_info=info,
            buy_point_name=buy_point_name,
            allow_watch=plan_type == "trial",
        )
        signal["pre_trade_check"] = {
            "ts_code": ts_code,
            "all_passed": checklist["all_passed"],
            "checks": checklist["checks"],
            "three_questions": checklist["three_questions"],
            "block_reasons": checklist["block_reasons"],
        }

        if market_closed:
            signal["reason"] = "市场开关关闭，仅观察"
            report["observation_pool"].append({"category": "blocked_market_closed", **signal})
            continue

        if not checklist["all_passed"]:
            signal["reason"] = "买入前检查不通过: " + "; ".join(checklist["block_reasons"])
            report["blocked_reasons"].append(signal["reason"])
            report["observation_pool"].append({"category": "blocked_pre_trade", **signal})
            report["pre_trade_checks"].append(signal["pre_trade_check"])
            continue

        route = _routing_status(info.get("status", ""))
        if route == "ready":
            if plan_type == "trial":
                report["trial_plans"].append(signal)
            else:
                report["executable_plans"].append(signal)
            report["pre_trade_checks"].append(signal["pre_trade_check"])
        elif route == "pending":
            report["pending_confirmations"].append(signal)
        else:
            report["blocked_reasons"].append(
                f"{ts_code} {buy_point_name} pending 回看状态 {info.get('status')}，不生成预案"
            )

    for stock in core_universe:
        sector_context = theme_by_code.get(stock.get("sector_code"))
        # 板块高潮仅阻断该板块内的追涨（买点一），不做全局影响
        stock_score = score
        if sector_context and check_sector_climax(sector_context)["climax"]:
            stock_score = dict(score)
            stock_score["emotion_extreme"] = True

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

        info = bp["buy_points"][selected]
        signal = {
            "ts_code": stock["ts_code"],
            "name": stock.get("name"),
            "sector_code": stock.get("sector_code"),
            "core_status": stock.get("status"),
            "amount_rank": stock.get("amount_rank"),
            "conditions": stock.get("conditions", {}),
            "plan_type": "trial" if trial_mode else "standard",
            "buy_point": selected,
            "status": info.get("status"),
            "setup_date": bp.get("setup_date"),
            "confirm_date": bp.get("confirm_date"),
            "execution_date": bp.get("execution_date"),
            "close": info.get("execution_check", {}).get("confirm_close", bp.get("close")),
            "stop_loss": info.get("stop_loss"),
            "execution_check": info.get("execution_check"),
            "failure_signals": info.get("failure_signals", []),
            "manual_checks": info.get("manual_checks", []),
            "suppressed_by_priority": bp.get("suppressed_by_priority", []),
        }
        signal.update(risk_budget_for_plan(
            stock_score,
            selected,
            plan_type=signal["plan_type"],
            emotion_extreme=bool(stock_score.get("emotion_extreme")),
        ))

        # ── 买入前检查清单（前置阻断）──
        checklist = pre_trade_checklist(
            market_context=score,
            theme_context=sector_context,
            core_stock=stock,
            buy_point_info=info,
            buy_point_name=selected,
            allow_watch=trial_mode,
        )
        signal["pre_trade_check"] = {
            "ts_code": stock["ts_code"],
            "all_passed": checklist["all_passed"],
            "checks": checklist["checks"],
            "three_questions": checklist["three_questions"],
            "block_reasons": checklist["block_reasons"],
        }

        report["buy_scans"].append(bp)

        # ── 路由 ──
        if market_closed:
            signal["reason"] = "市场开关关闭，仅观察"
            report["blocked_reasons"].append(f"{stock['ts_code']} {selected} 因市场开关关闭不列入预案")
            report["observation_pool"].append({"category": "blocked_market_closed", **signal})
            continue

        if not checklist["all_passed"]:
            signal["reason"] = "买入前检查不通过: " + "; ".join(checklist["block_reasons"])
            report["blocked_reasons"].append(signal["reason"])
            report["observation_pool"].append({"category": "blocked_pre_trade", **signal})
            report["pre_trade_checks"].append(signal["pre_trade_check"])
            continue

        route = _routing_status(info.get("status", ""))
        if route == "ready":
            if trial_mode:
                report["trial_plans"].append(signal)
            else:
                report["executable_plans"].append(signal)
            report["pre_trade_checks"].append(signal["pre_trade_check"])
        elif route == "pending":
            report["pending_confirmations"].append(signal)
        else:
            report["blocked_reasons"].append(
                f"{stock['ts_code']} {selected} 状态 {info.get('status')}，不生成预案"
            )

    if not report["buy_scans"]:
        report["human_judgment"].append("核心股中无买点 setup 触发")

    return report
