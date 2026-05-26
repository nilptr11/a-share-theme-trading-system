"""市场评分。"""

import numpy as np

from theme_trading.data.market_data import fetch_daily, fetch_index_daily, fetch_limit_cpt_list, fetch_limit_list

from .constants import (
    BREADTH_ICE,
    BREADTH_OVERHEAT,
    BREADTH_WEAK_UPPER,
    INDEX_DAILY_DROP_STOP,
    LIMIT_BREAK_RATE_WARN,
    MARKET_SHRINK_DAYS,
    MARKET_VOLUME_STRONG_RATIO,
    MARKET_VOLUME_WEAK_RATIO,
    MA_WINDOW,
    SCORE_MID,
    SCORE_STRONG,
)
from .utils import _ma, _n_days_ago, _recent_all_ratio


def _market_level(score: int) -> str:
    if score >= SCORE_STRONG:
        return "strong"
    if score == SCORE_MID:
        return "medium"
    return "weak"


def _trade_permission(level: str, hard_passed: bool) -> str:
    if not hard_passed or level == "weak":
        return "closed"
    if level == "medium":
        return "restricted"
    return "open"


def _limit_counts(limit_df) -> tuple[int, int, int, list[str]]:
    warnings = []
    if limit_df is None or len(limit_df) == 0:
        return 0, 0, 0, warnings

    limit_col = None
    for col in ("limit", "limit_type"):
        if col in limit_df.columns:
            limit_col = col
            break

    if limit_col is None:
        warnings.append("涨跌停字段口径无法确认，未自动计算炸板率")
        return 0, 0, 0, warnings

    values = limit_df[limit_col].astype(str)
    return int((values == "U").sum()), int((values == "D").sum()), int((values == "Z").sum()), warnings


def _breadth_state(up_count: int) -> str:
    if up_count < BREADTH_ICE:
        return "ice"
    if up_count < BREADTH_WEAK_UPPER:
        return "weak"
    if up_count <= BREADTH_OVERHEAT:
        return "normal"
    return "overheat"


