"""暂停与空仓规则。

实现 trading-reference.md 第 7 章：
  不开新仓条件
  日内刹车
  强制暂停
  恢复规则
"""

from __future__ import annotations


def evaluate_no_new_positions(
    market_context: dict | None = None,
    theme_context: dict | None = None,
    consecutive_losses: int = 0,
    consecutive_wins: int = 0,
    daily_pnl_pct: float = 0.0,
    drawdown_from_peak: float = 0.0,
    missed_stop_count: int = 0,
    revenge_trade_count: int = 0,
    non_compliant_count: int = 0,
) -> dict:
    """评估当日是否允许开新仓。

    组合 2.1 市场开关的硬规则 + 第 7 章的空仓暂停条件。
    """
    result = {
        "ok": True,
        "can_open": True,
        "block_reasons": [],
        "pause_required": False,
        "pause_reasons": [],
        "risk_budget_note": None,
        "human_judgment": [],
    }

    # ── 市场开关层面的不开仓条件 ──
    if market_context:
        score = market_context.get("score", 0)
        if score < 6:
            result["block_reasons"].append(f"市场评分 {score} < 6")
            result["can_open"] = False

        hard_rules = market_context.get("hard_rules", {})
        for v in hard_rules.get("violations", []):
            result["block_reasons"].append(v)
            result["can_open"] = False

        details = market_context.get("details", {})

        # 炸板率 ≥ 40% → 不做追涨，只观察
        if details.get("zha_ban_rate", 0) >= 0.40:
            result["risk_budget_note"] = "炸板率 ≥ 40%，不做追涨，只观察"

        # 指数单日跌幅 ≥ 3%
        if details.get("sh_pct_chg", 0) <= -3.0:
            result["block_reasons"].append("指数单日跌幅 ≥ 3%，停止新开仓")
            result["can_open"] = False

    # ── 主线层面的不开仓条件 ──
    if theme_context:
        confirmed = theme_context.get("confirmed_themes", [])
        if not confirmed:
            watch = theme_context.get("watch_themes", [])
            if not watch:
                result["block_reasons"].append("无确认主线，不开新仓")
                result["can_open"] = False
            else:
                result["human_judgment"].append("仅有观察主线，需人工判断是否交易")

    # ── 第 7 章：其他不开仓条件（需外部传入）──
    # 主线轮动太快，一日游严重 → 外层判断
    # 指数放量破位 → 已在 market_context 中
    # 高标股集体杀跌 → 已在 market_context 中

    # ── 情绪极端时风险预算降至 0.5%（不禁止但限制）──
    if market_context and market_context.get("emotion_extreme"):
        result["risk_budget_note"] = "情绪极端（上涨家数 > 3500 或板块高潮），风险预算降至 0.5%，不追涨"

    # ── 日内刹车 ──
    if daily_pnl_pct <= -0.01:
        result["block_reasons"].append(f"当日亏损 {daily_pnl_pct:.1%} 达本金 1%，当天不再开新仓")
        result["can_open"] = False

    # ── 连续盈利后降风险 ──
    if consecutive_wins >= 5:
        result["risk_budget_note"] = f"连续盈利 {consecutive_wins} 笔，下一笔风险预算降至 0.5%"

    # ── 强制暂停条件 ──
    pause_conditions = []

    if consecutive_losses >= 5:
        pause_conditions.append(f"连续亏损 {consecutive_losses} 笔")

    if daily_pnl_pct <= -0.02:
        pause_conditions.append(f"单日亏损 {daily_pnl_pct:.1%} 超过本金 2%")

    if drawdown_from_peak >= 0.10:
        pause_conditions.append(f"账户从阶段高点回撤 {drawdown_from_peak:.1%} ≥ 10%")

    if missed_stop_count >= 1:
        pause_conditions.append(f"出现 {missed_stop_count} 次不按止损执行")

    if revenge_trade_count >= 1:
        pause_conditions.append(f"出现 {revenge_trade_count} 次报复交易")

    if non_compliant_count >= 3:
        pause_conditions.append(f"连续 {non_compliant_count} 笔交易不符合规则")

    if pause_conditions:
        result["pause_required"] = True
        result["pause_reasons"] = pause_conditions
        result["can_open"] = False
        result["human_judgment"].append(
            f"触发强制暂停: {'; '.join(pause_conditions)}。至少暂停 1 个完整交易日，补齐复盘。"
        )

    return result


def recovery_rules(previous_pause: bool, pause_days: int = 0, review_done: bool = False) -> dict:
    """评估暂停后是否满足恢复条件。

    恢复规则：
    - 至少暂停 1 个完整交易日
    - 补齐复盘
    - 恢复后第一笔风险预算降至 0.5%
    """
    result = {
        "ok": True,
        "can_resume": False,
        "first_trade_risk_budget": 0.005,
        "notes": [],
    }

    if not previous_pause:
        result["can_resume"] = True
        return result

    if pause_days < 1:
        result["notes"].append(f"暂停仅 {pause_days} 个交易日，需满 1 个完整交易日")
        return result

    if not review_done:
        result["notes"].append("暂停后需补齐复盘")
        return result

    result["can_resume"] = True
    result["notes"].append("恢复后第一笔风险预算降至 0.5%")
    return result
