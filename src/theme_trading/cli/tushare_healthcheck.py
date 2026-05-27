"""Tushare 数据健康检查命令。"""

import argparse
from datetime import datetime

from theme_trading.data.tushare_client import get_pro, is_tushare_auth_error


def _latest_date(df) -> str | None:
    if df is None or len(df) == 0 or "trade_date" not in df.columns:
        return None
    return str(df["trade_date"].astype(str).max())


def _status(df, trade_date: str, required_fields: set[str]) -> tuple[str, list[str]]:
    if df is None:
        return "error_or_none", ["接口返回 None"]
    if len(df) == 0:
        return "empty", ["接口返回 0 行"]

    notes = []
    latest = _latest_date(df)
    if latest is not None and latest != trade_date:
        notes.append(f"最新 trade_date={latest}，不是目标日期 {trade_date}")

    missing = sorted(required_fields - set(df.columns))
    if missing:
        notes.append("缺少字段: " + ", ".join(missing))

    if notes:
        return "stale_or_field_mismatch", notes
    return "ok", []


def _print_result(name: str, df, trade_date: str, required_fields: set[str]) -> None:
    status, notes = _status(df, trade_date, required_fields)
    rows = 0 if df is None else len(df)
    cols = [] if df is None else list(df.columns)
    latest = _latest_date(df) or "-"
    print(f"{name:18s} status={status:24s} rows={rows:<5d} latest={latest}")
    print(f"{'':18s} fields={', '.join(cols) if cols else '-'}")
    for note in notes:
        print(f"{'':18s} note={note}")


def run_healthcheck(trade_date: str) -> int:
    pro = get_pro()
    checks = [
        (
            "trade_cal",
            lambda: pro.trade_cal(exchange="SSE", start_date=trade_date, end_date=trade_date),
            {"cal_date", "is_open"},
        ),
        (
            "daily",
            lambda: pro.daily(trade_date=trade_date),
            {"ts_code", "trade_date", "close", "pct_chg", "amount"},
        ),
        (
            "index_daily_sh",
            lambda: pro.index_daily(ts_code="000001.SH", trade_date=trade_date),
            {"ts_code", "trade_date", "close", "pct_chg", "amount"},
        ),
        (
            "limit_list_d",
            lambda: pro.limit_list_d(trade_date=trade_date),
            {"ts_code", "trade_date", "limit", "limit_times"},
        ),
        (
            "limit_cpt_list",
            lambda: pro.limit_cpt_list(trade_date=trade_date),
            {"ts_code", "trade_date", "name", "days", "pct_chg"},
        ),
        (
            "ths_daily",
            lambda: pro.ths_daily(trade_date=trade_date),
            {"ts_code", "trade_date", "pct_change"},
        ),
    ]

    exit_code = 0
    print(f"Tushare healthcheck date={trade_date}")
    for name, fn, required_fields in checks:
        try:
            df = fn()
        except Exception as exc:
            exit_code = 1
            print(f"{name:18s} status=exception                rows=0     latest=-")
            print(f"{'':18s} note={type(exc).__name__}: {exc}")
            if is_tushare_auth_error(exc):
                print(f"{'':18s} note=鉴权失败，停止后续接口检查，避免触发更多未授权请求")
                break
            continue

        status, _ = _status(df, trade_date, required_fields)
        if status != "ok":
            exit_code = 1
        _print_result(name, df, trade_date, required_fields)

    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Tushare 关键接口健康检查")
    parser.add_argument("date", nargs="?", default=datetime.now().strftime("%Y%m%d"), help="交易日期 YYYYMMDD")
    args = parser.parse_args()
    raise SystemExit(run_healthcheck(args.date))


if __name__ == "__main__":
    main()
