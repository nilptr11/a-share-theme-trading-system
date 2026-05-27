"""买入预案风险预算比例。

本模块只输出风险预算比例，不计算持仓股数或交易记录。
"""

from .constants import SCORE_STRONG, SCORE_MID


def risk_budget_for_plan(
    market_context: dict | None,
    buy_point_name: str,
    plan_type: str = "standard",
    emotion_extreme: bool = False,
) -> dict:
    """按市场档位和买点类型返回风险预算比例。"""
    score = int(market_context.get("score", 0)) if market_context else 0

    if score >= SCORE_STRONG:
        pct = 0.01
        reason = "市场评分 ≥ 7，标准风险预算 1%"
    elif score == SCORE_MID:
        pct = 0.005
        reason = "市场评分 = 6，轻仓风险预算 0.5%"
    else:
        pct = 0.0
        reason = "市场评分 < 6，不开新仓"

    if plan_type == "trial" and pct > 0:
        pct = min(pct, 0.005)
        reason = "主线未确认买点一试错，风险预算 0.5%"

    if emotion_extreme and pct > 0:
        pct = min(pct, 0.005)
        reason = "情绪极端或板块高潮，新开仓风险预算降至 0.5%"

    if buy_point_name == "买点四_趋势均线" and pct > 0:
        pct = pct / 2
        reason = "买点四趋势成熟，风险预算按当前档位减半"

    return {
        "risk_budget_pct": pct,
        "risk_budget_label": f"{pct:.2%}",
        "risk_budget_reason": reason,
    }
