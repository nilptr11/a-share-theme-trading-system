"""Decision plan snapshot persistence for close-decision scans."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from .types import DecisionPlan

SCHEMA_VERSION = 1
DEFAULT_PLAN_DIR = Path("plans")


def _json_default(value: Any) -> Any:
    """Convert common dataframe/numpy scalar values for JSON output."""
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _dump_json(data: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2, default=_json_default)
        fp.write("\n")
    return path


def _load_json(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _plan_items(report: dict) -> list[dict]:
    """Return all close-decision plans without mutating the report snapshot."""
    plans: list[dict] = []
    for plan_type, key in (("standard", "pending_open_plans"), ("trial", "trial_plans")):
        for item in report.get(key, []) or []:
            plan = deepcopy(item)
            plan.setdefault("plan_type", plan_type)
            plan.setdefault("planned_execution_date", plan.get("execution_date"))
            plan["status"] = "pending_next_open"
            plan["execution_phase"] = "pending_open_confirmation"
            plans.append(plan)
    return plans


def _planned_execution_date(plans: list[dict]) -> str | None:
    dates = sorted({str(item.get("planned_execution_date") or item.get("execution_date")) for item in plans if item.get("planned_execution_date") or item.get("execution_date")})
    return dates[0] if dates else None


def build_decision_plan(report: dict, *, created_at: str | None = None) -> DecisionPlan:
    """Build an auditable, read-only close-decision snapshot."""
    snapshot = deepcopy(report)
    plans = _plan_items(snapshot)
    decision_date = snapshot.get("decision_date") or snapshot.get("trade_date")
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": "close_decision",
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
        "decision_date": decision_date,
        "latest_complete_trade_date": snapshot.get("latest_complete_trade_date") or decision_date,
        "planned_execution_date": _planned_execution_date(plans),
        "report": snapshot,
        "plans": plans,
    }


def default_plan_path(decision_date: str, *, base_dir: str | Path = DEFAULT_PLAN_DIR) -> Path:
    return Path(base_dir) / f"{decision_date}.json"


def save_decision_plan(report: dict, path: str | Path | None = None) -> tuple[DecisionPlan, Path]:
    plan = build_decision_plan(report)
    output_path = Path(path) if path is not None else default_plan_path(str(plan["decision_date"]))
    return plan, _dump_json(plan, output_path)


def load_decision_plan(path: str | Path) -> DecisionPlan:
    return _load_json(path)
