"""Scanner result type contracts."""

from typing import Any, Literal, NotRequired, TypedDict


JsonDict = dict[str, Any]
PlanType = Literal["standard", "trial"]
RouteStatus = Literal["ready", "pending", "blocked"]


class MarketScoreResult(TypedDict, total=False):
    ok: bool
    score: int
    market_level: str
    trade_permission: str
    emotion_extreme: bool
    hard_rules: JsonDict
    details: JsonDict
    human_judgment: list[str]
    data_warnings: list[str]


class ThemeItem(TypedDict, total=False):
    ts_code: str
    name: str
    status: str
    pct_chg: float
    amount_ratio: float
    vol_ratio: float
    up_in_sector: int
    amount_5d_high: bool
    condition_count: int
    missing_conditions: list[str]


class CoreStockItem(TypedDict, total=False):
    ts_code: str
    name: str | None
    sector_code: str | None
    status: str
    pct_chg: float
    amount_rank: int | None
    sector_amount_rank: int | None
    turnover_rate: float | None
    conditions: JsonDict
    missing_conditions: list[str]


class BuyPointInfo(TypedDict, total=False):
    triggered: bool
    setup_triggered: bool
    status: str
    priority: int
    details: JsonDict
    stop_loss: float | None
    execution_check: JsonDict
    failure_signals: list[str]
    manual_checks: list[str]


class BuyPointScanResult(TypedDict, total=False):
    ok: bool
    error: str
    ts_code: str
    trade_date: str
    setup_date: str
    confirm_date: str | None
    execution_date: str | None
    close: float
    buy_points: dict[str, BuyPointInfo]
    selected_buy_point: str | None
    suppressed_by_priority: list[str]
    any_triggered: bool
    triggered_list: list[str]
    setup_list: list[str]


class PreTradeChecklistResult(TypedDict, total=False):
    ok: bool
    all_passed: bool
    checks: JsonDict
    three_questions: JsonDict
    block_reasons: list[str]
    warnings: list[str]
    human_judgment: list[str]


class TradeSignal(TypedDict, total=False):
    ts_code: str
    name: str | None
    sector_code: str | None
    core_status: str | None
    amount_rank: int | None
    conditions: JsonDict
    plan_type: PlanType
    buy_point: str
    status: str | None
    setup_date: str | None
    confirm_date: str | None
    execution_date: str | None
    close: float | None
    stop_loss: float | None
    execution_check: JsonDict | None
    failure_signals: list[str]
    manual_checks: list[str]
    suppressed_by_priority: list[str]
    source: NotRequired[str]
    pre_trade_check: JsonDict
    risk_budget_pct: float
    risk_budget_label: str
    risk_budget_reason: str
    reason: str


class DailyScanReport(TypedDict, total=False):
    trade_date: str
    market_score: MarketScoreResult | None
    market_gate: str | None
    themes: JsonDict | None
    core_stocks: JsonDict | None
    buy_scans: list[JsonDict]
    observation_pool: list[JsonDict]
    pending_confirmations: list[JsonDict]
    executable_plans: list[TradeSignal]
    trial_plans: list[TradeSignal]
    pending_reviews: list[JsonDict]
    pre_trade_checks: list[JsonDict]
    blocked_reasons: list[str]
    data_warnings: list[str]
    human_judgment: list[str]
    risk_notes: NotRequired[list[str]]
