"""Individual buy point evaluators."""

from datetime import datetime, timedelta

import numpy as np

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
from .utils import BUY_POINT_PRIORITY, _check_open_gap, _has_prior_pullback


def n_days_after(date_str: str, n: int) -> str:
    return (datetime.strptime(date_str, "%Y%m%d") + timedelta(days=n)).strftime("%Y%m%d")


def find_uptrend_start(closes: np.ndarray, ma20: np.ndarray, today: int) -> tuple[int, bool]:
    search_start = max(today - 60, 0)
    for i in range(today - 1, search_start, -1):
        if np.isnan(ma20[i]) or np.isnan(ma20[i - 1]):
            continue
        if closes[i - 1] < ma20[i - 1] and closes[i] > ma20[i] and ma20[i] > ma20[i - 1]:
            return i, False
    return max(today - 30, 0), True


def empty_point(priority: int, manual_checks: list[str] | None = None) -> dict:
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


def is_platform_consolidation(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    today: int,
    days: int = 5,
    max_range_pct: float = 0.05,
    max_close_drift_pct: float = 0.03,
) -> tuple[bool, dict]:
    if today < days:
        return False, {
            "range_pct": None,
            "close_drift_pct": None,
            "center_bias_max": None,
            "close_band_ok": False,
            "close_drift_ok": False,
        }

    start = today - days
    recent_high = float(np.max(highs[start:today]))
    recent_low = float(np.min(lows[start:today]))
    recent_closes = closes[start:today].astype(float)
    range_pct = (recent_high - recent_low) / recent_low if recent_low > 0 else 1.0

    first_close = float(recent_closes[0])
    last_close = float(recent_closes[-1])
    close_drift_pct = abs(last_close / first_close - 1) if first_close > 0 else 1.0

    center = (recent_high + recent_low) / 2
    half_range = (recent_high - recent_low) / 2
    if center <= 0 or half_range <= 0:
        center_bias_max = 1.0
        close_band_ok = False
    else:
        center_bias = np.abs(recent_closes - center) / half_range
        center_bias_max = float(np.max(center_bias))
        close_band_ok = bool(center_bias_max <= 0.9)

    close_drift_ok = close_drift_pct <= max_close_drift_pct
    is_consolidating = range_pct <= max_range_pct and close_drift_ok and close_band_ok
    return is_consolidating, {
        "range_pct": range_pct,
        "close_drift_pct": close_drift_pct,
        "center_bias_max": center_bias_max,
        "close_band_ok": close_band_ok,
        "close_drift_ok": close_drift_ok,
    }


def consecutive_drops(closes: np.ndarray, today: int, max_days: int = 5) -> int:
    drops = 0
    for i in range(today, max(today - max_days, 0), -1):
        if closes[i] < closes[i - 1]:
            drops += 1
        else:
            break
    return drops


def near_ma_in_pullback(closes: np.ndarray, ma_values: np.ndarray, today: int, drops: int, tolerance: float = 0.01) -> bool:
    if drops < 2:
        return False
    start = max(today - drops + 1, 0)
    for i in range(start, today + 1):
        if not np.isnan(ma_values[i]) and ma_values[i] > 0 and abs(closes[i] - ma_values[i]) / ma_values[i] <= tolerance:
            return True
    return False


def pullback_has_volume_down(closes: np.ndarray, amounts: np.ndarray, amount_ma5: np.ndarray, today: int, drops: int) -> bool:
    start = max(today - drops + 1, 0)
    for i in range(start, today + 1):
        if closes[i] < closes[i - 1] and not np.isnan(amount_ma5[i]) and amounts[i] >= amount_ma5[i] * 1.2:
            return True
    return False


def execution_check(confirm_close: float, next_row) -> dict:
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


