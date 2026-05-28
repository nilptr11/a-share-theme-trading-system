"""买点扫描。"""

import numpy as np

from theme_trading.data.market_data import fetch_daily

from .buy_point_rules import (
    consecutive_drops,
    evaluate_breakout_buy_point,
    evaluate_breakout_confirm_buy_point,
    evaluate_pullback_buy_point,
    evaluate_trend_ma_buy_point,
    execution_check,
    rate_buy_point_strength,
    find_uptrend_start,
    is_platform_consolidation,
    n_days_after,
    near_ma_in_pullback,
    next_strength_ok,
    pullback_has_volume_down,
    status_for_setup,
)
from .utils import _ma, _n_days_ago, _select_highest_priority_buy_point

_n_days_after = n_days_after
_find_uptrend_start = find_uptrend_start
_execution_check = execution_check
_next_strength_ok = next_strength_ok
_is_platform_consolidation = is_platform_consolidation
_consecutive_drops = consecutive_drops
_near_ma_in_pullback = near_ma_in_pullback
_pullback_has_volume_down = pullback_has_volume_down
_status_for_setup = status_for_setup
_rate_buy_point_strength = rate_buy_point_strength


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
    next_next_row = df.iloc[today + 2] if today + 2 < len(df) else None
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
        "setup_date": trade_date,
        "confirm_date": None,
        "execution_date": None,
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

    uptrend_start, uptrend_start_fallback = _find_uptrend_start(closes, ma20, idx)
    drops = _consecutive_drops(closes, idx)
    sector_pct = sector_context.get("pct_chg") if sector_context else None
    sector_amount_ratio = None
    if sector_context:
        sector_amount_ratio = sector_context.get("amount_ratio")
        if sector_amount_ratio is None:
            sector_amount_ratio = sector_context.get("vol_ratio")
    emotion_extreme = bool(market_context.get("emotion_extreme")) if market_context else False

    result["buy_points"]["买点一_放量突破"] = evaluate_breakout_buy_point(
        highs=highs,
        lows=lows,
        closes=closes,
        amounts=amounts,
        amount_ma5=amount_ma5,
        idx=idx,
        next_row=next_row,
        common_manual=common_manual,
        sector_pct=sector_pct,
        emotion_extreme=emotion_extreme,
    )
    result["buy_points"]["买点二_主升回踩"] = evaluate_pullback_buy_point(
        closes=closes,
        lows=lows,
        amounts=amounts,
        ma5=ma5,
        amount_ma5=amount_ma5,
        idx=idx,
        drops=drops,
        uptrend_start=uptrend_start,
        uptrend_start_fallback=uptrend_start_fallback,
        next_row=next_row,
        next_next_row=next_next_row,
        common_manual=common_manual,
        sector_amount_ratio=sector_amount_ratio,
    )
    result["buy_points"]["买点三_突破确认"] = evaluate_breakout_confirm_buy_point(
        hist=hist,
        highs=highs,
        lows=lows,
        closes=closes,
        amounts=amounts,
        idx=idx,
        next_row=next_row,
        next_next_row=next_next_row,
        common_manual=common_manual,
        sector_pct=sector_pct,
    )
    result["buy_points"]["买点四_趋势均线"] = evaluate_trend_ma_buy_point(
        closes=closes,
        lows=lows,
        amounts=amounts,
        ma10=ma10,
        ma20=ma20,
        amount_ma5=amount_ma5,
        idx=idx,
        drops=drops,
        uptrend_start=uptrend_start,
        uptrend_start_fallback=uptrend_start_fallback,
        next_row=next_row,
        next_next_row=next_next_row,
        common_manual=common_manual,
    )

    for name, info in result["buy_points"].items():
        info.update(_rate_buy_point_strength(name, info))
        needs_strength = name != "买点一_放量突破"
        info["confirm_date"] = next_row["trade_date"] if needs_strength and next_row is not None else trade_date
        info["execution_date"] = next_next_row["trade_date"] if needs_strength and next_next_row is not None else (next_row["trade_date"] if next_row is not None else None)

    selected, suppressed = _select_highest_priority_buy_point(result["buy_points"])
    result["selected_buy_point"] = selected
    result["suppressed_by_priority"] = suppressed
    result["any_triggered"] = selected is not None
    result["triggered_list"] = [name for name, info in result["buy_points"].items() if info.get("triggered")]
    result["setup_list"] = [name for name, info in result["buy_points"].items() if info.get("setup_triggered")]

    needs_strength = selected is not None and selected != "买点一_放量突破"
    if needs_strength:
        result["confirm_date"] = next_row["trade_date"] if next_row is not None else None
        result["execution_date"] = next_next_row["trade_date"] if next_next_row is not None else None
    else:
        result["confirm_date"] = trade_date
        result["execution_date"] = next_row["trade_date"] if next_row is not None else None

    return result


def confirm_pending_buy_point(
    ts_code: str,
    setup_date: str,
    confirm_date: str,
    buy_point_name: str,
    market_context: dict | None = None,
    sector_context: dict | None = None,
    core_context: dict | None = None,
) -> dict:
    """用 confirm_date 行情确认此前回踩 setup 是否转强。"""
    bp = scan_buy_points(
        ts_code,
        setup_date,
        market_context=market_context,
        sector_context=sector_context,
        core_context=core_context,
    )
    if not bp.get("ok", True):
        return {
            "ok": False,
            "ts_code": ts_code,
            "buy_point": buy_point_name,
            "setup_date": setup_date,
            "confirm_date": confirm_date,
            "status": "invalid",
            "reason": bp.get("error", "买点扫描失败"),
        }

    info = bp.get("buy_points", {}).get(buy_point_name)
    if info is None:
        return {
            "ok": False,
            "ts_code": ts_code,
            "buy_point": buy_point_name,
            "setup_date": setup_date,
            "confirm_date": confirm_date,
            "status": "invalid",
            "reason": "未知买点类型",
        }

    actual_confirm_date = info.get("confirm_date", bp.get("confirm_date"))
    if actual_confirm_date != confirm_date:
        return {
            "ok": True,
            "ts_code": ts_code,
            "buy_point": buy_point_name,
            "setup_date": setup_date,
            "confirm_date": actual_confirm_date,
            "status": "pending_next_day_strength",
            "reason": "确认日行情尚未覆盖到本次扫描日期",
            "buy_scan": bp,
        }

    return {
        "ok": True,
        "ts_code": ts_code,
        "buy_point": buy_point_name,
        "setup_date": setup_date,
        "confirm_date": actual_confirm_date,
        "execution_date": info.get("execution_date", bp.get("execution_date")),
        "status": info.get("status"),
        "triggered": info.get("triggered"),
        "setup_triggered": info.get("setup_triggered"),
        "buy_scan": bp,
        "buy_point_info": info,
    }
