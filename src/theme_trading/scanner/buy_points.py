"""买点扫描。"""

from datetime import datetime, timedelta

import numpy as np

from theme_trading.data.market_data import fetch_daily

from .constants import (
    BREAKOUT_AMOUNT_RATIO,
    BREAKOUT_CONFIRM_RATIO,
    BUY_POINT_4_MAX_GAIN_20D,
    NEXT_OPEN_GAP_LIMIT,
    PULLBACK_AMOUNT_MA5_RATIO,
    PULLBACK_AMOUNT_PREV_RATIO,
    REBOUND_AMOUNT_RATIO,
    STOP_LOSS_RATIO,
)
from .utils import BUY_POINT_PRIORITY, _check_open_gap, _ma, _n_days_ago, _select_highest_priority_buy_point


def _n_days_after(date_str: str, n: int) -> str:
    return (datetime.strptime(date_str, "%Y%m%d") + timedelta(days=n)).strftime("%Y%m%d")


def _empty_point(priority: int, manual_checks: list[str] | None = None) -> dict:
    return {
        "triggered": False,
        "setup_triggered": False,
        "status": "not_triggered",
        "priority": priority,
        "details": {},
        "stop_loss": None,
        "execution_check": {},
        "failure_signals": [],
        "manual_checks": manual_checks or [],
    }


def _execution_check(confirm_close: float, next_row) -> dict:
    next_open = float(next_row["open"]) if next_row is not None and "open" in next_row else None
    gap = _check_open_gap(confirm_close, next_open, NEXT_OPEN_GAP_LIMIT)
    return {
        "confirm_close": round(float(confirm_close), 2),
        "next_trade_date": next_row.get("trade_date") if next_row is not None else None,
        "next_open": round(next_open, 2) if next_open is not None else None,
        "gap_limit_pct": NEXT_OPEN_GAP_LIMIT,
        "gap_check": gap,
        "rule": "次日开盘价相对确认日收盘价在 ±3% 内才可执行",
    }


def _next_strength_ok(next_row, base_amount: float) -> bool | None:
    if next_row is None:
        return None
    if "close" not in next_row or "open" not in next_row or "amount" not in next_row:
        return None
    return bool(float(next_row["close"]) > float(next_row["open"]) and float(next_row["amount"]) >= base_amount * REBOUND_AMOUNT_RATIO)


def _consecutive_drops(closes: np.ndarray, today: int, max_days: int = 5) -> int:
    drops = 0
    for i in range(today, max(today - max_days, 0), -1):
        if closes[i] < closes[i - 1]:
            drops += 1
        else:
            break
    return drops


def _near_ma_in_pullback(closes: np.ndarray, ma_values: np.ndarray, today: int, drops: int, tolerance: float = 0.01) -> bool:
    if drops < 2:
        return False
    start = max(today - drops + 1, 0)
    for i in range(start, today + 1):
        if not np.isnan(ma_values[i]) and ma_values[i] > 0 and abs(closes[i] - ma_values[i]) / ma_values[i] <= tolerance:
            return True
    return False


def _pullback_has_volume_down(closes: np.ndarray, amounts: np.ndarray, amount_ma5: np.ndarray, today: int, drops: int) -> bool:
    start = max(today - drops + 1, 0)
    for i in range(start, today + 1):
        if closes[i] < closes[i - 1] and not np.isnan(amount_ma5[i]) and amounts[i] >= amount_ma5[i] * 1.2:
            return True
    return False


def _status_for_setup(setup: bool, next_row, confirm_close: float, needs_strength: bool, strength_ok: bool | None, blocked: bool = False) -> tuple[bool, str, dict]:
    execution = _execution_check(confirm_close, next_row)
    gap = execution["gap_check"]
    if not setup:
        return False, "not_triggered", execution
    if blocked:
        return False, "watch", execution
    if gap["checked"] and not gap["passed"]:
        return False, "invalid", execution
    if needs_strength:
        if strength_ok is None:
            return False, "pending_next_day_strength", execution
        return strength_ok, "executable_plan" if strength_ok else "invalid", execution
    if not gap["checked"]:
        return True, "pending_next_open", execution
    return True, "executable_plan", execution


