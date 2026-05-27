"""Daily scan report helpers."""

from .types import DailyScanReport


def new_daily_report(trade_date: str) -> DailyScanReport:
    return {
        "trade_date": trade_date,
        "market_score": None,
        "market_gate": None,
        "themes": None,
        "core_stocks": None,
        "buy_scans": [],
        "observation_pool": [],
        "pending_confirmations": [],
        "executable_plans": [],
        "trial_plans": [],
        "pending_reviews": [],
        "pre_trade_checks": [],
        "blocked_reasons": [],
        "data_warnings": [],
        "human_judgment": [],
    }


def append_observation(report: DailyScanReport, category: str, items: list[dict]) -> None:
    for item in items:
        report["observation_pool"].append({"category": category, **item})


def add_messages(report: DailyScanReport, source_result: dict) -> None:
    report["human_judgment"].extend(source_result.get("human_judgment", []))
    report["data_warnings"].extend(source_result.get("data_warnings", []))


def add_risk_note(report: DailyScanReport, note: str) -> None:
    report.setdefault("risk_notes", []).append(note)
