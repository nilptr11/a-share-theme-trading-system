"""卖点预案扫描。

本模块只做信号扫描，不管理真实交易状态、不计算仓位。
"""

from __future__ import annotations

import numpy as np

from theme_trading.data.market_data import fetch_daily

from .constants import BREAKOUT_AMOUNT_RATIO, STOP_LOSS_RATIO
from .utils import _ma, _n_days_ago


def _fetch_ohlc(ts_code: str, trade_date: str, lookback: int = 30):
    start = _n_days_ago(trade_date, lookback)
    df = fetch_daily(ts_code=ts_code, start_date=start, end_date=trade_date)
    if df is None or len(df) < 5:
        return None
    return df.sort_values("trade_date").reset_index(drop=True)


def evaluate_must_sell(
    ts_code: str,
    trade_date: str,
    reference_levels: dict | None = None,
    market_context: dict | None = None,
    sector_context: dict | None = None,
) -> dict:
    """扫描必须处理的卖点信号。

    reference_levels 可包含 breakout_level、stop_loss，用于检查买点失败和止损参考。
    """
    result = {
        "ok": True,
        "must_sell": False,
        "triggered_signals": [],
        "market_deterioration_signals": [],
        "diagnostic_signals": [],
        "human_judgment": [],
    }

    df = _fetch_ohlc(ts_code, trade_date, lookback=30)
    if df is None:
        result["ok"] = False
        result["human_judgment"].append("数据不足，无法扫描必须卖出信号")
        return result

    closes = df["close"].astype(float).values
    amounts = df["amount"].astype(float).values
    ma5 = _ma(closes, 5)
    ma10 = _ma(closes, 10)
    amount_ma5 = _ma(amounts, 5)
    idx = len(closes) - 1

    refs = reference_levels or {}
    breakout_level = refs.get("breakout_level")
    if breakout_level and closes[idx] < float(breakout_level) * STOP_LOSS_RATIO:
        result["triggered_signals"].append("收盘价 < 突破位 × 0.99")

    stop_loss = refs.get("stop_loss")
    if stop_loss and closes[idx] < float(stop_loss):
        result["triggered_signals"].append("收盘价跌破止损参考位")

    ma5_val = ma5[idx] if not np.isnan(ma5[idx]) else None
    ma10_val = ma10[idx] if not np.isnan(ma10[idx]) else None
    if ma5_val is not None and closes[idx] < ma5_val:
        result["diagnostic_signals"].append("持仓诊断：收盘跌破 5 日线，关注是否叠加放量下跌、板块走弱或止损位失守")
    if ma10_val is not None and closes[idx] < ma10_val:
        result["diagnostic_signals"].append("持仓诊断：收盘跌破 10 日线，关注趋势是否继续转弱")

    if idx > 0:
        pct = (closes[idx] - closes[idx - 1]) / closes[idx - 1] if closes[idx - 1] > 0 else 0
        amt_ratio = amounts[idx] / amount_ma5[idx] if not np.isnan(amount_ma5[idx]) and amount_ma5[idx] > 0 else 0
        if pct <= -0.05 and amt_ratio >= BREAKOUT_AMOUNT_RATIO:
            result["triggered_signals"].append(
                f"放量长阴：跌幅 {pct:.1%}，成交额/5日均量 {amt_ratio:.1f}"
            )

    if market_context:
        details = market_context.get("details", {})
        limit_down = details.get("limit_down", 0)
        if limit_down >= 50:
            result["market_deterioration_signals"].append(f"跌停数 {limit_down}，市场风险升高")

        zha_ban_rate = details.get("zha_ban_rate", 0)
        if zha_ban_rate >= 0.5:
            result["market_deterioration_signals"].append(f"炸板率 {zha_ban_rate:.0%}，市场情绪恶化")

        sh_pct = details.get("sh_pct_chg", 0)
        if sh_pct <= -2.0:
            result["market_deterioration_signals"].append(f"上证跌幅 {sh_pct:.1f}%，指数走弱")

    if sector_context and sector_context.get("pct_chg", 0) <= -3.0:
        result["market_deterioration_signals"].append("板块跌幅 ≥ 3%")

    result["must_sell"] = bool(result["triggered_signals"] or result["market_deterioration_signals"])
    if result["must_sell"]:
        signals = result["triggered_signals"] + result["market_deterioration_signals"]
        result["human_judgment"].append(f"触发卖点预案: {'; '.join(signals)}")

    return result