def compute_market_score(trade_date: str) -> dict:
    """计算市场评分 (0-10) 并检查硬规则。

    返回:
        { score, index_score, volume_score, sentiment_score, theme_score,
          market_level, trade_permission, hard_rules, details, action_notes,
          human_judgment }
    """
    result = {
        "ok": True,
        "score": 0,
        "market_level": "weak",
        "trade_permission": "closed",
        "emotion_extreme": False,
        "index_score": 0,
        "volume_score": 0,
        "sentiment_score": 0,
        "theme_score": 0,
        "hard_rules": {"passed": True, "violations": []},
        "details": {},
        "action_notes": [],
        "human_judgment": [],
        "data_warnings": [],
    }

    sh_idx = fetch_index_daily(
        "000001.SH",
        start_date=_n_days_ago(trade_date, MA_WINDOW + 10),
        end_date=trade_date,
    )

    # ── 1a. 指数维度 (0-2) ──
    if sh_idx is None or len(sh_idx) < 20:
        result["human_judgment"].append("指数数据不足，无法计算 MA20")
    else:
        sh_idx = sh_idx.sort_values("trade_date")
        closes = sh_idx["close"].astype(float).values
        ma20 = _ma(closes, 20)
        latest = sh_idx.iloc[-1]
        latest_close = float(latest["close"])
        latest_pct = float(latest.get("pct_chg", 0))
        latest_ma20 = ma20[-1]
        prev_ma20 = ma20[-2] if len(ma20) >= 2 else None

        above_ma = latest_close > latest_ma20 if not np.isnan(latest_ma20) else None
        ma_up = latest_ma20 > prev_ma20 if (
            prev_ma20 is not None and not np.isnan(latest_ma20) and not np.isnan(prev_ma20)
        ) else None

        if above_ma and ma_up:
            result["index_score"] = 2
        elif above_ma and not ma_up:
            result["index_score"] = 1
        else:
            result["index_score"] = 0

        result["details"].update({
            "sh_close": latest_close,
            "sh_pct_chg": latest_pct,
            "sh_ma20": float(latest_ma20) if not np.isnan(latest_ma20) else None,
            "sh_above_ma20": above_ma,
            "sh_ma20_up": ma_up,
        })

        if latest_pct <= INDEX_DAILY_DROP_STOP:
            result["hard_rules"]["passed"] = False
            result["hard_rules"]["violations"].append(
                f"上证指数单日跌幅 {latest_pct:.2f}% ≤ {INDEX_DAILY_DROP_STOP:.0f}% → 停止新开仓"
            )

    # ── 1b. 成交量维度 (0-2) ──
    sz_idx = fetch_index_daily("399001.SZ", start_date=_n_days_ago(trade_date, 20), end_date=trade_date)
    if sh_idx is not None and sz_idx is not None:
        sh_amt = sh_idx.sort_values("trade_date")[["trade_date", "amount"]].copy()
        sz_amt = sz_idx.sort_values("trade_date")[["trade_date", "amount"]].copy()
        merged = sh_amt.merge(sz_amt, on="trade_date", suffixes=("_sh", "_sz"))
        merged["total_amount"] = merged["amount_sh"].astype(float) + merged["amount_sz"].astype(float)

        if len(merged) >= 5:
            latest_amt = float(merged["total_amount"].iloc[-1])
            avg_5d = float(merged["total_amount"].tail(5).mean())
            ratio = latest_amt / avg_5d if avg_5d > 0 else 1.0

            if ratio >= MARKET_VOLUME_STRONG_RATIO:
                result["volume_score"] = 2
            elif ratio >= MARKET_VOLUME_WEAK_RATIO:
                result["volume_score"] = 1
            else:
                result["volume_score"] = 0

            shrink_3d = _recent_all_ratio(
                merged,
                "total_amount",
                window=5,
                ratio=MARKET_VOLUME_WEAK_RATIO,
                days=MARKET_SHRINK_DAYS,
                above=False,
            )

            result["details"].update({
                "total_amount": latest_amt,
                "amount_5d_avg": avg_5d,
                "amount_ratio": float(ratio),
                "market_shrink_3d": shrink_3d,
            })

            if shrink_3d:
                result["hard_rules"]["passed"] = False
                result["hard_rules"]["violations"].append(
                    "连续 3 日全市场成交额 < 各自 5 日均值 0.85 倍 → 空仓"
                )

    # ── 1c. 情绪维度 (0-3) ──
    limit_df = fetch_limit_list(trade_date)
    limit_cpt = fetch_limit_cpt_list(trade_date)
    up_count, down_count, break_count, limit_warnings = _limit_counts(limit_df)
    result["data_warnings"].extend(limit_warnings)

    limit_data_available = limit_df is not None and len(limit_df) > 0 and not limit_warnings
    ladders = 0
    if limit_df is not None and len(limit_df) > 0 and "limit_times" in limit_df.columns:
        ladders = int(limit_df["limit_times"].fillna(0).astype(float).max())

    if limit_data_available:
        break_denominator = up_count + break_count
        break_rate = break_count / break_denominator if break_denominator > 0 else 0

        result["details"].update({
            "limit_up": up_count,
            "limit_down": down_count,
            "zha_ban": break_count,
            "zha_ban_rate": round(break_rate, 3),
            "ladder_height": ladders,
        })

        if break_rate >= LIMIT_BREAK_RATE_WARN:
            result["hard_rules"]["passed"] = False
            result["hard_rules"]["violations"].append(
                f"炸板率 {break_rate:.0%} ≥ 40% → 不做追涨，只观察"
            )

        sentiment_hints = []
        if up_count >= 80:
            sentiment_hints.append("涨停多")
        if down_count <= 10:
            sentiment_hints.append("跌停少")
        if break_count <= up_count * 0.3:
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
            f"({', '.join(sentiment_hints) if sentiment_hints else '无明显积极信号'})"
        )
    else:
        result["sentiment_score"] = 0
        result["details"]["sentiment_hints"] = ["涨跌停数据缺失或字段口径不明"]
        result["human_judgment"].append("情绪建议: 涨跌停数据缺失或字段口径不明，请人工判断市场情绪")

    # ── 1d. 上涨家数/情绪极端 ──
    daily_df = fetch_daily(trade_date=trade_date)
    if daily_df is not None and len(daily_df) > 0 and "pct_chg" in daily_df.columns:
        pct = daily_df["pct_chg"].astype(float)
        breadth_up = int((pct > 0).sum())
        breadth_down = int((pct < 0).sum())
        breadth_flat = int((pct == 0).sum())
        breadth_state = _breadth_state(breadth_up)
        result["details"].update({
            "breadth_up": breadth_up,
            "breadth_down": breadth_down,
            "breadth_flat": breadth_flat,
            "breadth_state": breadth_state,
        })
        if breadth_up > BREADTH_OVERHEAT:
            result["emotion_extreme"] = True
            result["action_notes"].append("上涨家数 > 3500，情绪过热：不追涨，只等分歧后的回踩确认")
        elif breadth_up < BREADTH_ICE:
            result["action_notes"].append("上涨家数 < 800，情绪冰点：谨慎观察，优先等待修复确认")
    else:
        result["data_warnings"].append("全市场日线数据缺失，无法统计上涨家数")

    # ── 1e. 主线维度 (0-3) ──
    if limit_cpt is not None and len(limit_cpt) > 0:
        top_sector = limit_cpt.iloc[0]
        days = int(top_sector.get("days", 0))
        result["details"]["top_sector"] = top_sector.get("name", "")
        result["details"]["top_sector_days"] = days
        result["details"]["theme_score_basis"] = "limit_cpt_list preliminary"

        if days >= 4:
            result["theme_score"] = 3
        elif days >= 2:
            result["theme_score"] = 2
        else:
            result["theme_score"] = 1
    else:
        result["theme_score"] = 0

    result["human_judgment"].append(f"主线建议 {result['theme_score']}/3 分，请以后续主线条件清单为准")

    # ── 汇总 ──
    result["score"] = (
        result["index_score"] + result["volume_score"] +
        result["sentiment_score"] + result["theme_score"]
    )

    if result["score"] < SCORE_MID:
        result["hard_rules"]["passed"] = False
        result["hard_rules"]["violations"].append(
            f"市场评分 {result['score']} < 6 → 不开新仓"
        )

    result["market_level"] = _market_level(result["score"])
    result["trade_permission"] = _trade_permission(result["market_level"], result["hard_rules"]["passed"])
    result["ok"] = result["trade_permission"] != "closed"
    return result


