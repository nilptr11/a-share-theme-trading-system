"""市场扫描器 — 量化筛选逻辑

对应 trading-reference.md 的每日执行流程:
    1. 市场评分 → compute_market_score()
    2. 主线识别 → find_main_themes()
    3. 核心强势股筛选 → filter_core_stocks()
    4. 买点扫描 → scan_buy_points()

所有函数返回 dict: {ok, data, diagnostics, human_judgment}
ok=False 表示前置条件不满足，不应继续后续步骤。
human_judgment 列出需要人工判断的项。
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timedelta

from market_data import (
    fetch_index_daily, fetch_limit_list, fetch_stk_limit, fetch_limit_cpt_list,
    fetch_ths_index, fetch_ths_daily, fetch_ths_member,
    fetch_daily, fetch_daily_basic, fetch_stock_basic, fetch_moneyflow,
    fetch_trade_cal,
)
from tushare_proxy import clear_cache

# ── 常量 ───────────────────────────────────────────────────────────

# 主要指数
INDEX_CODES = {
    "上证综指": "000001.SH",
    "深证成指": "399001.SZ",
    "创业板指": "399006.SZ",
    "科创50":   "000688.SH",
    "沪深300":  "000300.SH",
}

# 计算均线所需的最少交易日
MA_WINDOW = 25

# 市场评分阈值
SCORE_BULL = 7   # ≥7 可交易 1% 风险预算
SCORE_MID  = 6   # =6 轻仓 0.5% 风险预算
SCORE_BEAR = 0   # <6 不开仓


# ── 工具函数 ───────────────────────────────────────────────────────

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


# ── 1. 市场评分 ───────────────────────────────────────────────────

def compute_market_score(trade_date: str) -> dict:
    """计算市场评分 (0-10) 并检查硬规则

    返回:
        { score, index_score(0-2), volume_score(0-2),
          sentiment_score(0-3), theme_score(0-3),
          hard_rules: {passed, violations[]},
          details: {...},
          human_judgment: [...] }
    """
    result = {
        "ok": True,
        "score": 0,
        "index_score": 0,
        "volume_score": 0,
        "sentiment_score": 0,
        "theme_score": 0,
        "hard_rules": {"passed": True, "violations": []},
        "details": {},
        "human_judgment": [],
    }

    # ── 1a. 指数维度 (0-2) ──
    sh_idx = fetch_index_daily("000001.SH", start_date=_n_days_ago(trade_date, MA_WINDOW + 5),
                               end_date=trade_date)
    if sh_idx is None or len(sh_idx) < 20:
        result["human_judgment"].append("指数数据不足，无法计算 MA20")
    else:
        sh_idx = sh_idx.sort_values("trade_date")
        closes = sh_idx["close"].values
        ma20 = _ma(closes, 20)
        latest_close = closes[-1]
        latest_ma20 = ma20[-1]
        prev_ma20 = ma20[-2] if len(ma20) >= 2 else None

        above_ma = latest_close > latest_ma20 if not np.isnan(latest_ma20) else None
        ma_up = latest_ma20 > prev_ma20 if (prev_ma20 is not None and
                                              not np.isnan(latest_ma20) and
                                              not np.isnan(prev_ma20)) else None

        if above_ma and ma_up:
            result["index_score"] = 2
        elif above_ma and not ma_up:
            result["index_score"] = 1
        else:
            result["index_score"] = 0

        result["details"]["sh_close"] = float(latest_close)
        result["details"]["sh_ma20"] = float(latest_ma20) if not np.isnan(latest_ma20) else None
        result["details"]["sh_above_ma20"] = above_ma
        result["details"]["sh_ma20_up"] = ma_up

    # ── 1b. 成交量维度 (0-2) ──
    # 用上证+深证成交额之和近似全市场
    sz_idx = fetch_index_daily("399001.SZ", start_date=_n_days_ago(trade_date, 10),
                               end_date=trade_date)
    if sh_idx is not None and sz_idx is not None:
        sh_amt = sh_idx.sort_values("trade_date")[["trade_date", "amount"]].copy()
        sz_amt = sz_idx.sort_values("trade_date")[["trade_date", "amount"]].copy()
        merged = sh_amt.merge(sz_amt, on="trade_date", suffixes=("_sh", "_sz"))
        merged["total_amount"] = merged["amount_sh"] + merged["amount_sz"]

        if len(merged) >= 5:
            latest_amt = merged["total_amount"].iloc[-1]
            avg_5d = merged["total_amount"].tail(5).mean()
            ratio = latest_amt / avg_5d if avg_5d > 0 else 1.0

            if ratio >= 1.2:
                result["volume_score"] = 2
            elif ratio >= 0.85:
                result["volume_score"] = 1
            else:
                result["volume_score"] = 0

            result["details"]["total_amount"] = float(latest_amt)
            result["details"]["amount_5d_avg"] = float(avg_5d)
            result["details"]["amount_ratio"] = float(ratio)

            # 硬规则: 连续 3 日缩量
            if len(merged) >= 3:
                last_3 = merged["total_amount"].tail(3).values
                avg_5d_val = avg_5d
                if all(a < avg_5d_val * 0.85 for a in last_3):
                    result["hard_rules"]["passed"] = False
                    result["hard_rules"]["violations"].append(
                        "连续 3 日全市场成交额 < 5 日均值 0.85 倍 → 空仓")

    # ── 1c. 情绪维度 (0-3) ──
    limit_df = fetch_limit_list(trade_date)
    limit_cpt = fetch_limit_cpt_list(trade_date)

    up_count = down_count = zt_count = ladders = 0
    limit_data_available = False

    if limit_df is not None and len(limit_df) > 0:
        limit_data_available = True
        up_count = len(limit_df[limit_df["limit"] == "U"])
        down_count = len(limit_df[limit_df["limit"] == "D"])
        zt_count = len(limit_df[limit_df["limit"] == "Z"])
        total = len(limit_df)
        zt_rate = zt_count / total if total > 0 else 0

        result["details"]["limit_up"] = up_count
        result["details"]["limit_down"] = down_count
        result["details"]["zha_ban"] = zt_count
        result["details"]["zha_ban_rate"] = round(zt_rate, 3)

        # 连板高度
        if "limit_times" in limit_df.columns:
            ladders = int(limit_df["limit_times"].max())

        # 硬规则: 炸板率 ≥ 40%
        if zt_rate >= 0.4:
            result["hard_rules"]["passed"] = False
            result["hard_rules"]["violations"].append(
                f"炸板率 {zt_rate:.0%} ≥ 40% → 不做追涨，只观察")

    if not limit_data_available:
        # limit_list 数据缺失时，情绪维度不评分，标记为需人工判断
        result["sentiment_score"] = 0
        result["details"]["sentiment_hints"] = ["涨跌停数据缺失"]
        result["human_judgment"].append("情绪建议: 涨跌停数据缺失，无法自动评分，请人工判断市场情绪")
    else:
        # 情绪综合评分
        sentiment_hints = []
        if up_count >= 80:
            sentiment_hints.append("涨停多")
        if down_count <= 10:
            sentiment_hints.append("跌停少")
        if zt_count <= up_count * 0.3:
            sentiment_hints.append("炸板低")
        if ladders >= 4:
            sentiment_hints.append(f"连板高度 {ladders} 板")

        if len(sentiment_hints) >= 4:
            result["sentiment_score"] = 3
        elif len(sentiment_hints) >= 2:
            result["sentiment_score"] = 2
        elif len(sentiment_hints) >= 1:
            result["sentiment_score"] = 1
        else:
            result["sentiment_score"] = 0

        result["details"]["sentiment_hints"] = sentiment_hints
        result["human_judgment"].append(
            f"情绪建议 {result['sentiment_score']}/3 分，请人工确认 "
            f"({', '.join(sentiment_hints) if sentiment_hints else '无明显积极信号'})")

    # ── 1d. 主线维度 (0-3) ──
    if limit_cpt is not None and len(limit_cpt) > 0:
        # 看最强板块的持续天数
        top_sector = limit_cpt.iloc[0]
        days = int(top_sector.get("days", 0))
        result["details"]["top_sector"] = top_sector.get("name", "")
        result["details"]["top_sector_days"] = days

        if days >= 4:
            result["theme_score"] = 3
        elif days >= 2:
            result["theme_score"] = 2
        else:
            result["theme_score"] = 1
    else:
        result["theme_score"] = 0

    result["human_judgment"].append(f"主线建议 {result['theme_score']}/3 分，请结合资讯判断是否清晰持续")

    # ── 汇总 ──
    result["score"] = (result["index_score"] + result["volume_score"] +
                       result["sentiment_score"] + result["theme_score"])

    # 硬规则: 评分 < 6
    if result["score"] < SCORE_MID:
        result["hard_rules"]["passed"] = False
        result["hard_rules"]["violations"].append(
            f"市场评分 {result['score']} < 6 → 不开新仓")

    result["ok"] = result["hard_rules"]["passed"]
    return result


def format_score_report(result: dict) -> str:
    """格式化市场评分报告"""
    lines = [
        "=" * 60,
        f"市场评分: {result['score']}/10  {'可交易' if result['ok'] else '不开仓'}",
        f"  指数 {result['index_score']}/2 | 成交量 {result['volume_score']}/2 | "
        f"情绪 {result['sentiment_score']}/3 | 主线 {result['theme_score']}/3",
    ]
    d = result.get("details", {})
    if "sh_close" in d:
        lines.append(f"  上证: {d['sh_close']:.0f}  MA20: {d.get('sh_ma20', 'N/A')}"
                     f"  {'站上↑' if d.get('sh_above_ma20') else '跌破↓'}")
    if "amount_ratio" in d:
        lines.append(f"  成交额/5日均值: {d['amount_ratio']:.2f}")
    if "limit_up" in d:
        lines.append(f"  涨停: {d['limit_up']}  跌停: {d['limit_down']}  "
                     f"炸板: {d['zha_ban']}  炸板率: {d.get('zha_ban_rate', 0):.1%}")
    if result["hard_rules"]["violations"]:
        lines.append("  硬规则触发:")
        for v in result["hard_rules"]["violations"]:
            lines.append(f"    ⚠ {v}")
    if result["human_judgment"]:
        lines.append("  需人工确认:")
        for h in result["human_judgment"]:
            lines.append(f"    ? {h}")
    lines.append("=" * 60)
    return "\n".join(lines)


# ── 2. 主线识别 ───────────────────────────────────────────────────

def find_main_themes(trade_date: str, min_days: int = 2, top_n: int = 15) -> dict:
    """扫描满足主线条件的板块

    策略: 先从当日全量板块中筛选强于市场的，再对前 top_n 个单独拉历史数据评分。
    这避免了 ths_daily 单次 3000 行限制导致历史数据不足的问题。

    min_days: 板块需连续多少天强于市场（默认 2）
    返回:
        { candidates: [{ts_code, name, pct_chg, vol_ratio, score, ...}],
          top_sectors: [...],
          human_judgment: [...] }
    """
    result = {"ok": True, "candidates": [], "top_sectors": [], "human_judgment": []}

    # Step 1: 获取当日所有板块行情
    sector_day = fetch_ths_daily(trade_date=trade_date)
    if sector_day is None or len(sector_day) == 0:
        result["human_judgment"].append("当日无板块数据")
        return result

    # Step 2: 获取当日上证涨幅作为基准
    sh_idx = fetch_index_daily("000001.SH", trade_date=trade_date)
    benchmark_pct = 0
    if sh_idx is not None and len(sh_idx) > 0:
        benchmark_pct = float(sh_idx.iloc[0]["pct_chg"])

    # Step 3: 第一轮筛选 — 当日强于市场的板块，取涨幅前 top_n
    sector_day["pct_change_f"] = sector_day["pct_change"].astype(float)
    stronger_today = sector_day[sector_day["pct_change_f"] > benchmark_pct]
    candidates_today = stronger_today.nlargest(top_n, "pct_change_f")

    # 同时获取板块名称映射
    ths_idx = fetch_ths_index()
    name_map = {}
    if ths_idx is not None:
        name_map = dict(zip(ths_idx["ts_code"], ths_idx["name"]))

    # Step 4: 获取同期的指数日线用于逐日对比
    hist_start = _n_days_ago(trade_date, 10)
    sh_hist = fetch_index_daily("000001.SH", start_date=hist_start, end_date=trade_date)
    sh_daily_map = {}
    if sh_hist is not None:
        for _, r in sh_hist.iterrows():
            sh_daily_map[r["trade_date"]] = float(r["pct_chg"])

    # Step 5: 对每个候选板块拉历史数据并评分
    for _, row in candidates_today.iterrows():
        code = row["ts_code"]
        name = name_map.get(code, code)
        pct = float(row["pct_change"])

        # 拉该板块近 10 日数据
        hist = fetch_ths_daily(ts_code=code, start_date=hist_start, end_date=trade_date)
        if hist is None or len(hist) < 5:
            continue
        hist = hist.sort_values("trade_date")

        # 成交量 vs 5日均量
        vols = hist["vol"].astype(float)
        latest_vol = float(vols.iloc[-1])
        avg_5_vol = float(vols.tail(5).mean())
        vol_ratio = latest_vol / avg_5_vol if avg_5_vol > 0 else 1.0

        # 连续强于市场天数（逐日对比当天的大盘涨幅）
        consecutive = 0
        for _, hrow in hist.iloc[::-1].iterrows():
            h_date = hrow["trade_date"]
            h_pct = float(hrow["pct_change"])
            day_benchmark = sh_daily_map.get(h_date, 0)
            if h_pct > day_benchmark:
                consecutive += 1
            else:
                break

        # 板块内涨停数（通过 limit_list 统计）
        up_in_sector = 0
        members = fetch_ths_member(code)
        if members is not None and len(members) > 0:
            member_codes = set(members["con_code"].tolist())
            limit_df = fetch_limit_list(trade_date, limit_type="U")
            if limit_df is not None and len(limit_df) > 0:
                up_in_sector = len(limit_df[limit_df["ts_code"].isin(member_codes)])

        # 评分
        score = 0
        score += 1  # stronger today (已通过第一轮筛选)
        if consecutive >= min_days:
            score += 2
        if vol_ratio >= 1.3:
            score += 2

        result["candidates"].append({
            "ts_code": code,
            "name": name,
            "pct_chg": round(pct, 2),
            "benchmark_pct": round(benchmark_pct, 2),
            "consecutive_days": consecutive,
            "vol_ratio": round(vol_ratio, 2),
            "up_in_sector": up_in_sector,
            "score": score,
        })

    # 按评分排序
    result["candidates"].sort(key=lambda x: (x["score"], x["pct_chg"]), reverse=True)
    result["top_sectors"] = result["candidates"][:5]

    if not result["candidates"]:
        result["ok"] = False
        result["human_judgment"].append("未发现符合主线条件的板块 → 不交易")
    else:
        names = [f"{c['name']}({c['score']}分)" for c in result["top_sectors"]]
        result["human_judgment"].append(f"候选主线: {', '.join(names)}，请结合资讯确认题材级别和持续性")

    return result


# ── 3. 核心强势股筛选 ──────────────────────────────────────────────

def filter_core_stocks(trade_date: str, sector_codes: list[str] = None) -> dict:
    """在候选主线板块中筛选核心强势股

    条件: 成交额排名 + 涨幅排名 + 流动性底线
    """
    result = {"ok": True, "candidates": [], "human_judgment": []}

    # 获取全市场日线
    all_daily = fetch_daily(trade_date=trade_date)
    if all_daily is None or len(all_daily) == 0:
        result["human_judgment"].append("当日无个股行情数据")
        return result

    # 获取流动性指标
    basic = fetch_daily_basic(trade_date=trade_date)
    if basic is not None:
        all_daily = all_daily.merge(
            basic[["ts_code", "turnover_rate", "circ_mv"]],
            on="ts_code", how="left")

    # 获取板块成分股
    sector_stocks = set()
    if sector_codes:
        for code in sector_codes:
            members = fetch_ths_member(code)
            if members is not None and len(members) > 0:
                sector_stocks.update(members["con_code"].tolist())

    # 计算全市场排名
    all_daily["amount_rank"] = all_daily["amount"].rank(ascending=False)
    all_daily["pct_chg_rank"] = all_daily["pct_chg"].rank(ascending=False)

    # 流动性底线过滤
    liquidity_ok = pd.Series(True, index=all_daily.index)

    # 日均成交额 ≥ 5000万 (amount 单位是千元)
    liquidity_ok &= (all_daily["amount"] >= 50000)

    # 换手率 ≥ 2%
    if "turnover_rate" in all_daily.columns:
        liquidity_ok &= (all_daily["turnover_rate"] >= 2.0)
    else:
        # 没有换手率数据时用成交量/流通股本近似，这里先跳过
        pass

    # 流通市值 ≥ 20亿 (circ_mv 单位是万元)
    if "circ_mv" in all_daily.columns:
        liquidity_ok &= (all_daily["circ_mv"] >= 200000)

    # 限制在板块内（如果指定了板块）
    if sector_stocks:
        in_sector = all_daily["ts_code"].isin(sector_stocks)
    else:
        in_sector = pd.Series(True, index=all_daily.index)

    # 核心强势股 = 流动性达标 + 板块内 + 成交额前100 或 涨幅突出
    core_mask = liquidity_ok & in_sector & (
        (all_daily["amount_rank"] <= 100) |
        (all_daily["pct_chg_rank"] <= 200)
    )
    # 排除 ST
    if "name" in all_daily.columns:
        core_mask &= ~all_daily["name"].str.contains("ST|\\*ST", na=False)

    core = all_daily[core_mask].sort_values("amount", ascending=False)

    for _, row in core.head(20).iterrows():
        result["candidates"].append({
            "ts_code": row["ts_code"],
            "pct_chg": round(float(row["pct_chg"]), 2),
            "amount": float(row["amount"]),
            "amount_rank": int(row["amount_rank"]),
            "turnover_rate": round(float(row.get("turnover_rate", 0)), 2) if pd.notna(row.get("turnover_rate")) else None,
            "circ_mv": float(row.get("circ_mv", 0)) if pd.notna(row.get("circ_mv")) else None,
        })

    if not result["candidates"]:
        result["ok"] = False
        result["human_judgment"].append("未筛选出核心强势股")
    else:
        result["human_judgment"].append(
            f"筛选出 {len(result['candidates'])} 只候选核心股，请人工确认是否符合'带动板块'条件")

    return result


# ── 4. 买点扫描 ────────────────────────────────────────────────────

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


# ── 5. 一站式每日扫描 ──────────────────────────────────────────────

def daily_scan(
    trade_date: str,
    sector_codes: list[str] = None,
    theme_top_n: int = 15,
    include_buy_points: bool = True,
) -> dict:
    """执行完整的每日扫描流程

    返回:
        { market_score, themes, core_stocks, buy_scans, human_judgment }
    """
    clear_cache()

    report = {
        "trade_date": trade_date,
        "market_score": None,
        "themes": None,
        "core_stocks": None,
        "buy_scans": [],
        "human_judgment": [],
    }

    # Step 1: 市场评分
    score = compute_market_score(trade_date)
    report["market_score"] = score
    report["human_judgment"].extend(score.get("human_judgment", []))

    if not score["ok"]:
        report["human_judgment"].append("市场开关关闭，停止后续扫描")
        return report

    # Step 2: 主线识别
    themes = find_main_themes(trade_date, top_n=theme_top_n)
    report["themes"] = themes
    report["human_judgment"].extend(themes.get("human_judgment", []))

    if not themes["ok"]:
        report["human_judgment"].append("无主线，停止选股")
        return report

    # 自动获取候选主线的板块代码
    if sector_codes is None and themes.get("candidates"):
        sector_codes = [t["ts_code"] for t in themes["candidates"][:3]]

    # Step 3: 核心强势股筛选
    stocks = filter_core_stocks(trade_date, sector_codes)
    report["core_stocks"] = stocks
    report["human_judgment"].extend(stocks.get("human_judgment", []))

    if not stocks["ok"]:
        return report

    # Step 4: 买点扫描
    if include_buy_points:
        for stock in stocks.get("candidates", [])[:10]:
            bp = scan_buy_points(stock["ts_code"], trade_date)
            if bp.get("any_triggered"):
                report["buy_scans"].append(bp)

        if not report["buy_scans"]:
            report["human_judgment"].append("候选核心股中无买点触发")

    return report
