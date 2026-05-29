"""Render daily scan reports for CLI output."""

from theme_trading.cli.labels import format_condition_labels
from theme_trading.scanner import format_score_report


_STRENGTH_LABELS = {"weak": "弱", "medium": "中", "strong": "强"}


def _format_strength(item: dict) -> str | None:
    level = item.get("strength_level")
    score = item.get("strength_score")
    if level is None or score is None:
        return None
    label = _STRENGTH_LABELS.get(level, level)
    reasons = item.get("strength_reasons", [])
    reason_text = "；".join(reasons[:3])
    return f"强度: {label} {score}分" + (f"；{reason_text}" if reason_text else "")


def _format_core_evidence(stock: dict) -> str | None:
    rel = stock.get("relative_strength_evidence") or {}
    leader = stock.get("leader_effect_evidence") or {}
    parts = []
    if rel.get("recent_days"):
        parts.append(
            f"分歧抗跌 {rel.get('defensive_days', 0)}/{rel.get('divergence_days', 0)}，"
            f"修复领先 {rel.get('leading_repair_days', 0)}/{rel.get('repair_days', 0)}"
        )
    if leader.get("up_breadth") is not None and leader.get("down_breadth") is not None:
        parts.append(
            f"上涨日板块均涨 {leader.get('up_sector_avg'):+.2f}% / 广度 {leader.get('up_breadth'):.0%}，"
            f"下跌日 {leader.get('down_sector_avg'):+.2f}% / 广度 {leader.get('down_breadth'):.0%}"
        )
    return "；".join(parts) if parts else None


def render_daily_scan_report(report: dict, elapsed_seconds: float | None = None) -> str:
    lines: list[str] = []
    lines.append(format_score_report(report["market_score"]))
    lines.append("")

    themes = report.get("themes") or {}
    confirmed_themes = themes.get("confirmed_themes", [])
    watch_themes = themes.get("watch_themes", [])
    if confirmed_themes:
        lines.append(f"确认主线 ({len(confirmed_themes)} 个):")
        for t in confirmed_themes[:8]:
            lines.append(
                f"  {t['name']:24s} {t['pct_chg']:+.2f}%  "
                f"满足 {t['condition_count']}/5  连续强 {t['consecutive_days']}日  "
                f"量比 {t['amount_ratio']:.1f}  涨停 {t.get('up_in_sector', '?')}只"
            )
            missing = t.get("missing_conditions", [])
            if missing:
                lines.append(f"    缺: {format_condition_labels(missing)}")
        lines.append("")
    if watch_themes:
        lines.append(f"观察主线 ({len(watch_themes)} 个):")
        for t in watch_themes[:5]:
            lines.append(
                f"  {t['name']:24s} {t['pct_chg']:+.2f}%  满足 {t['condition_count']}/5  "
                f"缺: {format_condition_labels(t.get('missing_conditions', []))}"
            )
        lines.append("")

    stocks = report.get("core_stocks") or {}
    confirmed_stocks = stocks.get("confirmed_core_stocks", [])
    watch_stocks = stocks.get("watch_core_stocks", [])
    if confirmed_stocks:
        lines.append(f"确认核心强势股 ({len(confirmed_stocks)} 只):")
        for s in confirmed_stocks[:12]:
            leader = s.get("leader_effect")
            leader_str = "带动" if leader is True else ("未带动" if leader is False else "带动?")
            lines.append(
                f"  {s['ts_code']:12s} {s.get('name') or '':8s} {s['pct_chg']:+.2f}%  "
                f"满足 {s['condition_count']}/5  成交额排名 {s['amount_rank']}  "
                f"板块排名 {s.get('sector_amount_rank')}  换手 {s['turnover_rate']}%  "
                f"带动性: {leader_str}"
            )
            evidence = _format_core_evidence(s)
            if evidence:
                lines.append(f"    证据: {evidence}")
        lines.append("")
    if watch_stocks:
        lines.append(f"观察核心股 ({len(watch_stocks)} 只):")
        for s in watch_stocks[:8]:
            leader = s.get("leader_effect")
            leader_str = "带动" if leader is True else ("未带动" if leader is False else "带动?")
            lines.append(
                f"  {s['ts_code']:12s} {s.get('name') or '':8s} {s['pct_chg']:+.2f}%  "
                f"满足 {s['condition_count']}/5  缺: {format_condition_labels(s.get('missing_conditions', []))}  "
                f"带动性: {leader_str}"
            )
            evidence = _format_core_evidence(s)
            if evidence:
                lines.append(f"    证据: {evidence}")
        lines.append("")

    pending = [item for item in report.get("pending_confirmations", []) if item.get("category") != "buy_point_scan_failure"]
    if pending:
        lines.append(f"待确认 ({len(pending)} 项):")
        for item in pending[:12]:
            if "buy_point" in item:
                strength = _format_strength(item)
                strength_text = f"  {strength}" if strength else ""
                lines.append(f"  {item['ts_code']} {item['buy_point']}  状态 {item['status']}  止损参考 {item.get('stop_loss')}{strength_text}")
                for check in item.get("manual_checks", [])[:2]:
                    lines.append(f"    - {check}")
            else:
                lines.append(f"  {item.get('ts_code', '-')}: {item.get('reason', item)}")
        lines.append("")

    _append_watch_buy_shapes(lines, report.get("watch_buy_shapes", []))
    _append_invalid_buy_setups(lines, report.get("observation_pool", []))

    _append_plans(lines, "待开盘确认预案", report.get("pending_open_plans", []))
    _append_plans(lines, "待开盘确认试错预案", report.get("trial_plans", []), suffix=" — 主线未确认，仅买点一")
    _append_no_plan_diagnostics(lines, report)

    pre_trade = report.get("pre_trade_checks", [])
    if pre_trade:
        lines.append(f"买入前检查清单 ({len(pre_trade)} 项):")
        for check in pre_trade:
            passed_str = "通过" if check["all_passed"] else "未通过"
            questions = check.get("three_questions", {})
            lines.append(f"  {check['ts_code']}: {passed_str}")
            if questions.get("answered"):
                lines.append(f"    为什么是它: {questions['why_this']}")
                lines.append(f"    为什么是现在: {questions['why_now']}")
                lines.append(f"    错了在哪里走: {questions['where_exit']}")
            for reason in check.get("block_reasons", []):
                lines.append(f"    - {reason}")
        lines.append("")

    blocked = report.get("blocked_reasons", [])
    if blocked:
        lines.append("阻断原因:")
        for reason in blocked[:12]:
            lines.append(f"  - {reason}")
        lines.append("")

    warnings = report.get("data_warnings", [])
    if warnings:
        lines.append("数据提示:")
        for warning in dict.fromkeys(warnings):
            lines.append(f"  - {warning}")
        lines.append("")

    human = report.get("human_judgment", [])
    if human:
        lines.append("─" * 60)
        lines.append("需人工确认:")
        for h in human:
            lines.append(f"  - {h}")

    risk_notes = report.get("risk_notes", [])
    if risk_notes:
        lines.append("")
        lines.append("风险提示:")
        for note in risk_notes:
            lines.append(f"  - {note}")

    if elapsed_seconds is not None:
        lines.append("")
        lines.append(f"总耗时: {elapsed_seconds:.0f}s")

    return "\n".join(lines)


