"""核心强势股筛选。"""

import numpy as np
import pandas as pd

from theme_trading.data.market_data import fetch_daily, fetch_daily_basic, fetch_stock_basic, fetch_ths_member

from .constants import (
    CORE_MARKET_AMOUNT_TOP_N,
    CORE_MIN_CONDITIONS,
    CORE_RECENT_DAYS,
    CORE_SECTOR_AMOUNT_TOP_N,
    CORE_TOP_PCTILE,
    MIN_AVG_AMOUNT,
    MIN_CIRC_MV,
    MIN_TURNOVER_RATE,
)
from .utils import _is_above_ma_stack, _ma, _n_days_ago, _rank_map, _top_percent_threshold


def _load_sector_members(sector_codes: list[str] | None) -> tuple[set, dict, dict]:
    sector_stocks = set()
    stock_sector = {}
    sector_members = {}
    if not sector_codes:
        return sector_stocks, stock_sector, sector_members

    for code in sector_codes:
        members = fetch_ths_member(code)
        if members is None or len(members) == 0 or "con_code" not in members.columns:
            continue
        codes = set(members["con_code"].tolist())
        sector_members[code] = codes
        sector_stocks.update(codes)
        for ts_code in codes:
            stock_sector.setdefault(ts_code, code)
    return sector_stocks, stock_sector, sector_members


