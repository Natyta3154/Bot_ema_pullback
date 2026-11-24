"""
Laboratorio de Investigación Cuantitativa de Gatillos de Entrada (Fase 3)
Estrategia: EMA_PULLBACK_TREND
Comparación de Variantes de Gatillo:
  - Variante A: Gatillo actual de ruptura en 5M.
  - Variante B: Confirmación de continuación en 15M.
  - Variante C: Gatillo de ruptura en 5M con filtros de Volumen y Volatilidad (ATR).

Validación en dos horizontes:
  1. Período Baseline de Auditoría: 2026-06-01 a 2026-07-05 (35 días, 10.080 velas 5M).
  2. Período Extendido Multirégimen: 2026-01-01 a 2026-07-05 (6 meses, 53.568 velas 5M).
Partición cronológica In-Sample (IS) y Out-of-Sample (OOS).
Reconciliación contable exacta al centavo.
"""
import os
import sys
import io
import contextlib
import pandas as pd
import numpy as np

# Configurar path raíz
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)

from bot.config import settings
from bot.backtest.data_loader import DataLoader
from bot.backtest.engine import BacktestEngine
from bot.backtest.metrics import calculate_metrics
from bot.strategies.ema_pullback_trend_strategy import EMAPullbackTrendStrategy
import pandas_ta as ta

# ------------------------------------------------------------------------------
# 1. DEFINICIÓN DE ESTRATEGIAS EXPERIMENTALES AISLADAS
# ------------------------------------------------------------------------------

class StrategyVariantA(EMAPullbackTrendStrategy):
    """Variante A: Gatillo de Ruptura Actual en 5M (Lógica Base Sin Modificaciones)."""
    pass


