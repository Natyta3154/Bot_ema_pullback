import os
import sys
import pandas as pd
import contextlib
import io

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)

from bot.config import settings
from bot.backtest.data_loader import DataLoader
from bot.backtest.engine import BacktestEngine
from bot.strategies.ema_pullback_trend_strategy import EMAPullbackTrendStrategy
from bot.research.trigger_investigation_lab import analyze_simulation_history

class Strategy1H_15M_5M_Limit(EMAPullbackTrendStrategy):
    """
    Variante A Modificada:
    - 4H eliminado: La tendencia se determina EXCLUSIVAMENTE por 1H.
    - 15M: Preparación de pullback sobre 1H.
    - 5M: Gatillo de ruptura de swing local.
    - Entrada LIMIT: Modelo Maker de comisión (0.02% / 0.0002) y slippage 0.0%.
    """
    def generate_signal(self, current_price, saldo, dfs):
        result = {'action': 'NONE', 'price': 0.0, 'sl': 0.0, 'tp': 0.0, 'features': {}, 'reason': ''}
        df_1h = dfs.get('1h')
        df_15m = dfs.get('15m')
        df_5m = dfs.get('5m')
        
        if df_1h is None or df_15m is None or df_5m is None:
            result['reason'] = 'MISSING_DATA'
            return result
        if len(df_1h) < 50 or len(df_15m) < 50 or len(df_5m) < 10:
            result['reason'] = 'INSUFFICIENT_WARMUP'
            return result
            
        # 1. TENDENCIA EXCLUSIVA EN 1H (SIN 4H)
        trend_1h = self.evaluate_trend(df_1h)
        if trend_1h == 'NONE':
            self.pending_preparation = None
            result['reason'] = 'NO_CONFIRMED_TREND_1H'
            return result
            
        active_trend = trend_1h
        if self.pending_preparation and self.pending_preparation['side'] != active_trend:
            self.pending_preparation = None
            
        # 2. PREPARACIÓN EN 15M
        new_prep = self.evaluate_15m_pullback(df_15m, active_trend)
        if new_prep is not None:
            curr_prep_ts = str(df_15m['timestamp'].iloc[-1])
            if self.pending_preparation is None or self.pending_preparation.get('prep_15m_ts') != curr_prep_ts:
                self.pending_preparation = new_prep
                
        if self.pending_preparation is None:
            result['reason'] = 'WAITING_15M_PULLBACK'
            return result
            
        self.pending_preparation['candles_5m_count'] += 1
        if self.pending_preparation['candles_5m_count'] > self.preparation_expiry_5m_bars:
            self.pending_preparation = None
            result['reason'] = 'PREPARATION_EXPIRED'
            return result
            
        last_close_5m = float(df_5m['close'].iloc[-1])
        if self.pending_preparation['side'] == 'LONG':
            if last_close_5m < self.pending_preparation['low_15m']:
                self.pending_preparation = None
                result['reason'] = 'PREPARATION_STRUCTURE_BROKEN'
                return result
        elif self.pending_preparation['side'] == 'SHORT':
            if last_close_5m > self.pending_preparation['high_15m']:
                self.pending_preparation = None
                result['reason'] = 'PREPARATION_STRUCTURE_BROKEN'
                return result
                
        # 3. GATILLO EN 5M (CON ORDEN LIMIT)
        trigger_signal = self.evaluate_5m_trigger(df_5m, self.pending_preparation)
        if trigger_signal is not None:
            self.pending_preparation = None
            trigger_signal['reason'] = 'TRIGGER_CONFIRMED_5M_LIMIT'
            return trigger_signal
            
        result['reason'] = 'WAITING_5M_TRIGGER'
        return result

