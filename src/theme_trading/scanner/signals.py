"""Trade signal builders."""

from .pre_trade import pre_trade_checklist
from .risk_budget import risk_budget_for_plan
from .types import TradeSignal


def _attach_risk_and_checklist(
    signal: TradeSignal,
    *,
    market_context: dict,
    theme_context: dict | None,
    core_stock: dict,
    buy_point_info: dict,
    buy_point_name: str,
    allow_watch: bool,
    emotion_extreme: bool,
) -> TradeSignal:
    signal.update(risk_budget_for_plan(
        market_context,
        buy_point_name,
        plan_type=signal["plan_type"],
        emotion_extreme=emotion_extreme,
    ))
    checklist = pre_trade_checklist(
        market_context=market_context,
        theme_context=theme_context,
        core_stock=core_stock,
        buy_point_info=buy_point_info,
        buy_point_name=buy_point_name,
        allow_watch=allow_watch,
    )
    signal["pre_trade_check"] = {
        "ts_code": signal["ts_code"],
        "all_passed": checklist["all_passed"],
        "checks": checklist["checks"],
        "three_questions": checklist["three_questions"],
        "block_reasons": checklist["block_reasons"],
    }
    return signal


def build_signal_from_pending_review(
    pending: dict,
    review: dict,
    *,
    market_context: dict,
    theme_context: dict | None,
    core_stock: dict,
) -> TradeSignal:
    buy_point_name = pending["buy_point"]
    plan_type = pending.get("plan_type", "standard")
    bp = review["buy_scan"]
    info = review["buy_point_info"]
    signal: TradeSignal = {
        "ts_code": pending["ts_code"],
        "plan_type": plan_type,
        "buy_point": buy_point_name,
        "status": info.get("status"),
        "setup_date": bp.get("setup_date"),
        "confirm_date": info.get("confirm_date", bp.get("confirm_date")),
        "execution_date": info.get("execution_date", bp.get("execution_date")),
        "close": info.get("execution_check", {}).get("confirm_close", bp.get("close")),
        "stop_loss": info.get("stop_loss"),
        "execution_check": info.get("execution_check"),
        "failure_signals": info.get("failure_signals", []),
        "manual_checks": info.get("manual_checks", []),
        "suppressed_by_priority": bp.get("suppressed_by_priority", []),
        "source": "pending_setup_review",
    }
    return _attach_risk_and_checklist(
        signal,
        market_context=market_context,
        theme_context=theme_context,
        core_stock=core_stock,
        buy_point_info=info,
        buy_point_name=buy_point_name,
        allow_watch=plan_type == "trial",
        emotion_extreme=bool(market_context.get("emotion_extreme")),
    )


def build_signal_from_buy_scan(
    stock: dict,
    buy_scan: dict,
    selected: str,
    *,
    market_context: dict,
    theme_context: dict | None,
    trial_mode: bool,
) -> TradeSignal:
    info = buy_scan["buy_points"][selected]
    signal: TradeSignal = {
        "ts_code": stock["ts_code"],
        "name": stock.get("name"),
        "sector_code": stock.get("sector_code"),
        "core_status": stock.get("status"),
        "amount_rank": stock.get("amount_rank"),
        "conditions": stock.get("conditions", {}),
        "plan_type": "trial" if trial_mode else "standard",
        "buy_point": selected,
        "status": info.get("status"),
        "setup_date": buy_scan.get("setup_date"),
        "confirm_date": info.get("confirm_date", buy_scan.get("confirm_date")),
        "execution_date": info.get("execution_date", buy_scan.get("execution_date")),
        "close": info.get("execution_check", {}).get("confirm_close", buy_scan.get("close")),
        "stop_loss": info.get("stop_loss"),
        "execution_check": info.get("execution_check"),
        "failure_signals": info.get("failure_signals", []),
        "manual_checks": info.get("manual_checks", []),
        "suppressed_by_priority": buy_scan.get("suppressed_by_priority", []),
    }
    return _attach_risk_and_checklist(
        signal,
        market_context=market_context,
        theme_context=theme_context,
        core_stock=stock,
        buy_point_info=info,
        buy_point_name=selected,
        allow_watch=trial_mode,
        emotion_extreme=bool(market_context.get("emotion_extreme")),
    )
