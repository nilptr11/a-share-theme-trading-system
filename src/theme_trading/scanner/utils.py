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