def _append_no_plan_diagnostics(lines: list[str], report: dict) -> None:
    if report.get("pending_open_plans") or report.get("trial_plans"):
        return

    diagnostics = report.get("no_plan_diagnostics") or _derive_no_plan_diagnostics(report)
    lines.append("无人工执行预案诊断:")
    lines.append(
        "  "
        f"市场开关: {diagnostics.get('market_gate') or '-'}；"
        f"确认主线: {diagnostics.get('confirmed_theme_count', 0)}；"
        f"确认核心股: {diagnostics.get('confirmed_core_count', 0)}；"
        f"买点扫描失败: {diagnostics.get('scan_failure_count', 0)}；"
        f"已失效买点: {diagnostics.get('invalid_setup_count', 0)}；"
        f"待确认项: {diagnostics.get('pending_confirmation_count', 0)}；"
        f"风险提示: {diagnostics.get('risk_notes_count', 0)}"
    )
    reasons = diagnostics.get("main_reasons") or ["没有符合规则的待开盘人工执行确认预案"]
    for reason in reasons[:8]:
        lines.append(f"  - {reason}")
    scan_failures = [item for item in report.get("pending_confirmations", []) if item.get("category") == "buy_point_scan_failure"]
    for item in scan_failures[:5]:
        lines.append(f"    扫描失败: {item.get('ts_code', '-')} {item.get('name') or ''} — {item.get('reason', '买点扫描失败')}")
    lines.append("")


def _derive_no_plan_diagnostics(report: dict) -> dict:
    themes = report.get("themes") or {}
    stocks = report.get("core_stocks") or {}
    pending = report.get("pending_confirmations") or []
    observation_pool = report.get("observation_pool") or []
    scan_failure_count = len([item for item in pending if item.get("category") == "buy_point_scan_failure"])
    return {
        "market_gate": report.get("market_gate") or (report.get("market_score") or {}).get("trade_permission"),
        "confirmed_theme_count": len(themes.get("confirmed_themes", []) or []),
        "confirmed_core_count": len(stocks.get("confirmed_core_stocks", []) or []),
        "scan_failure_count": scan_failure_count,
        "invalid_setup_count": len([item for item in observation_pool if item.get("category") == "invalid_buy_setup"]),
        "pending_confirmation_count": len([item for item in pending if item.get("category") != "buy_point_scan_failure"]),
        "risk_notes_count": len(report.get("risk_notes", []) or []),
        "main_reasons": [],
    }