class StrategyVariantB(EMAPullbackTrendStrategy):
    """
    Variante B: Gatillo por Confirmación Estructural en 15M.
    Regla de Entrada Definida A Priori:
      - Tras la vela de preparación en 15M (que tocó EMA y cerró a favor),
        se espera confirmación en las siguientes velas de 15M (máximo 2 velas = 30 min).
      - Para LONG: La vela de 15M debe romper y cerrar por encima del máximo de la
        vela de preparación (close_15m > prep['high_15m']), confirmando intención alcista.
        Condición de invalidación: low_15m no perfora el swing_ref.
      - Para SHORT: La vela de 15M debe romper y cerrar por debajo del mínimo de la
        vela de preparación (close_15m < prep['low_15m']).
      - SL: Ubicado en swing_ref - buffer * ATR_15m (Long) / swing_ref + buffer * ATR_15m (Short).
      - TP: 2R proyectado.
    """
    def __init__(self, position_manager, risk_manager):
        super().__init__(position_manager, risk_manager)
        self.last_evaluated_15m_ts = None
        self.prep_15m_candles_elapsed = 0

    def evaluate_15m_confirmation_trigger(self, df_15m: pd.DataFrame, prep: dict) -> dict:
        if df_15m is None or len(df_15m) < 2:
            return None

        row_curr = df_15m.iloc[-1]
        close_15m = float(row_curr['close'])
        open_15m = float(row_curr['open'])
        high_15m = float(row_curr['high'])
        low_15m = float(row_curr['low'])
        atr_15m = float(row_curr.get('atr', close_15m * 0.01))

        side = prep['side']

        if side == "LONG":
            prep_high = prep.get('high_15m', prep['prep_price'])
            # Confirmación de ruptura en 15M: cierre sobre el máximo de la preparación
            is_breakout = close_15m > prep_high
            # Vela verde
            is_bullish = close_15m > open_15m
            # No violar estructura
            structure_intact = low_15m >= prep['swing_ref']

            if not (is_breakout and is_bullish and structure_intact):
                return None

            # SL y TP
            if self.sl_type == 'atr':
                sl_price = close_15m - (self.sl_atr_mult * atr_15m)
            else:
                sl_price = prep['swing_ref'] - (self.sl_swing_buffer_atr * atr_15m)

            risk_dist = close_15m - sl_price
            min_dist = close_15m * self.sl_min_dist_pct
            max_dist = close_15m * self.sl_max_dist_pct

            if sl_price >= close_15m or risk_dist < min_dist or risk_dist > max_dist:
                return None

            tp_price = close_15m + (self.rr_ratio * risk_dist)

            # Costos
            roundtrip_cost_pct = (self.est_commission_pct + self.est_slippage_pct) * 2
            est_cost = close_15m * roundtrip_cost_pct
            net_reward = (tp_price - close_15m) - est_cost
            net_risk = (close_15m - sl_price) + est_cost
            if net_risk <= 0 or (net_reward / net_risk) < float(self.params.get('min_net_rr', 0.5)):
                return None

            return {
                'action': 'LONG',
                'price': close_15m,
                'sl': sl_price,
                'tp': tp_price,
                'features': {
                    'sl_type': self.sl_type,
                    'sl_price': sl_price,
                    'atr_15m': atr_15m,
                    'prep_price': prep['prep_price'],
                    'net_rr': round(net_reward / net_risk, 2)
                }
            }

        elif side == "SHORT":
            prep_low = prep.get('low_15m', prep['prep_price'])
            is_breakout = close_15m < prep_low
            is_bearish = close_15m < open_15m
            structure_intact = high_15m <= prep['swing_ref']

            if not (is_breakout and is_bearish and structure_intact):
                return None

            if self.sl_type == 'atr':
                sl_price = close_15m + (self.sl_atr_mult * atr_15m)
            else:
                sl_price = prep['swing_ref'] + (self.sl_swing_buffer_atr * atr_15m)
            risk_dist = sl_price - close_15m
            min_dist = close_15m * self.sl_min_dist_pct
            max_dist = close_15m * self.sl_max_dist_pct

            if sl_price <= close_15m or risk_dist < min_dist or risk_dist > max_dist:
                return None

            tp_price = close_15m - (self.rr_ratio * risk_dist)

            roundtrip_cost_pct = (self.est_commission_pct + self.est_slippage_pct) * 2
            est_cost = close_15m * roundtrip_cost_pct
            net_reward = (close_15m - tp_price) - est_cost
            net_risk = (sl_price - close_15m) + est_cost
            if net_risk <= 0 or (net_reward / net_risk) < float(self.params.get('min_net_rr', 0.5)):
                return None

            return {
                'action': 'SHORT',
                'price': close_15m,
                'sl': sl_price,
                'tp': tp_price,
                'features': {
                    'sl_type': 'swing_15m',
                    'sl_price': sl_price,
                    'atr_15m': atr_15m,
                    'prep_price': prep['prep_price'],
                    'net_rr': round(net_reward / net_risk, 2)
                }
            }

        return None

    def generate_signal(self, current_price: float, saldo: float, dfs: dict) -> dict:
        result = {'action': 'NONE', 'price': 0.0, 'sl': 0.0, 'tp': 0.0, 'features': {}, 'reason': ''}
        df_4h = dfs.get(self.macro_tf)
        df_1h = dfs.get(self.trend_confirm_tf)
        df_15m = dfs.get(self.pullback_tf)
        if df_15m is None:
            df_15m = dfs.get(self.params.get('entry_tf', '15m'))
        df_5m = dfs.get(self.trigger_tf)

        if df_4h is None or df_1h is None or df_15m is None or df_5m is None:
            result['reason'] = 'MISSING_DATA'
            return result

        if len(df_4h) < 50 or len(df_1h) < 50 or len(df_15m) < 50 or len(df_5m) < 10:
            result['reason'] = 'INSUFFICIENT_WARMUP'
            return result

        # 1. Tendencia 4H y 1H
        trend_4h = self.evaluate_trend(df_4h)
        trend_1h = self.evaluate_trend(df_1h)
        if trend_4h == "NONE" or trend_1h == "NONE" or trend_4h != trend_1h:
            self.pending_preparation = None
            result['reason'] = 'NO_CONFIRMED_TREND'
            return result

        active_trend = trend_4h

        # Verificar si cerró nueva vela de 15M
        curr_15m_ts = str(df_15m['timestamp'].iloc[-1])
        is_new_15m_candle = (self.last_evaluated_15m_ts != curr_15m_ts)

        if is_new_15m_candle:
            self.last_evaluated_15m_ts = curr_15m_ts

            if self.pending_preparation is not None:
                if self.pending_preparation['side'] != active_trend:
                    self.pending_preparation = None
                else:
                    self.prep_15m_candles_elapsed += 1

            new_prep = self.evaluate_15m_pullback(df_15m, active_trend)
            if new_prep is not None:
                if self.pending_preparation is None or self.pending_preparation.get('prep_15m_ts') != curr_15m_ts:
                    self.pending_preparation = new_prep
                    self.prep_15m_candles_elapsed = 0

            # Caducidad: Máximo 2 velas de 15M (30 min)
            if self.pending_preparation is not None and self.prep_15m_candles_elapsed > 2:
                self.pending_preparation = None

            # Si hay preparación activa y pasaron 1 o 2 velas, evaluar confirmación en 15M
            if self.pending_preparation is not None and self.prep_15m_candles_elapsed >= 1:
                sig = self.evaluate_15m_confirmation_trigger(df_15m, self.pending_preparation)
                if sig is not None:
                    self.pending_preparation = None
                    self.prep_15m_candles_elapsed = 0
                    sig['reason'] = 'TRIGGER_CONFIRMED_15M'
                    return sig

        if self.pending_preparation is None:
            result['reason'] = 'WAITING_15M_PULLBACK'
        else:
            result['reason'] = 'WAITING_15M_TRIGGER'
        return result


