"""买点扫描。"""

import numpy as np

from theme_trading.data.market_data import fetch_daily

from .utils import _ma, _n_days_ago


def scan_buy_points(ts_code: str, trade_date: str) -> dict:
    """对单只个股扫描四个买点条件

    返回每个买点的满足情况和详细指标。
    确认日 = trade_date
    """
    # 获取近 60 日数据
    start = _n_days_ago(trade_date, 70)
    df = fetch_daily(ts_code=ts_code, start_date=start, end_date=trade_date)
    if df is None or len(df) < 25:
        return {"ok": False, "error": "数据不足"}

    df = df.sort_values("trade_date").reset_index(drop=True)
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    vols = df["vol"].values
    amounts = df["amount"].values

    # 均线
    ma5 = _ma(closes, 5)
    ma10 = _ma(closes, 10)
    ma20 = _ma(closes, 20)
    vol_ma5 = _ma(vols, 5)

    today = len(closes) - 1
    prev = today - 1

    result = {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "close": float(closes[today]),
        "ma5": float(ma5[today]) if not np.isnan(ma5[today]) else None,
        "ma10": float(ma10[today]) if not np.isnan(ma10[today]) else None,
        "ma20": float(ma20[today]) if not np.isnan(ma20[today]) else None,
        "vol_ratio": float(vols[today] / vol_ma5[today]) if not np.isnan(vol_ma5[today]) and vol_ma5[today] > 0 else None,
        "buy_points": {},
    }

    # ── 买点一：低位放量突破 ──
    bp1_ok = False
    bp1_details = {}

    # 近 5 日横盘整理（最高最低差 ≤ 3%）
    if len(closes) >= 10:
        recent_5_high = np.max(highs[-6:-1])  # 前 5 天
        recent_5_low = np.min(lows[-6:-1])
        range_pct = (recent_5_high - recent_5_low) / recent_5_low if recent_5_low > 0 else 1.0
        bp1_details["consolidation_5d_range"] = round(float(range_pct), 3)
        is_consolidating = range_pct <= 0.05  # 振幅 ≤ 5% 视为横盘
    else:
        is_consolidating = False

    # 突破近 20 日高点
    high_20 = np.max(highs[-21:-1]) if len(highs) >= 21 else np.max(highs[:-1])
    is_breakout = closes[today] > high_20
    bp1_details["high_20"] = float(high_20)
    bp1_details["breakout"] = is_breakout

    # 放量 ≥ 5日均量 1.5 倍
    vol_ok = (vols[today] >= vol_ma5[today] * 1.5) if not np.isnan(vol_ma5[today]) else False
    bp1_details["vol_ok"] = vol_ok

    # 收盘 ≥ 突破位 × 1.005
    confirm_close = closes[today] >= high_20 * 1.005
    bp1_details["close_confirm"] = confirm_close

    bp1_ok = is_consolidating and is_breakout and vol_ok and confirm_close

    result["buy_points"]["买点一_放量突破"] = {
        "triggered": bp1_ok,
        "details": bp1_details,
        "stop_loss": round(float(high_20 * 0.99), 2) if is_breakout else None,
    }

    # ── 买点二：主升第一次缩量回踩 ──
    bp2_ok = False
    bp2_details = {}

    # 连续 3 日站上 5 日线
    above_ma5_3d = all(
        closes[i] > ma5[i] for i in range(today - 3, today)
        if i >= 0 and not np.isnan(ma5[i])
    ) if len(closes) >= 4 else False
    bp2_details["above_ma5_3d"] = above_ma5_3d

    # 5 日线向上
    ma5_up = ma5[today] > ma5[today - 1] if (not np.isnan(ma5[today]) and
                                                not np.isnan(ma5[today - 1])) else False
    bp2_details["ma5_up"] = ma5_up

    # 第一次回踩: 收盘价连续 ≥ 2 日下降 + 距 5 日线 ≤ 1%
    consecutive_drop = 0
    for i in range(today, max(today - 5, -len(closes)), -1):
        if closes[i] < closes[i - 1]:
            consecutive_drop += 1
        else:
            break
    is_pullback_seq = consecutive_drop >= 2

    near_ma5 = abs(closes[today] - ma5[today]) / ma5[today] <= 0.01 if (
        not np.isnan(ma5[today]) and ma5[today] > 0) else False
    bp2_details["consecutive_drops"] = consecutive_drop
    bp2_details["near_ma5"] = near_ma5
    bp2_details["is_first_pullback"] = is_pullback_seq and near_ma5

    # 缩量: ≤ 前一日 70% 且 ≤ 5 日均量 80%
    vol_shrink = (vols[today] <= vols[prev] * 0.7 and
                  vols[today] <= vol_ma5[today] * 0.8) if not np.isnan(vol_ma5[today]) else False
    bp2_details["vol_shrink"] = vol_shrink

    # 不破 5 日线
    above_ma5 = closes[today] > ma5[today] if not np.isnan(ma5[today]) else False
    bp2_details["above_ma5"] = above_ma5

    bp2_needs = [above_ma5_3d, ma5_up, is_pullback_seq, near_ma5, vol_shrink, above_ma5]
    bp2_ok = all(bp2_needs)

    pullback_low = float(lows[today])
    result["buy_points"]["买点二_主升回踩"] = {
        "triggered": bp2_ok,
        "details": bp2_details,
        "stop_loss": round(float(pullback_low * 0.99), 2),
        "note": "需次日收阳且成交额 ≥ 回调日 1.2 倍才能确认执行",
    }

    # ── 买点三：突破回踩确认 ──
    bp3_ok = False
    bp3_details = {}

    # 近 10 日内有过 60 日新高
    high_60 = np.max(highs[-61:-1]) if len(highs) >= 61 else np.max(highs[:-1])
    recent_high_60 = any(h >= high_60 for h in highs[-11:-1])  # 前 1-10 天
    bp3_details["high_60"] = float(high_60)
    bp3_details["recent_60d_high"] = recent_high_60

    # 回踩缩量 ≤ 突破日 60%
    breakout_day_vol = vols[-11:-1][np.argmax(highs[-11:-1])] if len(vols) >= 11 else vols[-1]
    bp3_vol_shrink = vols[today] <= breakout_day_vol * 0.6
    bp3_details["vol_shrink_vs_breakout"] = bp3_vol_shrink

    # 不破突破位
    bp3_above_breakout = closes[today] > high_60 * 0.99
    bp3_details["above_breakout"] = bp3_above_breakout

    bp3_ok = recent_high_60 and bp3_vol_shrink and bp3_above_breakout

    result["buy_points"]["买点三_突破确认"] = {
        "triggered": bp3_ok,
        "details": bp3_details,
        "stop_loss": round(float(high_60 * 0.99), 2),
        "note": "需次日收阳且成交额 ≥ 回踩日 1.2 倍才能确认执行",
    }

    # ── 买点四：趋势均线支撑 ──
    bp4_ok = False
    bp4_details = {}

    # 选择均线: 10 日或 20 日
    if not np.isnan(ma10[today]) and ma10[today] < ma20[today]:
        trend_ma = ma10
        trend_ma_name = "MA10"
    else:
        trend_ma = ma20
        trend_ma_name = "MA20"

    trend_ma_val = trend_ma[today]
    trend_ma_up = trend_ma[today] > trend_ma[today - 1] if (
        not np.isnan(trend_ma[today]) and not np.isnan(trend_ma[today - 1])) else False

    # 连续 10 日沿均线上行
    along_ma_10d = all(closes[i] > trend_ma[i] for i in range(today - 10, today)
                       if i >= 0 and not np.isnan(trend_ma[i]))
    bp4_details["along_ma_10d"] = along_ma_10d
    bp4_details["trend_ma"] = trend_ma_name
    bp4_details["trend_ma_val"] = float(trend_ma_val) if not np.isnan(trend_ma_val) else None
    bp4_details["trend_ma_up"] = trend_ma_up

    # 首次回踩: 距均线 ≤ 1% + 连续 ≥ 2 日下降
    near_trend_ma = abs(closes[today] - trend_ma_val) / trend_ma_val <= 0.01 if (
        not np.isnan(trend_ma_val) and trend_ma_val > 0) else False
    bp4_details["near_trend_ma"] = near_trend_ma

    # 近 20 日涨幅 ≤ 50%
    if len(closes) >= 20:
        gain_20d = (closes[today] - closes[-20]) / closes[-20]
        bp4_details["gain_20d"] = round(float(gain_20d), 3)
        gain_ok = gain_20d <= 0.50
    else:
        gain_ok = True
    bp4_details["gain_ok"] = gain_ok

    # 缩量
    bp4_vol_shrink = vols[today] <= vol_ma5[today] * 0.8 if not np.isnan(vol_ma5[today]) else False
    bp4_details["vol_shrink"] = bp4_vol_shrink

    # 不破均线
    bp4_above_ma = closes[today] > trend_ma_val if not np.isnan(trend_ma_val) else False
    bp4_details["above_ma"] = bp4_above_ma

    bp4_ok = (trend_ma_up and along_ma_10d and near_trend_ma and
              is_pullback_seq and gain_ok and bp4_vol_shrink and bp4_above_ma)

    result["buy_points"]["买点四_趋势均线"] = {
        "triggered": bp4_ok,
        "details": bp4_details,
        "stop_loss": round(float(trend_ma_val * 0.99), 2) if not np.isnan(trend_ma_val) else None,
        "note": "风险预算减半。需次日收阳且成交额 ≥ 回踩日 1.2 倍确认",
    }

    # 汇总
    triggered = [k for k, v in result["buy_points"].items() if v["triggered"]]
    result["any_triggered"] = len(triggered) > 0
    result["triggered_list"] = triggered

    return result
