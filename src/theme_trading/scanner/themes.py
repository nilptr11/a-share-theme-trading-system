"""主线识别。"""

import pandas as pd

from theme_trading.data.market_data import fetch_daily, fetch_index_daily, fetch_limit_list, fetch_ths_daily, fetch_ths_index, fetch_ths_member

from .constants import (
    THEME_LADDER_MIN,
    THEME_LIMIT_UP_MIN,
    THEME_MARKET_AMOUNT_TOP_N,
    THEME_MIN_CONDITIONS,
    THEME_SECTOR_AMOUNT_TOP_N,
    THEME_STRONG_DAYS,
    THEME_VOLUME_DAYS,
    THEME_VOLUME_RATIO,
)
from .utils import _amount_col, _n_days_ago, _rank_map, _recent_all_ratio


def _benchmark_map(trade_date: str, start_date: str) -> dict:
    sh_hist = fetch_index_daily("000001.SH", start_date=start_date, end_date=trade_date)
    if sh_hist is None:
        return {}
    return {row["trade_date"]: float(row.get("pct_chg", 0)) for _, row in sh_hist.iterrows()}


def _limit_stats(trade_date: str) -> tuple[set, dict, list[str]]:
    warnings = []
    limit_df = fetch_limit_list(trade_date)
    if limit_df is None or len(limit_df) == 0:
        return set(), {}, ["涨停/连板数据缺失，主线高度条件需人工确认"]

    limit_col = "limit" if "limit" in limit_df.columns else "limit_type" if "limit_type" in limit_df.columns else None
    if limit_col is None:
        return set(), {}, ["涨跌停字段口径无法确认，主线高度条件需人工确认"]

    up_codes = set(limit_df[limit_df[limit_col].astype(str) == "U"]["ts_code"].tolist())
    ladder_map = {}
    if "limit_times" in limit_df.columns:
        ladder_map = dict(zip(limit_df["ts_code"], limit_df["limit_times"].fillna(0).astype(float)))
    else:
        warnings.append("连板高度字段缺失，3 连板以上高度股需人工确认")
    return up_codes, ladder_map, warnings


def _sector_members(code: str) -> set:
    members = fetch_ths_member(code)
    if members is None or len(members) == 0 or "con_code" not in members.columns:
        return set()
    return set(members["con_code"].tolist())


def _sector_core_amount_condition(members: set, all_daily: pd.DataFrame | None, amount_rank_map: dict) -> tuple[bool, list[dict]]:
    if not members or all_daily is None or all_daily.empty or "amount" not in all_daily.columns:
        return False, []

    sector_daily = all_daily[all_daily["ts_code"].isin(members)].copy()
    if sector_daily.empty:
        return False, []

    sector_daily["amount"] = sector_daily["amount"].astype(float)
    sector_daily["sector_amount_rank"] = sector_daily["amount"].rank(ascending=False, method="min").astype(int)
    sector_daily["amount_rank"] = sector_daily["ts_code"].map(amount_rank_map)
    top = sector_daily.sort_values("amount", ascending=False).head(THEME_SECTOR_AMOUNT_TOP_N)
    condition = bool(
        ((sector_daily["sector_amount_rank"] <= THEME_SECTOR_AMOUNT_TOP_N) |
         (sector_daily["amount_rank"] <= THEME_MARKET_AMOUNT_TOP_N)).any()
    )
    records = []
    for _, row in top.iterrows():
        records.append({
            "ts_code": row["ts_code"],
            "amount": float(row["amount"]),
            "amount_rank": int(row["amount_rank"]) if pd.notna(row["amount_rank"]) else None,
            "sector_amount_rank": int(row["sector_amount_rank"]),
            "pct_chg": round(float(row.get("pct_chg", 0)), 2),
        })
    return condition, records


def _divergence_return_condition(hist: pd.DataFrame, benchmark: dict) -> bool | None:
    if hist is None or len(hist) < 4:
        return None
    recent = hist.sort_values("trade_date").tail(5).copy()
    latest = recent.iloc[-1]
    latest_benchmark = benchmark.get(latest["trade_date"], 0)
    had_divergence = any(float(row["pct_change"]) < benchmark.get(row["trade_date"], 0) for _, row in recent.iloc[:-1].iterrows())
    latest_return = float(latest["pct_change"]) > latest_benchmark
    return bool(had_divergence and latest_return)