def run_test():
    settings.ENVIRONMENT = "BACKTEST"
    settings.ENABLE_DETAILED_LOGS = False
    loader = DataLoader('BTC/USDT')
    timeframes = ['1h', '15m', '5m']
    
    settings.ACTIVE_STRATEGY = 'EMA_PULLBACK_TREND'
    settings.STRATEGY_PARAMS['EMA_PULLBACK_TREND'] = {
        'macro_tf': '1h', 'trend_confirm_tf': '1h', 'pullback_tf': '15m', 'trigger_tf': '5m',
        'fast_ema': 17, 'mid_ema': 30, 'slow_ema': 50, 'rsi_period': 14,
        'rsi_long_min': 45.0, 'rsi_long_max': 65.0, 'rsi_short_min': 35.0, 'rsi_short_max': 55.0,
        'body_ratio_threshold': 0.55, 'rr_ratio': 2.0, 'sl_atr_mult': 1.0, 'sl_type': 'atr',
        'sl_swing_buffer_atr': 0.2, 'sl_min_dist_pct': 0.001, 'sl_max_dist_pct': 0.05,
        'risk_pct': 0.01, 'max_risk_usdt': 8.0, 'preparation_expiry_5m_bars': 6,
        'local_swing_lookback_5m': 5, 'est_commission_pct': 0.0002, 'est_slippage_pct': 0.0, 'min_net_rr': 0.5
    }

    # 1. PERÍODO BASELINE (2026-06-01 a 2026-07-05)
    print("=" * 80)
    print("TEST 1: BASELINE (2026-06-01 a 2026-07-05) — 1H + 15M + 5M con LIMIT (Maker 0.02%)")
    print("=" * 80)
    dfs_base = {tf: loader.fetch_data(tf, '2026-06-01', '2026-07-05') for tf in timeframes}
    engine_base = BacktestEngine(dfs_base)
    engine_base.engine.strategy = Strategy1H_15M_5M_Limit(engine_base.engine.position_manager, engine_base.engine.risk_manager)
    engine_base.engine.strategy.analyze_market(dfs_base)
    # Maker fees: 0.02% (0.0002) y slippage 0.0%
    engine_base.mock_order_manager.commission = 0.0002
    engine_base.mock_order_manager.slippage = 0.0
    with contextlib.redirect_stdout(io.StringIO()):
        hist_base = engine_base.run()
    res_base = analyze_simulation_history(hist_base, 1000.0, split_date='2026-06-20')
    
    print(f"Total Trades:       {res_base['trades_count']}")
    print(f"Win Rate:           {res_base['win_rate']}%")
    print(f"Profit Factor:      {res_base['profit_factor']}")
    print(f"Gross PnL:          {res_base['gross_pnl']:+.2f} USDT")
    print(f"Comisiones Totales: {res_base['total_fees']:.2f} USDT")
    print(f"PnL Neto Real:      {res_base['real_net_pnl']:+.2f} USDT")
    print(f"Max Drawdown:       {res_base['max_dd_pct']}% ({res_base['max_dd_usdt']} USDT)")
    print(f"Expectancy:         {res_base['expectancy_usdt']:+.2f} USDT/trade")
    print(f"IS / OOS PnL:       IS: {res_base['is_net']:+.2f} USDT (PF {res_base['is_pf']}) | OOS: {res_base['oos_net']:+.2f} USDT (PF {res_base['oos_pf']})")

    # 2. PERÍODO EXTENDIDO (2026-01-01 a 2026-07-05)
    print("\n" + "=" * 80)
    print("TEST 2: EXTENDIDO 6 MESES (2026-01-01 a 2026-07-05) — 1H + 15M + 5M con LIMIT (Maker 0.02%)")
    print("=" * 80)
    dfs_ext = {tf: loader.fetch_data(tf, '2026-01-01', '2026-07-05') for tf in timeframes}
    engine_ext = BacktestEngine(dfs_ext)
    engine_ext.engine.strategy = Strategy1H_15M_5M_Limit(engine_ext.engine.position_manager, engine_ext.engine.risk_manager)
    engine_ext.engine.strategy.analyze_market(dfs_ext)
    engine_ext.mock_order_manager.commission = 0.0002
    engine_ext.mock_order_manager.slippage = 0.0
    with contextlib.redirect_stdout(io.StringIO()):
        hist_ext = engine_ext.run()
    res_ext = analyze_simulation_history(hist_ext, 1000.0, split_date='2026-04-30')

    print(f"Total Trades:       {res_ext['trades_count']}")
    print(f"Win Rate:           {res_ext['win_rate']}%")
    print(f"Profit Factor:      {res_ext['profit_factor']}")
    print(f"Gross PnL:          {res_ext['gross_pnl']:+.2f} USDT")
    print(f"Comisiones Totales: {res_ext['total_fees']:.2f} USDT")
    print(f"PnL Neto Real:      {res_ext['real_net_pnl']:+.2f} USDT")
    print(f"Max Drawdown:       {res_ext['max_dd_pct']}% ({res_ext['max_dd_usdt']} USDT)")
    print(f"Expectancy:         {res_ext['expectancy_usdt']:+.2f} USDT/trade")
    print(f"Longs:              {res_ext['longs']} trades | WR: {res_ext['long_wr']}% | PnL: {res_ext['long_pnl']:+.2f} USDT")
    print(f"Shorts:             {res_ext['shorts']} trades | WR: {res_ext['short_wr']}% | PnL: {res_ext['short_pnl']:+.2f} USDT")
    print(f"IS / OOS PnL:       IS: {res_ext['is_net']:+.2f} USDT (PF {res_ext['is_pf']}) | OOS: {res_ext['oos_net']:+.2f} USDT (PF {res_ext['oos_pf']})")

if __name__ == '__main__':
    run_test()