def scan_buy_points(
    ts_code: str,
    trade_date: str,
    market_context: dict | None = None,
    sector_context: dict | None = None,
    core_context: dict | None = None,
) -> dict:
    """对单只个股扫描四个买点条件。"""
    start = _n_days_ago(trade_date, 90)
    end = _n_days_after(trade_date, 10)
    df = fetch_daily(ts_code=ts_code, start_date=start, end_date=end)
    if df is None or len(df) < 25:
        return {"ok": False, "error": "数据不足"}

    df = df.sort_values("trade_date").reset_index(drop=True)
    confirm_matches = df.index[df["trade_date"] == trade_date].tolist()
    if not confirm_matches:
        return {"ok": False, "error": "确认日无行情数据"}

    today = confirm_matches[0]
    if today < 24:
        return {"ok": False, "error": "确认日前历史数据不足"}

    next_row = df.iloc[today + 1] if today + 1 < len(df) else None
    hist = df.iloc[:today + 1].copy()
    closes = hist["close"].astype(float).values
    highs = hist["high"].astype(float).values
    lows = hist["low"].astype(float).values
    amounts = hist["amount"].astype(float).values

    ma5 = _ma(closes, 5)
    ma10 = _ma(closes, 10)
    ma20 = _ma(closes, 20)
    amount_ma5 = _ma(amounts, 5)
    idx = len(closes) - 1

    common_manual = []
    if market_context is None:
        common_manual.append("缺少市场上下文，市场评分需由外层流程确认")
    if sector_context is None:
        common_manual.append("缺少板块上下文，主线和板块同步需人工确认")
    if core_context is None:
        common_manual.append("缺少核心股上下文，核心强势股身份需人工确认")

    result = {
        "ok": True,
        "ts_code": ts_code,
        "trade_date": trade_date,
        "confirm_date": trade_date,
        "close": float(closes[idx]),
        "ma5": float(ma5[idx]) if not np.isnan(ma5[idx]) else None,
        "ma10": float(ma10[idx]) if not np.isnan(ma10[idx]) else None,
        "ma20": float(ma20[idx]) if not np.isnan(ma20[idx]) else None,
        "amount_today": float(amounts[idx]),
        "amount_ma5": float(amount_ma5[idx]) if not np.isnan(amount_ma5[idx]) else None,
        "amount_ratio": float(amounts[idx] / amount_ma5[idx]) if not np.isnan(amount_ma5[idx]) and amount_ma5[idx] > 0 else None,
        "buy_points": {},
        "manual_checks": common_manual,
    }

    sector_pct = sector_context.get("pct_chg") if sector_context else None
    sector_amount_ratio = sector_context.get("amount_ratio") or sector_context.get("vol_ratio") if sector_context else None
    emotion_extreme = bool(market_context.get("emotion_extreme")) if market_context else False

    # ── 买点一：低位放量突破 ──
    bp1 = _empty_point(BUY_POINT_PRIORITY["买点一_放量突破"], common_manual.copy())
    recent_5_high = float(np.max(highs[-6:-1]))
    recent_5_low = float(np.min(lows[-6:-1]))
    range_pct = (recent_5_high - recent_5_low) / recent_5_low if recent_5_low > 0 else 1.0
    is_consolidating = range_pct <= 0.05
    high_20 = float(np.max(highs[-21:-1]))
    is_breakout = closes[idx] > high_20
    amount_ok = amounts[idx] >= amount_ma5[idx] * BREAKOUT_AMOUNT_RATIO if not np.isnan(amount_ma5[idx]) else False
    close_confirm = closes[idx] >= high_20 * BREAKOUT_CONFIRM_RATIO
    sector_follow = sector_pct is None or sector_pct >= 1.0
    if sector_pct is None:
        bp1["manual_checks"].append("买点一板块当日涨幅 ≥ 1% 需人工确认")

    bp1_setup = is_consolidating and is_breakout and amount_ok and close_confirm and sector_follow
    stop_loss = recent_5_low * STOP_LOSS_RATIO if recent_5_low < high_20 else high_20 * STOP_LOSS_RATIO
    bp1_triggered, bp1_status, bp1_execution = _status_for_setup(
        bp1_setup,
        next_row,
        closes[idx],
        needs_strength=False,
        strength_ok=None,
        blocked=emotion_extreme,
    )
    if emotion_extreme and bp1_setup:
        bp1["manual_checks"].append("情绪极端日不追涨，买点一仅列观察")
    bp1.update({
        "triggered": bp1_triggered,
        "setup_triggered": bp1_setup,
        "status": bp1_status,
        "details": {
            "consolidation_5d_range": round(float(range_pct), 3),
            "is_consolidating": is_consolidating,
            "high_20": high_20,
            "breakout": is_breakout,
            "amount_ok": amount_ok,
            "close_confirm": close_confirm,
            "sector_follow": sector_follow,
        },
        "stop_loss": round(float(stop_loss), 2) if is_breakout else None,
        "execution_check": bp1_execution,
        "failure_signals": [
            f"收盘价 < 突破位 × {STOP_LOSS_RATIO}",
            "放量长上影或放量收阴",
            "板块没有跟随",
            "次日低开低走",
        ],
    })
    result["buy_points"]["买点一_放量突破"] = bp1

    # ── 买点二：主升第一次缩量回踩 ──
    bp2 = _empty_point(BUY_POINT_PRIORITY["买点二_主升回踩"], common_manual.copy())
    above_ma5_3d = all(closes[i] > ma5[i] for i in range(max(idx - 2, 0), idx + 1) if not np.isnan(ma5[i]))
    ma5_up = ma5[idx] > ma5[idx - 1] if not np.isnan(ma5[idx]) and not np.isnan(ma5[idx - 1]) else False
    drops = _consecutive_drops(closes, idx)
    near_ma5 = _near_ma_in_pullback(closes, ma5, idx, drops)
    volume_down_invalid = _pullback_has_volume_down(closes, amounts, amount_ma5, idx, drops)
    amount_shrink = amounts[idx] <= amounts[idx - 1] * PULLBACK_AMOUNT_PREV_RATIO and amounts[idx] <= amount_ma5[idx] * PULLBACK_AMOUNT_MA5_RATIO
    above_ma5 = closes[idx] > ma5[idx] if not np.isnan(ma5[idx]) else False
    sector_amount_ok = sector_amount_ratio is None or sector_amount_ratio >= 1.0
    if sector_amount_ratio is None:
        bp2["manual_checks"].append("买点二板块成交额未跌破 5 日均值需人工确认")

    bp2_setup = above_ma5_3d and ma5_up and drops >= 2 and near_ma5 and amount_shrink and above_ma5 and sector_amount_ok and not volume_down_invalid
    strength_ok = _next_strength_ok(next_row, amounts[idx])
    bp2_triggered, bp2_status, bp2_execution = _status_for_setup(bp2_setup, next_row, closes[idx], True, strength_ok)
    ma5_stop = ma5[idx] * STOP_LOSS_RATIO if not np.isnan(ma5[idx]) else None
    low_stop = lows[idx] * STOP_LOSS_RATIO
    bp2_stop = ma5_stop if ma5_stop is not None and ma5[idx] >= lows[idx] and (ma5[idx] - lows[idx]) / lows[idx] <= 0.02 else low_stop
    bp2.update({
        "triggered": bp2_triggered,
        "setup_triggered": bp2_setup,
        "status": bp2_status,
        "details": {
            "above_ma5_3d": above_ma5_3d,
            "ma5_up": ma5_up,
            "consecutive_drops": drops,
            "near_ma5": near_ma5,
            "amount_shrink": amount_shrink,
            "above_ma5": above_ma5,
            "sector_amount_ok": sector_amount_ok,
            "volume_down_invalid": volume_down_invalid,
            "next_strength_ok": strength_ok,
        },
        "stop_loss": round(float(bp2_stop), 2),
        "execution_check": bp2_execution,
        "failure_signals": [
            "回调变成放量下跌",
            "收盘跌破止损位",
            "反弹日成交额 < 5 日均额 90%",
            "板块核心股集体走弱",
        ],
    })
    result["buy_points"]["买点二_主升回踩"] = bp2

    # ── 买点三：突破回踩确认 ──
    bp3 = _empty_point(BUY_POINT_PRIORITY["买点三_突破确认"], common_manual.copy())
    high_60 = float(np.max(highs[-61:-1])) if len(highs) >= 61 else float(np.max(highs[:-1]))
    breakout_candidates = [i for i in range(max(idx - 10, 0), idx) if highs[i] >= high_60]
    breakout_idx = breakout_candidates[-1] if breakout_candidates else None
    recent_high_60 = breakout_idx is not None
    breakout_amount = amounts[breakout_idx] if breakout_idx is not None else amounts[idx]
    bp3_amount_shrink = amounts[idx] <= breakout_amount * 0.6
    bp3_above_breakout = closes[idx] >= high_60
    sector_not_weak = sector_pct is None or sector_pct >= 0
    if sector_pct is None:
        bp3["manual_checks"].append("买点三板块同期没有走弱需人工确认")
    bp3_setup = recent_high_60 and bp3_amount_shrink and bp3_above_breakout and sector_not_weak
    bp3_strength_ok = _next_strength_ok(next_row, amounts[idx])
    bp3_triggered, bp3_status, bp3_execution = _status_for_setup(bp3_setup, next_row, closes[idx], True, bp3_strength_ok)
    pullback_low = float(lows[idx])
    bp3_stop = pullback_low * STOP_LOSS_RATIO if pullback_low > high_60 * 1.03 else high_60 * STOP_LOSS_RATIO
    bp3.update({
        "triggered": bp3_triggered,
        "setup_triggered": bp3_setup,
        "status": bp3_status,
        "details": {
            "high_60": high_60,
            "recent_60d_high": recent_high_60,
            "breakout_date": hist.iloc[breakout_idx]["trade_date"] if breakout_idx is not None else None,
            "breakout_amount": float(breakout_amount),
            "amount_shrink_vs_breakout": bp3_amount_shrink,
            "above_breakout": bp3_above_breakout,
            "sector_not_weak": sector_not_weak,
            "next_strength_ok": bp3_strength_ok,
        },
        "stop_loss": round(float(bp3_stop), 2),
        "execution_check": bp3_execution,
        "failure_signals": [
            f"收盘跌破突破位 × {STOP_LOSS_RATIO}",
            "回踩变成放量下跌",
            "反弹日成交额 < 5 日均额 90%",
            "板块走弱",
        ],
    })
    result["buy_points"]["买点三_突破确认"] = bp3

    # ── 买点四：趋势均线支撑 ──
    bp4 = _empty_point(BUY_POINT_PRIORITY["买点四_趋势均线"], common_manual.copy())
    gain_20d = (closes[idx] - closes[-20]) / closes[-20] if len(closes) >= 20 else 0
    bp4_candidates = []
    for ma_name, trend_ma in (("MA10", ma10), ("MA20", ma20)):
        if np.isnan(trend_ma[idx]) or np.isnan(trend_ma[idx - 1]):
            continue
        trend_ma_up = trend_ma[idx] > trend_ma[idx - 1]
        along_ma_10d = all(closes[i] > trend_ma[i] for i in range(max(idx - 9, 0), idx + 1) if not np.isnan(trend_ma[i]))
        near_trend_ma = _near_ma_in_pullback(closes, trend_ma, idx, drops)
        amount_shrink4 = amounts[idx] <= amount_ma5[idx] * PULLBACK_AMOUNT_MA5_RATIO if not np.isnan(amount_ma5[idx]) else False
        above_trend_ma = closes[idx] > trend_ma[idx]
        gain_ok = gain_20d <= BUY_POINT_4_MAX_GAIN_20D
        setup = trend_ma_up and along_ma_10d and near_trend_ma and drops >= 2 and gain_ok and amount_shrink4 and above_trend_ma
        bp4_candidates.append({
            "ma_name": ma_name,
            "trend_ma_val": float(trend_ma[idx]),
            "trend_ma_up": trend_ma_up,
            "along_ma_10d": along_ma_10d,
            "near_trend_ma": near_trend_ma,
            "amount_shrink": amount_shrink4,
            "above_ma": above_trend_ma,
            "gain_ok": gain_ok,
            "setup": setup,
        })
    selected_bp4 = next((item for item in bp4_candidates if item["setup"]), bp4_candidates[0] if bp4_candidates else None)
    bp4_setup = bool(selected_bp4 and selected_bp4["setup"])
    bp4_strength_ok = _next_strength_ok(next_row, amounts[idx])
    bp4_triggered, bp4_status, bp4_execution = _status_for_setup(bp4_setup, next_row, closes[idx], True, bp4_strength_ok)
    if selected_bp4:
        ma_stop = selected_bp4["trend_ma_val"] * STOP_LOSS_RATIO
        low_stop = lows[idx] * STOP_LOSS_RATIO
        bp4_stop = max(ma_stop, low_stop)
    else:
        bp4_stop = None
    bp4.update({
        "triggered": bp4_triggered,
        "setup_triggered": bp4_setup,
        "status": bp4_status,
        "details": {
            "selected_ma": selected_bp4["ma_name"] if selected_bp4 else None,
            "candidates": bp4_candidates,
            "consecutive_drops": drops,
            "gain_20d": round(float(gain_20d), 3),
            "next_strength_ok": bp4_strength_ok,
            "note": "趋势成熟阶段，买点优先级最低",
        },
        "stop_loss": round(float(bp4_stop), 2) if bp4_stop is not None else None,
        "execution_check": bp4_execution,
        "failure_signals": [
            f"收盘跌破均线 × {STOP_LOSS_RATIO}",
            "放量跌破均线",
            "反弹无力，次日继续下跌",
            "板块核心股集体走弱",
        ],
    })
    result["buy_points"]["买点四_趋势均线"] = bp4

    selected, suppressed = _select_highest_priority_buy_point(result["buy_points"])
    result["selected_buy_point"] = selected
    result["suppressed_by_priority"] = suppressed
    result["any_triggered"] = selected is not None
    result["triggered_list"] = [name for name, info in result["buy_points"].items() if info.get("triggered")]
    result["setup_list"] = [name for name, info in result["buy_points"].items() if info.get("setup_triggered")]
    return result
