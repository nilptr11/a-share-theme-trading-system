import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd

from theme_trading.scanner.buy_points import (
    _is_platform_consolidation,
    confirm_pending_buy_point,
    scan_buy_points,
)
from theme_trading.scanner.daily_scan import daily_scan
from theme_trading.scanner.market_score import _limit_counts, compute_market_score
from theme_trading.scanner.risk_budget import risk_budget_for_plan
from theme_trading.data.tushare_client import is_tushare_auth_error


def _trade_dates(start: str, count: int) -> list[str]:
    base = datetime.strptime(start, "%Y%m%d")
    return [(base + timedelta(days=i)).strftime("%Y%m%d") for i in range(count)]


def _daily_df(closes: list[float], amounts: list[float], start: str = "20260101") -> pd.DataFrame:
    dates = _trade_dates(start, len(closes))
    return pd.DataFrame({
        "trade_date": dates,
        "open": [round(close - 0.03, 2) for close in closes],
        "high": [round(close + 0.05, 2) for close in closes],
        "low": [round(close - 0.05, 2) for close in closes],
        "close": closes,
        "amount": amounts,
    })


class ScannerRuleTests(unittest.TestCase):
    def test_platform_consolidation_rejects_slow_one_way_rise(self):
        highs = np.array([10.06, 10.16, 10.26, 10.36, 10.45, 11.0])
        lows = np.array([9.96, 10.06, 10.16, 10.26, 10.36, 10.8])
        closes = np.array([10.0, 10.1, 10.2, 10.3, 10.4, 10.9])

        ok, details = _is_platform_consolidation(highs, lows, closes, today=5)

        self.assertFalse(ok)
        self.assertLessEqual(details["range_pct"], 0.05)
        self.assertFalse(details["close_drift_ok"])

    def test_bp3_short_history_uses_available_lookback(self):
        closes = [10 + i * 0.05 for i in range(25)]
        amounts = [1000] * 25
        df = _daily_df(closes, amounts)

        with patch("theme_trading.scanner.buy_points.fetch_daily", return_value=df):
            result = scan_buy_points("000001.SZ", "20260125")

        self.assertTrue(result["ok"])
        details = result["buy_points"]["买点三_突破确认"]["details"]
        self.assertEqual(details["high_60_lookback_days"], 24)

    def test_pending_bp2_can_confirm_on_next_trade_date(self):
        closes = [
            10.0, 10.1, 10.2, 10.3, 10.4,
            10.5, 10.6, 10.7, 10.8, 10.9,
            11.0, 11.1, 11.2, 11.3, 11.4,
            11.5, 11.6, 11.7, 11.8, 12.1,
            12.2, 12.3, 12.8, 12.7, 12.6,
            12.9, 12.95,
        ]
        amounts = [
            1500, 1500, 1500, 1500, 1500,
            1500, 1500, 1500, 1500, 1500,
            1500, 1500, 1500, 1500, 1500,
            1500, 1500, 1500, 1500, 1500,
            1500, 1400, 1300, 900, 600,
            800, 820,
        ]
        df = _daily_df(closes, amounts)
        df.loc[df["trade_date"] == "20260126", "open"] = 12.55

        with patch("theme_trading.scanner.buy_points.fetch_daily", return_value=df):
            result = confirm_pending_buy_point(
                "000001.SZ",
                "20260125",
                "20260126",
                "买点二_主升回踩",
                market_context={"score": 7},
                sector_context={"pct_chg": 1.0, "amount_ratio": 1.1},
                core_context={"ts_code": "000001.SZ", "status": "confirmed_core"},
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "executable_plan")
        self.assertTrue(result["triggered"])

    def test_risk_budget_trial_and_bp4_ratio_only(self):
        trial = risk_budget_for_plan({"score": 7}, "买点一_放量突破", plan_type="trial")
        bp4 = risk_budget_for_plan({"score": 6}, "买点四_趋势均线")

        self.assertEqual(trial["risk_budget_pct"], 0.005)
        self.assertEqual(bp4["risk_budget_pct"], 0.0025)
        self.assertNotIn("planned_shares", trial)

    def test_daily_scan_routes_pending_review_without_position_state(self):
        review = {
            "ok": True,
            "ts_code": "000001.SZ",
            "buy_point": "买点二_主升回踩",
            "setup_date": "20260125",
            "confirm_date": "20260126",
            "execution_date": None,
            "status": "pending_next_open",
            "triggered": True,
            "setup_triggered": True,
            "buy_scan": {
                "setup_date": "20260125",
                "confirm_date": "20260126",
                "execution_date": None,
                "close": 12.9,
                "suppressed_by_priority": [],
            },
            "buy_point_info": {
                "status": "pending_next_open",
                "stop_loss": 12.1,
                "execution_check": {"confirm_close": 12.9},
                "failure_signals": [],
                "manual_checks": [],
                "triggered": True,
                "setup_triggered": True,
            },
        }

        with (
            patch("theme_trading.scanner.daily_scan.clear_cache"),
            patch("theme_trading.scanner.daily_scan.compute_market_score", return_value={
                "score": 7,
                "trade_permission": "open",
                "hard_rules": {"violations": []},
                "human_judgment": [],
                "data_warnings": [],
                "emotion_extreme": False,
            }),
            patch("theme_trading.scanner.daily_scan.find_main_themes", return_value={
                "confirmed_themes": [{"ts_code": "881001.TI", "status": "confirmed"}],
                "watch_themes": [],
                "human_judgment": [],
                "data_warnings": [],
            }),
            patch("theme_trading.scanner.daily_scan.filter_core_stocks", return_value={
                "confirmed_core_stocks": [{
                    "ts_code": "000001.SZ",
                    "sector_code": "881001.TI",
                    "status": "confirmed_core",
                }],
                "watch_core_stocks": [],
                "human_judgment": [],
                "data_warnings": [],
            }),
            patch("theme_trading.scanner.daily_scan.check_sector_climax", return_value={
                "climax": False,
                "reasons": [],
                "action_notes": [],
            }),
            patch("theme_trading.scanner.daily_scan.confirm_pending_buy_point", return_value=review),
            patch("theme_trading.scanner.daily_scan.scan_buy_points", return_value={
                "ok": True,
                "selected_buy_point": None,
            }),
            patch("theme_trading.scanner.daily_scan.pre_trade_checklist", return_value={
                "all_passed": True,
                "checks": {},
                "three_questions": {},
                "block_reasons": [],
            }),
        ):
            report = daily_scan(
                "20260126",
                pending_setups=[{
                    "ts_code": "000001.SZ",
                    "setup_date": "20260125",
                    "buy_point": "买点二_主升回踩",
                }],
            )

        self.assertEqual(len(report["executable_plans"]), 1)
        self.assertEqual(report["executable_plans"][0]["source"], "pending_setup_review")
        self.assertEqual(report["executable_plans"][0]["risk_budget_pct"], 0.01)

    def test_limit_counts_accepts_limit_list_d_fields(self):
        limit_df = pd.DataFrame({
            "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
            "limit": ["U", "D", "Z"],
            "limit_times": [1, 1, 0],
        })

        self.assertEqual(_limit_counts(limit_df), (1, 1, 1, []))

    def test_market_score_skips_stale_index_range_data(self):
        stale_index = pd.DataFrame({
            "trade_date": [f"202601{day:02d}" for day in range(1, 22)],
            "close": [100 + day for day in range(21)],
            "pct_chg": [0.1] * 21,
            "amount": [1000] * 21,
        })

        with (
            patch("theme_trading.scanner.market_score.fetch_index_daily", return_value=stale_index),
            patch("theme_trading.scanner.market_score.fetch_limit_list", return_value=None),
            patch("theme_trading.scanner.market_score.fetch_limit_cpt_list", return_value=None),
            patch("theme_trading.scanner.market_score.fetch_daily", return_value=None),
        ):
            result = compute_market_score("20260122")

        self.assertEqual(result["index_score"], 0)
        self.assertNotIn("sh_close", result["details"])
        self.assertTrue(any("早于扫描日期 20260122" in item for item in result["data_warnings"]))

    def test_tushare_auth_error_detection(self):
        self.assertTrue(is_tushare_auth_error(Exception("tenant key expired (contact admin to renew)")))
        self.assertTrue(is_tushare_auth_error(Exception("server refused due to unauthorized access attempts")))
        self.assertFalse(is_tushare_auth_error(Exception("temporary network timeout")))


if __name__ == "__main__":
    unittest.main()