def _append_watch_buy_shapes(lines: list[str], items: list[dict]) -> None:
    if not items:
        return
    lines.append(f"观察买点形态 / 即将确认（{len(items)} 项，仅观察，不生成正式预案）:")
    for item in items[:12]:
        strength = _format_strength(item)
        lines.append(
            f"  {item['ts_code']} {item.get('name') or ''}  {item['buy_point']}  "
            f"状态 {item.get('status')}  止损参考 {item.get('stop_loss')}  "
            f"主线 {item.get('theme_name')}({item.get('theme_condition_count')}/5)"
        )
        if strength:
            lines.append(f"    {strength}")
        missing = item.get("theme_missing_conditions", [])
        if missing:
            lines.append(f"    主线缺: {format_condition_labels(missing)}")
        lines.append(f"    {item.get('reason')}")
    lines.append("")


def _append_invalid_buy_setups(lines: list[str], observation_pool: list[dict]) -> None:
    items = [item for item in observation_pool if item.get("category") == "invalid_buy_setup"]
    if not items:
        return
    lines.append(f"已失效买点形态 ({len(items)} 项，仅诊断，不生成人工执行预案):")
    for item in items[:12]:
        strength = _format_strength(item)
        execution = item.get("execution_check") or {}
        gap = execution.get("gap_check") or {}
        gap_text = ""
        if gap.get("checked"):
            gap_pct = gap.get("gap_pct")
            gap_text = f"  开盘偏离 {gap_pct:+.1%}" if gap_pct is not None else "  开盘偏离已检查"
            if gap.get("passed") is False:
                gap_text += "，超出执行范围"
        lines.append(
            f"  {item['ts_code']} {item.get('name') or ''}  {item['buy_point']}  "
            f"状态 {item.get('status')}  止损参考 {item.get('stop_loss')}{gap_text}"
        )
        if strength:
            lines.append(f"    {strength}")
        failures = item.get("failure_signals", [])
        if failures:
            lines.append(f"    失败信号: {' / '.join(failures[:3])}")
        lines.append(f"    {item.get('reason')}")
    lines.append("")


def render_execution_confirmation(confirmation: dict) -> str:
    lines = [
        "开盘执行确认结果",
        f"计划文件: {confirmation.get('plan_path')}",
        f"决策日: {confirmation.get('decision_date') or '-'}  执行确认日: {confirmation.get('execution_date') or '-'}",
    ]
    summary = confirmation.get("summary", {})
    lines.append(
        f"汇总: 共 {summary.get('total', 0)} 项，通过 {summary.get('executable', 0)} 项，"
        f"跳过 {summary.get('skipped', 0)} 项，失效 {summary.get('invalid', 0)} 项"
    )
    lines.append("")
    for item in confirmation.get("results", []):
        status = item.get("status")
        status_text = "已通过确认，可人工执行" if status == "executable_plan" else status
        gap = (item.get("execution_check") or {}).get("gap_check") or {}
        gap_pct = gap.get("gap_pct")
        gap_text = f"，开盘偏离 {gap_pct:+.1%}" if gap_pct is not None else ""
        lines.append(
            f"  {item.get('ts_code')} {item.get('buy_point')}  状态 {status_text}  "
            f"开盘 {item.get('open')}{gap_text}"
        )
        lines.append(f"    原因: {item.get('reason')}")
    return "\n".join(lines)


def _append_plans(lines: list[str], title: str, plans: list[dict], suffix: str = "") -> None:
    if not plans:
        return
    lines.append(f"{title} ({len(plans)} 只){suffix}:")
    for item in plans:
        execution = item.get("execution_check", {})
        planned_execution_date = item.get("planned_execution_date") or item.get("execution_date")
        dates = f"信号日 {item.get('setup_date') or '-'}  →  确认日 {item.get('confirm_date') or '-'}  →  计划确认日 {planned_execution_date or '-'}"
        status_text = "待人工执行确认" if item.get("status") == "pending_next_open" else item.get("status")
        lines.append(f"  {item['ts_code']}  {item['buy_point']}  状态 {status_text}")
        lines.append(f"    {dates}")
        lines.append(
            f"    确认收盘 {item.get('close')}  止损参考 {item.get('stop_loss')}  "
            f"人工执行确认条件: {execution.get('rule', '次日开盘 ±3% 内')}"
        )
        strength = _format_strength(item)
        if strength:
            lines.append(f"    {strength}")
        if item.get("risk_budget_label"):
            lines.append(f"    风险预算: {item['risk_budget_label']}（{item.get('risk_budget_reason', '')}）")
        failures = item.get("failure_signals", [])
        if failures:
            lines.append(f"    失败信号: {' / '.join(failures[:3])}")
    lines.append("")