def next_strength_ok(next_row, base_amount: float) -> bool | None:
    if next_row is None:
        return None
    if "close" not in next_row or "open" not in next_row or "amount" not in next_row:
        return None
    return bool(float(next_row["close"]) > float(next_row["open"]) and float(next_row["amount"]) >= base_amount * REBOUND_AMOUNT_RATIO)


def status_for_setup(setup: bool, next_row, confirm_close: float, needs_strength: bool, strength_ok: bool | None, blocked: bool = False) -> tuple[bool, str, dict]:
    execution = execution_check(confirm_close, next_row)
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
        if not strength_ok:
            return False, "invalid", execution
        if not gap["checked"]:
            return True, "pending_next_open", execution
        return True, "executable_plan", execution
    if not gap["checked"]:
        return True, "pending_next_open", execution
    return True, "executable_plan", execution


def _strength_level(score: int) -> str:
    if score >= 5:
        return "strong"
    if score >= 3:
        return "medium"
    return "weak"


def _bool_reason(score: int, reasons: list[str], passed: bool, reason: str) -> int:
    if passed:
        reasons.append(reason)
        return score + 1
    return score


def rate_buy_point_strength(name: str, info: dict) -> dict:
    details = info.get("details", {})
    reasons: list[str] = []
    score = 0

    if not info.get("setup_triggered") and not info.get("triggered"):
        return {"strength_score": 0, "strength_level": "weak", "strength_reasons": []}

    score = _bool_reason(score, reasons, bool(info.get("setup_triggered")), "买点形态成立")
    status = info.get("status")
    score = _bool_reason(score, reasons, status in ("pending_next_open", "executable_plan"), "已进入可计划状态")

    if name == "买点一_放量突破":
        amount_ratio = details.get("amount_ratio") or 0
        range_pct = details.get("consolidation_5d_range")
        if amount_ratio >= 1.5:
            reasons.append(f"放量 {amount_ratio:.1f} 倍")
            score += 1
        if amount_ratio >= 2.0:
            reasons.append("放量超过 2 倍")
            score += 1
        if range_pct is not None and range_pct <= 0.03:
            reasons.append(f"平台收敛 {range_pct:.1%}")
            score += 1
        score = _bool_reason(score, reasons, bool(details.get("close_confirm")), "收盘确认突破")
        score = _bool_reason(score, reasons, bool(details.get("sector_follow")), "板块跟随")
    elif name == "买点二_主升回踩":
        score = _bool_reason(score, reasons, bool(details.get("ma5_up")), "MA5 上行")
        score = _bool_reason(score, reasons, bool(details.get("near_ma5")) and bool(details.get("above_ma5")), "缩量回踩 MA5 不破")
        prev_ratio = details.get("amount_vs_prev_ratio")
        ma5_ratio = details.get("amount_vs_ma5_ratio")
        if (prev_ratio is not None and prev_ratio <= 0.7) or (ma5_ratio is not None and ma5_ratio <= 0.8):
            reasons.append("回踩明显缩量")
            score += 1
        score = _bool_reason(score, reasons, bool(details.get("next_strength_ok")), "次日转强确认")
        score = _bool_reason(score, reasons, bool(details.get("sector_amount_ok")), "板块成交额配合")
        score = _bool_reason(score, reasons, not bool(details.get("volume_down_invalid")), "未出现放量下跌")
    elif name == "买点三_突破确认":
        score = _bool_reason(score, reasons, bool(details.get("recent_60d_high")), "近期突破 60 日高点")
        ratio = details.get("amount_vs_breakout_ratio")
        if ratio is not None and ratio <= 0.6:
            reasons.append(f"回踩量缩至突破日 {ratio:.1f}")
            score += 1
        score = _bool_reason(score, reasons, bool(details.get("above_breakout")), "回踩不破突破位")
        score = _bool_reason(score, reasons, bool(details.get("next_strength_ok")), "次日转强确认")
        score = _bool_reason(score, reasons, bool(details.get("sector_not_weak")), "板块未走弱")
    elif name == "买点四_趋势均线":
        selected = None
        for candidate in details.get("candidates", []):
            if candidate.get("ma_name") == details.get("selected_ma"):
                selected = candidate
                break
        selected = selected or (details.get("candidates", [])[:1] or [None])[0]
        if selected:
            score = _bool_reason(score, reasons, bool(selected.get("trend_ma_up")), f"{selected.get('ma_name')} 上行")
            score = _bool_reason(score, reasons, bool(selected.get("along_ma_10d")), "10 日沿趋势均线运行")
            score = _bool_reason(score, reasons, bool(selected.get("near_trend_ma")) and bool(selected.get("above_ma")), "缩量回踩趋势均线不破")
            score = _bool_reason(score, reasons, bool(selected.get("amount_shrink")), "回踩缩量")
            score = _bool_reason(score, reasons, bool(selected.get("gain_ok")), "近 20 日涨幅未过热")
        score = _bool_reason(score, reasons, bool(details.get("next_strength_ok")), "次日转强确认")

    return {
        "strength_score": score,
        "strength_level": _strength_level(score),
        "strength_reasons": reasons[:4],
    }


