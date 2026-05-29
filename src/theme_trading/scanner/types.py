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
    relative_strength_evidence: JsonDict
    leader_effect_evidence: JsonDict


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
    strength_score: int
    strength_level: str
    strength_reasons: list[str]


class BuyPointScanResult(TypedDict, total=False):
    ok: bool
    error: str
    ts_code: str
    trade_date: str
    setup_date: str
    confirm_date: str | None
    execution_date: str | None
    close: float
    phase: str
    allow_execution_check: bool
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
    planned_execution_date: str | None
    close: float | None
    stop_loss: float | None
    execution_check: JsonDict | None
    failure_signals: list[str]
    manual_checks: list[str]
    strength_score: int | None
    strength_level: str | None
    strength_reasons: list[str]
    suppressed_by_priority: list[str]
    source: NotRequired[str]
    pre_trade_check: JsonDict
    risk_budget_pct: float
    risk_budget_label: str
    risk_budget_reason: str
    reason: str


class DecisionPlan(TypedDict, total=False):
    schema_version: int
    phase: str
    decision_date: str
    latest_complete_trade_date: str
    planned_execution_date: str | None
    created_at: str
    report: JsonDict
    plans: list[JsonDict]


class ExecutionConfirmation(TypedDict, total=False):
    schema_version: int
    phase: str
    plan_path: str
    decision_date: str | None
    latest_complete_trade_date: str | None
    execution_date: str | None
    created_at: str
    results: list[JsonDict]
    summary: JsonDict


class NoPlanDiagnostics(TypedDict, total=False):
    has_plan: bool
    market_gate: str | None
    confirmed_theme_count: int
    watch_theme_count: int
    confirmed_core_count: int
    watch_core_count: int
    scan_failure_count: int
    invalid_setup_count: int
    no_buy_point_count: int
    pending_confirmation_count: int
    risk_notes_count: int
    reason_codes: list[str]
    main_reasons: list[str]


class DailyScanReport(TypedDict, total=False):
    trade_date: str
    decision_date: str
    latest_complete_trade_date: str
    phase: str
    market_score: MarketScoreResult | None
    market_gate: str | None
    themes: JsonDict | None
    core_stocks: JsonDict | None
    buy_scans: list[JsonDict]
    observation_pool: list[JsonDict]
    pending_confirmations: list[JsonDict]
    watch_buy_shapes: list[JsonDict]
    pending_open_plans: list[TradeSignal]
    trial_plans: list[TradeSignal]
    pending_reviews: list[JsonDict]
    pre_trade_checks: list[JsonDict]
    blocked_reasons: list[str]
    data_warnings: list[str]
    human_judgment: list[str]
    no_plan_diagnostics: NoPlanDiagnostics
    risk_notes: NotRequired[list[str]]
