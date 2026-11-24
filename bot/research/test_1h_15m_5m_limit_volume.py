"""
Experimento Cuantitativo: 1H-15M-5M con Órdenes LIMIT + Filtro de Volumen de Alta Convicción.
Objetivo:
Reducir la sobreoperación de 466 trades a trades de alta convicción (~100-200),
reduciendo el gasto en comisiones a la mitad y evaluando si la ganancia bruta se preserva
para lograr rentabilidad neta (Profit Factor > 1.0 y PnL neto positivo).

Se evalúan dos variantes de filtro de volumen:
  - D1: Ruptura 5M con Volumen > SMA20(Vol) * 1.10 (Expansión moderada-alta)
  - D2: Ruptura 5M con Volumen > SMA20(Vol) * 1.00 (Expansión estándar)
  - D3: Ruptura 5M con Volumen > SMA20 * 1.10 Y Régimen ATR > SMA20 (Volumen + Volatilidad completa)
"""
import os
import sys
import contextlib
import io
import pandas as pd
import numpy as np

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)

from bot.config import settings
from bot.backtest.data_loader import DataLoader
from bot.backtest.engine import BacktestEngine
from bot.strategies.ema_pullback_trend_strategy import EMAPullbackTrendStrategy
from bot.research.trigger_investigation_lab import analyze_simulation_history

class Strategy1H_15M_5M_VolumeLimit(EMAPullbackTrendStrategy):
    def __init__(self, position_manager, risk_manager, vol_mult=1.10, require_atr=False):
        super().__init__(position_manager, risk_manager)
        self.vol_mult = vol_mult
        self.require_atr = require_atr

    def analyze_market(self, dfs: dict) -> None:
        super().analyze_market(dfs)
        df_5m = dfs.get(self.trigger_tf)
        if df_5m is not None and len(df_5m) >= 25:
            if 'volume_sma20' not in df_5m.columns:
                df_5m['volume_sma20'] = df_5m['volume'].rolling(window=20).mean()
            if 'atr_sma20' not in df_5m.columns:
                df_5m['atr_sma20'] = df_5m['atr'].rolling(window=20).mean()
            df_5m.ffill(inplace=True)

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

        # 1. Tendencia exclusiva 1H
        trend_1h = self.evaluate_trend(df_1h)
        if trend_1h == 'NONE':
            self.pending_preparation = None
            result['reason'] = 'NO_CONFIRMED_TREND_1H'
            return result

        active_trend = trend_1h
        if self.pending_preparation and self.pending_preparation['side'] != active_trend:
            self.pending_preparation = None

        # 2. Preparación 15M
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

        # 3. Gatillo 5M
        trigger_signal = self.evaluate_5m_trigger(df_5m, self.pending_preparation)
        if trigger_signal is not None:
            # Evaluar filtro de volumen
            row_curr = df_5m.iloc[-1]
            vol = float(row_curr.get('volume', 0.0))
            vol_sma20 = float(row_curr.get('volume_sma20', 0.0))
            atr_5m = float(row_curr.get('atr', 0.0))
            atr_sma20 = float(row_curr.get('atr_sma20', 0.0))

            vol_ok = (vol_sma20 > 0) and (vol >= vol_sma20 * self.vol_mult)

            atr_ok = True
            if self.require_atr:
                atr_ok = (atr_sma20 > 0) and (atr_5m >= atr_sma20) and ((atr_5m / last_close_5m) >= 0.001)

            if vol_ok and atr_ok:
                self.pending_preparation = None
                trigger_signal['reason'] = 'TRIGGER_CONFIRMED_5M_LIMIT_VOL'
                trigger_signal['features']['vol_ratio'] = round(vol / vol_sma20, 2) if vol_sma20 > 0 else 1.0
                return trigger_signal

        result['reason'] = 'WAITING_5M_TRIGGER'
        return result