def evaluate_reduce_or_sell(
    ts_code: str,
    trade_date: str,
    market_context: dict | None = None,
    sector_context: dict | None = None,
) -> dict:
    """扫描减仓或卖出预案信号。出现任意两个信号即提示处理。"""
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
        result["human_judgment"].append("数据不足，无法扫描减仓/卖出信号")
        return result

    closes = df["close"].astype(float).values
    amounts = df["amount"].astype(float).values
    highs = df["high"].astype(float).values
    ma5 = _ma(closes, 5)
    amount_ma5 = _ma(amounts, 5)
    idx = len(closes) - 1

    amt_ratio = amounts[idx] / amount_ma5[idx] if not np.isnan(amount_ma5[idx]) and amount_ma5[idx] > 0 else None
    if amt_ratio is not None and amt_ratio < 0.7:
        result["signals"].append("逻辑弱：成交额萎缩至 5 日均量 70% 以下")

    if amt_ratio is not None and amt_ratio >= 1.3 and idx > 0:
        pct = (closes[idx] - closes[idx - 1]) / closes[idx - 1]
        if pct < 0.01:
            result["signals"].append(f"资金弱：放量但涨幅仅 {pct:.1%}")

    ma5_val = ma5[idx] if not np.isnan(ma5[idx]) else None
    if ma5_val is not None and closes[idx] < ma5_val:
        result["signals"].append("技术弱：收盘跌破 5 日线（单独不构成必须卖出）")

    if idx >= 3:
        recent_high = float(np.max(highs[idx - 3:idx]))
        if closes[idx] < recent_high * 0.98:
            result["signals"].append("技术弱：反弹不过前高")

    row = df.iloc[idx]
    open_price, high_price, close_price = float(row["open"]), float(row["high"]), float(row["close"])
    body = abs(close_price - open_price)
    upper_shadow = high_price - max(close_price, open_price)
    if body > 0 and upper_shadow >= body * 2:
        result["signals"].append(f"技术弱：长上影（上影线/实体 = {upper_shadow / body:.1f}）")

    if market_context:
        details = market_context.get("details", {})
        if details.get("zha_ban_rate", 0) >= 0.35:
            result["signals"].append(f"情绪退：炸板率 {details['zha_ban_rate']:.0%}")
        if details.get("limit_up", 0) < 30:
            result["signals"].append(f"情绪退：涨停数仅 {details.get('limit_up', 0)}")

    if sector_context and sector_context.get("pct_chg", 0) < -1.5:
        result["signals"].append("情绪退：板块核心股集体走弱")

    result["signal_count"] = len(result["signals"])
    result["should_reduce"] = result["signal_count"] >= 2
    if result["should_reduce"]:
        result["human_judgment"].append(f"触发 {result['signal_count']} 个减仓/卖出信号")
    return result


