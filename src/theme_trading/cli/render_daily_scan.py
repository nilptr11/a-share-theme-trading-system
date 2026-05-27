"""Render daily scan reports for CLI output."""

from theme_trading.scanner import format_score_report


THEME_CONDITION_LABELS = {
    "stronger_than_market_2d": "连续2日强于上证",
    "amount_expand_2d": "连续2日成交额≥5日均额1.3倍",
    "limit_up_or_ladder": "涨停≥5只或高度≥3板",
    "core_amount_rank": "板块内/全市场成交额核心",
    "divergence_return": "分歧后资金回流",
}


def _format_theme_conditions(keys: list[str]) -> str:
    return ", ".join(THEME_CONDITION_LABELS.get(key, key) for key in keys)


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
                lines.append(f"    缺: {_format_theme_conditions(missing)}")
        lines.append("")
    if watch_themes:
        lines.append(f"观察主线 ({len(watch_themes)} 个):")
        for t in watch_themes[:5]:
            lines.append(
                f"  {t['name']:24s} {t['pct_chg']:+.2f}%  满足 {t['condition_count']}/5  "
                f"缺: {_format_theme_conditions(t.get('missing_conditions', []))}"
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
        lines.append("")
    if watch_stocks:
        lines.append(f"观察核心股 ({len(watch_stocks)} 只):")
        for s in watch_stocks[:8]:
            leader = s.get("leader_effect")
            leader_str = "带动" if leader is True else ("未带动" if leader is False else "带动?")
            lines.append(
                f"  {s['ts_code']:12s} {s.get('name') or '':8s} {s['pct_chg']:+.2f}%  "
                f"满足 {s['condition_count']}/5  缺: {', '.join(s.get('missing_conditions', []))}  "
                f"带动性: {leader_str}"
            )
        lines.append("")

    pending = report.get("pending_confirmations", [])
    if pending:
        lines.append(f"待确认 ({len(pending)} 项):")
        for item in pending[:12]:
            if "buy_point" in item:
                lines.append(f"  {item['ts_code']} {item['buy_point']}  状态 {item['status']}  止损参考 {item.get('stop_loss')}")
                for check in item.get("manual_checks", [])[:2]:
                    lines.append(f"    ? {check}")
            else:
                lines.append(f"  {item.get('ts_code', '-')}: {item.get('reason', item)}")
        lines.append("")

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
        if item.get("risk_budget_label"):
            lines.append(f"    风险预算: {item['risk_budget_label']}（{item.get('risk_budget_reason', '')}）")
        failures = item.get("failure_signals", [])
        if failures:
            lines.append(f"    失败信号: {' / '.join(failures[:3])}")
    lines.append("")
