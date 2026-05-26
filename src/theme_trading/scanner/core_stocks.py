"""核心强势股筛选。"""

import pandas as pd

from theme_trading.data.market_data import fetch_daily, fetch_daily_basic, fetch_ths_member


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
