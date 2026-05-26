"""卖出规则。

实现 trading-reference.md 第 6 章全部 5 个子规则：
  6.1 可以继续持有
  6.2 必须卖出
  6.3 减仓或卖出
  6.4 主动止盈
  6.5 流动性退出
"""

from __future__ import annotations

import numpy as np

from theme_trading.data.market_data import fetch_daily, fetch_limit_list

from .constants import (
    BREAKOUT_AMOUNT_RATIO,
    STOP_LOSS_RATIO,
)
from .utils import _ma, _n_days_ago


def _fetch_ohlc(ts_code: str, trade_date: str, lookback: int = 30):
    start = _n_days_ago(trade_date, lookback)
    df = fetch_daily(ts_code=ts_code, start_date=start, end_date=trade_date)
    if df is None or len(df) < 5:
        return None
    return df.sort_values("trade_date").reset_index(drop=True)


def evaluate_hold(
    ts_code: str,
    trade_date: str,
    position: dict | None = None,
    market_context: dict | None = None,
    sector_context: dict | None = None,
) -> dict:
    """评估持仓是否可继续持有（6.1 可以继续持有）。

    position 至少包含: entry_price, stop_loss
    """
    result = {
        "ok": True,
        "can_hold": True,
        "checks": {},
        "warnings": [],
        "human_judgment": [],
    }

    df = _fetch_ohlc(ts_code, trade_date)
    if df is None:
        result["ok"] = False
        result["can_hold"] = False
        result["human_judgment"].append("数据不足，无法评估持有条件")
        return result

    closes = df["close"].astype(float).values
    amounts = df["amount"].astype(float).values
    ma5 = _ma(closes, 5)
    idx = len(closes) - 1

    # 1. 上涨放量，回调缩量
    if idx >= 1:
        up_vol_ok = closes[idx] > closes[idx - 1] and amounts[idx] > amounts[idx - 1]
        down_shrink_ok = closes[idx] < closes[idx - 1] and amounts[idx] < amounts[idx - 1]
        vol_healthy = up_vol_ok or down_shrink_ok or closes[idx] == closes[idx - 1]
    else:
        vol_healthy = True
    result["checks"]["volume_healthy"] = vol_healthy

    # 2. 收盘仍在 5 日线上方
    above_ma5 = closes[idx] > ma5[idx] if not np.isnan(ma5[idx]) else None
    result["checks"]["above_ma5"] = above_ma5

    # 3. 板块仍强
    sector_strong = True
    if sector_context is not None:
        sector_pct = sector_context.get("pct_chg")
        sector_strong = sector_pct is None or sector_pct >= 0
    result["checks"]["sector_strong"] = sector_strong

    # 4. 核心股没有明显走弱（需要人工判断或外层传入）
    result["checks"]["core_stocks_healthy"] = "需人工确认"

    # 5. 没有触发硬止损或市场环境止损
    hard_stop_hit = False
    if position and position.get("stop_loss"):
        hard_stop_hit = closes[idx] < position["stop_loss"]
    result["checks"]["stop_loss_hit"] = hard_stop_hit

    # 汇总
    auto_checks = [vol_healthy, above_ma5, sector_strong, not hard_stop_hit]
    result["can_hold"] = all(c for c in auto_checks if c is not None)
    result["auto_check_count"] = sum(1 for c in auto_checks if c)
    result["auto_check_total"] = len(auto_checks)

    if hard_stop_hit:
        result["warnings"].append("收盘价跌破止损位，必须处理")
    if above_ma5 is False:
        result["warnings"].append("收盘跌破 5 日线，考虑减仓或卖出")
    if not sector_strong:
        result["warnings"].append("板块走弱，持有逻辑弱化")
    if not vol_healthy:
        result["warnings"].append("量价关系不健康")

    return result


