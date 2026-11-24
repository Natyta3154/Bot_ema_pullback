"""
Módulo: ema_pullback_trend_strategy.py
=================================================
Estrategia Multitemporal: 4H + 1H + 15M + 5M (EMA Pullback Trend)

Arquitectura de Decisión Cuantitativa:
- 4H: Define la tendencia macro (EMA 17, 30, 50 y pendiente EMA30).
- 1H: Confirma la tendencia operativa (EMA 17, 30, 50 y pendiente EMA30).
- 15m: Identifica el retroceso (pullback), confirmación de vela y prepara la entrada.
- 5m: Gatillo de entrada por confirmación estructural (ruptura local) y optimización de precio.

Opera estrictamente sobre velas cerradas y valida gestión de riesgo 2R.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
from bot.strategies.base import BaseStrategy
from bot.core.trade_logger import logger
import pandas_ta as ta


class EMAPullbackTrendStrategy(BaseStrategy):
    """
    Estrategia de Tendencia Multitemporal (4H, 1H, 15M, 5M).
    Reutiliza la gestión de riesgo y ejecución existentes del bot.
    """
    def __init__(self, position_manager, risk_manager):
        super().__init__(position_manager, risk_manager)
        self.name = "EMA_PULLBACK_TREND"
        from bot.config import settings
        self.params = settings.STRATEGY_PARAMS.get("EMA_PULLBACK_TREND", {})

        # Configuración de Timeframes y Filtro 4H
        self.macro_tf = self.params.get('macro_tf', '1h')
        self.trend_confirm_tf = self.params.get('trend_confirm_tf', '1h')
        self.pullback_tf = self.params.get('pullback_tf', '15m')
        self.trigger_tf = self.params.get('trigger_tf', '5m')
        self.use_4h_filter = bool(self.params.get('use_4h_filter', (self.macro_tf == '4h')))
        self.strict_ema_alignment = bool(self.params.get('strict_ema_alignment', True))

        # Filtros de Volumen y Volatilidad (Perfil 2: Agresivo Balanceado + Anti-Racha)
        self.use_volume_filter = bool(self.params.get('use_volume_filter', True))
        self.vol_multiplier = float(self.params.get('vol_multiplier', 1.00))
        self.use_atr_regime = bool(self.params.get('use_atr_regime', False))
        self.min_atr_pct = float(self.params.get('min_atr_pct', 0.0005))
        self.order_type = str(self.params.get('order_type', 'LIMIT'))

        # Protección Anti-Racha y Anti-Techo/Piso
        self.prevent_exhaustion_entries = bool(self.params.get('prevent_exhaustion_entries', True))
        self.require_15m_ema_alignment = bool(self.params.get('require_15m_ema_alignment', True))
        self.sl_cooldown_15m_bars = int(self.params.get('sl_cooldown_15m_bars', 2))
        self.max_consecutive_sl_same_side = int(self.params.get('max_consecutive_sl_same_side', 2))

        # Parámetros de Indicadores
        self.fast_ema = self.params.get('fast_ema', 17)
        self.mid_ema = self.params.get('mid_ema', 30)
        self.slow_ema = self.params.get('slow_ema', 50)
        self.rsi_period = self.params.get('rsi_period', 14)

        # Filtros de Entrada
        self.rsi_long_min = self.params.get('rsi_long_min', 40.0)
        self.rsi_long_max = self.params.get('rsi_long_max', 72.0)
        self.rsi_short_min = self.params.get('rsi_short_min', 28.0)
        self.rsi_short_max = self.params.get('rsi_short_max', 60.0)
        self.body_ratio_threshold = self.params.get('body_ratio_threshold', 0.25)
        self.pullback_tolerance_pct = float(self.params.get('pullback_tolerance_pct', 0.0015))

        # Caducidad de Preparación en 15m y Gatillo en 5m
        self.preparation_expiry_5m_bars = self.params.get('preparation_expiry_5m_bars', 12)
        self.local_swing_lookback_5m = self.params.get('local_swing_lookback_5m', 4)

        # Ratios de Salida y Stop Loss Estructural (Ratio 1:2 con respiro anti-spread)
        self.sl_type = self.params.get('sl_type', 'atr')
        self.sl_atr_mult = float(self.params.get('sl_atr_mult', 1.2))
        self.sl_swing_buffer_atr = float(self.params.get('sl_swing_buffer_atr', 0.20))
        self.sl_min_dist_pct = float(self.params.get('sl_min_dist_pct', 0.0018))
        self.sl_max_dist_pct = float(self.params.get('sl_max_dist_pct', 0.05))
        self.rr_ratio = float(self.params.get('rr_ratio', 2.0))
        self.min_net_rr = float(self.params.get('min_net_rr', 0.5))
        self.est_commission_pct = float(self.params.get('est_commission_pct', 0.0002))
        self.est_slippage_pct = float(self.params.get('est_slippage_pct', 0.0))

        # Estado Interno de la Estrategia (Preparación Pendiente y Memoria Anti-Racha)
        self.pending_preparation: Optional[Dict[str, Any]] = None
        self.last_evaluated_candle_ts: Optional[str] = None
        self.last_consumed_prep_15m_ts: Optional[str] = None
        self.consecutive_sl: Dict[str, int] = {'LONG': 0, 'SHORT': 0}
        self.last_sl_ts: Dict[str, Optional[pd.Timestamp]] = {'LONG': None, 'SHORT': None}
        self.last_sl_entry: Dict[str, Optional[float]] = {'LONG': None, 'SHORT': None}
        self.last_active_trend: str = "NONE"

    def register_trade_outcome(self, side: str, is_win: bool, entry_price: float, exit_price: float, timestamp_str: str = "") -> None:
        """
        Registra el resultado de un trade cerrado para activar el enfriamiento (cooldown)
        y bloquear rachas de re-entradas perdedoras en techos o pisos.
        """
        if side not in ('LONG', 'SHORT'):
            return
        if is_win:
            self.consecutive_sl[side] = 0
            self.last_sl_ts[side] = None
            self.last_sl_entry[side] = None
        else:
            self.consecutive_sl[side] = self.consecutive_sl.get(side, 0) + 1
            if entry_price > 0:
                if self.last_sl_entry[side] is None:
                    self.last_sl_entry[side] = float(entry_price)
                else:
                    # Conservar el mejor nivel de referencia que debe ser superado para desbloquear
                    if side == 'LONG':
                        self.last_sl_entry[side] = max(float(self.last_sl_entry[side]), float(entry_price))
                    else:
                        self.last_sl_entry[side] = min(float(self.last_sl_entry[side]), float(entry_price))
            try:
                self.last_sl_ts[side] = pd.to_datetime(timestamp_str) if timestamp_str else pd.Timestamp.utcnow()
            except Exception:
                self.last_sl_ts[side] = None
            logger.info(
                f"🛡️ [ANTI-RACHA] SL registrado en {side} (#{self.consecutive_sl[side]} consecutivo) "
                f"@ {entry_price:.2f}. Activando enfriamiento ({self.sl_cooldown_15m_bars * 15} min)."
            )

    def get_required_timeframes(self) -> List[str]:
        """Devuelve la lista única de temporalidades requeridas por la estrategia."""
        tfs = [self.trend_confirm_tf, self.pullback_tf, self.trigger_tf]
        if self.use_4h_filter and '4h' not in tfs:
            tfs.insert(0, '4h')
        elif self.macro_tf not in tfs:
            tfs.insert(0, self.macro_tf)
        # Si se especificó entry_tf antiguo para compatibilidad
        if 'entry_tf' in self.params and self.params['entry_tf'] not in tfs:
            tfs.append(self.params['entry_tf'])
        return list(dict.fromkeys(tfs))

    def analyze_market(self, dfs: Dict[str, pd.DataFrame]) -> None:
        """Calcula todos los indicadores necesarios sobre velas cerradas para cada temporalidad."""
        for tf, df in dfs.items():
            if df is None or len(df) < 50:
                continue

            # Calcular EMAs en todas las temporalidades de tendencia y pullback
            if 'ema17' not in df.columns:
                df['ema17'] = ta.ema(df['close'], length=self.fast_ema)
            if 'ema30' not in df.columns:
                df['ema30'] = ta.ema(df['close'], length=self.mid_ema)
            if 'ema50' not in df.columns:
                df['ema50'] = ta.ema(df['close'], length=self.slow_ema)

            # Pendiente de EMA17 y EMA30
            if 'slope_ema17' not in df.columns:
                df['slope_ema17'] = df['ema17'].diff()
            if 'slope_ema30' not in df.columns:
                df['slope_ema30'] = df['ema30'].diff()

            # RSI y ATR
            if 'rsi' not in df.columns:
                df['rsi'] = ta.rsi(df['close'], length=self.rsi_period)
            if 'atr' not in df.columns:
                df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)

            # Swings locales y métricas de volumen / volatilidad
            if tf == self.trigger_tf:
                lookback = self.local_swing_lookback_5m
                df['local_swing_high'] = df['high'].shift(1).rolling(window=lookback).max()
                df['local_swing_low'] = df['low'].shift(1).rolling(window=lookback).min()
                if 'volume_sma20' not in df.columns and 'volume' in df.columns:
                    df['volume_sma20'] = df['volume'].rolling(window=20).mean()
                if 'atr_sma20' not in df.columns and 'atr' in df.columns:
                    df['atr_sma20'] = df['atr'].rolling(window=20).mean()
            elif tf == self.pullback_tf:
                df['swing_high'] = df['high'].shift(1).rolling(window=10).max()
                df['swing_low'] = df['low'].shift(1).rolling(window=10).min()

            df.ffill(inplace=True)

    def evaluate_trend(self, df: pd.DataFrame) -> str:
        """
        Determina la dirección de la tendencia para un DataFrame (4H o 1H).
        - Modo estricto: EMA17 > EMA30 > EMA50 y pendiente EMA30 > 0 (o inverso para SHORT).
        - Filtro anti-giro (prevent_exhaustion_entries): bloquea LONG en techos cuando el precio
          de 1H ya rompió bajo la EMA17 con pendiente de EMA17 negativa (y viceversa en pisos).
        Retorna: 'LONG', 'SHORT' o 'NONE'.
        """
        if df is None or len(df) < 50:
            return "NONE"

        row = df.iloc[-1]
        close_p = row.get('close')
        ema17 = row.get('ema17')
        ema30 = row.get('ema30')
        ema50 = row.get('ema50')
        slope30 = row.get('slope_ema30')
        slope17 = row.get('slope_ema17', 0.0)

        if pd.isna(ema17) or pd.isna(ema30) or pd.isna(ema50) or pd.isna(slope30):
            return "NONE"

        raw_trend = "NONE"
        if ema17 > ema30 and ema30 > ema50 and slope30 > 0:
            raw_trend = "LONG"
        elif ema17 < ema30 and ema30 < ema50 and slope30 < 0:
            raw_trend = "SHORT"
        elif not self.strict_ema_alignment and not pd.isna(close_p):
            if ema17 > ema30 and close_p > ema50 and slope30 > 0:
                raw_trend = "LONG"
            elif ema17 < ema30 and close_p < ema50 and slope30 < 0:
                raw_trend = "SHORT"

        if raw_trend != "NONE" and self.prevent_exhaustion_entries and not pd.isna(close_p) and not pd.isna(slope17):
            if raw_trend == "LONG" and float(close_p) < float(ema17) and float(slope17) < 0:
                return "NONE"
            if raw_trend == "SHORT" and float(close_p) > float(ema17) and float(slope17) > 0:
                return "NONE"

        return raw_trend

    def evaluate_15m_pullback(self, df_15m: pd.DataFrame, trend: str) -> Optional[Dict[str, Any]]:
        """
        Evalúa si la última vela cerrada de 15m representa un retroceso válido con confirmación.
        Retorna un diccionario de preparación si es válida, o None si no califica.
        """
        if df_15m is None or len(df_15m) < 50:
            return None

        row = df_15m.iloc[-1]
        close_p = float(row['close'])
        open_p = float(row['open'])
        high_p = float(row['high'])
        low_p = float(row['low'])
        ema17_p = float(row.get('ema17', close_p))
        ema30_p = float(row.get('ema30', close_p))
        rsi_p = float(row.get('rsi', 50.0))
        atr_p = float(row.get('atr', close_p * 0.01))

        candle_range = high_p - low_p
        if candle_range <= 0:
            return None

        body_ratio = abs(close_p - open_p) / candle_range

        if trend == "LONG":
            # 0. Verificar que las EMAs de 15m no estén ya cruzadas a la baja
            if self.require_15m_ema_alignment and ema17_p < ema30_p:
                return None
            # 1. Retroceso hasta EMA17 o EMA30 (toque o zona de proximidad con buffer de tolerancia)
            ema17_threshold = ema17_p * (1.0 + self.pullback_tolerance_pct)
            ema30_threshold = ema30_p * (1.0 + self.pullback_tolerance_pct)
            touched_ema = (low_p <= ema17_threshold) or (low_p <= ema30_threshold)
            # 2. Vela de confirmación alcista recuperando la EMA17 (o EMA30 si no se exige alineación 15m)
            if self.require_15m_ema_alignment:
                bullish_close = (close_p > open_p) and (close_p >= ema17_p)
            else:
                bullish_close = (close_p > open_p) and ((close_p > ema17_p) or (close_p > ema30_p))
            # 3. Filtro de cuerpo
            solid_body = (body_ratio >= self.body_ratio_threshold)
            # 4. Filtro de Momentum RSI
            rsi_ok = (self.rsi_long_min <= rsi_p <= self.rsi_long_max)

            if touched_ema and bullish_close and solid_body and rsi_ok:
                swing_low_val = min(low_p, float(row.get('swing_low', low_p))) if not pd.isna(row.get('swing_low')) else low_p
                return {
                    'side': 'LONG',
                    'prep_15m_ts': str(row.get('timestamp', '')),
                    'prep_price': close_p,
                    'atr_15m': atr_p,
                    'swing_ref': swing_low_val,
                    'low_15m': low_p,
                    'rsi_15m': rsi_p,
                    'body_ratio_15m': body_ratio,
                    'candles_5m_count': 0
                }

        elif trend == "SHORT":
            # 0. Verificar que las EMAs de 15m no estén ya cruzadas al alza
            if self.require_15m_ema_alignment and ema17_p > ema30_p:
                return None
            # 1. Retroceso hasta EMA17 o EMA30 (toque o zona de proximidad con buffer de tolerancia)
            ema17_threshold = ema17_p * (1.0 - self.pullback_tolerance_pct)
            ema30_threshold = ema30_p * (1.0 - self.pullback_tolerance_pct)
            touched_ema = (high_p >= ema17_threshold) or (high_p >= ema30_threshold)
            # 2. Vela de confirmación bajista cerrando bajo la EMA17 (o EMA30 si no se exige alineación 15m)
            if self.require_15m_ema_alignment:
                bearish_close = (close_p < open_p) and (close_p <= ema17_p)
            else:
                bearish_close = (close_p < open_p) and ((close_p < ema17_p) or (close_p < ema30_p))
            # 3. Filtro de cuerpo
            solid_body = (body_ratio >= self.body_ratio_threshold)
            # 4. Filtro de Momentum RSI
            rsi_ok = (self.rsi_short_min <= rsi_p <= self.rsi_short_max)

            if touched_ema and bearish_close and solid_body and rsi_ok:
                swing_high_val = max(high_p, float(row.get('swing_high', high_p))) if not pd.isna(row.get('swing_high')) else high_p
                return {
                    'side': 'SHORT',
                    'prep_15m_ts': str(row.get('timestamp', '')),
                    'prep_price': close_p,
                    'atr_15m': atr_p,
                    'swing_ref': swing_high_val,
                    'high_15m': high_p,
                    'rsi_15m': rsi_p,
                    'body_ratio_15m': body_ratio,
                    'candles_5m_count': 0
                }

        return None

    def evaluate_5m_trigger(self, df_5m: pd.DataFrame, prep: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Evalúa el gatillo de entrada en la última vela cerrada de 5m.
        Verifica:
        - Ruptura del swing local (máximo local para Long, mínimo local para Short).
        - Ruptura fresca (no perseguir movimientos ya extendidos).
        - Stop Loss técnico válido y viable.
        - Relación riesgo/beneficio neta aceptable (>= 2R teórico, considerando costes).
        """
        if df_5m is None or len(df_5m) < self.local_swing_lookback_5m + 2:
            return None

        row_curr = df_5m.iloc[-1]
        row_prev = df_5m.iloc[-2]

        close_5m = float(row_curr['close'])
        open_5m = float(row_curr['open'])
        atr_5m = float(row_curr.get('atr', close_5m * 0.005))
        atr_ref = prep.get('atr_15m', atr_5m)

        side = prep['side']

        if side == "LONG":
            swing_high_5m = float(row_curr.get('local_swing_high', 0.0))
            if swing_high_5m <= 0 or pd.isna(swing_high_5m):
                return None

            # Ruptura del máximo local en 5m
            is_breakout = close_5m > swing_high_5m
            # Ruptura fresca: la vela anterior o la apertura no estaban ya por encima del breakout
            is_fresh = (float(row_prev['close']) <= swing_high_5m) or (open_5m <= swing_high_5m)

            if not (is_breakout and is_fresh):
                return None

            # Stop Loss Técnico
            if self.sl_type == 'swing':
                sl_price = prep['swing_ref'] - (self.sl_swing_buffer_atr * atr_ref)
            else:
                sl_price = close_5m - (self.sl_atr_mult * atr_ref)

            # Validación de distancia técnica
            risk_dist = close_5m - sl_price
            min_dist = close_5m * self.sl_min_dist_pct
            max_dist = close_5m * self.sl_max_dist_pct
            if sl_price >= close_5m or risk_dist < min_dist or risk_dist > max_dist:
                return None  # Distancia inviable o fuera de límites razonables

            # Take Profit: Objetivo 2R
            tp_price = close_5m + (self.rr_ratio * risk_dist)

            # Validación de R:R neto tras comisiones y deslizamiento
            roundtrip_cost_pct = (self.est_commission_pct + self.est_slippage_pct) * 2
            est_cost = close_5m * roundtrip_cost_pct
            net_reward = (tp_price - close_5m) - est_cost
            net_risk = (close_5m - sl_price) + est_cost

            min_net_rr = float(self.params.get('min_net_rr', 0.5))
            if net_risk <= 0 or (net_reward / net_risk) < min_net_rr:
                return None  # Relación neta insuficiente

            return {
                'action': 'LONG',
                'price': close_5m,
                'sl': sl_price,
                'tp': tp_price,
                'features': {
                    'sl_type': self.sl_type,
                    'sl_price': sl_price,
                    'atr_5m': atr_5m,
                    'atr_15m': atr_ref,
                    'prep_price': prep['prep_price'],
                    'candles_5m_count': prep['candles_5m_count'],
                    'net_rr': round(net_reward / net_risk, 2)
                }
            }

        elif side == "SHORT":
            swing_low_5m = float(row_curr.get('local_swing_low', 0.0))
            if swing_low_5m <= 0 or pd.isna(swing_low_5m):
                return None

            # Ruptura del mínimo local en 5m
            is_breakout = close_5m < swing_low_5m
            # Ruptura fresca
            is_fresh = (float(row_prev['close']) >= swing_low_5m) or (open_5m >= swing_low_5m)

            if not (is_breakout and is_fresh):
                return None

            # Stop Loss Técnico
            if self.sl_type == 'swing':
                sl_price = prep['swing_ref'] + (self.sl_swing_buffer_atr * atr_ref)
            else:
                sl_price = close_5m + (self.sl_atr_mult * atr_ref)

            # Validación de distancia técnica
            risk_dist = sl_price - close_5m
            min_dist = close_5m * self.sl_min_dist_pct
            max_dist = close_5m * self.sl_max_dist_pct
            if sl_price <= close_5m or risk_dist < min_dist or risk_dist > max_dist:
                return None

            # Take Profit: Objetivo 2R
            tp_price = close_5m - (self.rr_ratio * risk_dist)

            # Validación de R:R neto tras comisiones y deslizamiento
            roundtrip_cost_pct = (self.est_commission_pct + self.est_slippage_pct) * 2
            est_cost = close_5m * roundtrip_cost_pct
            net_reward = (close_5m - tp_price) - est_cost
            net_risk = (sl_price - close_5m) + est_cost

            min_net_rr = float(self.params.get('min_net_rr', 0.5))
            if net_risk <= 0 or (net_reward / net_risk) < min_net_rr:
                return None

            return {
                'action': 'SHORT',
                'price': close_5m,
                'sl': sl_price,
                'tp': tp_price,
                'features': {
                    'sl_type': self.sl_type,
                    'sl_price': sl_price,
                    'atr_5m': atr_5m,
                    'atr_15m': atr_ref,
                    'prep_price': prep['prep_price'],
                    'candles_5m_count': prep['candles_5m_count'],
                    'net_rr': round(net_reward / net_risk, 2)
                }
            }

        return None

    def generate_signal(self, current_price: float, saldo: float, dfs: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """
        Gatillo principal de la estrategia multi-temporal (Fase 3 Validada):
        1. Evalúa y valida tendencia operativa 1H (o 4H+1H si use_4h_filter está habilitado).
        2. En 15m busca nuevas preparaciones por retroceso técnico (pullback a EMA17/30).
        3. En 5m evalúa el gatillo de confirmación de entrada por ruptura local.
        4. Aplica filtros de alta convicción: expansión de volumen (>=1.10x SMA20) y régimen ATR.
        """
        result = {'action': 'NONE', 'price': 0.0, 'sl': 0.0, 'tp': 0.0, 'features': {}, 'reason': ''}

        # ----------------------------------------------------------------------
        # Verificación de datos de entrada requeridos
        # ----------------------------------------------------------------------
        df_1h = dfs.get(self.trend_confirm_tf)
        if df_1h is None:
            df_1h = dfs.get('1h')

        df_15m = dfs.get(self.pullback_tf)
        if df_15m is None:
            df_15m = dfs.get(self.params.get('entry_tf', '15m'))

        df_5m = dfs.get(self.trigger_tf)
        if df_5m is None:
            df_5m = dfs.get('5m')

        if df_1h is None or df_15m is None or df_5m is None:
            result['reason'] = 'MISSING_DATA'
            return result

        if len(df_1h) < 50 or len(df_15m) < 50 or len(df_5m) < 10:
            result['reason'] = 'INSUFFICIENT_WARMUP'
            return result

        # ----------------------------------------------------------------------
        # 1. EVALUAR TENDENCIA OPERATIVA (1H o 4H+1H)
        # ----------------------------------------------------------------------
        trend_4h = "NONE"
        if self.use_4h_filter:
            df_4h = dfs.get(self.macro_tf)
            if df_4h is None:
                df_4h = dfs.get('4h')
            if df_4h is None:
                result['reason'] = 'MISSING_DATA'
                return result
            if len(df_4h) < 50:
                result['reason'] = 'INSUFFICIENT_WARMUP'
                return result

            trend_4h = self.evaluate_trend(df_4h)
            trend_1h = self.evaluate_trend(df_1h)

            if trend_4h == "NONE" or trend_1h == "NONE":
                self.pending_preparation = None
                result['reason'] = 'NO_CONFIRMED_TREND'
                return result

            if trend_4h != trend_1h:
                self.pending_preparation = None
                result['reason'] = 'TREND_CONFLICT_4H_1H'
                return result

            active_trend = trend_4h
        else:
            # Arquitectura Fase 3 Ganadora: 1H único rector de tendencia
            trend_1h = self.evaluate_trend(df_1h)
            if trend_1h == "NONE":
                self.pending_preparation = None
                result['reason'] = 'NO_CONFIRMED_TREND'
                return result

            active_trend = trend_1h

        # Resetear contador de SLs del lado opuesto si la tendencia de 1H cambia
        if active_trend != self.last_active_trend:
            if active_trend != 'LONG':
                self.consecutive_sl['LONG'] = 0
            if active_trend != 'SHORT':
                self.consecutive_sl['SHORT'] = 0
            self.last_active_trend = active_trend

        # ----------------------------------------------------------------------
        # 1B. PROTECCIÓN ANTI-RACHA Y ENFRIAMIENTO TRAS STOP LOSS
        # ----------------------------------------------------------------------
        curr_5m_ts_raw = df_5m['timestamp'].iloc[-1]
        try:
            curr_5m_dt = pd.to_datetime(curr_5m_ts_raw)
        except Exception:
            curr_5m_dt = None

        last_close_5m = float(df_5m['close'].iloc[-1])

        if self.last_sl_ts.get(active_trend) is not None and curr_5m_dt is not None:
            try:
                sl_dt = self.last_sl_ts[active_trend]
                if getattr(sl_dt, 'tzinfo', None) is not None and getattr(curr_5m_dt, 'tzinfo', None) is None:
                    sl_dt = sl_dt.tz_localize(None)
                elif getattr(sl_dt, 'tzinfo', None) is None and getattr(curr_5m_dt, 'tzinfo', None) is not None:
                    curr_5m_dt = curr_5m_dt.tz_localize(None)
                mins_since_sl = (curr_5m_dt - sl_dt).total_seconds() / 60.0
            except Exception:
                mins_since_sl = 999.0

            if 0.0 <= mins_since_sl < (self.sl_cooldown_15m_bars * 15):
                self.pending_preparation = None
                result['reason'] = 'COOLDOWN_AFTER_SL'
                result['features'] = {'mins_since_sl': round(mins_since_sl, 1), 'consecutive_sl': self.consecutive_sl.get(active_trend, 0)}
                return result

            if self.consecutive_sl.get(active_trend, 0) >= self.max_consecutive_sl_same_side:
                if mins_since_sl < 360.0:
                    ref_entry = self.last_sl_entry.get(active_trend)
                    if ref_entry is not None:
                        if active_trend == 'LONG' and last_close_5m < ref_entry:
                            self.pending_preparation = None
                            result['reason'] = 'MAX_CONSECUTIVE_SL_GUARD'
                            result['features'] = {'consecutive_sl': self.consecutive_sl[active_trend], 'ref_entry': ref_entry}
                            return result
                        if active_trend == 'SHORT' and last_close_5m > ref_entry:
                            self.pending_preparation = None
                            result['reason'] = 'MAX_CONSECUTIVE_SL_GUARD'
                            result['features'] = {'consecutive_sl': self.consecutive_sl[active_trend], 'ref_entry': ref_entry}
                            return result
                else:
                    self.consecutive_sl[active_trend] = 0

        # ----------------------------------------------------------------------
        # 2. EVALUAR O ACTUALIZAR PREPARACIÓN EN 15m
        # ----------------------------------------------------------------------
        if self.pending_preparation is not None:
            if self.pending_preparation['side'] != active_trend:
                self.pending_preparation = None  # Tendencia cambió de dirección

        new_prep = self.evaluate_15m_pullback(df_15m, active_trend)
        if new_prep is not None:
            curr_prep_ts = str(df_15m['timestamp'].iloc[-1])
            if curr_prep_ts != self.last_consumed_prep_15m_ts:
                if self.pending_preparation is None or self.pending_preparation.get('prep_15m_ts') != curr_prep_ts:
                    self.pending_preparation = new_prep
                    logger.info(f"📍 [15M PREP] Preparación {active_trend} detectada @ {new_prep['prep_price']:.2f}. Esperando gatillo en 5m.")

        # ----------------------------------------------------------------------
        # 3. VERIFICAR CADUCIDAD Y CONDICIONES DE PREPARACIÓN EN 5m
        # ----------------------------------------------------------------------
        if self.pending_preparation is None:
            result['reason'] = 'WAITING_15M_PULLBACK'
            return result

        self.pending_preparation['candles_5m_count'] += 1

        if self.pending_preparation['candles_5m_count'] > self.preparation_expiry_5m_bars:
            self.last_consumed_prep_15m_ts = self.pending_preparation.get('prep_15m_ts')
            self.pending_preparation = None
            result['reason'] = 'PREPARATION_EXPIRED'
            return result

        last_close_5m = float(df_5m['close'].iloc[-1])
        if self.pending_preparation['side'] == 'LONG':
            if last_close_5m < self.pending_preparation['low_15m']:
                self.last_consumed_prep_15m_ts = self.pending_preparation.get('prep_15m_ts')
                self.pending_preparation = None
                result['reason'] = 'PREPARATION_STRUCTURE_BROKEN'
                return result
        elif self.pending_preparation['side'] == 'SHORT':
            if last_close_5m > self.pending_preparation['high_15m']:
                self.last_consumed_prep_15m_ts = self.pending_preparation.get('prep_15m_ts')
                self.pending_preparation = None
                result['reason'] = 'PREPARATION_STRUCTURE_BROKEN'
                return result

        # ----------------------------------------------------------------------
        # 4. GATILLO DE ENTRADA EN 5m Y FILTROS DE ALTA CONVICCIÓN
        # ----------------------------------------------------------------------
        trigger_signal = self.evaluate_5m_trigger(df_5m, self.pending_preparation)
        if trigger_signal is not None:
            row_curr = df_5m.iloc[-1]
            vol = float(row_curr.get('volume', 0.0))
            vol_sma20 = float(row_curr.get('volume_sma20', 0.0))
            atr_5m = float(row_curr.get('atr', 0.0))
            atr_sma20 = float(row_curr.get('atr_sma20', 0.0))

            vol_ok = True
            if self.use_volume_filter:
                vol_ok = (vol_sma20 > 0) and (vol >= vol_sma20 * self.vol_multiplier)

            atr_ok = True
            if self.use_atr_regime:
                atr_ok = (atr_sma20 > 0) and (atr_5m >= atr_sma20) and ((atr_5m / last_close_5m) >= self.min_atr_pct)

            if vol_ok and atr_ok:
                self.last_consumed_prep_15m_ts = self.pending_preparation.get('prep_15m_ts')
                self.pending_preparation = None
                trigger_signal['reason'] = 'TRIGGER_CONFIRMED_5M_LIMIT_VOL'
                trigger_signal['features']['vol_ratio'] = round(vol / vol_sma20, 2) if vol_sma20 > 0 else 1.0
                trigger_signal['features']['order_type'] = self.order_type
                return trigger_signal
            else:
                result['reason'] = 'FILTER_VOLUME_ATR_REJECT'
                result['features'] = {
                    'vol_ratio': round(vol / vol_sma20, 2) if vol_sma20 > 0 else 1.0,
                    'vol_ok': vol_ok,
                    'atr_ok': atr_ok
                }
                return result

        result['reason'] = 'WAITING_5M_TRIGGER'
        result['features'] = {
            'prep_side': self.pending_preparation['side'],
            'prep_candles_elapsed': self.pending_preparation['candles_5m_count'],
            'trend_1h': active_trend
        }
        if self.use_4h_filter:
            result['features']['trend_4h'] = trend_4h
        return result

    def manage_open_position(self, current_price: float, dfs: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """Gestión de posición abierta si se requiere trailing stop dinámico."""
        return {'action': 'NONE', 'reason': ''}

    def print_multitf_dashboard(self, current_price: float, saldo: float, dfs: Dict[str, pd.DataFrame], signal: Dict[str, Any]) -> None:
        """
        Imprime en consola un tablero visual completo y ultra-informativo del estado
        de los marcos temporales (1H -> 15M -> 5M con filtros de volumen y volatilidad), detallando:
        - Motivo exacto de descarte o validación
        - Porcentaje de avance hacia la entrada y porcentaje faltante
        - Tendencias con EMAs, RSI, ATRs y ratio de volumen
        """
        from bot.core.trade_logger import Colors, logger
        from bot.config import settings

        df_1h = dfs.get(self.trend_confirm_tf)
        if df_1h is None:
            df_1h = dfs.get('1h')

        df_15m = dfs.get(self.pullback_tf)
        if df_15m is None:
            df_15m = dfs.get(self.params.get('entry_tf', '15m'))

        df_5m = dfs.get(self.trigger_tf)
        if df_5m is None:
            df_5m = dfs.get('5m')

        if df_1h is None or df_15m is None or df_5m is None:
            return

        df_4h = None
        t4 = "NONE"
        if self.use_4h_filter:
            df_4h = dfs.get(self.macro_tf)
            if df_4h is None:
                df_4h = dfs.get('4h')
            if df_4h is not None and len(df_4h) >= 50:
                t4 = self.evaluate_trend(df_4h)

        r1 = df_1h.iloc[-1]
        r15 = df_15m.iloc[-1]
        r5 = df_5m.iloc[-1]

        t1 = self.evaluate_trend(df_1h)

        # 1. Porcentaje de Avance (Alineación hacia la entrada)
        is_triggered = signal.get('action') in ['LONG', 'SHORT']
        has_15m_prep = (self.pending_preparation is not None) or is_triggered
        prep_side_display = self.pending_preparation['side'] if self.pending_preparation else signal.get('action', '')

        if self.use_4h_filter:
            score_4h = 25.0 if t4 != "NONE" else 0.0
            score_1h = 25.0 if (t1 != "NONE" and t1 == t4) else 0.0
            score_15m = 25.0 if has_15m_prep else 0.0
            score_5m = 25.0 if is_triggered else 0.0
            total_score = score_4h + score_1h + score_15m + score_5m
        else:
            score_1h = 35.0 if t1 != "NONE" else 0.0
            score_15m = 35.0 if has_15m_prep else 0.0
            score_5m = 30.0 if is_triggered else 0.0
            total_score = score_1h + score_15m + score_5m
        falta_pct = max(0.0, 100.0 - total_score)

        # 2. Explicación de por qué no entra
        reason_code = signal.get('reason', 'NONE')
        if signal.get('action') in ['LONG', 'SHORT']:
            human_reason = f"¡GATILLO CONFIRMADO! Orden {signal['action']} ({self.order_type}) lista para ejecución inmediata."
            status_color = Colors.GREEN
        elif self.use_4h_filter and t4 != t1:
            human_reason = f"Conflicto de temporalidades: 4H es {t4} pero 1H es {t1}. Bloqueo estricto por divergencia."
            status_color = Colors.RED
        elif t1 == "NONE":
            human_reason = "Mercado sin dirección en 1H o en giro/agotamiento: EMAs desalineadas o ruptura de EMA17."
            status_color = Colors.YELLOW
        elif reason_code == 'COOLDOWN_AFTER_SL':
            mins_s = signal.get('features', {}).get('mins_since_sl', 0)
            human_reason = f"Enfriamiento Anti-Racha tras Stop Loss activo ({mins_s}m / {self.sl_cooldown_15m_bars * 15}m requeridos)."
            status_color = Colors.YELLOW
        elif reason_code == 'MAX_CONSECUTIVE_SL_GUARD':
            c_sl = signal.get('features', {}).get('consecutive_sl', 0)
            ref_e = signal.get('features', {}).get('ref_entry', 0.0)
            human_reason = f"Bloqueo Anti-Racha: {c_sl} SL seguidos en {t1}. Exige recuperar nivel {ref_e:,.2f} antes de re-entrar."
            status_color = Colors.RED
        elif self.pending_preparation is None:
            human_reason = f"Tendencia 1H alineada en {t1}. Esperando retroceso (pullback) a EMA17/30 en 15m."
            status_color = Colors.CYAN
        elif reason_code == 'FILTER_VOLUME_ATR_REJECT':
            vol_val = float(r5.get('volume', 0.0))
            vol_sma = float(r5.get('volume_sma20', 1.0))
            v_rat = (vol_val / vol_sma) if vol_sma > 0 else 1.0
            human_reason = f"Ruptura en 5m detectada pero DESCARTADA por filtro cuantitativo (Volumen actual: {v_rat:.2f}x vs {self.vol_multiplier:.2f}x requerido)."
            status_color = Colors.YELLOW
        elif signal.get('action') == 'NONE':
            prep_side = self.pending_preparation['side']
            prep_bars = self.pending_preparation.get('candles_5m_count', 0)
            human_reason = f"Preparación {prep_side} activa en 15m. Esperando gatillo 5m con volumen (Velas: {prep_bars}/{self.preparation_expiry_5m_bars})."
            status_color = Colors.BLUE
        else:
            human_reason = f"Condición no cumplida: {reason_code}"
            status_color = Colors.YELLOW

        # 3. Métricas de Volatilidad y Volumen
        atr_5m_val = float(r5.get('atr', 0.0))
        atr_5m_pct = (atr_5m_val / current_price * 100.0) if current_price > 0 else 0.0
        atr_15m_val = float(r15.get('atr', 0.0))
        atr_15m_pct = (atr_15m_val / current_price * 100.0) if current_price > 0 else 0.0
        rsi_15m_val = float(r15.get('rsi', 50.0))

        vol_5m_val = float(r5.get('volume', 0.0))
        vol_sma_val = float(r5.get('volume_sma20', vol_5m_val))
        vol_ratio_val = (vol_5m_val / vol_sma_val) if vol_sma_val > 0 else 1.0

        def badge(cond):
            return f"{Colors.GREEN}✔ CUMPLIDO{Colors.RESET}" if cond else f"{Colors.RED}✖ PENDIENTE{Colors.RESET}"

        t1_str = f"{Colors.GREEN}LONG (Alcista){Colors.RESET}" if t1 == 'LONG' else (f"{Colors.RED}SHORT (Bajista){Colors.RESET}" if t1 == 'SHORT' else f"{Colors.YELLOW}NONE (Rango/Transición){Colors.RESET}")
        prep_str = f"{Colors.GREEN}ACTIVA ({prep_side_display}){Colors.RESET}" if has_15m_prep else f"{Colors.YELLOW}ESPERANDO RETROCESO A EMA17/30{Colors.RESET}"
        trigger_str = f"{Colors.GREEN}CONFIRMADO ({signal.get('action')}){Colors.RESET}" if is_triggered else f"{Colors.YELLOW}ESPERANDO RUPTURA + VOLUMEN{Colors.RESET}"

        saldo_str = f"{saldo:.2f} USDT" if isinstance(saldo, float) else str(saldo)
        compresion_str = " (Compresión)" if atr_5m_pct < 0.20 else (" (Normal)" if atr_5m_pct < 0.60 else " (Alta Volatilidad)")

        print("")
        logger.info(f"{Colors.CYAN}╔════════════════════════════════════════════════════════════════════════════════════════╗{Colors.RESET}")
        logger.info(f"{Colors.CYAN}║ 📊 TABLERO MULTITEMPORAL DE DECISIÓN | {settings.SYMBOL} | PRECIO: {current_price:,.2f} USD         ║{Colors.RESET}")
        logger.info(f"{Colors.CYAN}╠════════════════════════════════════════════════════════════════════════════════════════╣{Colors.RESET}")
        logger.info(f"║ • Saldo Cuenta     : {saldo_str}")
        logger.info(f"║ • Acción del Motor : {status_color}{signal.get('action', 'NONE')}{Colors.RESET} [{reason_code}]")
        logger.info(f"║ • Estado Operativo : {Colors.CYAN}{total_score:.1f}% Completado{Colors.RESET} │ {Colors.YELLOW}Falta el {falta_pct:.1f}% para entrar al mercado{Colors.RESET}")
        logger.info(f"║ • Tipo de Orden    : {self.order_type} (Maker / Comisiones Bajas)")
        logger.info(f"║")
        logger.info(f"║ 💡 {Colors.YELLOW}¿POR QUÉ NO ENTRA?: {human_reason}{Colors.RESET}")
        logger.info(f"║")
        logger.info(f"{Colors.CYAN}╟────────────────────────────────────────────────────────────────────────────────────────╢{Colors.RESET}")
        logger.info(f"║ ⏱️  ESTADO Y TENDENCIA POR TEMPORALIDAD:                                                 ║")
        if self.use_4h_filter and df_4h is not None:
            r4 = df_4h.iloc[-1]
            t4_str = f"{Colors.GREEN}LONG (Alcista){Colors.RESET}" if t4 == 'LONG' else (f"{Colors.RED}SHORT (Bajista){Colors.RESET}" if t4 == 'SHORT' else f"{Colors.YELLOW}NONE (Rango/Transición){Colors.RESET}")
            logger.info(f"║  [4H Macro]      Tendencia: {t4_str} │ {badge(t4 != 'NONE')}")
            logger.info(f"║                  EMAs: 17={r4.get('ema17',0):,.1f} | 30={r4.get('ema30',0):,.1f} | 50={r4.get('ema50',0):,.1f}")
        logger.info(f"║  [1H Estructura] Tendencia: {t1_str} │ {badge(t1 != 'NONE')}")
        logger.info(f"║                  EMAs: 17={r1.get('ema17',0):,.1f} | 30={r1.get('ema30',0):,.1f} | 50={r1.get('ema50',0):,.1f} │ Pendiente EMA30: {r1.get('slope_ema30',0):+.1f}")
        logger.info(f"║  [15M Pullback]  Estado: {prep_str} │ {badge(has_15m_prep)}")
        logger.info(f"║                  RSI: {rsi_15m_val:.1f} (Rango: {self.rsi_long_min:.0f}-{self.rsi_long_max:.0f} L / {self.rsi_short_min:.0f}-{self.rsi_short_max:.0f} S) │ ATR: {atr_15m_val:.2f} USD ({atr_15m_pct:.2f}%)")
        logger.info(f"║  [5M Gatillo]    Estado: {trigger_str} │ {badge(is_triggered)}")
        vol_req_str = f">={self.vol_multiplier:.2f}x" if self.use_volume_filter else "OFF (Agresivo)"
        logger.info(f"║                  Volumen 5M: {vol_ratio_val:.2f}x SMA20 (Filtro: {vol_req_str}) │ ATR 5m: {atr_5m_val:.2f} USD ({atr_5m_pct:.2f}%{compresion_str})")
        if getattr(self, 'shadow_ai', None) is not None:
            ai_sum = self.shadow_ai.get_dashboard_summary()
            logger.info(f"{Colors.CYAN}╟────────────────────────────────────────────────────────────────────────────────────────╢{Colors.RESET}")
            logger.info(
                f"║ 🧠 [IA LightGBM+SHAP] Modo: {Colors.YELLOW}{ai_sum['mode_str']}{Colors.RESET} │ "
                f"Aprendizaje: {Colors.CYAN}{ai_sum['total_learned']}/{ai_sum['target_learned']} trades ({ai_sum['readiness_pct']:.0f}%){Colors.RESET} │ "
                f"Precisión CV: {ai_sum['cv_accuracy']:.1f}%"
            )
        logger.info(f"{Colors.CYAN}╚════════════════════════════════════════════════════════════════════════════════════════╝{Colors.RESET}")

