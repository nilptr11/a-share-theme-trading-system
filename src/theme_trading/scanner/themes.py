"""主线识别。"""

from theme_trading.data.market_data import fetch_index_daily, fetch_limit_list, fetch_ths_daily, fetch_ths_index, fetch_ths_member

from .utils import _n_days_ago


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
