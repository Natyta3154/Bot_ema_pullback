import unittest
from unittest.mock import patch

from bot.backtest.mock_order_manager import MockOrderManager
from bot.config import settings
from bot.core.order import OrderManager
from bot.core.order_planner import OrderPlanner
from bot.core.position import PositionManager
from bot.core.risk import RiskManager


class SimulatedExecutionTests(unittest.TestCase):
    def test_limit_entry_and_stop_update_position_state(self):
        manager = MockOrderManager()

        entry_id = manager.place_limit_long(
            amount=1.0,
            price=100.0,
            features={"sl_price": 95.0},
        )
        manager.process_candle(101.0, 99.0, "2026-01-01 00:00:00")

        self.assertEqual(manager.check_order_status(entry_id)["status"], "closed")
        self.assertEqual(manager.get_position_amount(), 1.0)

        stop_id = manager.place_stop_market("LONG", 1.0, 95.0)
        manager.process_candle(96.0, 94.0, "2026-01-01 00:15:00")

        self.assertEqual(manager.check_order_status(stop_id)["status"], "closed")
        self.assertEqual(manager.get_position_amount(), 0.0)
        self.assertEqual(len(manager.history), 2)

    def test_market_close_has_simulated_price_and_fee(self):
        manager = MockOrderManager()
        entry_id = manager.place_limit_long(1.0, 100.0, {"sl_price": 95.0})
        manager.process_candle(101.0, 99.0, "2026-01-01 00:00:00")
        self.assertEqual(manager.check_order_status(entry_id)["status"], "closed")

        manager.current_price = 102.0
        close = manager.execute_market_close("LONG", 1.0)

        self.assertEqual(close["status"], "closed")
        self.assertEqual(close["average"], 102.0)
        self.assertGreater(close["fee"]["cost"], 0.0)
        self.assertEqual(manager.get_position_amount(), 0.0)


class PaperOrderManagerTests(unittest.TestCase):
    @patch.object(OrderManager, "setup_account")
    def test_paper_delegates_order_lifecycle_to_simulator(self, _setup_account):
        original_environment = settings.ENVIRONMENT
        settings.ENVIRONMENT = "PAPER"
        try:
            manager = OrderManager()
            order_id = manager.place_limit_long(1.0, 100.0, {"sl_price": 95.0})
            manager.process_candle(101.0, 99.0, "2026-01-01 00:00:00")

            self.assertEqual(manager.check_order_status(order_id)["status"], "closed")
            self.assertEqual(manager.get_position_amount(), 1.0)
        finally:
            settings.ENVIRONMENT = original_environment


class PositionStateTests(unittest.TestCase):
    @patch.object(settings, "ENVIRONMENT", "BACKTEST")
    def test_position_transitions_preserve_event_time_and_remaining_amount(self):
        position = PositionManager()
        position.open_from_fill("SHORT", 2.0, 100.0, "2026-01-01T00:15:00")

        self.assertTrue(position.is_open)
        self.assertEqual(position.entry_time, "2026-01-01T00:15:00")
        self.assertEqual(position.apply_partial_exit(0.75), 0.75)
        self.assertEqual(position.amount, 1.25)
        self.assertTrue(position.has_remaining_amount())

        position.reset_position()
        self.assertFalse(position.is_open)
        self.assertEqual(position.amount, 0.0)
        self.assertEqual(position.last_candle_1h_time, "")


class OrderPlannerTests(unittest.TestCase):
    def test_build_plan_does_not_mutate_signal_targets(self):
        planner = OrderPlanner(RiskManager())
        signal = {
            "action": "LONG",
            "price": 100.0,
            "sl": 95.0,
            "tp_targets": [{"price": 110.0, "amount_pct": 0.5}],
        }

        plan = planner.build_entry_plan(signal, 1000.0)

        self.assertIsNotNone(plan)
        self.assertIn("amount_pct", signal["tp_targets"][0])
        self.assertEqual(plan.tp_targets[0]["amount"], round(plan.amount * 0.5, 4))
        self.assertEqual(plan.features["sl_price"], 95.0)


class LiveSafetyTests(unittest.TestCase):
    @patch.object(settings, "ENVIRONMENT", "LIVE")
    @patch.object(settings, "LIVE_TRADING_ENABLED", False)
    def test_live_mode_is_blocked_before_exchange_setup(self):
        with self.assertRaisesRegex(RuntimeError, "LIVE trading bloqueado"):
            OrderManager()


if __name__ == "__main__":
    unittest.main()