def evaluate_breakout_buy_point(
    *,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    amounts: np.ndarray,
    amount_ma5: np.ndarray,
    idx: int,
    next_row,
    common_manual: list[str],
    sector_pct: float | None,
    emotion_extreme: bool,
) -> dict:
    bp = empty_point(BUY_POINT_PRIORITY["买点一_放量突破"], common_manual.copy())
    recent_5_low = float(np.min(lows[-6:-1]))
    is_consolidating, consolidation = is_platform_consolidation(highs, lows, closes, idx)
    range_pct = consolidation["range_pct"] if consolidation["range_pct"] is not None else 1.0
    high_20 = float(np.max(highs[-21:-1]))
    is_breakout = closes[idx] > high_20
    amount_ok = amounts[idx] >= amount_ma5[idx] * BREAKOUT_AMOUNT_RATIO if not np.isnan(amount_ma5[idx]) else False
    close_confirm = closes[idx] >= high_20 * BREAKOUT_CONFIRM_RATIO
    sector_follow = sector_pct is None or sector_pct >= 1.0
    if sector_pct is None:
        bp["manual_checks"].append("买点一板块当日涨幅 ≥ 1% 需人工确认")

    setup = is_consolidating and is_breakout and amount_ok and close_confirm and sector_follow
    stop_loss = recent_5_low * STOP_LOSS_RATIO if recent_5_low < high_20 else high_20 * STOP_LOSS_RATIO
    triggered, status, execution = status_for_setup(setup, next_row, closes[idx], False, None, blocked=emotion_extreme)
    if emotion_extreme and setup:
        bp["manual_checks"].append("情绪极端日不追涨，买点一仅列观察")
    bp.update({
        "triggered": triggered,
        "setup_triggered": setup,
        "status": status,
        "details": {
            "consolidation_5d_range": round(float(range_pct), 3),
            "is_consolidating": is_consolidating,
            "consolidation_close_drift": round(float(consolidation["close_drift_pct"]), 3) if consolidation["close_drift_pct"] is not None else None,
            "consolidation_center_bias": round(float(consolidation["center_bias_max"]), 3) if consolidation["center_bias_max"] is not None else None,
            "consolidation_close_drift_ok": consolidation["close_drift_ok"],
            "consolidation_close_band_ok": consolidation["close_band_ok"],
            "high_20": high_20,
            "breakout": is_breakout,
            "amount_ok": amount_ok,
            "amount_ratio": round(float(amounts[idx] / amount_ma5[idx]), 2) if not np.isnan(amount_ma5[idx]) and amount_ma5[idx] > 0 else None,
            "close_confirm": close_confirm,
            "sector_follow": sector_follow,
        },
        "stop_loss": round(float(stop_loss), 2) if is_breakout else None,
        "execution_check": execution,
        "failure_signals": [
            f"收盘价 < 突破位 × {STOP_LOSS_RATIO}",
            "放量长上影或放量收阴",
            "板块没有跟随",
            "次日低开低走",
        ],
    })
    return bp