def evaluate_must_sell(
    ts_code: str,
    trade_date: str,
    position: dict | None = None,
    market_context: dict | None = None,
) -> dict:
    """检查必须卖出条件（6.2 必须卖出）。

    返回 triggered 列表和匹配的具体信号。
    """
    result = {
        "ok": True,
        "must_sell": False,
        "triggered_signals": [],
        "market_deterioration_signals": [],
        "warnings": [],
        "human_judgment": [],
    }

    df = _fetch_ohlc(ts_code, trade_date, lookback=30)
    if df is None:
        result["ok"] = False
        result["human_judgment"].append("数据不足")
        return result

    closes = df["close"].astype(float).values
    amounts = df["amount"].astype(float).values
    ma5 = _ma(closes, 5)
    ma10 = _ma(closes, 10)
    amount_ma5 = _ma(amounts, 5)
    idx = len(closes) - 1

    # 1. 实际亏损达到本笔风险预算金额（需外层传入 risk_budget 判断）
    if position and position.get("risk_budget") and position.get("entry_price"):
        unrealized_loss = (position["entry_price"] - closes[idx]) / position["entry_price"]
        result["checks"] = {"unrealized_loss_pct": round(float(unrealized_loss), 4)}
        if unrealized_loss < 0:
            loss_amount = abs(closes[idx] - position["entry_price"])
            # 这里只能做比例估算，具体金额需外层判断
            result["warnings"].append("实际亏损需外层流程对比 risk_budget 确认")

    # 2. 收盘价 < 突破位 × 0.99（需外层传入突破位）
    if position and position.get("breakout_level"):
        if closes[idx] < position["breakout_level"] * STOP_LOSS_RATIO:
            result["triggered_signals"].append("收盘价 < 突破位 × 0.99")

    # 3. 收盘跌破关键支撑位 × 0.99
    ma5_val = ma5[idx] if not np.isnan(ma5[idx]) else None
    ma10_val = ma10[idx] if not np.isnan(ma10[idx]) else None
    support_broken = False
    if ma5_val is not None and closes[idx] < ma5_val * STOP_LOSS_RATIO:
        result["triggered_signals"].append(f"收盘跌破 5 日线 × {STOP_LOSS_RATIO}")
        support_broken = True
    if ma10_val is not None and closes[idx] < ma10_val * STOP_LOSS_RATIO:
        result["triggered_signals"].append(f"收盘跌破 10 日线 × {STOP_LOSS_RATIO}")
        support_broken = True

    # 4. 跌破 5 日线或 10 日线
    if ma5_val is not None and closes[idx] < ma5_val:
        if "收盘跌破 5 日线" not in str(result["triggered_signals"]):
            result["triggered_signals"].append("收盘跌破 5 日线")
    if ma10_val is not None and closes[idx] < ma10_val:
        if "收盘跌破 10 日线" not in str(result["triggered_signals"]):
            result["triggered_signals"].append("收盘跌破 10 日线")

    # 5. 跌幅 ≥ 5%，且成交额 ≥ 5 日均量 1.5 倍（放量长阴）
    if idx >= 0:
        pct = (closes[idx] - closes[idx - 1]) / closes[idx - 1] if idx > 0 and closes[idx - 1] > 0 else 0
        amt_ratio = amounts[idx] / amount_ma5[idx] if not np.isnan(amount_ma5[idx]) and amount_ma5[idx] > 0 else 0
        if pct <= -0.05 and amt_ratio >= BREAKOUT_AMOUNT_RATIO:
            result["triggered_signals"].append(
                f"放量长阴：跌幅 {pct:.1%}，成交额/5日均量 {amt_ratio:.1f}"
            )

    # 6. 买入后次日不能继续走强，反包或突破失败
    if position and position.get("entry_date"):
        if position["entry_date"] == trade_date:
            if closes[idx] < df["open"].astype(float).values[idx]:
                result["triggered_signals"].append("买入当日收阴，突破失败")
        # 次日检查由外层流程触发

    # ── 市场突然恶化（6.2 后半部分）──
    if market_context:
        details = market_context.get("details", {})

        # 高标集体杀跌 → 跌停数量明显增加
        limit_down = details.get("limit_down", 0)
        if limit_down >= 50:
            result["market_deterioration_signals"].append(f"跌停数 {limit_down}，高标集体杀跌")

        # 炸板率飙升
        zha_ban_rate = details.get("zha_ban_rate", 0)
        if zha_ban_rate >= 0.5:
            result["market_deterioration_signals"].append(f"炸板率 {zha_ban_rate:.0%}，市场情绪恶化")

        # 指数放量破位
        sh_pct = details.get("sh_pct_chg", 0)
        if sh_pct <= -2.0:
            result["market_deterioration_signals"].append(f"上证跌幅 {sh_pct:.1f}%，指数破位")

    # 板块跌幅 ≥ 3%
    if sector_context and sector_context.get("pct_chg", 0) <= -3.0:
        result["market_deterioration_signals"].append("板块跌幅 ≥ 3%")

    result["must_sell"] = len(result["triggered_signals"]) > 0 or len(result["market_deterioration_signals"]) > 0

    if result["must_sell"]:
        all_signals = result["triggered_signals"] + result["market_deterioration_signals"]
        result["human_judgment"].append(f"触发必须卖出信号: {'; '.join(all_signals)}")

    return result