def evaluate_active_profit_taking(
    ts_code: str,
    trade_date: str,
    sector_context: dict | None = None,
) -> dict:
    """扫描主动止盈预案信号。"""
    result = {
        "ok": True,
        "should_take_profit": False,
        "signals": [],
        "human_judgment": [],
    }

    df = _fetch_ohlc(ts_code, trade_date, lookback=20)
    if df is None:
        result["ok"] = False
        result["human_judgment"].append("数据不足，无法扫描止盈信号")
        return result

    closes = df["close"].astype(float).values
    amounts = df["amount"].astype(float).values
    amount_ma5 = _ma(amounts, 5)
    idx = len(closes) - 1

    if idx >= 2:
        gain_3d = (closes[idx] - closes[idx - 2]) / closes[idx - 2]
        if gain_3d >= 0.20:
            result["signals"].append(f"个股 3 日累计涨幅 {gain_3d:.1%} ≥ 20%")

    if sector_context and sector_context.get("up_in_sector", 0) >= 8:
        result["signals"].append("板块内涨停 ≥ 8 只")

    if sector_context and sector_context.get("pct_chg", 0) >= 4.0:
        result["signals"].append(f"板块涨幅 {sector_context['pct_chg']:.1f}% ≥ 4%")

    if sector_context and sector_context.get("pct_chg", 0) >= 3.0 and sector_context.get("amount_5d_high"):
        result["signals"].append("板块涨幅 ≥ 3% 且成交额创近 5 日新高")

    amt_ratio = amounts[idx] / amount_ma5[idx] if not np.isnan(amount_ma5[idx]) and amount_ma5[idx] > 0 else None
    if amt_ratio is not None and amt_ratio >= 2.0 and idx > 0:
        pct = (closes[idx] - closes[idx - 1]) / closes[idx - 1]
        if pct < 0.01:
            result["signals"].append(f"放量滞涨：成交额/5日均量 {amt_ratio:.1f}，涨幅仅 {pct:.1%}")

    result["human_judgment"].append("后排补涨/媒体讨论、涨停封单变化需人工确认")
    result["should_take_profit"] = bool(result["signals"])
    return result


def evaluate_liquidity_risk(
    ts_code: str,
    trade_date: str,
    market_context: dict | None = None,
) -> dict:
    """扫描流动性风险预案。"""
    result = {
        "ok": True,
        "risk_off": False,
        "signals": [],
        "human_judgment": [],
    }

    df = _fetch_ohlc(ts_code, trade_date, lookback=5)
    if df is None:
        result["ok"] = False
        result["human_judgment"].append("数据不足，无法扫描流动性风险")
        return result

    result["human_judgment"].append("连续 2 日无法在止损参考位成交需人工确认")

    if market_context:
        details = market_context.get("details", {})
        if details.get("limit_down", 0) >= 50:
            result["signals"].append("市场跌停数 ≥ 50，只降风险，不加仓、不抄底")
            result["risk_off"] = True

    return result


def scan_sell_points(
    ts_code: str,
    trade_date: str,
    reference_levels: dict | None = None,
    market_context: dict | None = None,
    sector_context: dict | None = None,
) -> dict:
    """聚合卖点预案扫描结果。"""
    must = evaluate_must_sell(ts_code, trade_date, reference_levels, market_context, sector_context)
    reduce_ = evaluate_reduce_or_sell(ts_code, trade_date, market_context, sector_context)
    profit = evaluate_active_profit_taking(ts_code, trade_date, sector_context)
    liquidity = evaluate_liquidity_risk(ts_code, trade_date, market_context)

    action = "observe"
    reasons = []
    if liquidity["risk_off"]:
        action = "risk_off"
        reasons.extend(liquidity["signals"])
    elif must["must_sell"]:
        action = "sell_plan"
        reasons.extend(must["triggered_signals"])
        reasons.extend(must["market_deterioration_signals"])
    elif reduce_["should_reduce"]:
        action = "reduce_or_sell_plan"
        reasons.extend(reduce_["signals"])
    elif profit["should_take_profit"]:
        action = "take_profit_plan"
        reasons.extend(profit["signals"])

    return {
        "ok": all(item["ok"] for item in [must, reduce_, profit, liquidity]),
        "action": action,
        "reasons": reasons,
        "must_sell": must,
        "diagnostic_signals": must.get("diagnostic_signals", []),
        "reduce_or_sell": reduce_,
        "active_profit_taking": profit,
        "liquidity_risk": liquidity,
        "human_judgment": (
            must.get("human_judgment", [])
            + reduce_.get("human_judgment", [])
            + profit.get("human_judgment", [])
            + liquidity.get("human_judgment", [])
        ),
    }