def evaluate_pullback_buy_point(
    *,
    closes: np.ndarray,
    lows: np.ndarray,
    amounts: np.ndarray,
    ma5: np.ndarray,
    amount_ma5: np.ndarray,
    idx: int,
    drops: int,
    uptrend_start: int,
    uptrend_start_fallback: bool,
    next_row,
    next_next_row,
    common_manual: list[str],
    sector_amount_ratio: float | None,
) -> dict:
    bp = empty_point(BUY_POINT_PRIORITY["买点二_主升回踩"], common_manual.copy())
    above_ma5_3d = all(closes[i] > ma5[i] for i in range(max(idx - 2, 0), idx + 1) if not np.isnan(ma5[i]))
    ma5_up = ma5[idx] > ma5[idx - 1] if not np.isnan(ma5[idx]) and not np.isnan(ma5[idx - 1]) else False
    near_ma5 = near_ma_in_pullback(closes, ma5, idx, drops)
    volume_down_invalid = pullback_has_volume_down(closes, amounts, amount_ma5, idx, drops)
    amount_shrink = amounts[idx] <= amounts[idx - 1] * PULLBACK_AMOUNT_PREV_RATIO and amounts[idx] <= amount_ma5[idx] * PULLBACK_AMOUNT_MA5_RATIO
    above_ma5 = closes[idx] > ma5[idx] if not np.isnan(ma5[idx]) else False
    sector_amount_ok = sector_amount_ratio is None or sector_amount_ratio >= 1.0
    if sector_amount_ratio is None:
        bp["manual_checks"].append("买点二板块成交额未跌破 5 日均值需人工确认")

    setup = above_ma5_3d and ma5_up and drops >= 2 and near_ma5 and amount_shrink and above_ma5 and sector_amount_ok and not volume_down_invalid
    if uptrend_start_fallback and setup:
        bp["manual_checks"].append("未找到明确主升启动日，第一次回踩仅回看近 30 日，需人工确认此前是否已有回踩 5 日线")
    if _has_prior_pullback(closes, ma5, idx, current_drops=drops, lookback=idx - uptrend_start):
        bp["manual_checks"].append("检测到此前已出现过回踩 5 日线，当前可能不是第一次回踩 → 禁止清单：不做第二次回踩")
        setup = False
    strength_ok = next_strength_ok(next_row, amounts[idx])
    confirm_close = float(next_row["close"]) if next_row is not None else closes[idx]
    triggered, status, execution = status_for_setup(setup, next_next_row, confirm_close, True, strength_ok)
    ma5_stop = ma5[idx] * STOP_LOSS_RATIO if not np.isnan(ma5[idx]) else None
    low_stop = lows[idx] * STOP_LOSS_RATIO
    stop_loss = ma5_stop if ma5_stop is not None and ma5[idx] >= lows[idx] and (ma5[idx] - lows[idx]) / lows[idx] <= 0.02 else low_stop
    bp.update({
        "triggered": triggered,
        "setup_triggered": setup,
        "status": status,
        "details": {
            "above_ma5_3d": above_ma5_3d,
            "ma5_up": ma5_up,
            "consecutive_drops": drops,
            "near_ma5": near_ma5,
            "amount_shrink": amount_shrink,
            "amount_vs_prev_ratio": round(float(amounts[idx] / amounts[idx - 1]), 2) if idx > 0 and amounts[idx - 1] > 0 else None,
            "amount_vs_ma5_ratio": round(float(amounts[idx] / amount_ma5[idx]), 2) if not np.isnan(amount_ma5[idx]) and amount_ma5[idx] > 0 else None,
            "above_ma5": above_ma5,
            "sector_amount_ok": sector_amount_ok,
            "volume_down_invalid": volume_down_invalid,
            "next_strength_ok": strength_ok,
        },
        "stop_loss": round(float(stop_loss), 2),
        "execution_check": execution,
        "failure_signals": [
            "回调变成放量下跌",
            "收盘跌破止损位，而非单日轻微跌破 MA5",
            "反弹日成交额 < 5 日均额 90%",
            "板块核心股集体走弱",
        ],
    })
    return bp


