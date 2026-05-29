"""Open execution confirmation for previously saved decision plans."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from theme_trading.data.market_data import fetch_daily

from .buy_point_rules import execution_check
from .plans import SCHEMA_VERSION, load_decision_plan
from .types import ExecutionConfirmation

DEFAULT_CONFIRMATION_DIR = Path("confirmations")


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _dump_json(data: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2, default=_json_default)
        fp.write("\n")
    return path


def _open_row(ts_code: str, execution_date: str):
    df = fetch_daily(ts_code=ts_code, trade_date=execution_date)
    if df is None or len(df) == 0:
        return None
    return df.sort_values("trade_date").iloc[0]


def _status_from_gap(gap_check: dict, row) -> tuple[str, str]:
    if row is None:
        return "skipped", "计划执行日无开盘行情，跳过人工执行"
    if not gap_check.get("checked"):
        return "skipped", "开盘价或确认收盘价缺失，无法确认执行条件"
    if gap_check.get("passed"):
        return "executable_plan", "已通过开盘偏离确认，可进入人工执行窗口"
    return "invalid", "开盘价相对确认日收盘价超出 ±3%，预案失效"


def build_execution_confirmation(plan_snapshot: dict, *, plan_path: str | Path, execution_date: str | None = None, created_at: str | None = None) -> ExecutionConfirmation:
    """Confirm saved plans against execution-date open data without mutating the plan."""
    plans = deepcopy(plan_snapshot.get("plans", []))
    selected_execution_date = execution_date or plan_snapshot.get("planned_execution_date")
    results: list[dict] = []

    for index, plan in enumerate(plans, start=1):
        planned_date = plan.get("planned_execution_date") or plan.get("execution_date")
        if selected_execution_date and planned_date and str(planned_date) != str(selected_execution_date):
            results.append({
                "plan_index": index,
                "ts_code": plan.get("ts_code"),
                "buy_point": plan.get("buy_point"),
                "status": "skipped",
                "reason": "计划执行日与本次确认日期不一致",
                "planned_execution_date": planned_date,
                "execution_date": selected_execution_date,
                "execution_check": {},
            })
            continue

        if not planned_date and not selected_execution_date:
            results.append({
                "plan_index": index,
                "ts_code": plan.get("ts_code"),
                "buy_point": plan.get("buy_point"),
                "status": "skipped",
                "reason": "预案缺少 planned_execution_date，无法读取开盘行情",
                "planned_execution_date": None,
                "execution_date": None,
                "execution_check": {},
            })
            continue

        actual_execution_date = str(selected_execution_date or planned_date)
        ts_code = plan.get("ts_code")
        row = _open_row(str(ts_code), actual_execution_date) if ts_code else None
        confirm_close = plan.get("close")
        if confirm_close is None:
            confirm_close = (plan.get("execution_check") or {}).get("confirm_close")
        check = execution_check(float(confirm_close), row) if confirm_close is not None else {
            "confirm_close": None,
            "next_trade_date": actual_execution_date,
            "next_open": float(row["open"]) if row is not None and "open" in row else None,
            "gap_limit_pct": None,
            "gap_check": {"checked": False, "passed": None, "gap_pct": None},
            "rule": "次日开盘价相对确认日收盘价在 ±3% 内才可进入人工执行确认窗口",
        }
        status, reason = _status_from_gap(check.get("gap_check", {}), row)
        results.append({
            "plan_index": index,
            "ts_code": ts_code,
            "name": plan.get("name"),
            "buy_point": plan.get("buy_point"),
            "plan_type": plan.get("plan_type"),
            "original_status": plan.get("status"),
            "status": status,
            "reason": reason,
            "decision_date": plan_snapshot.get("decision_date"),
            "setup_date": plan.get("setup_date"),
            "confirm_date": plan.get("confirm_date"),
            "planned_execution_date": planned_date,
            "execution_date": actual_execution_date,
            "confirm_close": check.get("confirm_close"),
            "open": check.get("next_open"),
            "execution_check": check,
            "stop_loss": plan.get("stop_loss"),
            "risk_budget_label": plan.get("risk_budget_label"),
            "risk_budget_pct": plan.get("risk_budget_pct"),
            "manual_action": status == "executable_plan",
        })

    summary = {
        "total": len(results),
        "executable": sum(1 for item in results if item.get("status") == "executable_plan"),
        "skipped": sum(1 for item in results if item.get("status") == "skipped"),
        "invalid": sum(1 for item in results if item.get("status") == "invalid"),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": "open_execution_confirmation",
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
        "plan_path": str(plan_path),
        "decision_date": plan_snapshot.get("decision_date"),
        "latest_complete_trade_date": plan_snapshot.get("latest_complete_trade_date"),
        "execution_date": selected_execution_date,
        "results": results,
        "summary": summary,
    }


def default_confirmation_path(execution_date: str, *, base_dir: str | Path = DEFAULT_CONFIRMATION_DIR) -> Path:
    return Path(base_dir) / f"{execution_date}.json"


def save_execution_confirmation(confirmation: dict, path: str | Path | None = None) -> Path:
    execution_date = confirmation.get("execution_date") or "unknown"
    output_path = Path(path) if path is not None else default_confirmation_path(str(execution_date))
    return _dump_json(confirmation, output_path)


def confirm_open_from_plan(plan_path: str | Path, *, execution_date: str | None = None, output_path: str | Path | None = None) -> tuple[ExecutionConfirmation, Path]:
    plan_snapshot = load_decision_plan(plan_path)
    confirmation = build_execution_confirmation(plan_snapshot, plan_path=plan_path, execution_date=execution_date)
    return confirmation, save_execution_confirmation(confirmation, output_path)
