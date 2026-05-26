"""买入前检查清单。

实现 trading-reference.md 第 4 章：
  三个必答问题 + 7 项检查清单
"""

from __future__ import annotations


def pre_trade_checklist(
    market_context: dict | None = None,
    theme_context: dict | None = None,
    core_stock: dict | None = None,
    buy_point_info: dict | None = None,
    position_plan: dict | None = None,
) -> dict:
    """买入前 7 项检查清单。

    有一项不满足 → 不买。

    参数:
        market_context: 市场评分结果（compute_market_score 返回值）
        theme_context: 主线扫描结果中该股所属板块的信息
        core_stock: 核心强势股筛选结果中该股的信息
        buy_point_info: 买点扫描结果中该买点的信息
        position_plan: 仓位计算计划 {risk_budget_pct, entry_price, stop_loss, planned_shares, ...}
    """
    result = {
        "ok": True,
        "all_passed": True,
        "checks": {},
        "three_questions": {"answered": False, "why_this": "", "why_now": "", "where_exit": ""},
        "block_reasons": [],
        "warnings": [],
        "human_judgment": [],
    }

    # ── [1] 市场评分 ≥ 6 ──
    score = market_context.get("score", 0) if market_context else 0
    result["checks"]["market_score_ge_6"] = score >= 6
    if score < 6:
        result["block_reasons"].append(f"市场评分 {score} < 6")

    # ── [2] 属于当前主线 ──
    in_theme = False
    if theme_context:
        confirmed = theme_context.get("status") == "confirmed"
        watch = theme_context.get("status") == "watch"
        in_theme = confirmed or watch
    result["checks"]["in_main_theme"] = in_theme
    if not in_theme:
        result["block_reasons"].append("不属于确认/观察主线板块")

    # ── [3] 是核心强势股 ──
    is_core = False
    if core_stock:
        is_core = core_stock.get("status") in ("confirmed_core", "watch_core")
    result["checks"]["is_core_stock"] = is_core
    if not is_core:
        result["block_reasons"].append("非核心强势股")

    # ── [4] 符合标准买点之一 ──
    has_buy_point = False
    if buy_point_info:
        has_buy_point = buy_point_info.get("triggered") or buy_point_info.get("setup_triggered")
    result["checks"]["valid_buy_point"] = has_buy_point
    if not has_buy_point:
        result["block_reasons"].append("未触发标准买点")

    # ── [5] 止损位明确，未人为放宽 ──
    stop_loss_clear = False
    if buy_point_info and buy_point_info.get("stop_loss") is not None:
        stop_loss_clear = True
    result["checks"]["stop_loss_clear"] = stop_loss_clear
    if not stop_loss_clear:
        result["block_reasons"].append("止损位不明确")

    # ── [6] 仓位按公式倒推 ──
    position_ok = False
    if position_plan:
        has_shares = position_plan.get("planned_shares", 0) > 0
        within_limit = position_plan.get("position_pct", 1.0) <= 0.40
        position_ok = has_shares and within_limit
    result["checks"]["position_by_formula"] = position_ok
    if not position_ok:
        if position_plan and position_plan.get("position_pct", 0) > 0.40:
            result["block_reasons"].append(f"仓位 {position_plan['position_pct']:.0%} 超过单票 40% 上限")
        else:
            result["warnings"].append("仓位计划未传入或无效，需人工确认")

    # ── [7] 预期盈利 ≥ 交易成本 10 倍 ──
    # 需要完整的交易成本估算和盈亏比计算
    result["checks"]["profit_ge_10x_cost"] = "需人工确认"
    result["warnings"].append("交易成本过滤需人工确认（预期盈利 ≥ 交易成本 10 倍）")

    result["all_passed"] = all(
        v is not False
        for k, v in result["checks"].items()
        if k != "profit_ge_10x_cost"
    )

    # ── 三个必答问题 ──
    result["three_questions"] = _build_three_questions(
        core_stock, buy_point_info, theme_context
    )

    if not result["all_passed"]:
        result["human_judgment"].append(
            f"检查清单不通过: {'; '.join(result['block_reasons'])}"
        )

    return result


def _build_three_questions(
    core_stock: dict | None,
    buy_point_info: dict | None,
    theme_context: dict | None,
) -> dict:
    """基于已有数据构建三个必答问题的参考回答。"""
    q = {"answered": False, "why_this": "", "why_now": "", "where_exit": ""}

    if not core_stock:
        q["why_this"] = "⚠ 需人工填写：为什么是它？"
        q["why_now"] = "⚠ 需人工填写：为什么是现在？"
        q["where_exit"] = "⚠ 需人工填写：错了在哪里走？"
        return q

    # 为什么是它
    name = core_stock.get("name", core_stock.get("ts_code", ""))
    amount_rank = core_stock.get("amount_rank", "?")
    why_parts = [f"{name} 是主线板块成交额排名第 {amount_rank} 的核心股"]
    if core_stock.get("conditions", {}).get("relative_strength"):
        why_parts.append("板块分歧时抗跌、修复时率先反弹")
    if core_stock.get("conditions", {}).get("technical_strength"):
        why_parts.append("技术面强势（站上均线堆栈或突破新高）")
    q["why_this"] = "；".join(why_parts) + "。"

    # 为什么是现在
    if buy_point_info:
        bp_name = buy_point_info.get("buy_point", "")
        details = buy_point_info.get("details", {})
        if "突破" in bp_name:
            q["why_now"] = (
                f"触发{bp_name}：放量突破近 20 日高点，"
                f"成交额达到 5 日均量 {details.get('amount_ratio', '?')} 倍"
            )
        elif "回踩" in bp_name:
            q["why_now"] = (
                f"触发{bp_name}：主升后第一次缩量回踩，"
                f"量缩至前日 {details.get('amount_shrink', '?')}"
            )
        else:
            setup_list = buy_point_info.get("setup_list", [])
            q["why_now"] = f"触发买点: {', '.join(setup_list) if setup_list else bp_name}"
    else:
        q["why_now"] = "⚠ 需人工填写"

    # 错了在哪里走
    if buy_point_info and buy_point_info.get("stop_loss") is not None:
        q["where_exit"] = (
            f"止损位 {buy_point_info['stop_loss']:.2f}，"
            f"收盘跌破止损位或实际亏损达本笔风险预算即卖出"
        )
    else:
        q["where_exit"] = "⚠ 需人工填写止损位"

    q["answered"] = "⚠ 需人工填写" not in q["why_this"]
    return q