def run_experiment_suite():
    settings.ENVIRONMENT = "BACKTEST"
    settings.ENABLE_DETAILED_LOGS = False

    loader = DataLoader('BTC/USDT')
    timeframes = ['4h', '1h', '15m', '5m']

    settings.ACTIVE_STRATEGY = 'EMA_PULLBACK_TREND'
    base_params = {
        'macro_tf': '1h', 'trend_confirm_tf': '1h', 'pullback_tf': '15m', 'trigger_tf': '5m',
        'fast_ema': 17, 'mid_ema': 30, 'slow_ema': 50, 'rsi_period': 14,
        'rsi_long_min': 45.0, 'rsi_long_max': 65.0, 'rsi_short_min': 35.0, 'rsi_short_max': 55.0,
        'body_ratio_threshold': 0.55, 'rr_ratio': 2.0, 'sl_atr_mult': 1.0, 'sl_type': 'atr',
        'sl_swing_buffer_atr': 0.2, 'sl_min_dist_pct': 0.001, 'sl_max_dist_pct': 0.05,
        'risk_pct': 0.01, 'max_risk_usdt': 8.0, 'preparation_expiry_5m_bars': 6,
        'local_swing_lookback_5m': 5, 'est_commission_pct': 0.0002, 'est_slippage_pct': 0.0, 'min_net_rr': 0.5
    }
    settings.STRATEGY_PARAMS['EMA_PULLBACK_TREND'] = base_params

    # Cargar datos
    print("Cargando series históricas...")
    dfs_base = {tf: loader.fetch_data(tf, '2026-06-01', '2026-07-05') for tf in timeframes}
    dfs_ext = {tf: loader.fetch_data(tf, '2026-01-01', '2026-07-05') for tf in timeframes}

    configurations = [
        ("Base (Sin Filtro Vol)", 0.0, False),
        ("Vol > 1.0x SMA20", 1.0, False),
        ("Vol > 1.1x SMA20", 1.1, False),
        ("Vol > 1.1x SMA20 + ATR", 1.1, True),
        ("Vol > 1.25x SMA20", 1.25, False),
    ]

    print("\n" + "=" * 95)
    print("🔬 EXPERIMENTO EXTENDIDO 6 MESES (2026-01-01 a 2026-07-05) — IMPACTO DE FILTROS DE VOLUMEN")
    print("=" * 95)
    header = f"{'Configuración':<26} | {'Trades':<6} | {'WR %':<6} | {'PF':<5} | {'Gross PnL':<10} | {'Fees Tot.':<10} | {'Net PnL':<10} | {'Max DD%':<8} | {'OOS Net':<8} | {'OOS PF':<6}"
    print(header)
    print("-" * 95)

    for name, v_mult, req_atr in configurations:
        engine = BacktestEngine(dfs_ext)
        strat = Strategy1H_15M_5M_VolumeLimit(engine.engine.position_manager, engine.engine.risk_manager, vol_mult=v_mult, require_atr=req_atr)
        engine.engine.strategy = strat
        engine.engine.strategy.analyze_market(dfs_ext)
        engine.mock_order_manager.commission = 0.0002
        engine.mock_order_manager.slippage = 0.0

        with contextlib.redirect_stdout(io.StringIO()):
            hist = engine.run()

        r = analyze_simulation_history(hist, 1000.0, split_date='2026-04-30')
        row = f"{name:<26} | {r['trades_count']:<6} | {r['win_rate']:<6.1f} | {r['profit_factor']:<5.2f} | {r['gross_pnl']:<+10.2f} | {r['total_fees']:<10.2f} | {r['real_net_pnl']:<+10.2f} | {r['max_dd_pct']:<8.2f} | {r['oos_net']:<+8.2f} | {r['oos_pf']:<6.2f}"
        print(row)

    print("\n" + "=" * 95)
    print("🔬 EXPERIMENTO PERÍODO BASELINE (2026-06-01 a 2026-07-05 / 35 DÍAS)")
    print("=" * 95)
    print(header)
    print("-" * 95)

    for name, v_mult, req_atr in configurations:
        engine = BacktestEngine(dfs_base)
        strat = Strategy1H_15M_5M_VolumeLimit(engine.engine.position_manager, engine.engine.risk_manager, vol_mult=v_mult, require_atr=req_atr)
        engine.engine.strategy = strat
        engine.engine.strategy.analyze_market(dfs_base)
        engine.mock_order_manager.commission = 0.0002
        engine.mock_order_manager.slippage = 0.0

        with contextlib.redirect_stdout(io.StringIO()):
            hist = engine.run()

        r = analyze_simulation_history(hist, 1000.0, split_date='2026-06-20')
        row = f"{name:<26} | {r['trades_count']:<6} | {r['win_rate']:<6.1f} | {r['profit_factor']:<5.2f} | {r['gross_pnl']:<+10.2f} | {r['total_fees']:<10.2f} | {r['real_net_pnl']:<+10.2f} | {r['max_dd_pct']:<8.2f} | {r['oos_net']:<+8.2f} | {r['oos_pf']:<6.2f}"
        print(row)

if __name__ == '__main__':
    run_experiment_suite()