def evaluate_reduce_or_sell(
    ts_code: str,
    trade_date: str,
    market_context: dict | None = None,
    sector_context: dict | None = None,
) -> dict:
    """检查减仓或卖出条件（6.3 减仓或卖出）。

    出现任意两个信号 → 减仓或卖出。
    """
    result = {
        "ok": True,
        "should_reduce": False,
        "signals": [],
        "signal_count": 0,
        "human_judgment": [],
    }

    df = _fetch_ohlc(ts_code, trade_date, lookback=20)
    if df is None:
        result["ok"] = False
        return result

    closes = df["close"].astype(float).values
    amounts = df["amount"].astype(float).values
    highs = df["high"].astype(float).values
    ma5 = _ma(closes, 5)
    amount_ma5 = _ma(amounts, 5)
    idx = len(closes) - 1

    # 逻辑弱：题材催化落地后没有资金继续承接
    amt_ratio = amounts[idx] / amount_ma5[idx] if not np.isnan(amount_ma5[idx]) and amount_ma5[idx] > 0 else None
    if amt_ratio is not None and amt_ratio < 0.7:
        result["signals"].append("逻辑弱：成交额萎缩至 5 日均量 70% 以下，资金承接不足")

    # 资金弱：放量但涨不动
    if amt_ratio is not None and amt_ratio >= 1.3 and idx > 0:
        pct = (closes[idx] - closes[idx - 1]) / closes[idx - 1]
        if pct < 0.01:
            result["signals"].append(
                f"资金弱：放量（量比 {amt_ratio:.1f}）但涨幅仅 {pct:.1%}，涨不动"
            )

    # 技术弱：跌破 5 日线
    ma5_val = ma5[idx] if not np.isnan(ma5[idx]) else None
    if ma5_val is not None and closes[idx] < ma5_val:
        result["signals"].append("技术弱：收盘跌破 5 日线")

    # 技术弱：反弹不过前高
    if idx >= 3:
        recent_high = float(np.max(highs[idx - 3:idx]))
        if closes[idx] < recent_high * 0.98:
            result["signals"].append("技术弱：反弹不过前高")

    # 技术弱：长上影 ≥ 实体 2 倍
    if idx >= 0:
        row = df.iloc[idx]
        o, h, c = float(row["open"]), float(row["high"]), float(row["close"])
        body = abs(c - o)
        upper_shadow = h - max(c, o)
        if body > 0 and upper_shadow >= body * 2:
            result["signals"].append(f"技术弱：长上影（上影线/实体 = {upper_shadow / body:.1f}）")

    # 情绪退：板块涨停减少、炸板升高（需市场上下文）
    if market_context:
        details = market_context.get("details", {})
        zha_ban_rate = details.get("zha_ban_rate", 0)
        limit_up = details.get("limit_up", 0)
        if zha_ban_rate >= 0.35:
            result["signals"].append(f"情绪退：炸板率 {zha_ban_rate:.0%}")
        if limit_up < 30:
            result["signals"].append(f"情绪退：涨停数仅 {limit_up}")

    # 核心股走弱（需板块上下文）
    if sector_context:
        sector_pct = sector_context.get("pct_chg", 0)
        if sector_pct < -1.5:
            result["signals"].append("情绪退：板块核心股集体走弱")

    result["signal_count"] = len(result["signals"])
    result["should_reduce"] = result["signal_count"] >= 2
    if result["should_reduce"]:
        result["human_judgment"].append(
            f"触发 {result['signal_count']} 个减仓信号 → 减仓或卖出"
        )
    return result


