"""Trade signal routing."""

from .types import DailyScanReport, RouteStatus, TradeSignal


def routing_status(bp_status: str) -> RouteStatus:
    if bp_status in ("executable_plan", "pending_next_open"):
        return "ready"
    if bp_status in ("pending_next_day_strength", "watch"):
        return "pending"
    return "blocked"


def route_signal(
    report: DailyScanReport,
    signal: TradeSignal,
    *,
    market_closed: bool,
    trial_mode: bool,
    blocked_message: str,
    market_closed_message: str | None = None,
) -> None:
    checklist = signal["pre_trade_check"]
    if market_closed:
        signal["reason"] = "市场开关关闭，仅观察"
        if market_closed_message:
            report["blocked_reasons"].append(market_closed_message)
        report["observation_pool"].append({"category": "blocked_market_closed", **signal})
        return

    if not checklist["all_passed"]:
        signal["reason"] = "买入前检查不通过: " + "; ".join(checklist["block_reasons"])
        report["blocked_reasons"].append(signal["reason"])
        report["observation_pool"].append({"category": "blocked_pre_trade", **signal})
        report["pre_trade_checks"].append(checklist)
        return

    route = routing_status(signal.get("status") or "")
    if route == "ready":
        if trial_mode:
            report["trial_plans"].append(signal)
        else:
            report["pending_open_plans"].append(signal)
        report["pre_trade_checks"].append(checklist)
    elif route == "pending":
        report["pending_confirmations"].append(signal)
    else:
        report["blocked_reasons"].append(blocked_message)
