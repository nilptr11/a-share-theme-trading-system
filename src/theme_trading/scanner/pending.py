"""Pending buy point review workflow."""

from .buy_points import confirm_pending_buy_point
from .market_score import check_sector_climax
from .routing import route_signal
from .signals import build_signal_from_pending_review
from .types import DailyScanReport

PENDING_REVIEW_BUY_POINTS = {"买点二_主升回踩", "买点三_突破确认", "买点四_趋势均线"}


def review_pending_setups(
    report: DailyScanReport,
    pending_setups: list[dict] | None,
    *,
    trade_date: str,
    score: dict,
    theme_by_code: dict[str, dict],
    stock_by_code: dict[str, dict],
    market_closed: bool,
) -> None:
    for pending in pending_setups or []:
        buy_point_name = pending.get("buy_point")
        if buy_point_name not in PENDING_REVIEW_BUY_POINTS:
            continue

        ts_code = pending.get("ts_code")
        setup_date = pending.get("setup_date")
        if not ts_code or not setup_date:
            report["pending_reviews"].append({
                "status": "invalid",
                "reason": "pending setup 缺少 ts_code 或 setup_date",
                "source": pending,
            })
            continue

        stock = stock_by_code.get(ts_code) or {
            "ts_code": ts_code,
            "name": pending.get("name"),
            "sector_code": pending.get("sector_code"),
            "status": pending.get("core_status"),
            "amount_rank": pending.get("amount_rank"),
            "conditions": pending.get("conditions", {}),
        }
        sector_context = theme_by_code.get(pending.get("sector_code") or stock.get("sector_code"))
        stock_score = score
        if sector_context and check_sector_climax(sector_context)["climax"]:
            stock_score = dict(score)
            stock_score["emotion_extreme"] = True

        review = confirm_pending_buy_point(
            ts_code,
            setup_date,
            trade_date,
            buy_point_name,
            market_context=stock_score,
            sector_context=sector_context,
            core_context=stock,
        )
        report["pending_reviews"].append(review)
        if not review.get("ok"):
            report["blocked_reasons"].append(f"{ts_code} {buy_point_name} pending 回看失败: {review.get('reason')}")
            continue

        if not review.get("buy_point_info") or not review.get("buy_scan"):
            report["pending_confirmations"].append({
                **pending,
                "ts_code": ts_code,
                "buy_point": buy_point_name,
                "status": review.get("status", "pending_next_day_strength"),
                "reason": review.get("reason", "等待确认日数据"),
                "setup_date": setup_date,
            })
            continue

        signal = build_signal_from_pending_review(
            {**pending, "ts_code": ts_code, "setup_date": setup_date, "buy_point": buy_point_name},
            review,
            market_context=stock_score,
            theme_context=sector_context,
            core_stock=stock,
        )
        route_signal(
            report,
            signal,
            market_closed=market_closed,
            trial_mode=signal["plan_type"] == "trial",
            blocked_message=f"{ts_code} {buy_point_name} pending 回看状态 {signal.get('status')}，不生成人工执行预案",
        )
