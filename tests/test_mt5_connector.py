"""
Pruebas de conectores de MetaTrader 5 (IC Markets)
"""
import unittest
from unittest.mock import patch, MagicMock
from bot.connectors.mt5_market_data import MT5MarketDataManager
from bot.connectors.mt5_order import MT5OrderManager


class TestMT5Connector(unittest.TestCase):
    @patch("bot.connectors.mt5_order.mt5")
    def test_mt5_order_manager_normalization(self, mock_mt5):
        # Configurar mock de symbol_info
        mock_info = MagicMock()
        mock_info.volume_min = 0.01
        mock_info.volume_max = 50.0
        mock_info.volume_step = 0.01
        mock_info.digits = 2
        mock_info.filling_mode = 1  # IOC
        mock_mt5.symbol_info.return_value = mock_info
        mock_mt5.initialize.return_value = True

        with patch("bot.config.settings.ENVIRONMENT", "BACKTEST"):
            om = MT5OrderManager()
            om.symbol = "BTCUSD"

            vol = om.normalize_volume(0.0543)
            self.assertEqual(vol, 0.05)

            p = om.normalize_price(64250.789)
            self.assertEqual(p, 64250.79)

    @patch("bot.connectors.mt5_market_data.mt5")
    def test_mt5_market_data_format(self, mock_mt5):
        import numpy as np

        # Crear estructura simulada de rates
        rates_dtype = [
            ('time', '<i8'), ('open', '<f8'), ('high', '<f8'),
            ('low', '<f8'), ('close', '<f8'), ('tick_volume', '<i8'),
            ('spread', '<i4'), ('real_volume', '<i8')
        ]
        sample_rates = np.array([
            (1700000000, 60000.0, 60500.0, 59900.0, 60200.0, 1500, 10, 0),
            (1700003600, 60200.0, 60800.0, 60100.0, 60700.0, 1800, 10, 0),
        ], dtype=rates_dtype)

        mock_mt5.copy_rates_from_pos.return_value = sample_rates
        mock_om = MagicMock()
        mock_om.symbol = "BTCUSD"

        md = MT5MarketDataManager(mock_om)
        df = md.fetch_ohlcv("1h", limit=2)

        self.assertIsNotNone(df)
        self.assertEqual(len(df), 2)
        self.assertIn("timestamp", df.columns)
        self.assertIn("timestamp_dt", df.columns)
        self.assertIn("open", df.columns)
        self.assertIn("close", df.columns)
        self.assertIn("volume", df.columns)
        self.assertEqual(df["volume"].iloc[0], 1500.0)

    @patch("bot.connectors.mt5_order.mt5")
    def test_mt5_place_limit_short_market_deal_fallback(self, mock_mt5):
        # Setup mocks
        mock_info = MagicMock()
        mock_info.volume_min = 0.01
        mock_info.volume_max = 50.0
        mock_info.volume_step = 0.01
        mock_info.digits = 2
        mock_info.filling_mode = 1
        mock_info.trade_stops_level = 0
        mock_info.point = 0.01
        mock_mt5.symbol_info.return_value = mock_info

        mock_tick = MagicMock()
        mock_tick.bid = 81500.0
        mock_tick.ask = 81505.0
        mock_mt5.symbol_info_tick.return_value = mock_tick

        mock_res = MagicMock()
        mock_res.retcode = mock_mt5.TRADE_RETCODE_DONE
        mock_res.order = 123456
        mock_mt5.order_send.return_value = mock_res
        mock_mt5.TRADE_ACTION_DEAL = 1
        mock_mt5.TRADE_ACTION_PENDING = 5
        mock_mt5.ORDER_TYPE_SELL = 1
        mock_mt5.ORDER_TYPE_SELL_LIMIT = 3
        mock_mt5.ORDER_TIME_GTC = 1
        mock_mt5.ORDER_FILLING_IOC = 1

        with patch("bot.config.settings.ENVIRONMENT", "BACKTEST"):
            om = MT5OrderManager()
            om.paper_trading = False
            om.symbol = "BTCUSD"

            # Case 1: Limit price <= Ask (81400 <= 81505) -> should execute at market (DEAL)
            ticket = om.place_limit_short(0.01, 81400.0, features={'sl_price': 81600.0, 'take_profit': 81000.0})
            self.assertEqual(ticket, "123456")
            call_req = mock_mt5.order_send.call_args[0][0]
            self.assertEqual(call_req['action'], mock_mt5.TRADE_ACTION_DEAL)
            self.assertEqual(call_req['type'], mock_mt5.ORDER_TYPE_SELL)
            self.assertEqual(call_req['price'], 81500.0)
            self.assertEqual(call_req['sl'], 81600.0)
            self.assertEqual(call_req['tp'], 81000.0)

            # Case 2: Limit price > Ask (81600 > 81505) -> should place pending limit order
            om.place_limit_short(0.01, 81600.0, features={'sl_price': 81800.0, 'take_profit': 81200.0})
            call_req2 = mock_mt5.order_send.call_args[0][0]
            self.assertEqual(call_req2['action'], mock_mt5.TRADE_ACTION_PENDING)
            self.assertEqual(call_req2['type'], mock_mt5.ORDER_TYPE_SELL_LIMIT)
            self.assertEqual(call_req2['price'], 81600.0)


if __name__ == "__main__":
    unittest.main()