def _merge_basic(all_daily: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    basic = fetch_daily_basic(trade_date=trade_date)
    if basic is not None and len(basic) > 0:
        cols = [col for col in ["ts_code", "turnover_rate", "circ_mv"] if col in basic.columns]
        all_daily = all_daily.merge(basic[cols], on="ts_code", how="left")

    stock_basic = fetch_stock_basic()
    if stock_basic is not None and len(stock_basic) > 0:
        cols = [col for col in ["ts_code", "name"] if col in stock_basic.columns]
        all_daily = all_daily.merge(stock_basic[cols], on="ts_code", how="left")
    return all_daily


def _recent_history(trade_date: str) -> pd.DataFrame | None:
    start = _n_days_ago(trade_date, 45)
    hist = fetch_daily(start_date=start, end_date=trade_date)
    if hist is None or len(hist) == 0:
        return None
    return hist.sort_values(["ts_code", "trade_date"]).copy()


def _stock_technical(ts_code: str, hist: pd.DataFrame | None) -> dict:
    if hist is None:
        return {"above_ma_stack_or_20d_high": False, "manual_check": "个股历史数据缺失，技术强势需人工确认"}
    stock_hist = hist[hist["ts_code"] == ts_code].sort_values("trade_date")
    if len(stock_hist) < 20:
        return {"above_ma_stack_or_20d_high": False, "manual_check": "个股历史数据不足，技术强势需人工确认"}

    closes = stock_hist["close"].astype(float).values
    highs = stock_hist["high"].astype(float).values
    ma5 = _ma(closes, 5)
    ma10 = _ma(closes, 10)
    ma20 = _ma(closes, 20)
    close = float(closes[-1])
    high_20 = float(np.max(highs[-21:-1])) if len(highs) >= 21 else float(np.max(highs[:-1]))
    above_ma_stack = _is_above_ma_stack(close, float(ma5[-1]), float(ma10[-1]), float(ma20[-1]))
    breakout_20d_high = close > high_20
    return {
        "above_ma_stack_or_20d_high": bool(above_ma_stack or breakout_20d_high),
        "above_ma_stack": bool(above_ma_stack),
        "breakout_20d_high": bool(breakout_20d_high),
        "ma5": float(ma5[-1]) if not np.isnan(ma5[-1]) else None,
        "ma10": float(ma10[-1]) if not np.isnan(ma10[-1]) else None,
        "ma20": float(ma20[-1]) if not np.isnan(ma20[-1]) else None,
        "high_20": high_20,
    }


def _sector_ranks(all_daily: pd.DataFrame, sector_members: dict) -> dict:
    ranks = {}
    if not sector_members or "amount" not in all_daily.columns:
        return ranks
    for sector_code, members in sector_members.items():
        sector_daily = all_daily[all_daily["ts_code"].isin(members)].copy()
        if sector_daily.empty:
            continue
        sector_daily["sector_amount_rank"] = sector_daily["amount"].astype(float).rank(ascending=False, method="min").astype(int)
        for _, row in sector_daily.iterrows():
            ranks[(sector_code, row["ts_code"])] = int(row["sector_amount_rank"])
    return ranks


def _top_20pct_days(ts_code: str, sector_code: str | None, hist: pd.DataFrame | None, sector_members: dict) -> int | None:
    if hist is None or not sector_code or sector_code not in sector_members:
        return None
    sector_hist = hist[hist["ts_code"].isin(sector_members[sector_code])].copy()
    if sector_hist.empty or "pct_chg" not in sector_hist.columns:
        return None

    count = 0
    for _, day_df in sector_hist.groupby("trade_date"):
        if ts_code not in set(day_df["ts_code"]):
            continue
        threshold = _top_percent_threshold(len(day_df), CORE_TOP_PCTILE)
        day_df = day_df.copy()
        day_df["pct_rank"] = day_df["pct_chg"].astype(float).rank(ascending=False, method="min")
        row = day_df[day_df["ts_code"] == ts_code].iloc[0]
        if int(row["pct_rank"]) <= threshold:
            count += 1
    return count


def _relative_strength(ts_code: str, sector_code: str | None, hist: pd.DataFrame | None, sector_members: dict) -> bool | None:
    if hist is None or not sector_code or sector_code not in sector_members:
        return None
    sector_hist = hist[hist["ts_code"].isin(sector_members[sector_code])].copy()
    stock_hist = hist[hist["ts_code"] == ts_code].copy()
    if sector_hist.empty or stock_hist.empty:
        return None

    recent_sector = sector_hist.groupby("trade_date")["pct_chg"].mean().tail(CORE_RECENT_DAYS)
    recent_stock = stock_hist.set_index("trade_date")["pct_chg"].astype(float).reindex(recent_sector.index)
    if recent_stock.isna().all():
        return None

    divergence_days = recent_sector[recent_sector < 0].index
    repair_days = recent_sector[recent_sector > 0].index
    defensive = True if len(divergence_days) == 0 else bool((recent_stock.loc[divergence_days] >= recent_sector.loc[divergence_days]).all())
    leading_repair = True if len(repair_days) == 0 else bool((recent_stock.loc[repair_days] >= recent_sector.loc[repair_days]).any())
    return defensive and leading_repair


def _avg_amount(ts_code: str, hist: pd.DataFrame | None, fallback: float) -> float:
    if hist is None or "amount" not in hist.columns:
        return fallback
    stock_hist = hist[hist["ts_code"] == ts_code].sort_values("trade_date").tail(CORE_RECENT_DAYS)
    if stock_hist.empty:
        return fallback
    return float(stock_hist["amount"].astype(float).mean())


def filter_core_stocks(trade_date: str, sector_codes: list[str] = None) -> dict:
    """在确认主线板块中筛选核心强势股。"""
    result = {
        "ok": True,
        "candidates": [],
        "confirmed_core_stocks": [],
        "watch_core_stocks": [],
        "human_judgment": [],
        "data_warnings": [],
    }

    all_daily = fetch_daily(trade_date=trade_date)
    if all_daily is None or len(all_daily) == 0:
        result["ok"] = False
        result["human_judgment"].append("当日无个股行情数据")
        return result

    all_daily = _merge_basic(all_daily.copy(), trade_date)
    sector_stocks, stock_sector, sector_members = _load_sector_members(sector_codes)
    hist = _recent_history(trade_date)
    if hist is None:
        result["data_warnings"].append("近 5 日历史行情缺失，部分核心股条件降级为人工确认")

    all_daily["amount"] = all_daily["amount"].astype(float)
    all_daily["amount_rank"] = all_daily["amount"].rank(ascending=False, method="min").astype(int)
    all_daily["pct_chg_rank"] = all_daily["pct_chg"].astype(float).rank(ascending=False, method="min").astype(int)
    amount_rank_map = _rank_map(all_daily, "amount", ascending=False)
    sector_amount_ranks = _sector_ranks(all_daily, sector_members)

    if sector_stocks:
        universe = all_daily[all_daily["ts_code"].isin(sector_stocks)].copy()
    else:
        universe = all_daily.copy()
        result["data_warnings"].append("未传入确认主线板块，核心股筛选退化为全市场观察")

    if "name" in universe.columns:
        universe = universe[~universe["name"].astype(str).str.contains(r"ST|\*ST", na=False)]
    else:
        result["data_warnings"].append("股票名称缺失，ST 过滤需人工确认")

    for _, row in universe.sort_values("amount", ascending=False).iterrows():
        ts_code = row["ts_code"]
        sector_code = stock_sector.get(ts_code)
        sector_amount_rank = sector_amount_ranks.get((sector_code, ts_code)) if sector_code else None
        amount_rank = amount_rank_map.get(ts_code, int(row["amount_rank"]))
        avg_amount = _avg_amount(ts_code, hist, float(row["amount"]))
        turnover_rate = float(row.get("turnover_rate", 0)) if pd.notna(row.get("turnover_rate")) else None
        circ_mv = float(row.get("circ_mv", 0)) if pd.notna(row.get("circ_mv")) else None

        liquidity_ok = avg_amount >= MIN_AVG_AMOUNT
        liquidity_ok = liquidity_ok and (turnover_rate is None or turnover_rate >= MIN_TURNOVER_RATE)
        liquidity_ok = liquidity_ok and (circ_mv is None or circ_mv >= MIN_CIRC_MV)
        if not liquidity_ok:
            continue

        top_20pct_days = _top_20pct_days(ts_code, sector_code, hist, sector_members)
        relative_strength = _relative_strength(ts_code, sector_code, hist, sector_members)
        technical = _stock_technical(ts_code, hist)
        manual_checks = ["是否真正带动同板块个股需人工结合分时和板块扩散确认"]
        if top_20pct_days is None:
            manual_checks.append("近 5 日板块内涨幅前 20% 数据不足，需人工确认")
        if relative_strength is None:
            manual_checks.append("板块分歧抗跌/修复先反弹需人工确认")
        if technical.get("manual_check"):
            manual_checks.append(technical["manual_check"])

        amount_condition = amount_rank <= CORE_MARKET_AMOUNT_TOP_N or (
            sector_amount_rank is not None and sector_amount_rank <= CORE_SECTOR_AMOUNT_TOP_N
        )
        recent_rank_condition = top_20pct_days is not None and top_20pct_days >= 2
        relative_condition = relative_strength is True
        technical_condition = technical.get("above_ma_stack_or_20d_high") is True

        conditions = {
            "amount_rank_core": amount_condition,
            "recent_sector_top_20pct": recent_rank_condition,
            "relative_strength": relative_condition,
            "technical_strength": technical_condition,
            "sector_leader_effect": False,
        }
        condition_count = sum(1 for passed in conditions.values() if passed)
        if condition_count >= CORE_MIN_CONDITIONS:
            status = "confirmed_core"
        elif condition_count == CORE_MIN_CONDITIONS - 1:
            status = "watch_core"
        else:
            continue

        item = {
            "ts_code": ts_code,
            "name": row.get("name"),
            "sector_code": sector_code,
            "pct_chg": round(float(row["pct_chg"]), 2),
            "amount": float(row["amount"]),
            "avg_amount_5d": round(avg_amount, 2),
            "amount_rank": int(amount_rank),
            "sector_amount_rank": int(sector_amount_rank) if sector_amount_rank is not None else None,
            "turnover_rate": round(turnover_rate, 2) if turnover_rate is not None else None,
            "circ_mv": circ_mv,
            "top_20pct_days": top_20pct_days,
            "conditions": conditions,
            "condition_count": condition_count,
            "missing_conditions": [key for key, passed in conditions.items() if not passed],
            "manual_checks": manual_checks,
            "technical": technical,
            "status": status,
        }
        if status == "confirmed_core":
            result["confirmed_core_stocks"].append(item)
        else:
            result["watch_core_stocks"].append(item)

    result["confirmed_core_stocks"].sort(key=lambda x: (x["condition_count"], -x["amount_rank"]), reverse=True)
    result["watch_core_stocks"].sort(key=lambda x: (x["condition_count"], -x["amount_rank"]), reverse=True)
    result["candidates"] = result["confirmed_core_stocks"][:20]

    if not result["confirmed_core_stocks"]:
        result["ok"] = False
        if result["watch_core_stocks"]:
            result["human_judgment"].append("仅筛选出观察核心股，未满足至少 3 条核心强势股条件")
        else:
            result["human_judgment"].append("未筛选出确认核心强势股")
    else:
        result["human_judgment"].append(
            f"筛选出 {len(result['confirmed_core_stocks'])} 只确认核心股，带动性仍需人工确认"
        )

    return result
