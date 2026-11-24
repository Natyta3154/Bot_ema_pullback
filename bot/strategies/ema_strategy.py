"""
Módulo: ema_strategy.py
=================================================
Estrategia EMA básica. Utiliza cruces de medias móviles para generar señales de compra/venta.
"""
from typing import Dict, Any
import pandas as pd
from datetime import datetime
from bot.strategies.base import BaseStrategy
from bot.config import settings
from bot.core.trade_logger import logger
from bot.indicators.ema import calculate_ema
from bot.indicators.rsi import calculate_rsi
from bot.indicators.volume import calculate_sma
from bot.ml.ml_service import MLService

class EMAStrategy(BaseStrategy):
    """
    Estrategia 1: EMA Strategy
    Es la lógica original del bot, extraída de forma idéntica.
    """
    def __init__(self, position_manager, risk_manager):
        super().__init__(position_manager, risk_manager)
        self.params = settings.STRATEGY_PARAMS["EMA_STRATEGY"]
        self.ml_service = MLService()

    def analyze_market(self, dfs: Dict[str, pd.DataFrame]) -> None:
        if self.params['trigger_tf'] in dfs:
            df = dfs[self.params['trigger_tf']]
            df['ema_17'] = calculate_ema(df['close'], self.params['fast_ema'])
            df['ema_30'] = calculate_ema(df['close'], self.params['slow_ema'])
            df['rsi_14'] = calculate_rsi(df['close'], 14)
            df['vol_sma_20'] = calculate_sma(df['volume'], 20)
            
        if self.params['macro_tf'] in dfs:
            df = dfs[self.params['macro_tf']]
            df['ema_17'] = calculate_ema(df['close'], self.params['fast_ema'])
            df['ema_30'] = calculate_ema(df['close'], self.params['slow_ema'])

    def generate_signal(self, current_price: float, saldo: float, dfs: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        df_1h = dfs.get(self.params['trigger_tf'])
        df_4h = dfs.get(self.params['macro_tf'])
        
        if df_1h is None or df_4h is None or len(df_1h) < 200 or len(df_4h) < 200:
            return {'action': 'NONE'}
            
        macro_close = df_4h['close'].iloc[-1]
        macro_ema_17 = df_4h['ema_17'].iloc[-1]
        macro_ema_30 = df_4h['ema_30'].iloc[-1]
        
        macro_bearish = macro_close < macro_ema_17 and macro_close < macro_ema_30
        macro_bullish = macro_close > macro_ema_17 and macro_close > macro_ema_30
        tendencia_str = "Bajista" if macro_bearish else ("Alcista" if macro_bullish else "Lateral")
        
        rsi_1h = df_1h['rsi_14'].iloc[-1]
        ema_17_1h = df_1h['ema_17'].iloc[-1]
        ema_30_1h = df_1h['ema_30'].iloc[-1]
        
        logger.info(f"🔎 Analizando mercado | Precio: {current_price:.2f} USDT | Saldo: {saldo:.2f} USDT | Tendencia 4H: {tendencia_str} | RSI 1H: {rsi_1h:.1f}")

        # SETUP SHORT
        if self.params['allow_short'] and macro_bearish:
            approved = True
            prob = 0.0
            if self.params['use_ml']:
                approved, prob = self.ml_service.predict(df_1h, df_4h, "SHORT")
                
            if 35 < rsi_1h < 55:
                if not approved:
                    faltante = max(0, self.ml_service.predictor.threshold_short - prob if self.ml_service.predictor else 0)
                    logger.info(f"🛑 [IA RECHAZA] Prob. éxito actual: {prob:.1%} (Falta {faltante:.1%}). Operación abortada.")
                else:
                    if self.params['use_ml']:
                        logger.info(f"✅ [IA APRUEBA] Probabilidad de éxito: {prob:.1%}. Calculando entrada...")
                    target_entry = min(ema_17_1h, ema_30_1h) if current_price < min(ema_17_1h, ema_30_1h) else max(ema_17_1h, ema_30_1h)
                    if target_entry > current_price:
                        sl_price = self.risk.get_recent_high(df_1h, 10)
                        if sl_price > target_entry:
                            tp_price = target_entry - ((sl_price - target_entry) * self.params['rr_ratio'])
                            return {'action': 'SHORT', 'price': target_entry, 'sl': sl_price, 'tp': tp_price}
            else:
                if self.params['use_ml']:
                    logger.info(f"⏳ Esperando retroceso | RSI no óptimo (35-55) | Predicción IA actual para SHORT: {prob:.1%}")

        # SETUP LONG
        elif self.params['allow_long'] and macro_bullish:
            approved = True
            prob = 0.0
            if self.params['use_ml']:
                approved, prob = self.ml_service.predict(df_1h, df_4h, "LONG")
                
            if 45 < rsi_1h < 65:
                if not approved:
                    faltante = max(0, self.ml_service.predictor.threshold_long - prob if self.ml_service.predictor else 0)
                    logger.info(f"🛑 [IA RECHAZA] Prob. éxito actual: {prob:.1%} (Falta {faltante:.1%}). Operación abortada.")
                else:
                    if self.params['use_ml']:
                        logger.info(f"✅ [IA APRUEBA] Probabilidad de éxito: {prob:.1%}. Calculando entrada...")
                    target_entry = max(ema_17_1h, ema_30_1h) if current_price > max(ema_17_1h, ema_30_1h) else min(ema_17_1h, ema_30_1h)
                    if target_entry < current_price:
                        sl_price = self.risk.get_recent_low(df_1h, 10)
                        if sl_price < target_entry:
                            tp_price = target_entry + ((target_entry - sl_price) * self.params['rr_ratio'])
                            return {'action': 'LONG', 'price': target_entry, 'sl': sl_price, 'tp': tp_price}
            else:
                if self.params['use_ml']:
                    logger.info(f"⏳ Esperando retroceso | RSI no óptimo (45-65) | Predicción IA actual para LONG: {prob:.1%}")

        return {'action': 'NONE'}

    def manage_open_position(self, current_price: float, dfs: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        df_1h = dfs.get(self.params['trigger_tf'])
        if df_1h is None:
            return {'action': 'NONE'}
            
        # Breakeven Dinámico
        if self.position.side == "SHORT":
            risk_distance = self.position.stop_loss - self.position.entry_price
            target_breakeven_price = self.position.entry_price - risk_distance
            if not self.position.breakeven_activated and current_price <= target_breakeven_price:
                return {'action': 'UPDATE_SL', 'new_sl': self.position.entry_price, 'reason': 'BREAKEVEN'}
                
        elif self.position.side == "LONG":
            risk_distance = self.position.entry_price - self.position.stop_loss
            target_breakeven_price = self.position.entry_price + risk_distance
            if not self.position.breakeven_activated and current_price >= target_breakeven_price:
                return {'action': 'UPDATE_SL', 'new_sl': self.position.entry_price * 1.001, 'reason': 'BREAKEVEN'}

        # Time Stop (Lateralización)
        entry_time_parsed = datetime.fromisoformat(self.position.entry_time) if self.position.entry_time else datetime.now()
        hours_open = (datetime.now() - entry_time_parsed).total_seconds() / 3600
        
        if hours_open >= self.params['time_stop_hours']:
            price_diff_pct = abs(current_price - self.position.entry_price) / self.position.entry_price
            last_vol = df_1h['volume'].iloc[-1]
            sma_vol = df_1h['vol_sma_20'].iloc[-1]
            
            if price_diff_pct <= self.params['lateralization_range_pct'] and last_vol < sma_vol:
                return {'action': 'EXIT', 'reason': 'TIME_STOP_LATERALIZATION'}

        return {'action': 'NONE'}