class StrategyVariantC(EMAPullbackTrendStrategy):
    """
    Variante C: Gatillo en 5M con Filtros Explícitos de Volumen y Régimen de Volatilidad.
    Mantiene:
      - Mismo filtro 4H/1H y misma preparación en 15M.
      - Misma lógica de ruptura de swing local en 5M.
    Añade Filtros Cuantitativos Pre-definidos:
      1. Filtro de Volumen: volume_5m > volume_sma20_5m * 1.10 (Expansión de volumen en la vela de ruptura).
      2. Filtro de Volatilidad: atr_5m > atr_sma20_5m (Régimen de expansión vs contracción)
         y atr_5m / close_5m >= 0.001 (sin micro-volatilidad anémica).
    """
    def analyze_market(self, dfs: dict) -> None:
        super().analyze_market(dfs)
        df_5m = dfs.get(self.trigger_tf)
        if df_5m is not None and len(df_5m) >= 25:
            if 'volume_sma20' not in df_5m.columns:
                df_5m['volume_sma20'] = df_5m['volume'].rolling(window=20).mean()
            if 'atr_sma20' not in df_5m.columns:
                df_5m['atr_sma20'] = df_5m['atr'].rolling(window=20).mean()
            df_5m.ffill(inplace=True)

    def evaluate_5m_trigger(self, df_5m: pd.DataFrame, prep: dict) -> dict:
        # Obtener señal base de 5M
        base_signal = super().evaluate_5m_trigger(df_5m, prep)
        if base_signal is None:
            return None

        # Evaluar filtros adicionales de Volumen y Volatilidad
        row_curr = df_5m.iloc[-1]
        volume = float(row_curr.get('volume', 0.0))
        vol_sma20 = float(row_curr.get('volume_sma20', 0.0))
        atr_5m = float(row_curr.get('atr', 0.0))
        atr_sma20 = float(row_curr.get('atr_sma20', 0.0))
        close_5m = float(row_curr.get('close', 1.0))

        # 1. Filtro de Volumen: Ruptura con volumen superior a la media (participación real)
        volume_ok = (vol_sma20 > 0) and (volume >= vol_sma20 * 1.10)

        # 2. Filtro de Volatilidad: ATR por encima de su media (expansión activa, no compresión)
        volatility_ok = (atr_sma20 > 0) and (atr_5m >= atr_sma20) and ((atr_5m / close_5m) >= 0.001)

        if not (volume_ok and volatility_ok):
            return None

        base_signal['features']['volume_ratio'] = round(volume / vol_sma20, 2) if vol_sma20 > 0 else 1.0
        base_signal['features']['atr_ratio'] = round(atr_5m / atr_sma20, 2) if atr_sma20 > 0 else 1.0
        return base_signal


# ------------------------------------------------------------------------------
# 2. MOTOR DE RECONCILIACIÓN Y CÁLCULO DE MÉTRICAS DETALLADAS
# ------------------------------------------------------------------------------

