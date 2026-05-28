"""市场扫描工具函数。"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd


def _n_days_ago(date_str: str, n: int) -> str:
    """返回 date_str 前 n 个自然日（YYYYMMDD 格式）"""
    dt = datetime.strptime(date_str, "%Y%m%d")
    return (dt - timedelta(days=n)).strftime("%Y%m%d")


def _ma(values: np.ndarray, window: int) -> np.ndarray:
    """简单移动平均，不足 window 的位置填 NaN"""
    if len(values) < window:
        return np.full_like(values, np.nan, dtype=float)
    result = np.full_like(values, np.nan, dtype=float)
    for i in range(window - 1, len(values)):
        result[i] = np.mean(values[i - window + 1 : i + 1])
    return result


def _ma_value(df: pd.DataFrame, col: str, window: int) -> float | None:
    """计算 DataFrame 中 col 列的 window 日均线最新值"""
    if df is None or len(df) < window:
        return None
    series = df.sort_values("trade_date")[col].values
    ma = _ma(series, window)
    return float(ma[-1]) if not np.isnan(ma[-1]) else None


def _prev_n_avg(df: pd.DataFrame, col: str, n: int) -> float | None:
    """最近 n 行 col 列的平均值"""
    if df is None or len(df) < n:
        return None
    return float(df.sort_values("trade_date")[col].tail(n).mean())


def _rolling_ma_series(values: pd.Series, window: int) -> pd.Series:
    return values.astype(float).rolling(window, min_periods=window).mean()


def _recent_ratio_flags(df: pd.DataFrame, col: str, window: int, ratio: float, days: int, above: bool = True) -> list[bool]:
    if df is None or len(df) < window + days - 1 or col not in df.columns:
        return []
    ordered = df.sort_values("trade_date").copy()
    ma = _rolling_ma_series(ordered[col], window)
    checks = []
    for idx in ordered.tail(days).index:
        avg = ma.loc[idx]
        value = float(ordered.loc[idx, col])
        if pd.isna(avg) or avg <= 0:
            return []
        checks.append(value >= avg * ratio if above else value < avg * ratio)
    return checks


def _recent_all_ratio(df: pd.DataFrame, col: str, window: int, ratio: float, days: int, above: bool = True) -> bool | None:
    checks = _recent_ratio_flags(df, col, window, ratio, days, above)
    return all(checks) if len(checks) == days else None


def _rank_map(df: pd.DataFrame, value_col: str, ascending: bool = False) -> dict:
    if df is None or df.empty or value_col not in df.columns:
        return {}
    ranked = df.copy()
    ranked[value_col] = ranked[value_col].astype(float)
    ranked["_rank"] = ranked[value_col].rank(ascending=ascending, method="min")
    return dict(zip(ranked["ts_code"], ranked["_rank"].astype(int)))


def _top_percent_threshold(size: int, pct: float) -> int:
    return max(1, int(np.ceil(size * pct)))


def _is_above_ma_stack(close: float, ma5: float | None, ma10: float | None, ma20: float | None) -> bool:
    mas = [ma5, ma10, ma20]
    return all(ma is not None and not np.isnan(ma) and close > ma for ma in mas)


def _check_open_gap(confirm_close: float, next_open: float | None, limit: float = 0.03) -> dict:
    if next_open is None or confirm_close <= 0:
        return {"checked": False, "passed": None, "gap_pct": None}
    gap_pct = next_open / confirm_close - 1
    return {"checked": True, "passed": abs(gap_pct) <= limit, "gap_pct": round(float(gap_pct), 4)}


BUY_POINT_PRIORITY = {
    "买点一_放量突破": 1,
    "买点三_突破确认": 2,
    "买点二_主升回踩": 3,
    "买点四_趋势均线": 4,
}

SELECTABLE_BUY_POINT_STATUSES = {
    "executable_plan",
    "pending_next_open",
    "pending_next_day_strength",
    "watch",
}


def _select_highest_priority_buy_point(buy_points: dict) -> tuple[str | None, list[str]]:
    triggered = [
        name
        for name, info in buy_points.items()
        if (info.get("triggered") or info.get("setup_triggered"))
        and info.get("status") in SELECTABLE_BUY_POINT_STATUSES
    ]
    if not triggered:
        return None, []
    selected = sorted(triggered, key=lambda name: BUY_POINT_PRIORITY.get(name, 99))[0]
    suppressed = [name for name in triggered if name != selected]
    return selected, suppressed


def _amount_col(df: pd.DataFrame) -> str:
    return "amount" if df is not None and "amount" in df.columns else "vol"


def _has_prior_pullback(closes: np.ndarray, ma_values: np.ndarray, today: int, current_drops: int = 0, lookback: int = 20, tolerance: float = 0.01) -> bool:
    """检查在当前回踩序列之前是否已有过满足"第一次回踩"定义的 pullback。

    current_drops: 当前已检测到的连续下跌天数，用于确定当前回踩的起点。
    只扫描当前回踩起点之前的区间，避免把当前回踩自身误判为"历史回踩"。
    """
    if today < 3:
        return False

    current_pullback_start = today - current_drops + 1 if current_drops > 0 else today
    prior_end = current_pullback_start - 2
    prior_start = max(today - lookback, 0)
    if prior_end <= prior_start:
        return False

    for i in range(prior_start + 2, prior_end + 1):
        if np.isnan(ma_values[i]):
            continue
        drops = 0
        for j in range(i, max(i - 5, prior_start), -1):
            if closes[j] < closes[j - 1]:
                drops += 1
            else:
                break
        if drops >= 2:
            for d in range(max(i - drops + 1, 0), i + 1):
                if not np.isnan(ma_values[d]) and ma_values[d] > 0 and abs(closes[d] - ma_values[d]) / ma_values[d] <= tolerance:
                    return True
    return False
