import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from theme_trading.scanner.core_stocks import _leader_effect_approximation, _relative_strength
from theme_trading.scanner.sell_rules import evaluate_must_sell
from theme_trading.scanner.signals import build_signal_from_buy_scan
from theme_trading.scanner.pre_trade import pre_trade_checklist
from theme_trading.scanner.daily_scan import daily_scan
from theme_trading.scanner.buy_point_rules import rate_buy_point_strength
from theme_trading.scanner.buy_points import scan_buy_points
from theme_trading.scanner.execution import build_execution_confirmation
from theme_trading.scanner.plans import build_decision_plan, save_decision_plan
from theme_trading.scanner.utils import _select_highest_priority_buy_point
from theme_trading.cli.render_daily_scan import render_daily_scan_report, render_execution_confirmation


def _daily_df(closes, amounts=None):
    amounts = amounts or [1000] * len(closes)
    rows = []
    for i, close in enumerate(closes, start=1):
        rows.append({
            "trade_date": f"202601{i:02d}",
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "amount": amounts[i - 1],
        })
    return pd.DataFrame(rows)


class SignalLayeringTest(unittest.TestCase):
    @patch("theme_trading.scanner.buy_points.fetch_daily")
    def test_close_decision_scan_does_not_upgrade_to_executable_plan(self, fetch_daily):
        closes = [10.0] * 24 + [10.0, 10.2, 11.0]
        amounts = [1000] * 24 + [1800, 1000, 2000]
        df = _daily_df(closes, amounts)
        df.loc[18:23, "low"] = [9.98, 9.99, 10.0, 10.01, 10.02, 10.03]
        df.loc[18:23, "high"] = [10.08, 10.09, 10.1, 10.11, 10.12, 10.13]
        df.loc[18:23, "close"] = [10.03, 10.04, 10.05, 10.06, 10.07, 10.08]
        df.loc[24, "open"] = 10.05
        df.loc[24, "high"] = 10.4
        df.loc[24, "low"] = 9.9
        df.loc[24, "close"] = 10.35
        df.loc[25, "open"] = 10.25
        df.loc[25, "close"] = 11.0
        df.loc[25, "high"] = 11.1
        df.loc[26, "open"] = 11.1
        fetch_daily.return_value = df

        result = scan_buy_points("000001.SZ", "20260125", allow_execution_check=False)

        info = result["buy_points"]["买点一_放量突破"]
        self.assertTrue(info["setup_triggered"])
        self.assertEqual(info["status"], "pending_next_open")
        self.assertEqual(info["execution_check"]["gap_check"]["checked"], False)
        self.assertEqual(result["phase"], "close_decision")

    @patch("theme_trading.scanner.buy_points.fetch_trade_cal")
    @patch("theme_trading.scanner.buy_points.fetch_daily")
    def test_close_decision_scan_does_not_use_future_close_for_strength_confirmation(self, fetch_daily, fetch_trade_cal):
        closes = [10.0] * 30
        amounts = [1000] * 30
        df = _daily_df(closes, amounts)
        df.loc[24:26, "close"] = [11.0, 10.8, 11.2]
        df.loc[24:26, "open"] = [10.9, 10.7, 10.9]
        df.loc[24:26, "high"] = [11.2, 11.0, 11.4]
        df.loc[24:26, "low"] = [10.7, 10.6, 10.8]
        df.loc[24:26, "amount"] = [2000, 800, 1800]
        fetch_daily.return_value = df
        fetch_trade_cal.return_value = pd.DataFrame([
            {"cal_date": "20260125", "is_open": "1"},
            {"cal_date": "20260126", "is_open": "1"},
            {"cal_date": "20260127", "is_open": "1"},
        ])

        result = scan_buy_points("000001.SZ", "20260125", allow_execution_check=False)

        info = result["buy_points"]["买点二_主升回踩"]
        self.assertIsNone(info["details"]["next_strength_ok"])
        self.assertEqual(info["status"], "pending_next_day_strength" if info["setup_triggered"] else "not_triggered")
        self.assertEqual(info["confirm_date"], "20260126")
        self.assertEqual(info["execution_date"], "20260127")

    @patch("theme_trading.scanner.sell_rules.fetch_daily")
    def test_ma_break_is_diagnostic_not_must_sell(self, fetch_daily):
        fetch_daily.return_value = _daily_df([10] * 29 + [9.8])

        result = evaluate_must_sell("000001.SZ", "20260130")

        self.assertFalse(result["must_sell"])
        self.assertEqual(result["triggered_signals"], [])
        self.assertIn("5 日线", result["diagnostic_signals"][0])
        self.assertIn("10 日线", result["diagnostic_signals"][1])

    @patch("theme_trading.scanner.sell_rules.fetch_daily")
    def test_stop_loss_still_triggers_must_sell(self, fetch_daily):
        fetch_daily.return_value = _daily_df([10] * 29 + [9.8])

        result = evaluate_must_sell("000001.SZ", "20260130", {"stop_loss": 9.9})

        self.assertTrue(result["must_sell"])
        self.assertIn("收盘价跌破止损参考位", result["triggered_signals"])

    def test_strength_counts_numpy_bool_values(self):
        result = rate_buy_point_strength("买点一_放量突破", {
            "setup_triggered": np.bool_(True),
            "triggered": np.bool_(True),
            "status": "executable_plan",
            "details": {
                "amount_ratio": 2.1,
                "consolidation_5d_range": 0.02,
                "close_confirm": np.bool_(True),
                "sector_follow": np.bool_(True),
            },
        })

        self.assertEqual(result["strength_level"], "strong")
        self.assertEqual(result["strength_score"], 7)

    def test_pre_trade_check_accepts_numpy_bool_values(self):
        result = pre_trade_checklist(
            market_context={"score": 6},
            theme_context={"status": "confirmed"},
            core_stock={"ts_code": "000001.SZ", "name": "测试股", "status": "confirmed_core"},
            buy_point_info={
                "triggered": np.bool_(True),
                "setup_triggered": False,
                "stop_loss": 9.5,
                "details": {},
                "failure_signals": [],
            },
            buy_point_name="买点一_放量突破",
        )

        self.assertTrue(result["all_passed"])
        self.assertTrue(result["checks"]["valid_buy_point"])

    def test_selector_skips_invalid_high_priority_buy_point(self):
        selected, suppressed = _select_highest_priority_buy_point({
            "买点一_放量突破": {
                "priority": 1,
                "setup_triggered": True,
                "triggered": False,
                "status": "invalid",
            },
            "买点三_突破确认": {
                "priority": 2,
                "setup_triggered": True,
                "triggered": True,
                "status": "executable_plan",
            },
        })

        self.assertEqual(selected, "买点三_突破确认")
        self.assertEqual(suppressed, [])

    def test_buy_signal_carries_strength(self):
        stock = {
            "ts_code": "000001.SZ",
            "name": "测试股",
            "sector_code": "881001.TI",
            "status": "confirmed_core",
            "amount_rank": 1,
            "conditions": {},
        }
        buy_scan = {
            "setup_date": "20260130",
            "confirm_date": "20260130",
            "execution_date": "20260131",
            "close": 10.0,
            "suppressed_by_priority": [],
            "buy_points": {
                "买点一_放量突破": {
                    "triggered": True,
                    "setup_triggered": True,
                    "status": "executable_plan",
                    "stop_loss": 9.5,
                    "execution_check": {"confirm_close": 10.0},
                    "failure_signals": [],
                    "manual_checks": [],
                    "strength_score": 6,
                    "strength_level": "strong",
                    "strength_reasons": ["放量 2.0 倍"],
                }
            },
        }

        signal = build_signal_from_buy_scan(
            stock,
            buy_scan,
            "买点一_放量突破",
            market_context={"score": 6},
            theme_context={"status": "confirmed"},
            trial_mode=False,
        )

        self.assertEqual(signal["strength_level"], "strong")
        self.assertEqual(signal["strength_score"], 6)
        self.assertEqual(signal["strength_reasons"], ["放量 2.0 倍"])

    def test_core_stock_strength_and_leader_evidence(self):
        dates = [f"2026010{i}" for i in range(1, 6)]
        rows = []
        for ts_code, pct_values in {
            "A": [2.0, -1.0, 3.0, -0.5, 1.0],
            "B": [1.0, -2.0, 1.0, -1.0, 0.5],
            "C": [1.0, -1.5, 0.5, -1.0, 0.2],
        }.items():
            for trade_date, pct_chg in zip(dates, pct_values):
                rows.append({"ts_code": ts_code, "trade_date": trade_date, "pct_chg": pct_chg})
        hist = pd.DataFrame(rows)
        members = {"S": {"A", "B", "C"}}

        relative, relative_evidence = _relative_strength("A", "S", hist, members)
        leader, _, leader_evidence = _leader_effect_approximation("A", "S", hist, members)

        self.assertTrue(relative)
        self.assertEqual(relative_evidence["defensive_days"], 2)
        self.assertEqual(relative_evidence["divergence_days"], 2)
        self.assertTrue(leader)
        self.assertGreater(leader_evidence["up_breadth"], leader_evidence["down_breadth"])

    def test_relative_strength_requires_other_sector_members(self):
        hist = pd.DataFrame([
            {"ts_code": "A", "trade_date": "20260101", "pct_chg": 2.0},
            {"ts_code": "A", "trade_date": "20260102", "pct_chg": -1.0},
            {"ts_code": "A", "trade_date": "20260103", "pct_chg": 1.0},
        ])

        relative, evidence = _relative_strength("A", "S", hist, {"S": {"A"}})

        self.assertIsNone(relative)
        self.assertEqual(evidence["reason"], "无同板块其它个股数据")

    def test_leader_effect_requires_other_sector_members(self):
        hist = pd.DataFrame([
            {"ts_code": "A", "trade_date": "20260101", "pct_chg": 2.0},
            {"ts_code": "A", "trade_date": "20260102", "pct_chg": -1.0},
            {"ts_code": "A", "trade_date": "20260103", "pct_chg": 1.0},
        ])

        leader, note, evidence = _leader_effect_approximation("A", "S", hist, {"S": {"A"}})

        self.assertIsNone(leader)
        self.assertIn("无同板块其它个股数据", note)
        self.assertIsNone(evidence["up_breadth"])

    def test_leader_effect_requires_up_and_down_peer_data(self):
        hist = pd.DataFrame([
            {"ts_code": "A", "trade_date": "20260101", "pct_chg": 2.0},
            {"ts_code": "A", "trade_date": "20260102", "pct_chg": -1.0},
            {"ts_code": "A", "trade_date": "20260103", "pct_chg": 1.0},
            {"ts_code": "B", "trade_date": "20260101", "pct_chg": 1.0},
            {"ts_code": "B", "trade_date": "20260103", "pct_chg": 0.5},
        ])

        leader, note, _ = _leader_effect_approximation("A", "S", hist, {"S": {"A", "B"}})

        self.assertIsNone(leader)
        self.assertIn("对照日期板块数据不足", note)

    @patch("theme_trading.scanner.daily_scan.route_signal")
    @patch("theme_trading.scanner.daily_scan.scan_buy_points")
    @patch("theme_trading.scanner.daily_scan.filter_core_stocks")
    @patch("theme_trading.scanner.daily_scan.find_main_themes")
    @patch("theme_trading.scanner.daily_scan.compute_market_score")
    @patch("theme_trading.scanner.daily_scan.clear_cache")
    def test_watch_theme_buy_shapes_are_not_routed_when_confirmed_theme_exists(self, clear_cache, compute_market_score, find_main_themes, filter_core_stocks, scan_buy_points, route_signal):
        compute_market_score.return_value = {
            "score": 6,
            "trade_permission": "open",
            "hard_rules": {"violations": []},
            "human_judgment": [],
        }
        find_main_themes.return_value = {
            "confirmed_themes": [{"ts_code": "CONF", "name": "确认主线", "status": "confirmed", "condition_count": 3, "missing_conditions": []}],
            "watch_themes": [{"ts_code": "WATCH", "name": "观察主线", "status": "watch", "condition_count": 2, "missing_conditions": ["amount_expand_2d"]}],
            "human_judgment": [],
        }

        def stocks_for(_, sector_codes):
            if sector_codes == ["CONF"]:
                return {"confirmed_core_stocks": [{"ts_code": "CONF_STOCK", "name": "确认股", "sector_code": "CONF", "status": "confirmed_core"}], "watch_core_stocks": [], "human_judgment": []}
            return {"confirmed_core_stocks": [], "watch_core_stocks": [{"ts_code": "WATCH_STOCK", "name": "观察股", "sector_code": "WATCH", "status": "watch_core"}], "human_judgment": ["仅筛选出观察核心股"]}

        filter_core_stocks.side_effect = stocks_for

        def buy_points_for(ts_code, *_args, **_kwargs):
            if ts_code == "CONF_STOCK":
                return {"ok": True, "selected_buy_point": None, "setup_list": [], "buy_points": {}}
            return {
                "ok": True,
                "selected_buy_point": "买点一_放量突破",
                "setup_list": ["买点一_放量突破"],
                "buy_points": {
                    "买点一_放量突破": {
                        "setup_triggered": True,
                        "triggered": False,
                        "status": "pending_next_open",
                        "strength_score": 4,
                        "strength_level": "medium",
                        "strength_reasons": ["买点形态成立"],
                    }
                },
            }

        scan_buy_points.side_effect = buy_points_for

        report = daily_scan("20260130")

        self.assertNotIn("仅筛选出观察核心股", report["human_judgment"])
        self.assertEqual(report["watch_buy_shapes"][0]["theme_human_judgment"], ["仅筛选出观察核心股"])
        self.assertEqual(report["pending_open_plans"], [])
        self.assertEqual(report["trial_plans"], [])
        self.assertEqual(len(report["watch_buy_shapes"]), 1)
        self.assertFalse(report["watch_buy_shapes"][0]["actionable"])
        route_signal.assert_not_called()

    @patch("theme_trading.scanner.daily_scan.scan_buy_points")
    @patch("theme_trading.scanner.daily_scan.filter_core_stocks")
    @patch("theme_trading.scanner.daily_scan.find_main_themes")
    @patch("theme_trading.scanner.daily_scan.compute_market_score")
    @patch("theme_trading.scanner.daily_scan.clear_cache")
    def test_watch_shapes_respect_requested_sector_codes(self, clear_cache, compute_market_score, find_main_themes, filter_core_stocks, scan_buy_points):
        compute_market_score.return_value = {
            "score": 6,
            "trade_permission": "open",
            "hard_rules": {"violations": []},
            "human_judgment": [],
        }
        find_main_themes.return_value = {
            "confirmed_themes": [{"ts_code": "CONF", "name": "确认主线", "status": "confirmed", "condition_count": 3, "missing_conditions": []}],
            "watch_themes": [{"ts_code": "WATCH", "name": "观察主线", "status": "watch", "condition_count": 2, "missing_conditions": []}],
            "human_judgment": [],
        }
        filter_core_stocks.return_value = {
            "confirmed_core_stocks": [{"ts_code": "CONF_STOCK", "name": "确认股", "sector_code": "CONF", "status": "confirmed_core"}],
            "watch_core_stocks": [],
            "human_judgment": [],
        }
        scan_buy_points.return_value = {"ok": True, "selected_buy_point": None, "setup_list": [], "buy_points": {}}

        report = daily_scan("20260130", sector_codes=["CONF"])

        self.assertEqual(report["watch_buy_shapes"], [])
        filter_core_stocks.assert_called_once_with("20260130", ["CONF"])

    @patch("theme_trading.scanner.daily_scan.scan_buy_points")
    @patch("theme_trading.scanner.daily_scan.filter_core_stocks")
    @patch("theme_trading.scanner.daily_scan.find_main_themes")
    @patch("theme_trading.scanner.daily_scan.compute_market_score")
    @patch("theme_trading.scanner.daily_scan.clear_cache")
    def test_trial_mode_does_not_duplicate_watch_shapes(self, clear_cache, compute_market_score, find_main_themes, filter_core_stocks, scan_buy_points):
        compute_market_score.return_value = {
            "score": 6,
            "trade_permission": "open",
            "hard_rules": {"violations": []},
            "human_judgment": [],
        }
        find_main_themes.return_value = {
            "confirmed_themes": [],
            "watch_themes": [{"ts_code": "WATCH", "name": "观察主线", "status": "watch", "condition_count": 2, "missing_conditions": []}],
            "human_judgment": [],
        }
        filter_core_stocks.return_value = {
            "confirmed_core_stocks": [],
            "watch_core_stocks": [{"ts_code": "WATCH_STOCK", "name": "观察股", "sector_code": "WATCH", "status": "watch_core"}],
            "human_judgment": [],
        }
        scan_buy_points.return_value = {"ok": True, "selected_buy_point": None, "setup_list": [], "buy_points": {}}

        report = daily_scan("20260130")

        self.assertEqual(report["watch_buy_shapes"], [])

    @patch("theme_trading.scanner.daily_scan.scan_buy_points")
    @patch("theme_trading.scanner.daily_scan.filter_core_stocks")
    def test_watch_theme_shapes_select_observable_point_when_invalid_has_higher_priority(self, filter_core_stocks, scan_buy_points):
        from theme_trading.scanner.daily_scan import _scan_watch_theme_buy_shapes

        report = {"watch_buy_shapes": [], "human_judgment": [], "data_warnings": []}
        filter_core_stocks.return_value = {
            "confirmed_core_stocks": [],
            "watch_core_stocks": [{"ts_code": "WATCH_STOCK", "name": "观察股", "sector_code": "WATCH", "status": "watch_core"}],
        }
        scan_buy_points.return_value = {
            "ok": True,
            "selected_buy_point": "买点一_放量突破",
            "buy_points": {
                "买点一_放量突破": {
                    "priority": 1,
                    "status": "invalid",
                    "setup_triggered": True,
                },
                "买点二_主升回踩": {
                    "priority": 3,
                    "status": "pending_next_open",
                    "setup_triggered": True,
                    "triggered": True,
                    "confirm_date": "20260131",
                    "execution_date": "20260201",
                    "stop_loss": 9.8,
                    "execution_check": {"rule": "次日开盘 ±3%"},
                    "failure_signals": ["收盘跌破止损位"],
                    "strength_score": 4,
                    "strength_level": "medium",
                    "strength_reasons": ["回踩明显缩量"],
                },
            },
        }

        _scan_watch_theme_buy_shapes(
            report,
            [{"ts_code": "WATCH", "name": "观察主线", "status": "watch", "condition_count": 2, "missing_conditions": []}],
            trade_date="20260130",
            score={"score": 6},
        )

        self.assertEqual(len(report["watch_buy_shapes"]), 1)
        item = report["watch_buy_shapes"][0]
        self.assertEqual(item["buy_point"], "买点二_主升回踩")
        self.assertEqual(item["stop_loss"], 9.8)
        self.assertEqual(item["confirm_date"], "20260131")
        self.assertEqual(item["execution_date"], "20260201")
        self.assertEqual(item["failure_signals"], ["收盘跌破止损位"])

    @patch("theme_trading.scanner.daily_scan.scan_buy_points")
    @patch("theme_trading.scanner.daily_scan.filter_core_stocks")
    def test_watch_theme_shapes_scan_cache_is_theme_scoped(self, filter_core_stocks, scan_buy_points):
        from theme_trading.scanner.daily_scan import _scan_watch_theme_buy_shapes

        report = {"watch_buy_shapes": [], "human_judgment": [], "data_warnings": []}
        filter_core_stocks.return_value = {
            "confirmed_core_stocks": [],
            "watch_core_stocks": [{"ts_code": "WATCH_STOCK", "name": "观察股", "sector_code": "WATCH", "status": "watch_core"}],
        }
        scan_buy_points.return_value = {
            "ok": True,
            "buy_points": {
                "买点一_放量突破": {
                    "priority": 1,
                    "setup_triggered": True,
                    "triggered": False,
                    "status": "pending_next_open",
                }
            },
        }

        _scan_watch_theme_buy_shapes(
            report,
            [
                {"ts_code": "WATCH1", "name": "观察主线1", "status": "watch", "condition_count": 2, "missing_conditions": []},
                {"ts_code": "WATCH2", "name": "观察主线2", "status": "watch", "condition_count": 2, "missing_conditions": []},
            ],
            trade_date="20260130",
            score={"score": 6},
        )

        self.assertEqual(len(report["watch_buy_shapes"]), 1)
        self.assertEqual(scan_buy_points.call_count, 2)

    @patch("theme_trading.scanner.daily_scan.scan_buy_points")
    @patch("theme_trading.scanner.daily_scan.filter_core_stocks")
    def test_watch_theme_shapes_deduplicate_same_stock_and_buy_point(self, filter_core_stocks, scan_buy_points):
        from theme_trading.scanner.daily_scan import _scan_watch_theme_buy_shapes

        report = {"watch_buy_shapes": [], "human_judgment": [], "data_warnings": []}
        filter_core_stocks.return_value = {
            "confirmed_core_stocks": [],
            "watch_core_stocks": [{"ts_code": "WATCH_STOCK", "name": "观察股", "sector_code": "WATCH", "status": "watch_core"}],
        }
        scan_buy_points.return_value = {
            "ok": True,
            "buy_points": {
                "买点一_放量突破": {
                    "priority": 1,
                    "setup_triggered": True,
                    "triggered": False,
                    "status": "pending_next_open",
                }
            },
        }

        _scan_watch_theme_buy_shapes(
            report,
            [
                {"ts_code": "WATCH1", "name": "观察主线1", "status": "watch", "condition_count": 2, "missing_conditions": []},
                {"ts_code": "WATCH2", "name": "观察主线2", "status": "watch", "condition_count": 2, "missing_conditions": []},
            ],
            trade_date="20260130",
            score={"score": 6},
        )

        self.assertEqual(len(report["watch_buy_shapes"]), 1)
        self.assertEqual(scan_buy_points.call_count, 2)

    @patch("theme_trading.scanner.daily_scan.route_signal")
    @patch("theme_trading.scanner.daily_scan.scan_buy_points")
    @patch("theme_trading.scanner.daily_scan.filter_core_stocks")
    @patch("theme_trading.scanner.daily_scan.find_main_themes")
    @patch("theme_trading.scanner.daily_scan.compute_market_score")
    @patch("theme_trading.scanner.daily_scan.clear_cache")
    def test_current_scan_reports_invalid_setup_instead_of_no_buy_point(self, clear_cache, compute_market_score, find_main_themes, filter_core_stocks, scan_buy_points, route_signal):
        compute_market_score.return_value = {
            "score": 6,
            "trade_permission": "open",
            "hard_rules": {"violations": []},
            "human_judgment": [],
        }
        find_main_themes.return_value = {
            "confirmed_themes": [{"ts_code": "CONF", "name": "确认主线", "status": "confirmed", "condition_count": 3, "missing_conditions": []}],
            "watch_themes": [],
            "human_judgment": [],
        }
        filter_core_stocks.return_value = {
            "confirmed_core_stocks": [{"ts_code": "CONF_STOCK", "name": "确认股", "sector_code": "CONF", "status": "confirmed_core"}],
            "watch_core_stocks": [],
            "human_judgment": [],
        }
        scan_buy_points.return_value = {
            "ok": True,
            "selected_buy_point": None,
            "setup_list": ["买点一_放量突破"],
            "buy_points": {
                "买点一_放量突破": {
                    "setup_triggered": True,
                    "triggered": False,
                    "status": "invalid",
                    "stop_loss": 9.8,
                    "execution_check": {"gap_check": {"checked": True, "passed": False}},
                    "failure_signals": ["次日低开低走"],
                    "manual_checks": [],
                    "strength_score": 3,
                    "strength_level": "medium",
                    "strength_reasons": ["买点形态成立"],
                }
            },
        }

        report = daily_scan("20260130")

        invalid_items = [item for item in report["observation_pool"] if item.get("category") == "invalid_buy_setup"]
        self.assertEqual(len(invalid_items), 1)
        self.assertEqual(invalid_items[0]["buy_point"], "买点一_放量突破")
        self.assertEqual(invalid_items[0]["execution_check"]["gap_check"]["passed"], False)
        self.assertFalse(any(item.get("category") == "core_no_buy_point" for item in report["observation_pool"]))
        route_signal.assert_not_called()

    @patch("theme_trading.scanner.daily_scan.scan_buy_points")
    @patch("theme_trading.scanner.daily_scan.filter_core_stocks")
    @patch("theme_trading.scanner.daily_scan.find_main_themes")
    @patch("theme_trading.scanner.daily_scan.compute_market_score")
    @patch("theme_trading.scanner.daily_scan.clear_cache")
    def test_no_plan_diagnostics_counts_buy_point_scan_failure(self, clear_cache, compute_market_score, find_main_themes, filter_core_stocks, scan_buy_points):
        compute_market_score.return_value = {
            "score": 8,
            "market_level": "strong",
            "trade_permission": "open",
            "index_score": 2,
            "volume_score": 2,
            "sentiment_score": 2,
            "theme_score": 2,
            "details": {},
            "hard_rules": {"violations": []},
            "human_judgment": [],
        }
        find_main_themes.return_value = {
            "confirmed_themes": [{
                "ts_code": "CONF",
                "name": "高潮主线",
                "status": "confirmed",
                "condition_count": 4,
                "missing_conditions": [],
                "pct_chg": 4.5,
                "consecutive_days": 2,
                "amount_ratio": 2.0,
                "up_in_sector": 9,
            }],
            "watch_themes": [],
            "human_judgment": [],
        }
        filter_core_stocks.return_value = {
            "confirmed_core_stocks": [{
                "ts_code": "688820.SH",
                "name": "核心股",
                "sector_code": "CONF",
                "status": "confirmed_core",
                "pct_chg": 3.0,
                "condition_count": 4,
                "amount_rank": 1,
                "sector_amount_rank": 1,
                "turnover_rate": 8.5,
            }],
            "watch_core_stocks": [],
            "human_judgment": [],
        }
        scan_buy_points.return_value = {"ok": False, "error": "确认日前历史数据不足"}

        report = daily_scan("20260525")
        rendered = render_daily_scan_report(report)

        diagnostics = report["no_plan_diagnostics"]
        self.assertFalse(diagnostics["has_plan"])
        self.assertEqual(diagnostics["market_gate"], "open")
        self.assertEqual(diagnostics["confirmed_theme_count"], 1)
        self.assertEqual(diagnostics["confirmed_core_count"], 1)
        self.assertEqual(diagnostics["scan_failure_count"], 1)
        self.assertEqual(diagnostics["pending_confirmation_count"], 0)
        self.assertIn("buy_point_scan_failed", diagnostics["reason_codes"])
        self.assertIn("risk_notes", diagnostics["reason_codes"])
        self.assertIn("无人工执行预案诊断", rendered)
        self.assertIn("买点扫描失败: 1", rendered)
        self.assertIn("确认日前历史数据不足", report["pending_confirmations"][0]["reason"])
        self.assertNotIn("待确认 (1 项)", rendered)

    def test_render_shows_invalid_buy_setup_diagnostics(self):
        report = {
            "market_score": {
                "score": 6,
                "market_level": "medium",
                "trade_permission": "open",
                "index_score": 1,
                "volume_score": 1,
                "sentiment_score": 2,
                "theme_score": 2,
                "details": {},
                "hard_rules": {"violations": []},
                "human_judgment": [],
            },
            "themes": {},
            "core_stocks": {},
            "pending_confirmations": [],
            "watch_buy_shapes": [],
            "pending_open_plans": [],
            "trial_plans": [],
            "pre_trade_checks": [],
            "blocked_reasons": [],
            "data_warnings": [],
            "human_judgment": [],
            "observation_pool": [{
                "category": "invalid_buy_setup",
                "ts_code": "CONF_STOCK",
                "name": "确认股",
                "buy_point": "买点一_放量突破",
                "status": "invalid",
                "stop_loss": 9.8,
                "execution_check": {"gap_check": {"checked": True, "passed": False, "gap_pct": 0.05}},
                "failure_signals": ["次日低开低走"],
                "strength_score": 3,
                "strength_level": "medium",
                "strength_reasons": ["买点形态成立"],
                "reason": "买点形态出现但执行条件已失效，不生成人工执行预案",
            }],
        }

        rendered = render_daily_scan_report(report)

        self.assertIn("已失效买点形态", rendered)
        self.assertIn("CONF_STOCK", rendered)
        self.assertIn("超出执行范围", rendered)
        self.assertIn("买点形态出现但执行条件已失效", rendered)

    @patch("theme_trading.scanner.daily_scan.scan_buy_points")
    @patch("theme_trading.scanner.daily_scan.filter_core_stocks")
    def test_watch_theme_shapes_skip_invalid_status(self, filter_core_stocks, scan_buy_points):
        from theme_trading.scanner.daily_scan import _scan_watch_theme_buy_shapes

        report = {"watch_buy_shapes": [], "human_judgment": [], "data_warnings": []}
        filter_core_stocks.return_value = {
            "confirmed_core_stocks": [],
            "watch_core_stocks": [{"ts_code": "WATCH_STOCK", "name": "观察股", "sector_code": "WATCH", "status": "watch_core"}],
        }
        scan_buy_points.return_value = {
            "ok": True,
            "selected_buy_point": "买点一_放量突破",
            "setup_list": ["买点一_放量突破"],
            "buy_points": {
                "买点一_放量突破": {
                    "setup_triggered": True,
                    "triggered": False,
                    "status": "invalid",
                    "strength_score": 1,
                    "strength_level": "weak",
                    "strength_reasons": [],
                }
            },
        }

        _scan_watch_theme_buy_shapes(
            report,
            [{"ts_code": "WATCH", "name": "观察主线", "status": "watch", "condition_count": 2, "missing_conditions": []}],
            trade_date="20260130",
            score={"score": 6},
        )

        self.assertEqual(report["watch_buy_shapes"], [])

    def test_build_decision_plan_contains_full_snapshot_and_pending_plans(self):
        report = {
            "trade_date": "20260130",
            "decision_date": "20260130",
            "latest_complete_trade_date": "20260130",
            "phase": "close_decision",
            "market_score": {"score": 6},
            "themes": {"confirmed_themes": [{"ts_code": "THEME", "name": "主线"}]},
            "core_stocks": {"confirmed_core_stocks": [{"ts_code": "000001.SZ"}]},
            "pending_open_plans": [{
                "ts_code": "000001.SZ",
                "buy_point": "买点一_放量突破",
                "status": "pending_next_open",
                "setup_date": "20260130",
                "confirm_date": "20260130",
                "execution_date": "20260202",
                "close": 10.0,
                "stop_loss": 9.5,
                "execution_check": {"confirm_close": 10.0, "rule": "次日开盘价相对确认日收盘价在 ±3% 内才可进入人工执行确认窗口"},
                "risk_budget_label": "标准",
                "failure_signals": ["次日低开低走"],
            }],
            "trial_plans": [],
        }

        plan = build_decision_plan(report, created_at="2026-01-30T18:00:00")

        self.assertEqual(plan["phase"], "close_decision")
        self.assertEqual(plan["decision_date"], "20260130")
        self.assertEqual(plan["latest_complete_trade_date"], "20260130")
        self.assertEqual(plan["planned_execution_date"], "20260202")
        self.assertEqual(plan["report"]["market_score"], {"score": 6})
        self.assertEqual(plan["plans"][0]["status"], "pending_next_open")
        self.assertEqual(plan["plans"][0]["planned_execution_date"], "20260202")
        self.assertEqual(plan["plans"][0]["failure_signals"], ["次日低开低走"])

    def test_save_plan_writes_json_snapshot(self):
        report = {
            "trade_date": "20260130",
            "decision_date": "20260130",
            "latest_complete_trade_date": "20260130",
            "market_score": {"score": 6},
            "pending_open_plans": [],
            "trial_plans": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "plan.json"
            _, path = save_decision_plan(report, output)
            data = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(data["phase"], "close_decision")
        self.assertEqual(data["report"]["market_score"]["score"], 6)
        self.assertEqual(data["plans"], [])

    @patch("theme_trading.scanner.execution.fetch_daily")
    def test_confirm_open_does_not_mutate_plan_and_generates_confirmation(self, fetch_daily):
        plan = {
            "phase": "close_decision",
            "decision_date": "20260130",
            "latest_complete_trade_date": "20260130",
            "planned_execution_date": "20260202",
            "plans": [{
                "ts_code": "000001.SZ",
                "name": "测试股",
                "buy_point": "买点一_放量突破",
                "plan_type": "standard",
                "status": "pending_next_open",
                "setup_date": "20260130",
                "confirm_date": "20260130",
                "planned_execution_date": "20260202",
                "close": 10.0,
                "stop_loss": 9.5,
            }],
        }
        original = json.loads(json.dumps(plan, ensure_ascii=False))
        fetch_daily.return_value = pd.DataFrame([{
            "ts_code": "000001.SZ",
            "trade_date": "20260202",
            "open": 10.2,
            "high": 10.5,
            "low": 10.1,
            "close": 10.4,
        }])

        confirmation = build_execution_confirmation(plan, plan_path="plans/20260130.json", created_at="2026-02-02T09:31:00")

        self.assertEqual(plan, original)
        self.assertEqual(confirmation["phase"], "open_execution_confirmation")
        self.assertEqual(confirmation["results"][0]["status"], "executable_plan")
        self.assertEqual(confirmation["results"][0]["open"], 10.2)
        self.assertTrue(confirmation["results"][0]["execution_check"]["gap_check"]["passed"])
        self.assertEqual(confirmation["summary"]["executable"], 1)

    def test_render_distinguishes_pending_plan_and_confirmed_execution(self):
        report = {
            "market_score": {
                "score": 6,
                "market_level": "medium",
                "trade_permission": "open",
                "index_score": 1,
                "volume_score": 1,
                "sentiment_score": 2,
                "theme_score": 2,
                "details": {},
                "hard_rules": {"violations": []},
                "human_judgment": [],
            },
            "themes": {},
            "core_stocks": {},
            "pending_confirmations": [],
            "watch_buy_shapes": [],
            "pending_open_plans": [{
                "ts_code": "000001.SZ",
                "buy_point": "买点一_放量突破",
                "status": "pending_next_open",
                "setup_date": "20260130",
                "confirm_date": "20260130",
                "planned_execution_date": "20260202",
                "close": 10.0,
                "stop_loss": 9.5,
                "execution_check": {"rule": "次日开盘价相对确认日收盘价在 ±3% 内才可进入人工执行确认窗口"},
            }],
            "trial_plans": [],
            "pre_trade_checks": [],
            "blocked_reasons": [],
            "data_warnings": [],
            "human_judgment": [],
            "observation_pool": [],
        }
        rendered_report = render_daily_scan_report(report)
        confirmation = {
            "plan_path": "plans/20260130.json",
            "decision_date": "20260130",
            "execution_date": "20260202",
            "summary": {"total": 1, "executable": 1, "skipped": 0, "invalid": 0},
            "results": [{
                "ts_code": "000001.SZ",
                "buy_point": "买点一_放量突破",
                "status": "executable_plan",
                "open": 10.2,
                "reason": "已通过开盘偏离确认，可进入人工执行窗口",
                "execution_check": {"gap_check": {"gap_pct": 0.02}},
            }],
        }
        rendered_confirmation = render_execution_confirmation(confirmation)

        self.assertIn("待开盘确认预案", rendered_report)
        self.assertIn("待人工执行确认", rendered_report)
        self.assertIn("计划确认日 20260202", rendered_report)
        self.assertIn("已通过确认，可人工执行", rendered_confirmation)
        self.assertIn("开盘执行确认结果", rendered_confirmation)


if __name__ == "__main__":
    unittest.main()
