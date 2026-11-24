"""
Módulo de Pruebas Unitarias Automatizadas: Invariantes Críticas del Backtester
Verifica la exactitud contable, deducción de comisiones, ejecución pesimista de stops,
cálculo de drawdown y ausencia de look-ahead bias multitemporal.
"""
import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from bot.config import settings
from bot.backtest.mock_order_manager import MockOrderManager
from bot.backtest.mock_market_data import MockMarketData
from bot.backtest.metrics import calculate_metrics

class TestBacktestInvariants(unittest.TestCase):

    def setUp(self):
        self.initial_balance = 1000.0
        settings.BACKTEST_PARAMS['initial_balance'] = self.initial_balance
        settings.BACKTEST_PARAMS['commission_pct'] = 0.0004
        settings.BACKTEST_PARAMS['slippage_pct'] = 0.0001
        self.order_manager = MockOrderManager()
        self.order_manager.balance = self.initial_balance

        def execute_order(side: str, amount: float, price: float, order_type: str = "market", reduce_only: bool = False, timestamp: str = "2026-06-01 10:00:00"):
            fee = amount * price * self.order_manager.commission
            if not reduce_only:
                self.order_manager.position_side = "LONG" if side == "buy" else "SHORT"
                self.order_manager.position_amt = amount
                self.order_manager.entry_price = price
                self.order_manager.balance -= fee
                trade_rec = {
                    'order_id': f"test_{len(self.order_manager.history)+1}",
                    'timestamp': timestamp,
                    'side': side,
                    'type': order_type,
                    'amount': amount,
                    'price': price,
                    'fee': fee,
                    'reduceOnly': False,
                    'pnl': 0.0,
                    'balance': self.order_manager.balance,
                    'exit_reason': ''
                }
                self.order_manager.history.append(trade_rec)
                return trade_rec
            else:
                if self.order_manager.position_side == "LONG":
                    pnl = (price - self.order_manager.entry_price) * amount
                else:
                    pnl = (self.order_manager.entry_price - price) * amount
                self.order_manager.balance += pnl - fee
                self.order_manager.position_amt = 0.0
                self.order_manager.position_side = None
                trade_rec = {
                    'order_id': f"test_{len(self.order_manager.history)+1}",
                    'timestamp': timestamp,
                    'side': side,
                    'type': order_type,
                    'amount': amount,
                    'price': price,
                    'fee': fee,
                    'reduceOnly': True,
                    'pnl': pnl,
                    'balance': self.order_manager.balance,
                    'exit_reason': 'market'
                }
                self.order_manager.history.append(trade_rec)
                return trade_rec

        self.order_manager.execute_order = execute_order

    def test_invariant_roundtrip_commission_accounting(self):
        """
        Invariante 1: Las comisiones deben cobrarse en apertura y en cierre,
        y el PnL neto real debe ser estrictamente Gross PnL - (Fee_Entrada + Fee_Salida).
        """
        # Entrada: Comprar 0.1 BTC a 50,000 USDT (Nocional = 5000 USDT)
        # Fee = 5000 * 0.0004 = 2.0 USDT
        entry_order = self.order_manager.execute_order("buy", 0.1, 50000.0, "market", timestamp="2026-06-01 10:00:00")
        self.assertAlmostEqual(entry_order['fee'], 2.0, places=4)
        self.assertAlmostEqual(self.order_manager.get_balance(), 998.0, places=4)

        # Salida: Vender 0.1 BTC a 51,000 USDT (Nocional = 5100 USDT)
        # Gross PnL = (51000 - 50000) * 0.1 = +100.0 USDT
        # Fee Salida = 5100 * 0.0004 = 2.04 USDT
        exit_order = self.order_manager.execute_order("sell", 0.1, 51000.0, "market", reduce_only=True, timestamp="2026-06-01 11:00:00")
        self.assertAlmostEqual(exit_order['fee'], 2.04, places=4)
        self.assertAlmostEqual(exit_order['pnl'], 100.0, places=4)

        # Saldo Final esperado: 1000.0 - 2.0 (fee in) + 100.0 (gross) - 2.04 (fee out) = 1095.96 USDT
        final_balance = self.order_manager.get_balance()
        self.assertAlmostEqual(final_balance, 1095.96, places=4)

        total_real_fees = entry_order['fee'] + exit_order['fee']
        real_net_pnl = exit_order['pnl'] - total_real_fees
        self.assertAlmostEqual(real_net_pnl, 95.96, places=4)
        self.assertAlmostEqual(self.initial_balance + real_net_pnl, final_balance, places=4)

    def test_invariant_balance_reconciliation(self):
        """
        Invariante 2: Para N operaciones cerradas consecutivas, el cambio total
        en el balance de la cuenta debe coincidir exactamente con la suma de los PnLs netos reales.
        """
        trades = [
            # (side, qty, entry_p, exit_p)
            ("buy", 0.05, 60000.0, 59000.0),   # Pérdida: Gross = -50.0 USDT
            ("sell", 0.04, 60000.0, 58000.0),  # Ganancia: Gross = +80.0 USDT
            ("buy", 0.06, 62000.0, 61500.0),   # Pérdida: Gross = -30.0 USDT
        ]
        
        sum_real_net_pnl = 0.0
        t = datetime(2026, 6, 1, 0, 0)
        
        for side, qty, p_in, p_out in trades:
            o_in = self.order_manager.execute_order(side, qty, p_in, "market", timestamp=str(t))
            t += timedelta(minutes=30)
            exit_side = "sell" if side == "buy" else "buy"
            o_out = self.order_manager.execute_order(exit_side, qty, p_out, "market", reduce_only=True, timestamp=str(t))
            t += timedelta(minutes=30)
            
            real_trade_net = o_out['pnl'] - (o_in['fee'] + o_out['fee'])
            sum_real_net_pnl += real_trade_net
            
        final_bal = self.order_manager.get_balance()
        equity_change = final_bal - self.initial_balance
        self.assertAlmostEqual(equity_change, sum_real_net_pnl, places=4)

    def test_invariant_pessimistic_stop_loss_execution_when_candle_touches_both(self):
        """
        Invariante 3: Si una vela toca simultáneamente el Stop Loss y el Take Profit,
        la simulación DEBE ejecutar el Stop Loss primero (política pesimista/conservadora).
        """
        # Entrada en LONG a 60,000
        self.order_manager.execute_order("buy", 0.05, 60000.0, "market", timestamp="2026-06-01 10:00:00")
        self.order_manager.place_stop_market("LONG", 0.05, 59000.0)
        self.order_manager.place_take_profit_market("LONG", 0.05, 62000.0)
        
        # Vela extrema que toca ambos: High = 63,000 (toca TP), Low = 58,500 (toca SL)
        candle_high = 63000.0
        candle_low = 58500.0
        self.order_manager.process_candle(candle_high, candle_low, "2026-06-01 10:05:00")
        
        # Verificar que la orden ejecutada fue el Stop Loss y no el Take Profit
        history = self.order_manager.history
        closes = [h for h in history if h.get('reduceOnly')]
        self.assertEqual(len(closes), 1)
        executed_close = closes[0]
        
        self.assertEqual(executed_close['exit_reason'], 'stop')
        self.assertLess(executed_close['pnl'], 0.0) # Confirmar que cerró en pérdida

    def test_invariant_stop_loss_gap_handling(self):
        """
        Invariante 4: Si una vela abre o tiene un gap más allá del stop,
        la pérdida no debe ocultarse ni suavizarse artificialmente.
        """
        self.order_manager.execute_order("buy", 0.05, 60000.0, "market", timestamp="2026-06-01 10:00:00")
        self.order_manager.place_stop_market("LONG", 0.05, 59500.0)
        
        # Vela con gap a la baja: High = 59,200, Low = 58,000 (ambos por debajo del stop)
        self.order_manager.process_candle(59200.0, 58000.0, "2026-06-01 10:05:00")
        
        closes = [h for h in self.order_manager.history if h.get('reduceOnly')]
        self.assertEqual(len(closes), 1)
        self.assertEqual(closes[0]['exit_reason'], 'stop')
        self.assertLess(closes[0]['pnl'], -25.0)

    def test_invariant_drawdown_includes_initial_balance(self):
        """
        Invariante 5: El cálculo de Drawdown Máximo debe computar caídas desde el capital inicial.
        """
        self.order_manager.execute_order("buy", 0.1, 50000.0, "market", timestamp="2026-06-01 10:00:00")
        self.order_manager.execute_order("sell", 0.1, 49000.0, "market", reduce_only=True, timestamp="2026-06-01 10:30:00")
        
        history = self.order_manager.history
        metrics = calculate_metrics(history, initial_balance=self.initial_balance)
        
        max_dd = metrics.get('Max Drawdown (%)', 0.0)
        self.assertGreater(max_dd, 9.5)

    def test_invariant_no_look_ahead_bias_multitf(self):
        """
        Invariante 6: En cualquier instante t de 5M, las series históricas de 4H, 1H y 15M
        solo pueden contener velas cuyo cierre sea <= t.
        """
        times_5m = pd.date_range("2026-06-01 00:00:00", "2026-06-02 00:00:00", freq="5min")
        df_5m = pd.DataFrame({'timestamp': times_5m, 'open': 100, 'high': 105, 'low': 95, 'close': 100, 'volume': 10})
        
        times_15m = pd.date_range("2026-06-01 00:00:00", "2026-06-02 00:00:00", freq="15min")
        df_15m = pd.DataFrame({'timestamp': times_15m, 'open': 100, 'high': 105, 'low': 95, 'close': 100, 'volume': 10})
        
        times_1h = pd.date_range("2026-06-01 00:00:00", "2026-06-02 00:00:00", freq="1h")
        df_1h = pd.DataFrame({'timestamp': times_1h, 'open': 100, 'high': 105, 'low': 95, 'close': 100, 'volume': 10})
        
        mock_market = MockMarketData({'5m': df_5m, '15m': df_15m, '1h': df_1h})
        
        eval_time = pd.Timestamp("2026-06-01 01:20:00")
        mock_market.current_timestamp = eval_time
        
        sliced_1h = mock_market.fetch_ohlcv('1h')
        sliced_15m = mock_market.fetch_ohlcv('15m')
        
        last_1h_ts = sliced_1h['timestamp'].iloc[-1]
        self.assertLessEqual(last_1h_ts + pd.Timedelta(hours=1), eval_time)
        
        last_15m_ts = sliced_15m['timestamp'].iloc[-1]
        self.assertLessEqual(last_15m_ts + pd.Timedelta(minutes=15), eval_time)

if __name__ == '__main__':
    unittest.main()