def evaluate_breakout_confirm_buy_point(
    *,
    hist,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    amounts: np.ndarray,
    idx: int,
    next_row,
    next_next_row,
    common_manual: list[str],
    sector_pct: float | None,
) -> dict:
    bp = empty_point(BUY_POINT_PRIORITY["买点三_突破确认"], common_manual.copy())
    high_60_window = highs[-61:-1] if len(highs) >= 61 else highs[:-1]
    high_60 = float(np.max(high_60_window))
    breakout_candidates = [i for i in range(max(idx - 10, 0), idx) if highs[i] >= high_60]
    breakout_idx = breakout_candidates[-1] if breakout_candidates else None
    recent_high_60 = breakout_idx is not None
    breakout_amount = amounts[breakout_idx] if breakout_idx is not None else amounts[idx]
    amount_shrink = amounts[idx] <= breakout_amount * 0.6
    above_breakout = closes[idx] >= high_60
    sector_not_weak = sector_pct is None or sector_pct >= 0
    if sector_pct is None:
        bp["manual_checks"].append("买点三板块同期没有走弱需人工确认")
    setup = recent_high_60 and amount_shrink and above_breakout and sector_not_weak
    strength_ok = next_strength_ok(next_row, amounts[idx])
    confirm_close = float(next_row["close"]) if next_row is not None else closes[idx]
    triggered, status, execution = status_for_setup(setup, next_next_row, confirm_close, True, strength_ok)
    pullback_low = float(lows[idx])
    stop_loss = pullback_low * STOP_LOSS_RATIO if pullback_low > high_60 * 1.03 else high_60 * STOP_LOSS_RATIO
    bp.update({
        "triggered": triggered,
        "setup_triggered": setup,
        "status": status,
        "details": {
            "high_60": high_60,
            "high_60_lookback_days": int(len(high_60_window)),
            "recent_60d_high": recent_high_60,
            "breakout_date": hist.iloc[breakout_idx]["trade_date"] if breakout_idx is not None else None,
            "breakout_amount": float(breakout_amount),
            "amount_shrink_vs_breakout": amount_shrink,
            "amount_vs_breakout_ratio": round(float(amounts[idx] / breakout_amount), 2) if breakout_amount > 0 else None,
            "above_breakout": above_breakout,
            "sector_not_weak": sector_not_weak,
            "next_strength_ok": strength_ok,
        },
        "stop_loss": round(float(stop_loss), 2),
        "execution_check": execution,
        "failure_signals": [
            f"收盘跌破突破位 × {STOP_LOSS_RATIO}",
            "回踩变成放量下跌",
            "反弹日成交额 < 5 日均额 90%",
            "板块走弱",
        ],
    })
    return bp