def find_main_themes(trade_date: str, min_days: int = THEME_STRONG_DAYS, top_n: int = 15) -> dict:
    """扫描满足主线条件的板块。"""
    result = {
        "ok": True,
        "candidates": [],
        "confirmed_themes": [],
        "watch_themes": [],
        "top_sectors": [],
        "human_judgment": [],
        "data_warnings": [],
    }

    sector_day = fetch_ths_daily(trade_date=trade_date)
    if sector_day is None or len(sector_day) == 0:
        result["ok"] = False
        result["human_judgment"].append("当日无板块数据")
        return result

    sh_idx = fetch_index_daily("000001.SH", trade_date=trade_date)
    benchmark_pct = 0.0
    if sh_idx is not None and len(sh_idx) > 0:
        benchmark_pct = float(sh_idx.iloc[0].get("pct_chg", 0))

    sector_day = sector_day.copy()
    sector_day["pct_change_f"] = sector_day["pct_change"].astype(float)
    stronger_today = sector_day[sector_day["pct_change_f"] > benchmark_pct]
    candidates_today = stronger_today.nlargest(top_n, "pct_change_f")

    ths_idx = fetch_ths_index()
    name_map = dict(zip(ths_idx["ts_code"], ths_idx["name"])) if ths_idx is not None and len(ths_idx) > 0 else {}

    hist_start = _n_days_ago(trade_date, 15)
    sh_daily_map = _benchmark_map(trade_date, hist_start)
    up_codes, ladder_map, limit_warnings = _limit_stats(trade_date)
    result["data_warnings"].extend(limit_warnings)

    all_daily = fetch_daily(trade_date=trade_date)
    amount_rank_map = _rank_map(all_daily, "amount", ascending=False) if all_daily is not None else {}

    for _, row in candidates_today.iterrows():
        code = row["ts_code"]
        name = name_map.get(code, code)
        pct = float(row["pct_change"])
        data_warnings = []
        manual_checks = []

        hist = fetch_ths_daily(ts_code=code, start_date=hist_start, end_date=trade_date)
        if hist is None or len(hist) < 5:
            continue
        hist = hist.sort_values("trade_date").copy()

        amount_col = _amount_col(hist)
        if amount_col != "amount":
            data_warnings.append("ths_daily.amount 字段缺失，暂用 vol 代理板块资金强度")

        latest_amount = float(hist[amount_col].astype(float).iloc[-1])
        avg_5_amount = float(hist[amount_col].astype(float).tail(5).mean())
        amount_ratio = latest_amount / avg_5_amount if avg_5_amount > 0 else 1.0

        # 成交额是否创近 5 日新高（逐一比较，不用均值）
        recent_5_amounts = hist[amount_col].astype(float).tail(6).values
        amount_5d_high = bool(len(recent_5_amounts) >= 6 and latest_amount > max(recent_5_amounts[:-1]))

        consecutive = 0
        for _, hrow in hist.iloc[::-1].iterrows():
            h_pct = float(hrow["pct_change"])
            day_benchmark = sh_daily_map.get(hrow["trade_date"], 0)
            if h_pct > day_benchmark:
                consecutive += 1
            else:
                break

        amount_expand_2d = _recent_all_ratio(
            hist,
            amount_col,
            window=5,
            ratio=THEME_VOLUME_RATIO,
            days=THEME_VOLUME_DAYS,
            above=True,
        )

        members = _sector_members(code)
        up_in_sector = len(up_codes & members) if members else 0
        ladder_height = 0
        if members and ladder_map:
            ladder_height = int(max([ladder_map.get(ts_code, 0) for ts_code in members] or [0]))
        elif not ladder_map:
            manual_checks.append("连板高度需人工确认")

        core_amount_ok, top_amount_members = _sector_core_amount_condition(members, all_daily, amount_rank_map)
        divergence_return = _divergence_return_condition(hist, sh_daily_map)
        if divergence_return is None:
            manual_checks.append("分歧后资金回流需人工确认")

        conditions = {
            "stronger_than_market_2d": consecutive >= min_days,
            "amount_expand_2d": amount_expand_2d is True,
            "limit_up_or_ladder": up_in_sector >= THEME_LIMIT_UP_MIN or ladder_height >= THEME_LADDER_MIN,
            "core_amount_rank": core_amount_ok,
            "divergence_return": divergence_return is True,
        }
        condition_count = sum(1 for passed in conditions.values() if passed)
        missing_conditions = [key for key, passed in conditions.items() if not passed]

        if condition_count >= THEME_MIN_CONDITIONS:
            status = "confirmed"
        elif condition_count == THEME_MIN_CONDITIONS - 1:
            status = "watch"
        else:
            status = "ignored"

        item = {
            "ts_code": code,
            "name": name,
            "pct_chg": round(pct, 2),
            "benchmark_pct": round(benchmark_pct, 2),
            "consecutive_days": consecutive,
            "amount_col": amount_col,
            "vol_ratio": round(amount_ratio, 2),
            "amount_ratio": round(amount_ratio, 2),
            "amount_5d_high": amount_5d_high,
            "up_in_sector": up_in_sector,
            "ladder_height": ladder_height,
            "top_amount_members": top_amount_members,
            "conditions": conditions,
            "condition_count": condition_count,
            "missing_conditions": missing_conditions,
            "manual_checks": manual_checks,
            "data_warnings": data_warnings,
            "score": condition_count,
            "status": status,
        }
        result["candidates"].append(item)
        if status == "confirmed":
            result["confirmed_themes"].append(item)
        elif status == "watch":
            result["watch_themes"].append(item)

    result["candidates"].sort(key=lambda x: (x["condition_count"], x["pct_chg"]), reverse=True)
    result["confirmed_themes"].sort(key=lambda x: (x["condition_count"], x["pct_chg"]), reverse=True)
    result["watch_themes"].sort(key=lambda x: (x["condition_count"], x["pct_chg"]), reverse=True)
    result["top_sectors"] = result["confirmed_themes"][:5] or result["watch_themes"][:5]

    if not result["confirmed_themes"]:
        result["ok"] = False
        if result["watch_themes"]:
            result["human_judgment"].append("仅发现观察主线，未满足至少 3 条主线条件 → 不交易")
        else:
            result["human_judgment"].append("未发现确认主线 → 不交易")
    else:
        names = [f"{c['name']}({c['condition_count']}/5)" for c in result["confirmed_themes"][:5]]
        result["human_judgment"].append(f"确认主线: {', '.join(names)}，题材级别仍需人工确认")

    return result
