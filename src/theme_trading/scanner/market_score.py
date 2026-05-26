"""市场评分。"""

import numpy as np

from theme_trading.data.market_data import fetch_index_daily, fetch_limit_cpt_list, fetch_limit_list

from .constants import MA_WINDOW, SCORE_MID
from .utils import _ma, _n_days_ago


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
