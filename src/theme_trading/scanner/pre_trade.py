"""买入前检查清单。

实现 trading-reference.md 第 4 章：
  三个必答问题 + 5 项可自动判断的检查清单
"""

from __future__ import annotations


def pre_trade_checklist(
    market_context: dict | None = None,
    theme_context: dict | None = None,
    core_stock: dict | None = None,
    buy_point_info: dict | None = None,
    buy_point_name: str = "",
    allow_watch: bool = False,
) -> dict:
    """买入前检查清单。

    有一项不满足 → 不买。

    参数:
        market_context: 市场评分结果（compute_market_score 返回值）
        theme_context: 主线扫描结果中该股所属板块的信息
        core_stock: 核心强势股筛选结果中该股的信息
        buy_point_info: 买点扫描结果中该买点的信息
        buy_point_name: 买点名称（如 买点一_放量突破）
        allow_watch: 是否允许观察主线/观察核心股通过试错预案检查
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
        status = theme_context.get("status")
        in_theme = status == "confirmed" or (allow_watch and status == "watch")
    result["checks"]["in_main_theme"] = in_theme
    if not in_theme:
        result["block_reasons"].append("不属于确认主线板块" if not allow_watch else "不属于确认/观察主线板块")

    # ── [3] 是核心强势股 ──
    is_core = False
    if core_stock:
        status = core_stock.get("status")
        is_core = status == "confirmed_core" or (allow_watch and status == "watch_core")
    result["checks"]["is_core_stock"] = is_core
    if not is_core:
        result["block_reasons"].append("非确认核心强势股" if not allow_watch else "非确认/观察核心强势股")

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

    # 所有检查均为可自动判断项
    result["all_passed"] = all(bool(v) for v in result["checks"].values())

    # ── 三个必答问题 ──
    result["three_questions"] = _build_three_questions(
        core_stock, buy_point_info, buy_point_name, theme_context
    )

    if not result["all_passed"]:
        result["human_judgment"].append(
            f"检查清单不通过: {'; '.join(result['block_reasons'])}"
        )

    return result


def _build_three_questions(
    core_stock: dict | None,
    buy_point_info: dict | None,
    buy_point_name: str = "",
    theme_context: dict | None = None,
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
    if buy_point_info and buy_point_name:
        details = buy_point_info.get("details", {})
        if buy_point_name == "买点一_放量突破":
            ratio = details.get("amount_ratio")
            ratio_str = f"{ratio} 倍" if ratio is not None else "?"
            q["why_now"] = (
                f"触发{buy_point_name}：放量突破近 20 日高点"
                f"（{details.get('high_20', '?')}），"
                f"成交额/5日均量 {ratio_str}"
            )
        elif buy_point_name == "买点二_主升回踩":
            vs_prev = details.get("amount_vs_prev_ratio")
            vs_ma5 = details.get("amount_vs_ma5_ratio")
            q["why_now"] = (
                f"触发{buy_point_name}：主升后第一次缩量回踩 5 日线，"
                f"量缩至前日 {vs_prev if vs_prev is not None else '?'}、"
                f"5日均量 {vs_ma5 if vs_ma5 is not None else '?'}"
            )
        elif buy_point_name == "买点三_突破确认":
            ratio = details.get("amount_vs_breakout_ratio")
            ratio_str = f"{ratio}" if ratio is not None else "?"
            q["why_now"] = (
                f"触发{buy_point_name}：突破后回踩不破突破位，"
                f"回踩量缩至突破日 {ratio_str}"
            )
        elif buy_point_name == "买点四_趋势均线":
            ma = details.get("selected_ma", "?")
            vs_ma5 = details.get("amount_vs_ma5_ratio")
            gain = details.get("gain_20d")
            gain_str = f"{gain:.0%}" if gain is not None else "?"
            q["why_now"] = (
                f"触发{buy_point_name}：趋势回踩 {ma} 获支撑，"
                f"量缩至 5 日均量 {vs_ma5 if vs_ma5 is not None else '?'}，"
                f"近 20 日涨幅 {gain_str}"
            )
        else:
            q["why_now"] = f"触发{buy_point_name}"
    else:
        q["why_now"] = "⚠ 需人工填写"

    # 错了在哪里走
    if buy_point_info and buy_point_info.get("stop_loss") is not None:
        failure_hint = ""
        if buy_point_info.get("failure_signals"):
            failure_hint = "；" + buy_point_info["failure_signals"][0]
        q["where_exit"] = (
            f"止损位 {buy_point_info['stop_loss']:.2f}，"
            f"收盘跌破止损位或买点失败信号触发即卖出{failure_hint}"
        )
    else:
        q["where_exit"] = "⚠ 需人工填写止损位"

    q["answered"] = "⚠ 需人工填写" not in q["why_this"]
    return q