def analyze_simulation_history(history: list, initial_balance: float = 1000.0, split_date: str = None) -> dict:
    if not history:
        return {'trades_count': 0, 'real_net_pnl': 0.0}

    df = pd.DataFrame(history)
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    opens = df[df['reduceOnly'] == False].copy().reset_index(drop=True)
    closes = df[df['reduceOnly'] == True].copy().reset_index(drop=True)

    reconciled = []
    n = min(len(opens), len(closes))
    for i in range(n):
        o = opens.iloc[i]
        c = closes.iloc[i]

        direction = "LONG" if o['side'] == 'buy' else "SHORT"
        p_in = float(o['price'])
        p_out = float(c['price'])
        qty = float(o['amount'])

        fee_in = float(o['fee'])
        fee_out = float(c['fee'])
        tot_fee = fee_in + fee_out

        gross_pnl = float(c['pnl'])
        real_net = gross_pnl - tot_fee

        reconciled.append({
            'trade_idx': i + 1,
            'direction': direction,
            'entry_time': o['timestamp'],
            'exit_time': c['timestamp'],
            'entry_price': p_in,
            'exit_price': p_out,
            'qty': qty,
            'gross_pnl': gross_pnl,
            'fee_in': fee_in,
            'fee_out': fee_out,
            'total_fees': tot_fee,
            'real_net_pnl': real_net,
            'exit_reason': c.get('exit_reason', c.get('type', '')),
            'end_balance': float(c['balance'])
        })

    df_rec = pd.DataFrame(reconciled)
    if len(df_rec) == 0:
        return {'trades_count': 0, 'real_net_pnl': 0.0}

    # Reconstrucción de la curva de equity
    equity_curve = [initial_balance]
    for b in df_rec['end_balance']:
        equity_curve.append(float(b))

    eq_s = pd.Series(equity_curve)
    peak_s = eq_s.cummax()
    dd_s = (eq_s - peak_s) / peak_s
    max_dd_usdt = round(float((peak_s - eq_s).max()), 2)
    max_dd_pct = round(float(abs(dd_s.min()) * 100.0), 2)

    wins = df_rec[df_rec['real_net_pnl'] > 0]
    losses = df_rec[df_rec['real_net_pnl'] <= 0]

    total_trades = len(df_rec)
    win_rate = round(len(wins) / total_trades * 100.0, 1)

    gross_profit = wins['real_net_pnl'].sum() if len(wins) > 0 else 0.0
    gross_loss = abs(losses['real_net_pnl'].sum()) if len(losses) > 0 else 0.0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

    sum_real_net = round(df_rec['real_net_pnl'].sum(), 2)
    sum_gross = round(df_rec['gross_pnl'].sum(), 2)
    sum_fees = round(df_rec['total_fees'].sum(), 2)

    avg_win = wins['real_net_pnl'].mean() if len(wins) > 0 else 0.0
    avg_loss = abs(losses['real_net_pnl'].mean()) if len(losses) > 0 else 0.0
    expectancy_usdt = round((win_rate / 100.0 * avg_win) - ((1 - win_rate / 100.0) * avg_loss), 2)

    # Duración media
    durations = (df_rec['exit_time'] - df_rec['entry_time']).dt.total_seconds() / 60.0
    avg_duration_mins = round(durations.mean(), 1)

    # Long vs Short
    longs = df_rec[df_rec['direction'] == 'LONG']
    shorts = df_rec[df_rec['direction'] == 'SHORT']
    long_wins = longs[longs['real_net_pnl'] > 0]
    short_wins = shorts[shorts['real_net_pnl'] > 0]
    long_pnl = round(longs['real_net_pnl'].sum(), 2) if len(longs) > 0 else 0.0
    short_pnl = round(shorts['real_net_pnl'].sum(), 2) if len(shorts) > 0 else 0.0
    long_wr = round(len(long_wins) / len(longs) * 100.0, 1) if len(longs) > 0 else 0.0
    short_wr = round(len(short_wins) / len(shorts) * 100.0, 1) if len(shorts) > 0 else 0.0

    # Partición In-Sample / Out-of-Sample
    is_trades, oos_trades = None, None
    is_net, oos_net = 0.0, 0.0
    is_wr, oos_wr = 0.0, 0.0
    is_pf, oos_pf = 0.0, 0.0
    is_count, oos_count = 0, 0

    if split_date is not None:
        split_dt = pd.to_datetime(split_date)
        df_is = df_rec[df_rec['entry_time'] <= split_dt]
        df_oos = df_rec[df_rec['entry_time'] > split_dt]

        is_count = len(df_is)
        oos_count = len(df_oos)
        if is_count > 0:
            is_net = round(df_is['real_net_pnl'].sum(), 2)
            is_w = df_is[df_is['real_net_pnl'] > 0]
            is_l = df_is[df_is['real_net_pnl'] <= 0]
            is_wr = round(len(is_w) / is_count * 100.0, 1)
            gp = is_w['real_net_pnl'].sum() if len(is_w) > 0 else 0.0
            gl = abs(is_l['real_net_pnl'].sum()) if len(is_l) > 0 else 0.0
            is_pf = round(gp / gl, 2) if gl > 0 else (999.0 if gp > 0 else 0.0)

        if oos_count > 0:
            oos_net = round(df_oos['real_net_pnl'].sum(), 2)
            oos_w = df_oos[df_oos['real_net_pnl'] > 0]
            oos_l = df_oos[df_oos['real_net_pnl'] <= 0]
            oos_wr = round(len(oos_w) / oos_count * 100.0, 1)
            gp = oos_w['real_net_pnl'].sum() if len(oos_w) > 0 else 0.0
            gl = abs(oos_l['real_net_pnl'].sum()) if len(oos_l) > 0 else 0.0
            oos_pf = round(gp / gl, 2) if gl > 0 else (999.0 if gp > 0 else 0.0)

    # Verificación de conciliación exacta
    final_balance = round(float(df_rec['end_balance'].iloc[-1]), 2)
    equity_delta = round(final_balance - initial_balance, 2)
    reconciled_ok = abs(sum_real_net - equity_delta) < 0.05

    return {
        'trades_count': total_trades,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'real_net_pnl': sum_real_net,
        'gross_pnl': sum_gross,
        'total_fees': sum_fees,
        'max_dd_usdt': max_dd_usdt,
        'max_dd_pct': max_dd_pct,
        'expectancy_usdt': expectancy_usdt,
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'avg_duration_mins': avg_duration_mins,
        'final_balance': final_balance,
        'equity_delta': equity_delta,
        'reconciled_ok': reconciled_ok,
        'longs': len(longs),
        'long_pnl': long_pnl,
        'long_wr': long_wr,
        'shorts': len(shorts),
        'short_pnl': short_pnl,
        'short_wr': short_wr,
        'is_count': is_count,
        'is_net': is_net,
        'is_wr': is_wr,
        'is_pf': is_pf,
        'oos_count': oos_count,
        'oos_net': oos_net,
        'oos_wr': oos_wr,
        'oos_pf': oos_pf,
        'df_rec': df_rec,
        'equity_curve': equity_curve
    }