def evaluate_trend_ma_buy_point(
    *,
    closes: np.ndarray,
    lows: np.ndarray,
    amounts: np.ndarray,
    ma10: np.ndarray,
    ma20: np.ndarray,
    amount_ma5: np.ndarray,
    idx: int,
    drops: int,
    uptrend_start: int,
    uptrend_start_fallback: bool,
    next_row,
    next_next_row,
    common_manual: list[str],
) -> dict:
    bp = empty_point(BUY_POINT_PRIORITY["买点四_趋势均线"], common_manual.copy())
    gain_20d = (closes[idx] - closes[-20]) / closes[-20] if len(closes) >= 20 else 0
    candidates = []
    for ma_name, trend_ma in (("MA10", ma10), ("MA20", ma20)):
        if np.isnan(trend_ma[idx]) or np.isnan(trend_ma[idx - 1]):
            continue
        trend_ma_up = trend_ma[idx] > trend_ma[idx - 1]
        along_ma_10d = all(closes[i] > trend_ma[i] for i in range(max(idx - 9, 0), idx + 1) if not np.isnan(trend_ma[i]))
        near_trend_ma = near_ma_in_pullback(closes, trend_ma, idx, drops)
        amount_shrink = amounts[idx] <= amount_ma5[idx] * PULLBACK_AMOUNT_MA5_RATIO if not np.isnan(amount_ma5[idx]) else False
        above_trend_ma = closes[idx] > trend_ma[idx]
        gain_ok = gain_20d <= BUY_POINT_4_MAX_GAIN_20D
        setup = trend_ma_up and along_ma_10d and near_trend_ma and drops >= 2 and gain_ok and amount_shrink and above_trend_ma
        candidates.append({
            "ma_name": ma_name,
            "trend_ma_val": float(trend_ma[idx]),
            "trend_ma_up": trend_ma_up,
            "along_ma_10d": along_ma_10d,
            "near_trend_ma": near_trend_ma,
            "amount_shrink": amount_shrink,
            "above_ma": above_trend_ma,
            "gain_ok": gain_ok,
            "setup": setup,
        })
    selected = next((item for item in candidates if item["setup"]), candidates[0] if candidates else None)
    setup = bool(selected and selected["setup"])
    if setup and selected:
        trend_ma_arr = ma10 if selected["ma_name"] == "MA10" else ma20
        if uptrend_start_fallback:
            bp["manual_checks"].append("未找到明确主升启动日，第一次回踩仅回看近 30 日，需人工确认此前是否已有回踩趋势均线")
        if _has_prior_pullback(closes, trend_ma_arr, idx, current_drops=drops, lookback=idx - uptrend_start):
            bp["manual_checks"].append("检测到此前已出现过回踩该均线，当前可能不是第一次回踩 → 禁止清单：不做第二次回踩")
            setup = False
    strength_ok = next_strength_ok(next_row, amounts[idx])
    confirm_close = float(next_row["close"]) if next_row is not None else closes[idx]
    triggered, status, execution = status_for_setup(setup, next_next_row, confirm_close, True, strength_ok)
    if selected:
        ma_stop = selected["trend_ma_val"] * STOP_LOSS_RATIO
        low_stop = lows[idx] * STOP_LOSS_RATIO
        stop_loss = max(ma_stop, low_stop)
        stop_loss_basis = "trend_ma" if ma_stop >= low_stop else "pullback_low"
    else:
        stop_loss = None
        stop_loss_basis = None
    bp.update({
        "triggered": triggered,
        "setup_triggered": setup,
        "status": status,
        "details": {
            "selected_ma": selected["ma_name"] if selected else None,
            "candidates": candidates,
            "consecutive_drops": drops,
            "gain_20d": round(float(gain_20d), 3),
            "amount_vs_ma5_ratio": round(float(amounts[idx] / amount_ma5[idx]), 2) if not np.isnan(amount_ma5[idx]) and amount_ma5[idx] > 0 else None,
            "next_strength_ok": strength_ok,
            "stop_loss_basis": stop_loss_basis,
            "stop_loss_rule": "均线价 × 0.99 与回踩低点 × 0.99 取更近的位置，不用更远止损放宽风险",
            "note": "趋势成熟阶段，买点优先级最低",
        },
        "stop_loss": round(float(stop_loss), 2) if stop_loss is not None else None,
        "execution_check": execution,
        "failure_signals": [
            "放量跌破趋势均线",
            "收盘跌破止损位，而非单日轻微跌破趋势均线",
            "反弹无力，次日继续下跌",
            "板块核心股集体走弱",
        ],
    })
    return bp
