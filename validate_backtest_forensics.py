"""
Script Forense de Auditoría y Validación Cuantitativa del Backtest
Reconciliación trade-por-trade, Drawdown exacto,手数料 (comisiones), y Comparativa Experimental A/B/C.
"""
import os
import sys
import io
import contextlib
import pandas as pd
import numpy as np

from bot.backtest.data_loader import DataLoader
from bot.config import settings
from bot.backtest.engine import BacktestEngine
from bot.backtest.metrics import calculate_metrics
from bot.strategies.ema_pullback_trend_strategy import EMAPullbackTrendStrategy
from bot.strategies.factory import StrategyFactory

def run_forensic_validation():
    print("=" * 80)
    print("🔍 INICIANDO AUDITORÍA FORENSE Y RECONCILIACIÓN DEL BACKTESTER")
    print("=" * 80)
    
    settings.ENVIRONMENT = "BACKTEST"
    settings.ENABLE_DETAILED_LOGS = False
    symbol = "BTC/USDT"
    start_date = "2026-06-01"
    end_date = "2026-07-05"
    timeframes = ['4h', '1h', '30m', '15m', '5m']
    loader = DataLoader(symbol=symbol)
    dfs = {}
    for tf in timeframes:
        df = loader.fetch_data(tf, start_date, end_date)
        if df is not None and len(df) > 0:
            dfs[tf] = df
            print(f"Cargado {tf}: {len(df)} velas.")

    initial_balance = 1000.0
    settings.ACTIVE_STRATEGY = "EMA_PULLBACK_TREND"
    settings.STRATEGY_PARAMS["EMA_PULLBACK_TREND"] = {
        "macro_tf": "4h",
        "trend_confirm_tf": "1h",
        "pullback_tf": "15m",
        "entry_tf": "15m",
        "trigger_tf": "5m",
        "fast_ema": 17,
        "mid_ema": 30,
        "slow_ema": 50,
        "rsi_period": 14,
        "rsi_long_min": 45.0,
        "rsi_long_max": 65.0,
        "rsi_short_min": 35.0,
        "rsi_short_max": 55.0,
        "rr_ratio": 2.0,
        "sl_atr_mult": 1.0,
        "sl_type": "atr",
        "sl_swing_buffer_atr": 0.2,
        "sl_min_dist_pct": 0.001,
        "sl_max_dist_pct": 0.05,
        "risk_pct": 0.01,
        "max_risk_usdt": 8.0,
        "preparation_expiry_5m_bars": 6,
        "local_swing_lookback_5m": 5,
        "est_commission_pct": 0.0004,
        "est_slippage_pct": 0.0001,
        "min_net_rr": 0.5
    }

    # Silenciar stdout durante BacktestEngine.run() para evitar saturar I/O con miles de tablas
    print("\n⏳ Ejecutando Backtest de la Estrategia Actual (Variante A)...")
    with contextlib.redirect_stdout(io.StringIO()):
        engine_a = BacktestEngine(dfs)
        history_a = engine_a.run()

    df_hist_a = pd.DataFrame(history_a)
    print(f"✅ Variante A completada: {len(df_hist_a)} eventos en historial.")

    # --------------------------------------------------------------------------
    # 1. VERIFICACIÓN DEL CÁLCULO DE DRAWDOWN
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("--- 1. VERIFICACIÓN DEL CÁLCULO DE DRAWDOWN ---")
    print("=" * 80)
    metrics_a = calculate_metrics(history_a, initial_balance)
    
    closes_a = df_hist_a[df_hist_a['reduceOnly'] == True].copy()
    opens_a = df_hist_a[df_hist_a['reduceOnly'] == False].copy()

    # Reconstrucción de la curva de balance real
    equity_curve = [initial_balance]
    for b in closes_a['balance']:
        equity_curve.append(float(b))
    
    eq_series = pd.Series(equity_curve)
    peak_series = eq_series.cummax()
    drawdown_series = peak_series - eq_series
    drawdown_pct_series = (drawdown_series / peak_series) * 100.0
    
    true_max_dd_usdt = round(drawdown_series.max(), 2)
    true_max_dd_pct = round(drawdown_pct_series.max(), 2)
    
    print(f"Claves devueltas por calculate_metrics: {list(metrics_a.keys())}")
    print(f"metrics.get('max_drawdown'): {metrics_a.get('max_drawdown')}")
    print(f"metrics.get('Max Drawdown (%)'): {metrics_a.get('Max Drawdown (%)')}")
    print(f"\nDrawdown Máximo Real en USDT: {true_max_dd_usdt} USDT")
    print(f"Drawdown Máximo Real en %:    {true_max_dd_pct}%")

    # --------------------------------------------------------------------------
    # 2. RECONCILIACIÓN TRADE-POR-TRADE DE PNL Y COMISIONES
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("--- 2. CONCILIACIÓN CONTABLE DE COMISIONES Y PNL ---")
    print("=" * 80)
    
    opens_list = opens_a.to_dict('records')
    closes_list = closes_a.to_dict('records')
    
    reconciled_trades = []
    for i in range(min(len(opens_list), len(closes_list))):
        o = opens_list[i]
        c = closes_list[i]
        
        direction = "LONG" if o['side'] == 'buy' else "SHORT"
        entry_price = float(o['price'])
        exit_price = float(c['price'])
        qty = float(o['amount'])
        
        entry_fee = float(o['fee'])
        exit_fee = float(c['fee'])
        total_fees = entry_fee + exit_fee
        
        gross_pnl = float(c['pnl'])
        real_net_pnl = round(gross_pnl - total_fees, 4)
        reported_net_pnl = round(gross_pnl - exit_fee, 4)
        
        # Riesgo monetario teórico programado
        risk_usdt = abs(entry_price - (float(c.get('sl', entry_price)))) * qty
        
        reconciled_trades.append({
            'trade_idx': i + 1,
            'direction': direction,
            'entry_time': o['timestamp'],
            'exit_time': c['timestamp'],
            'entry_price': entry_price,
            'exit_price': exit_price,
            'qty': qty,
            'notional_entry': round(entry_price * qty, 2),
            'gross_pnl': round(gross_pnl, 4),
            'entry_fee': round(entry_fee, 4),
            'exit_fee': round(exit_fee, 4),
            'total_fees': round(total_fees, 4),
            'real_net_pnl': round(real_net_pnl, 4),
            'reported_net_pnl': round(reported_net_pnl, 4),
            'fee_omission': round(entry_fee, 4),
            'exit_reason': c['exit_reason'],
            'end_balance': round(float(c['balance']), 2)
        })

    df_rec = pd.DataFrame(reconciled_trades)
    
    sum_gross_pnl = round(df_rec['gross_pnl'].sum(), 2)
    total_entry_fees = round(df_rec['entry_fee'].sum(), 2)
    total_exit_fees = round(df_rec['exit_fee'].sum(), 2)
    total_fees_real = round(df_rec['total_fees'].sum(), 2)
    sum_net_pnl_real = round(df_rec['real_net_pnl'].sum(), 2)
    sum_net_pnl_reported = round(df_rec['reported_net_pnl'].sum(), 2)
    total_fee_omission = round(df_rec['fee_omission'].sum(), 2)
    net_equity_change = round(float(closes_a['balance'].iloc[-1]) - initial_balance, 2)

    print(f"Suma Gross PnL (Bruto):               {sum_gross_pnl:8.2f} USDT")
    print(f"Total Comisiones de ENTRADA:           {total_entry_fees:8.2f} USDT")
    print(f"Total Comisiones de SALIDA:            {total_exit_fees:8.2f} USDT")
    print(f"Total Comisiones REALES (Roundtrip):   {total_fees_real:8.2f} USDT")
    print(f"PnL Neto REAL (Gross - Roundtrip):     {sum_net_pnl_real:8.2f} USDT")
    print(f"PnL Neto REPORTADO (Gross - ExitFee):  {sum_net_pnl_reported:8.2f} USDT")
    print(f"Diferencia Omitida por el Reporte:     {total_fee_omission:8.2f} USDT")
    print(f"Cambio Real en Saldo de Cuenta:        {net_equity_change:8.2f} USDT")
    print(f"Verificación Exacta (sum_net_pnl_real == net_equity_change): {abs(sum_net_pnl_real - net_equity_change) < 0.05}")

    # Guardar en CSV para archivo forense
    df_rec.to_csv("forensic_reconciled_trades.csv", index=False)
    print("✅ CSV 'forensic_reconciled_trades.csv' generado con éxito.")

    # --------------------------------------------------------------------------
    # 3. MOTIVOS DE SALIDA DE TRADES PERDEDORES
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("--- 3. MOTIVOS DE SALIDA DE TRADES PERDEDORES ---")
    print("=" * 80)
    losing_trades = df_rec[df_rec['real_net_pnl'] <= 0]
    winning_trades = df_rec[df_rec['real_net_pnl'] > 0]
    print(f"Total Trades: {len(df_rec)} | Ganadores: {len(winning_trades)} | Perdedores: {len(losing_trades)}")
    print("\nDistribución de salidas de trades perdedores:")
    print(losing_trades['exit_reason'].value_counts())

    # --------------------------------------------------------------------------
    # 4. COMPARACIÓN EXPERIMENTAL A / B / C CON PARTICIÓN CRONOLÓGICA OOS
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("--- 4. COMPARACIÓN EXPERIMENTAL REPRODUCIBLE (A, B, C) ---")
    print("=" * 80)

    # Definición de Clases Experimentales B y C
    class StrategyVariantB(EMAPullbackTrendStrategy):
        """Variante B: 1H confirmado y 4H en transición con pendiente EMA30 a favor."""
        def evaluate_custom_macro_trend(self, df_4h, df_1h):
            t4 = self.evaluate_trend(df_4h)
            t1 = self.evaluate_trend(df_1h)
            if t4 == t1 and t4 != "NONE":
                return t4
            if t1 != "NONE" and t4 == "NONE":
                r4 = df_4h.iloc[-1]
                slope4 = float(r4.get('slope_ema30', 0.0))
                if t1 == "LONG" and slope4 > 0:
                    return "LONG"
                elif t1 == "SHORT" and slope4 < 0:
                    return "SHORT"
            return "NONE"

        def generate_signal(self, current_price, saldo, dfs):
            df_4h = dfs.get(self.macro_tf)
            df_1h = dfs.get(self.trend_confirm_tf)
            df_15m = dfs.get(self.pullback_tf)
            if df_15m is None:
                df_15m = dfs.get(self.params.get('entry_tf', '15m'))
            df_5m = dfs.get(self.trigger_tf)

            if df_4h is None or df_1h is None or df_15m is None or df_5m is None:
                return {'action': 'NONE', 'price': 0.0, 'sl': 0.0, 'tp': 0.0, 'features': {}, 'reason': 'MISSING_DATA'}
            if len(df_4h) < 50 or len(df_1h) < 50 or len(df_15m) < 50 or len(df_5m) < 10:
                return {'action': 'NONE', 'price': 0.0, 'sl': 0.0, 'tp': 0.0, 'features': {}, 'reason': 'INSUFFICIENT_WARMUP'}

            active_trend = self.evaluate_custom_macro_trend(df_4h, df_1h)
            if active_trend == "NONE":
                self.pending_preparation = None
                return {'action': 'NONE', 'price': 0.0, 'sl': 0.0, 'tp': 0.0, 'features': {}, 'reason': 'NO_CONFIRMED_TREND'}

            if self.pending_preparation is not None and self.pending_preparation['side'] != active_trend:
                self.pending_preparation = None

            new_prep = self.evaluate_15m_pullback(df_15m, active_trend)
            if new_prep is not None:
                curr_prep_ts = str(df_15m['timestamp'].iloc[-1])
                if self.pending_preparation is None or self.pending_preparation.get('prep_15m_ts') != curr_prep_ts:
                    self.pending_preparation = new_prep

            if self.pending_preparation is None:
                return {'action': 'NONE', 'price': 0.0, 'sl': 0.0, 'tp': 0.0, 'features': {}, 'reason': 'WAITING_15M_PULLBACK'}

            self.pending_preparation['candles_5m_count'] += 1
            if self.pending_preparation['candles_5m_count'] > self.preparation_expiry_5m_bars:
                self.pending_preparation = None
                return {'action': 'NONE', 'price': 0.0, 'sl': 0.0, 'tp': 0.0, 'features': {}, 'reason': 'PREPARATION_EXPIRED'}

            last_close_5m = float(df_5m['close'].iloc[-1])
            if self.pending_preparation['side'] == 'LONG' and last_close_5m < self.pending_preparation['low_15m']:
                self.pending_preparation = None
                return {'action': 'NONE', 'price': 0.0, 'sl': 0.0, 'tp': 0.0, 'features': {}, 'reason': 'PREPARATION_STRUCTURE_BROKEN'}
            elif self.pending_preparation['side'] == 'SHORT' and last_close_5m > self.pending_preparation['high_15m']:
                self.pending_preparation = None
                return {'action': 'NONE', 'price': 0.0, 'sl': 0.0, 'tp': 0.0, 'features': {}, 'reason': 'PREPARATION_STRUCTURE_BROKEN'}

            trigger_signal = self.evaluate_5m_trigger(df_5m, self.pending_preparation)
            if trigger_signal is not None:
                self.pending_preparation = None
                trigger_signal['reason'] = 'TRIGGER_CONFIRMED_5M'
                return trigger_signal

            return {'action': 'NONE', 'price': 0.0, 'sl': 0.0, 'tp': 0.0, 'features': {}, 'reason': 'WAITING_5M_TRIGGER'}

    class StrategyVariantC(EMAPullbackTrendStrategy):
        """Variante C: 4H como contexto (precio sobre/bajo EMA50), 1H dirección, 15M prep, 5M trigger."""
        def evaluate_custom_macro_trend(self, df_4h, df_1h):
            t1 = self.evaluate_trend(df_1h)
            if t1 == "NONE":
                return "NONE"
            r4 = df_4h.iloc[-1]
            close4 = float(r4['close'])
            ema50_4 = float(r4['ema50'])
            if t1 == "LONG" and close4 > ema50_4:
                return "LONG"
            elif t1 == "SHORT" and close4 < ema50_4:
                return "SHORT"
            return "NONE"

        def generate_signal(self, current_price, saldo, dfs):
            df_4h = dfs.get(self.macro_tf)
            df_1h = dfs.get(self.trend_confirm_tf)
            df_15m = dfs.get(self.pullback_tf)
            if df_15m is None:
                df_15m = dfs.get(self.params.get('entry_tf', '15m'))
            df_5m = dfs.get(self.trigger_tf)

            if df_4h is None or df_1h is None or df_15m is None or df_5m is None:
                return {'action': 'NONE', 'price': 0.0, 'sl': 0.0, 'tp': 0.0, 'features': {}, 'reason': 'MISSING_DATA'}
            if len(df_4h) < 50 or len(df_1h) < 50 or len(df_15m) < 50 or len(df_5m) < 10:
                return {'action': 'NONE', 'price': 0.0, 'sl': 0.0, 'tp': 0.0, 'features': {}, 'reason': 'INSUFFICIENT_WARMUP'}

            active_trend = self.evaluate_custom_macro_trend(df_4h, df_1h)
            if active_trend == "NONE":
                self.pending_preparation = None
                return {'action': 'NONE', 'price': 0.0, 'sl': 0.0, 'tp': 0.0, 'features': {}, 'reason': 'NO_CONFIRMED_TREND'}

            if self.pending_preparation is not None and self.pending_preparation['side'] != active_trend:
                self.pending_preparation = None

            new_prep = self.evaluate_15m_pullback(df_15m, active_trend)
            if new_prep is not None:
                curr_prep_ts = str(df_15m['timestamp'].iloc[-1])
                if self.pending_preparation is None or self.pending_preparation.get('prep_15m_ts') != curr_prep_ts:
                    self.pending_preparation = new_prep

            if self.pending_preparation is None:
                return {'action': 'NONE', 'price': 0.0, 'sl': 0.0, 'tp': 0.0, 'features': {}, 'reason': 'WAITING_15M_PULLBACK'}

            self.pending_preparation['candles_5m_count'] += 1
            if self.pending_preparation['candles_5m_count'] > self.preparation_expiry_5m_bars:
                self.pending_preparation = None
                return {'action': 'NONE', 'price': 0.0, 'sl': 0.0, 'tp': 0.0, 'features': {}, 'reason': 'PREPARATION_EXPIRED'}

            last_close_5m = float(df_5m['close'].iloc[-1])
            if self.pending_preparation['side'] == 'LONG' and last_close_5m < self.pending_preparation['low_15m']:
                self.pending_preparation = None
                return {'action': 'NONE', 'price': 0.0, 'sl': 0.0, 'tp': 0.0, 'features': {}, 'reason': 'PREPARATION_STRUCTURE_BROKEN'}
            elif self.pending_preparation['side'] == 'SHORT' and last_close_5m > self.pending_preparation['high_15m']:
                self.pending_preparation = None
                return {'action': 'NONE', 'price': 0.0, 'sl': 0.0, 'tp': 0.0, 'features': {}, 'reason': 'PREPARATION_STRUCTURE_BROKEN'}

            trigger_signal = self.evaluate_5m_trigger(df_5m, self.pending_preparation)
            if trigger_signal is not None:
                self.pending_preparation = None
                trigger_signal['reason'] = 'TRIGGER_CONFIRMED_5M'
                return trigger_signal

            return {'action': 'NONE', 'price': 0.0, 'sl': 0.0, 'tp': 0.0, 'features': {}, 'reason': 'WAITING_5M_TRIGGER'}

    # Ejecutar Variante B
    print("⏳ Ejecutando Variante B (Anticipada 1H + Pendiente 4H)...")
    orig_create = StrategyFactory.create_strategy
    StrategyFactory.create_strategy = staticmethod(lambda name, pm, rm: StrategyVariantB(pm, rm))
    with contextlib.redirect_stdout(io.StringIO()):
        engine_b = BacktestEngine(dfs)
        history_b = engine_b.run()
    print(f"✅ Variante B completada: {len(history_b)} eventos.")

    # Ejecutar Variante C
    print("⏳ Ejecutando Variante C (Híbrida: 4H Contexto EMA50)...")
    StrategyFactory.create_strategy = staticmethod(lambda name, pm, rm: StrategyVariantC(pm, rm))
    with contextlib.redirect_stdout(io.StringIO()):
        engine_c = BacktestEngine(dfs)
        history_c = engine_c.run()
    print(f"✅ Variante C completada: {len(history_c)} eventos.")
    StrategyFactory.create_strategy = orig_create

    # Partición temporal cronológica:
    # Train / In-Sample (IS):   2026-06-01 a 2026-06-20
    # Test / Out-of-Sample (OOS): 2026-06-21 a 2026-07-05
    split_date = "2026-06-21 00:00:00"

    def compute_stats(name, history):
        df_h = pd.DataFrame(history)
        if len(df_h) == 0:
            return {'Variante': name, 'Trades': 0, 'NetPnL_Real': 0.0, 'WinRate%': 0.0, 'ProfitFactor': 0.0, 'MaxDD%': 0.0,
                    'IS_Trades': 0, 'IS_NetPnL': 0.0, 'IS_WR%': 0.0, 'IS_PF': 0.0,
                    'OOS_Trades': 0, 'OOS_NetPnL': 0.0, 'OOS_WR%': 0.0, 'OOS_PF': 0.0}
        
        closes = df_h[df_h['reduceOnly'] == True].copy()
        opens = df_h[df_h['reduceOnly'] == False].copy()
        if len(closes) == 0:
            return {'Variante': name, 'Trades': 0, 'NetPnL_Real': 0.0, 'WinRate%': 0.0, 'ProfitFactor': 0.0, 'MaxDD%': 0.0,
                    'IS_Trades': 0, 'IS_NetPnL': 0.0, 'IS_WR%': 0.0, 'IS_PF': 0.0,
                    'OOS_Trades': 0, 'OOS_NetPnL': 0.0, 'OOS_WR%': 0.0, 'OOS_PF': 0.0}

        entry_fees = opens['fee'].values[:len(closes)]
        closes['entry_fee'] = entry_fees
        closes['total_fee'] = closes['fee'] + closes['entry_fee']
        closes['real_net_pnl'] = closes['pnl'] - closes['total_fee']

        # Drawdown real
        eq = [initial_balance] + closes['balance'].tolist()
        s_eq = pd.Series(eq)
        peaks = s_eq.cummax()
        max_dd = ((peaks - s_eq) / peaks * 100.0).max()

        # Partición
        in_s = closes[closes['timestamp'] < split_date]
        out_s = closes[closes['timestamp'] >= split_date]

        def get_sub(sub_df):
            n = len(sub_df)
            if n == 0:
                return 0, 0.0, 0.0, 0.0
            wins = sub_df[sub_df['real_net_pnl'] > 0]
            loss = sub_df[sub_df['real_net_pnl'] <= 0]
            wr = round(len(wins) / n * 100.0, 1)
            gp = wins['real_net_pnl'].sum() if len(wins) > 0 else 0.0
            gl = abs(loss['real_net_pnl'].sum()) if len(loss) > 0 else 0.0
            pf = round(gp / gl, 2) if gl > 0 else (999.0 if gp > 0 else 0.0)
            net = round(sub_df['real_net_pnl'].sum(), 2)
            return n, net, wr, pf

        t_n, t_net, t_wr, t_pf = get_sub(closes)
        is_n, is_net, is_wr, is_pf = get_sub(in_s)
        oos_n, oos_net, oos_wr, oos_pf = get_sub(out_s)

        return {
            'Variante': name,
            'Trades': t_n,
            'NetPnL_Real': t_net,
            'WinRate%': t_wr,
            'ProfitFactor': t_pf,
            'MaxDD%': round(max_dd, 2),
            'IS_Trades': is_n,
            'IS_NetPnL': is_net,
            'IS_WR%': is_wr,
            'IS_PF': is_pf,
            'OOS_Trades': oos_n,
            'OOS_NetPnL': oos_net,
            'OOS_WR%': oos_wr,
            'OOS_PF': oos_pf
        }

    comp_list = [
        compute_stats("A. Actual (4H Estricto)", history_a),
        compute_stats("B. Anticipada (1H + 4H Slope)", history_b),
        compute_stats("C. Híbrida (4H Contexto EMA50)", history_c)
    ]

    df_comp = pd.DataFrame(comp_list)
    print("\n" + "=" * 105)
    print("📊 MATRIZ COMPARATIVA EXPERIMENTAL CON PARTICIÓN IN-SAMPLE (IS) Y OUT-OF-SAMPLE (OOS)")
    print("=" * 105)
    print(df_comp.to_string(index=False))

    return df_rec, df_comp

if __name__ == '__main__':
    run_forensic_validation()