# ------------------------------------------------------------------------------
# 3. EJECUTOR DE SIMULACIONES CONTROLADAS
# ------------------------------------------------------------------------------

def run_experiment(strategy_class, dfs: dict, initial_balance: float = 1000.0, split_date: str = None) -> dict:
    settings.ENVIRONMENT = "BACKTEST"
    settings.ENABLE_DETAILED_LOGS = False

    # Configuración base común obligatoria
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
        "body_ratio_threshold": 0.55,
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

    engine = BacktestEngine(dfs)
    # Inyectar la clase de estrategia personalizada
    engine.engine.strategy = strategy_class(engine.engine.position_manager, engine.engine.risk_manager)
    engine.engine.strategy.analyze_market(dfs)

    with contextlib.redirect_stdout(io.StringIO()):
        history = engine.run()

    return analyze_simulation_history(history, initial_balance, split_date)


def run_full_investigation():
    print("=" * 90)
    print("🔬 FASE 3: INVESTIGACIÓN CUANTITATIVA DE GATILLOS Y RENTABILIDAD")
    print("   Estrategia: EMA_PULLBACK_TREND")
    print("=" * 90)

    symbol = "BTC/USDT"
    loader = DataLoader(symbol=symbol)

    # --------------------------------------------------------------------------
    # BLOQUE 1: EXPERIMENTO SOBRE EL PERÍODO BASELINE (2026-06-01 a 2026-07-05)
    # --------------------------------------------------------------------------
    print("\n" + "=" * 90)
    print("📍 EXPERIMENTO 1: PERÍODO BASELINE DE AUDITORÍA FORENSE (35 DÍAS: 2026-06-01 A 2026-07-05)")
    print("   Partición: IS (2026-06-01 a 2026-06-20) / OOS (2026-06-21 a 2026-07-05)")
    print("=" * 90)

    timeframes = ['4h', '1h', '30m', '15m', '5m']
    dfs_base = {}
    for tf in timeframes:
        dfs_base[tf] = loader.fetch_data(tf, "2026-06-01", "2026-07-05")

    print("\n⏳ Ejecutando Variante A (Baseline 5M)...")
    res_a_base = run_experiment(StrategyVariantA, dfs_base, split_date="2026-06-20")

    print("⏳ Ejecutando Variante B (Confirmación 15M)...")
    res_b_base = run_experiment(StrategyVariantB, dfs_base, split_date="2026-06-20")

    print("⏳ Ejecutando Variante C (Gatillo 5M + Filtros Volumen y ATR)...")
    res_c_base = run_experiment(StrategyVariantC, dfs_base, split_date="2026-06-20")

    # --------------------------------------------------------------------------
    # BLOQUE 2: EXPERIMENTO SOBRE EL PERÍODO EXTENDIDO (6 MESES: 2026-01-01 a 2026-07-05)
    # --------------------------------------------------------------------------
    print("\n" + "=" * 90)
    print("📍 EXPERIMENTO 2: PERÍODO EXTENDIDO MULTIRÉGIMEN (6 MESES: 2026-01-01 A 2026-07-05)")
    print("   Partición: IS (2026-01-01 a 2026-04-30: 4 meses) / OOS (2026-05-01 a 2026-07-05: 2.2 meses)")
    print("=" * 90)

    dfs_ext = {}
    for tf in timeframes:
        dfs_ext[tf] = loader.fetch_data(tf, "2026-01-01", "2026-07-05")

    print("\n⏳ Ejecutando Variante A (Extendido 6M)...")
    res_a_ext = run_experiment(StrategyVariantA, dfs_ext, split_date="2026-04-30")

    print("⏳ Ejecutando Variante B (Extendido 6M)...")
    res_b_ext = run_experiment(StrategyVariantB, dfs_ext, split_date="2026-04-30")

    print("⏳ Ejecutando Variante C (Extendido 6M)...")
    res_c_ext = run_experiment(StrategyVariantC, dfs_ext, split_date="2026-04-30")

    # --------------------------------------------------------------------------
    # BLOQUE 3: CONSTRUCCIÓN DE TABLAS Y REPORTE COMPARATIVO
    # --------------------------------------------------------------------------
    def print_summary_table(title, results):
        print(f"\n{title}")
        print("-" * 125)
        header = f"{'Variante':<28} | {'Trades':<6} | {'WR %':<6} | {'PF':<5} | {'Net PnL':<10} | {'Max DD%':<8} | {'Expect':<8} | {'IS (Tr/PnL/PF)':<16} | {'OOS (Tr/PnL/PF)':<16}"
        print(header)
        print("-" * 125)
        for name, r in results.items():
            is_str = f"{r['is_count']} / {r['is_net']:+.1f} / {r['is_pf']:.2f}"
            oos_str = f"{r['oos_count']} / {r['oos_net']:+.1f} / {r['oos_pf']:.2f}"
            row = f"{name:<28} | {r['trades_count']:<6} | {r['win_rate']:<6.1f} | {r['profit_factor']:<5.2f} | {r['real_net_pnl']:<+10.2f} | {r['max_dd_pct']:<8.2f} | {r['expectancy_usdt']:<+8.2f} | {is_str:<16} | {oos_str:<16}"
            print(row)
        print("-" * 125)

    res_base = {
        "A. Base (5M Ruptura)": res_a_base,
        "B. Conf. 15M (Vela Cerrada)": res_b_base,
        "C. 5M + Vol/ATR": res_c_base
    }
    print_summary_table("📊 RESULTADOS EXPERIMENTO 1 — PERÍODO BASELINE (2026-06-01 a 2026-07-05)", res_base)

    res_ext = {
        "A. Base (5M Ruptura)": res_a_ext,
        "B. Conf. 15M (Vela Cerrada)": res_b_ext,
        "C. 5M + Vol/ATR": res_c_ext
    }
    print_summary_table("📊 RESULTADOS EXPERIMENTO 2 — PERÍODO EXTENDIDO 6 MESES (2026-01-01 a 2026-07-05)", res_ext)

    # Detalle de Costos y Long/Short
    print("\n" + "=" * 90)
    print("🔍 DESGLOSE DE COSTOS Y DIRECCIÓN (PERÍODO EXTENDIDO 6 MESES)")
    print("=" * 90)
    for name, r in res_ext.items():
        print(f"\n--- {name} ---")
        print(f"  • PnL Bruto:               {r['gross_pnl']:+8.2f} USDT")
        print(f"  • Comisiones Totales:      {r['total_fees']:8.2f} USDT")
        print(f"  • PnL Neto Real:           {r['real_net_pnl']:+8.2f} USDT")
        print(f"  • Conciliación Contable:   Delta Cuenta = {r['equity_delta']:+.2f} USDT | Coincidencia: {'100% EXACTA' if r['reconciled_ok'] else 'ERROR'}")
        print(f"  • Longs:  {r['longs']} trades | Win Rate: {r['long_wr']}% | PnL: {r['long_pnl']:+.2f} USDT")
        print(f"  • Shorts: {r['shorts']} trades | Win Rate: {r['short_wr']}% | PnL: {r['short_pnl']:+.2f} USDT")
        print(f"  • Duración media por trade: {r['avg_duration_mins']} minutos")

    # Guardar datos en archivo para la generación de entregable
    import json
    summary_export = {}
    for exp_name, d_res in [('baseline', res_base), ('extended', res_ext)]:
        summary_export[exp_name] = {}
        for var_name, r in d_res.items():
            summary_export[exp_name][var_name] = {
                'trades': int(r['trades_count']),
                'win_rate': float(r['win_rate']),
                'profit_factor': float(r['profit_factor']),
                'real_net_pnl': float(r['real_net_pnl']),
                'gross_pnl': float(r['gross_pnl']),
                'total_fees': float(r['total_fees']),
                'max_dd_usdt': float(r['max_dd_usdt']),
                'max_dd_pct': float(r['max_dd_pct']),
                'expectancy_usdt': float(r['expectancy_usdt']),
                'avg_win': float(r['avg_win']),
                'avg_loss': float(r['avg_loss']),
                'avg_duration_mins': float(r['avg_duration_mins']),
                'final_balance': float(r['final_balance']),
                'equity_delta': float(r['equity_delta']),
                'reconciled_ok': bool(r['reconciled_ok']),
                'longs': int(r['longs']),
                'long_pnl': float(r['long_pnl']),
                'long_wr': float(r['long_wr']),
                'shorts': int(r['shorts']),
                'short_pnl': float(r['short_pnl']),
                'short_wr': float(r['short_wr']),
                'is_count': int(r['is_count']),
                'is_net': float(r['is_net']),
                'is_wr': float(r['is_wr']),
                'is_pf': float(r['is_pf']),
                'oos_count': int(r['oos_count']),
                'oos_net': float(r['oos_net']),
                'oos_wr': float(r['oos_wr']),
                'oos_pf': float(r['oos_pf']),
                'equity_curve': [float(round(x, 2)) for x in r['equity_curve']]
            }
            # Guardar trades reconciliados en CSV
            csv_path = f"bot/research/trades_{exp_name}_{var_name.replace(' ', '_').replace('.', '').replace('(', '').replace(')', '').replace('/', '_')}.csv"
            r['df_rec'].to_csv(csv_path, index=False)

    with open("bot/research/investigation_fase3_results.json", "w") as f:
        json.dump(summary_export, f, indent=2)

    print("\n✅ Archivo 'bot/research/investigation_fase3_results.json' guardado con éxito.")
    print("✅ CSVs detallados de trades guardados en bot/research/.")

if __name__ == "__main__":
    run_full_investigation()
