"""Daily scan report helpers."""

from .types import DailyScanReport


def new_daily_report(trade_date: str) -> DailyScanReport:
    return {
        "trade_date": trade_date,
        "decision_date": trade_date,
        "latest_complete_trade_date": trade_date,
        "phase": "close_decision",
        "market_score": None,
        "market_gate": None,
        "themes": None,
        "core_stocks": None,
        "buy_scans": [],
        "observation_pool": [],
        "pending_confirmations": [],
        "watch_buy_shapes": [],
        "pending_open_plans": [],
        "trial_plans": [],
        "pending_reviews": [],
        "pre_trade_checks": [],
        "blocked_reasons": [],
        "data_warnings": [],
        "human_judgment": [],
        "no_plan_diagnostics": _empty_no_plan_diagnostics(),
    }


def _empty_no_plan_diagnostics() -> dict:
    return {
        "has_plan": False,
        "market_gate": None,
        "confirmed_theme_count": 0,
        "watch_theme_count": 0,
        "confirmed_core_count": 0,
        "watch_core_count": 0,
        "scan_failure_count": 0,
        "invalid_setup_count": 0,
        "no_buy_point_count": 0,
        "pending_confirmation_count": 0,
        "risk_notes_count": 0,
        "reason_codes": [],
        "main_reasons": [],
    }


def append_observation(report: DailyScanReport, category: str, items: list[dict]) -> None:
    for item in items:
        report["observation_pool"].append({"category": category, **item})


def add_messages(report: DailyScanReport, source_result: dict) -> None:
    report["human_judgment"].extend(source_result.get("human_judgment", []))
    report["data_warnings"].extend(source_result.get("data_warnings", []))


def add_risk_note(report: DailyScanReport, note: str) -> None:
    report.setdefault("risk_notes", []).append(note)
