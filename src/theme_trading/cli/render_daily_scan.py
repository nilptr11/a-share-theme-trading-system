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

    pending = report.get("pending_confirmations", [])
    if pending:
        lines.append(f"待确认 ({len(pending)} 项):")
        for item in pending[:12]:
            if "buy_point" in item:
                strength = _format_strength(item)
                strength_text = f"  {strength}" if strength else ""
                lines.append(f"  {item['ts_code']} {item['buy_point']}  状态 {item['status']}  止损参考 {item.get('stop_loss')}{strength_text}")
                for check in item.get("manual_checks", [])[:2]:
                    lines.append(f"    ? {check}")
            else:
                lines.append(f"  {item.get('ts_code', '-')}: {item.get('reason', item)}")
        lines.append("")

    _append_watch_buy_shapes(lines, report.get("watch_buy_shapes", []))
    _append_invalid_buy_setups(lines, report.get("observation_pool", []))

    _append_plans(lines, "可执行预案", report.get("executable_plans", []))
    _append_plans(lines, "试错预案", report.get("trial_plans", []), suffix=" — 主线未确认，仅买点一")

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
                lines.append(f"    ✗ {reason}")
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
            lines.append(f"  ? {warning}")
        lines.append("")

    human = report.get("human_judgment", [])
    if human:
        lines.append("─" * 60)
        lines.append("需人工确认:")
        for h in human:
            lines.append(f"  ? {h}")

    risk_notes = report.get("risk_notes", [])
    if risk_notes:
        lines.append("")
        lines.append("风险提示:")
        for note in risk_notes:
            lines.append(f"  ⚠ {note}")

    if elapsed_seconds is not None:
        lines.append("")
        lines.append(f"总耗时: {elapsed_seconds:.0f}s")

    return "\n".join(lines)


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
    lines.append(f"已失效买点形态 ({len(items)} 项，仅诊断，不生成预案):")
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


def _append_plans(lines: list[str], title: str, plans: list[dict], suffix: str = "") -> None:
    if not plans:
        return
    lines.append(f"{title} ({len(plans)} 只){suffix}:")
    for item in plans:
        execution = item.get("execution_check", {})
        dates = f"信号日 {item.get('setup_date') or '-'}  →  确认日 {item.get('confirm_date') or '-'}  →  计划买入日 {item.get('execution_date') or '-'}"
        lines.append(f"  {item['ts_code']}  {item['buy_point']}  状态 {item['status']}")
        lines.append(f"    {dates}")
        lines.append(
            f"    确认收盘 {item.get('close')}  止损参考 {item.get('stop_loss')}  "
            f"执行条件: {execution.get('rule', '次日开盘 ±3% 内')}"
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