def format_score_report(result: dict) -> str:
    """格式化市场评分报告。"""
    level_name = {"strong": "强", "medium": "中", "weak": "弱"}.get(result.get("market_level"), "弱")
    permission_name = {"open": "可交易", "restricted": "受限", "closed": "不开仓"}.get(
        result.get("trade_permission"), "不开仓"
    )
    lines = [
        "=" * 60,
        f"市场评分: {result['score']}/10  档位: {level_name}  权限: {permission_name}",
        f"  指数 {result['index_score']}/2 | 成交量 {result['volume_score']}/2 | "
        f"情绪 {result['sentiment_score']}/3 | 主线 {result['theme_score']}/3",
    ]
    d = result.get("details", {})
    if "sh_close" in d:
        lines.append(
            f"  上证: {d['sh_close']:.0f}  涨跌 {d.get('sh_pct_chg', 0):+.2f}%  "
            f"MA20: {d.get('sh_ma20', 'N/A')}  {'站上↑' if d.get('sh_above_ma20') else '跌破↓'}"
        )
    if "amount_ratio" in d:
        lines.append(f"  成交额/5日均值: {d['amount_ratio']:.2f}")
    if "breadth_up" in d:
        lines.append(f"  上涨家数: {d['breadth_up']}  下跌家数: {d['breadth_down']}  状态: {d['breadth_state']}")
    if "limit_up" in d:
        lines.append(
            f"  涨停: {d['limit_up']}  跌停: {d['limit_down']}  "
            f"炸板: {d['zha_ban']}  炸板率: {d.get('zha_ban_rate', 0):.1%}"
        )
    if result.get("action_notes"):
        lines.append("  行动提示:")
        for note in result["action_notes"]:
            lines.append(f"    - {note}")
    if result["hard_rules"]["violations"]:
        lines.append("  硬规则触发:")
        for v in result["hard_rules"]["violations"]:
            lines.append(f"    ⚠ {v}")
    if result.get("data_warnings"):
        lines.append("  数据提示:")
        for w in result["data_warnings"]:
            lines.append(f"    ? {w}")
    if result["human_judgment"]:
        lines.append("  需人工确认:")
        for h in result["human_judgment"]:
            lines.append(f"    ? {h}")
    lines.append("=" * 60)
    return "\n".join(lines)
