"""CLI display labels."""

CONDITION_LABELS = {
    "stronger_than_market_2d": "连续2日强于上证",
    "amount_expand_2d": "连续2日成交额≥5日均额1.3倍",
    "limit_up_or_ladder": "涨停≥5只或高度≥3板",
    "core_amount_rank": "板块内/全市场成交额核心",
    "divergence_return": "分歧后资金回流",
    "amount_rank_core": "全市场前50或板块前5成交额",
    "recent_sector_top_20pct": "近5日至少2日板块涨幅前20%",
    "relative_strength": "分歧抗跌或修复先反弹",
    "technical_strength": "均线多头或20日新高",
    "leader_effect": "带动同板块扩散",
}


def format_condition_labels(keys: list[str]) -> str:
    return ", ".join(CONDITION_LABELS.get(key, key) for key in keys)