def evaluate_active_profit_taking(
    ts_code: str,
    trade_date: str,
    sector_context: dict | None = None,
    market_context: dict | None = None,
) -> dict:
    """检查主动止盈信号（6.4 主动止盈）。"""
    result = {
        "ok": True,
        "should_take_profit": False,
        "signals": [],
        "human_judgment": [],
    }

    df = _fetch_ohlc(ts_code, trade_date, lookback=20)
    if df is None:
        result["ok"] = False
        return result

    closes = df["close"].astype(float).values
    amounts = df["amount"].astype(float).values
    amount_ma5 = _ma(amounts, 5)
    idx = len(closes) - 1

    # 1. 个股 3 日累计涨幅 ≥ 20%
    if idx >= 2:
        gain_3d = (closes[idx] - closes[idx - 2]) / closes[idx - 2]
        if gain_3d >= 0.20:
            result["signals"].append(f"个股 3 日累计涨幅 {gain_3d:.1%} ≥ 20%")

    # 2. 板块内涨停 ≥ 8 只（需 market_context 中的 limit_up 统计口径调整）
    if sector_context and sector_context.get("up_in_sector", 0) >= 8:
        result["signals"].append("板块内涨停 ≥ 8 只")

    # 3. 板块涨幅 ≥ 4%
    if sector_context and sector_context.get("pct_chg", 0) >= 4.0:
        result["signals"].append(f"板块涨幅 {sector_context['pct_chg']:.1f}% ≥ 4%")

    # 4. 板块涨幅 ≥ 3%，且成交额创近 5 日新高
    if sector_context and sector_context.get("pct_chg", 0) >= 3.0:
        sector_amt_ratio = sector_context.get("amount_ratio") or sector_context.get("vol_ratio")
        if sector_amt_ratio and sector_amt_ratio >= 1.0:
            result["signals"].append("板块涨幅 ≥ 3% 且成交额创近 5 日新高")

    # 5. 成交额 ≥ 5 日均量 2 倍，但收盘涨幅 < 1%（放量滞涨）
    amt_ratio = amounts[idx] / amount_ma5[idx] if not np.isnan(amount_ma5[idx]) and amount_ma5[idx] > 0 else None
    if amt_ratio is not None and amt_ratio >= 2.0 and idx > 0:
        pct = (closes[idx] - closes[idx - 1]) / closes[idx - 1]
        if pct < 0.01:
            result["signals"].append(
                f"放量滞涨：成交额/5日均量 {amt_ratio:.1f}，涨幅仅 {pct:.1%}"
            )

    # 6. 后排补涨明显，媒体大量讨论 → 无法程序化，标注为人工判断
    result["human_judgment"].append("后排补涨/媒体讨论 → 需人工确认")

    # 7. 涨停反复打开，封单快速减少 → 无法程序化
    result["human_judgment"].append("涨停封单变化 → 需盘中人工观察")

    result["should_take_profit"] = len(result["signals"]) > 0
    return result


def evaluate_liquidity_exit(
    ts_code: str,
    trade_date: str,
    market_context: dict | None = None,
) -> dict:
    """检查流动性退出条件（6.5 流动性退出）。"""
    result = {
        "ok": True,
        "must_exit": False,
        "signals": [],
        "human_judgment": [],
    }

    df = _fetch_ohlc(ts_code, trade_date, lookback=5)
    if df is None:
        result["ok"] = False
        return result

    # 1. 连续 2 日无法在止损位成交 → 需实际交易数据，标注为人工判断
    result["human_judgment"].append("连续 2 日无法在止损位成交 → 需人工确认，确认后次日开盘无条件出清")

    # 2. 持仓被 ST/*ST
    if ts_code and ("ST" in ts_code.upper() or "*ST" in ts_code.upper()):
        result["signals"].append("持仓被 ST/*ST，次日集合竞价无条件卖出")
        result["must_exit"] = True

    # 3. 市场跌停数 ≥ 50
    if market_context:
        details = market_context.get("details", {})
        if details.get("limit_down", 0) >= 50:
            result["signals"].append("市场跌停数 ≥ 50，只降风险，不加仓、不抄底")
            result["must_exit"] = True

    if result["must_exit"]:
        result["human_judgment"].append("触发流动性退出，不再等待理想价格")

    return result


def full_sell_evaluation(
    ts_code: str,
    trade_date: str,
    position: dict | None = None,
    market_context: dict | None = None,
    sector_context: dict | None = None,
) -> dict:
    """一站式卖出评估，聚合全部 5 个子规则。"""
    hold = evaluate_hold(ts_code, trade_date, position, market_context, sector_context)
    must = evaluate_must_sell(ts_code, trade_date, position, market_context)
    reduce_ = evaluate_reduce_or_sell(ts_code, trade_date, market_context, sector_context)
    profit = evaluate_active_profit_taking(ts_code, trade_date, sector_context, market_context)
    liquidity = evaluate_liquidity_exit(ts_code, trade_date, market_context)

    action = "hold"
    reasons = []

    if liquidity["must_exit"]:
        action = "exit_immediately"
        reasons.extend(liquidity["signals"])
    elif must["must_sell"]:
        action = "sell"
        reasons.extend(must["triggered_signals"])
        reasons.extend(must["market_deterioration_signals"])
    elif reduce_["should_reduce"]:
        action = "reduce"
        reasons.extend(reduce_["signals"])
    elif profit["should_take_profit"]:
        action = "take_profit"
        reasons.extend(profit["signals"])
    elif not hold["can_hold"]:
        action = "review"
        reasons.extend(hold["warnings"])

    return {
        "ok": all(r["ok"] for r in [hold, must, reduce_, profit, liquidity]),
        "action": action,
        "reasons": reasons,
        "hold": hold,
        "must_sell": must,
        "reduce_or_sell": reduce_,
        "active_profit_taking": profit,
        "liquidity_exit": liquidity,
        "human_judgment": (
            hold.get("human_judgment", [])
            + must.get("human_judgment", [])
            + reduce_.get("human_judgment", [])
            + profit.get("human_judgment", [])
            + liquidity.get("human_judgment", [])
        ),
    }
