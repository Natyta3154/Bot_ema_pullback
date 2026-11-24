"""
Módulo: breakout_strategy.py
=================================================
Estrategia Breakout. Opera rupturas de niveles clave de soporte y resistencia.
"""
from typing import Dict, Any
import pandas as pd
from datetime import datetime
from bot.strategies.base import BaseStrategy
from bot.config import settings
from bot.core.trade_logger import logger
from bot.indicators.price_action import find_pivots, detect_market_structure, detect_support_resistance
from bot.indicators.volume import calculate_sma
from bot.indicators.atr import calculate_atr
from bot.core.profiler import profile_method

class BreakoutStrategy(BaseStrategy):
    """
    Estrategia de Breakout y Retesteo basada en Acción del Precio (Price Action).
    Requiere que el precio rompa una zona con volumen, confirme el cierre fuera de ella,
    y luego genere una orden Limit en la zona rota durante el retesteo.
    """
    def __init__(self, position_manager, risk_manager):
        super().__init__(position_manager, risk_manager)
        self.params = settings.STRATEGY_PARAMS["BREAKOUT_RETEST"]
        
    def _is_valid_volatility(self, current_price: float, atr: float) -> bool:
        volatility_pct = atr / current_price
        min_v = self.params.get('atr_min_volatility', 0.001)
        max_v = self.params.get('atr_max_volatility', 0.03)
        return min_v <= volatility_pct <= max_v

    @profile_method(category="Strategy")
    def analyze_market(self, dfs: Dict[str, pd.DataFrame]) -> None:
        df_macro = dfs.get(self.params['macro_tf'])
        if df_macro is not None:
            # Encontrar pivotes y estructura en macro (1H)
            df_macro_p = find_pivots(df_macro, self.params['pivot_lookback'], self.params['pivot_lookback'])
            dfs[self.params['macro_tf']] = df_macro_p
            
        df_entry = dfs.get(self.params['entry_tf'])
        if df_entry is not None:
            # Volumen y ATR en 15m
            df_entry['vol_sma'] = calculate_sma(df_entry['volume'], self.params['vol_sma_period'])
            df_entry['atr'] = calculate_atr(df_entry, self.params['atr_period'])
            df_entry['ema_30'] = df_entry['close'].ewm(span=30, adjust=False).mean()
            
            # Pre-calcular RSI
            delta = df_entry['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df_entry['rsi'] = 100 - (100 / (1 + rs))
            
            # Pre-calcular ADX
            from bot.indicators.market_regime import MarketRegimeDetector
            df_entry['adx'] = MarketRegimeDetector._calc_adx(df_entry, 14)
            
            # Pivotes y Zonas en 15m
            df_entry_p = find_pivots(df_entry, self.params['pivot_lookback'], self.params['pivot_lookback'])
            dfs[self.params['entry_tf']] = df_entry_p

    def generate_signal(self, current_price: float, saldo: float, dfs: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        df_entry = dfs.get(self.params['entry_tf'])
        if df_entry is None:
            return {'action': 'NONE'}
            
        current_atr = df_entry['atr'].iloc[-1]
        if pd.isna(current_atr):
            return {'action': 'NONE'}

        state = self.position.strategy_state.get('status', 'SCAN')
        
        # 1. Motor de Decisión Institucional
        from bot.core.decision_engine import DecisionEngine
        decision = DecisionEngine.evaluate(dfs, current_price, current_atr, self.params)
        
        self.position.strategy_state['last_decision'] = decision
        
        direction = decision['direction']
        score = decision['score']
        conf = decision['confidence']
        
        # --- SOLUCIÓN DE CORTOCUITO: FILTRO DE CONSENSO DINÁMICO ---
        # Si el consenso de modelos alternativos da SIDEWAYS o hay conflicto estricto 
        # entre Dow y la acción del precio actual con respecto a la EMA(30), degradamos el score.
        consensus = decision['breakdown'].get('consensus_alternativo', 'SIDEWAYS')
        ema_30 = df_entry['ema_30'].iloc[-1] if 'ema_30' in df_entry else df_entry['close'].ewm(span=30, adjust=False).mean().iloc[-1]
        
        if not self.params.get('ablation_no_ema', False):
            if direction == "LONG" and current_price < ema_30: 
                # Si el motor quiere LONG pero el precio está por debajo del promedio, neutralizamos.
                score *= 0.8 
                if getattr(settings, 'ENVIRONMENT', '') != 'BACKTEST':
                    logger.warning("⚠️ Mitigación de riesgo: Intento de LONG bajo la EMA(30). Degradando Score.")
            elif direction == "SHORT" and current_price > ema_30:
                score *= 0.8
                if getattr(settings, 'ENVIRONMENT', '') != 'BACKTEST':
                    logger.warning("⚠️ Mitigación de riesgo: Intento de SHORT sobre la EMA(30). Degradando Score.")

        thresholds = getattr(settings, 'DECISION_THRESHOLDS', {"min_score": 75.0, "min_confidence": 80.0})
        min_score = thresholds['min_score']
        min_conf = thresholds['min_confidence']
        
        # 2. Máquina de Estados (10-Step State Machine simplificada para trading)
        if state == 'SCAN' or state == 'COOLDOWN':
            if direction != "NONE" and score >= min_score and conf >= min_conf:
                logger.info(f"🟢 [SCAN -> SETUP_FOUND] Score: {score:.1f} | Conf: {conf:.1f} | Dir: {direction}")
                self.position.strategy_state['status'] = 'SETUP_FOUND'
                self.position.strategy_state['target_direction'] = direction
                self.position.save()
            return {'action': 'NONE'}
            
        elif state == 'SETUP_FOUND':
            target_dir = self.position.strategy_state.get('target_direction', 'NONE')
            
            # Hysteresis (si el mercado se debilita abruptamente, volvemos a SCAN)
            if direction != target_dir or score < (min_score - 10) or conf < (min_conf - 10):
                logger.info("⚠️ [SETUP_FOUND -> SCAN] Condiciones de mercado deterioradas.")
                self.position.strategy_state['status'] = 'SCAN'
                self.position.save()
                return {'action': 'NONE'}
                
            # Evaluar Execution Score para ver si rompió S/R con volumen
            exec_data = decision['breakdown']['execution'][target_dir.lower()]
            exec_score = exec_data[0]
            
            if exec_score > 70.0:
                logger.info(f"🔥 [SETUP_FOUND -> BREAKOUT_CONFIRMED] Exec Score alto ({exec_score:.1f}). Pasando a WAIT_RETEST.")
                self.position.strategy_state['status'] = 'WAIT_RETEST'
                
                # --- CORRECCIÓN RECONOCIMIENTO DE ZONA DE RETEST ---
                # En un breakout, la zona rota es el MÁXIMO/MÍNIMO del pivote que causó la resistencia, no el S/R dinámico actual.
                swing_highs = decision['breakdown'].get('detected_swing_highs', [])
                swing_lows = decision['breakdown'].get('detected_swing_lows', [])
                
                if target_dir == 'LONG' and len(swing_highs) > 0:
                    # Buscamos el precio del Swing High más cercano que rompimos (antigua resistencia)
                    self.position.strategy_state['target_zone'] = swing_highs[-1]['price']
                elif target_dir == 'SHORT' and len(swing_lows) > 0:
                    # Buscamos el precio del Swing Low más cercano que rompimos (antiguo soporte)
                    self.position.strategy_state['target_zone'] = swing_lows[-1]['price']
                else:
                    # Fallback robusto basado en el precio anterior al impulso
                    self.position.strategy_state['target_zone'] = current_price - (current_atr * 0.5) if target_dir == 'LONG' else current_price + (current_atr * 0.5)
                
                logger.info(f"🎯 Zona de Retest fijada en: {self.position.strategy_state['target_zone']:.2f}")
                self.position.save()
                
            return {'action': 'NONE'}
            
        elif state == 'WAIT_RETEST':
            target_dir = self.position.strategy_state.get('target_direction', 'NONE')
            target_zone = self.position.strategy_state.get('target_zone', current_price)
            
            # Timeout (El precio se alejó demasiado, > 2x ATR)
            if target_dir == 'LONG' and current_price > target_zone + (current_atr * 2):
                self.position.strategy_state['status'] = 'SCAN'
                return {'action': 'NONE'}
            if target_dir == 'SHORT' and current_price < target_zone - (current_atr * 2):
                self.position.strategy_state['status'] = 'SCAN'
                return {'action': 'NONE'}
                
            # Evaluar Zona de Tolerancia (READY -> EXECUTE)
            tolerance = target_zone * self.params['tolerance_zone_pct']
            hit_retest = False
            
            if target_dir == 'LONG' and current_price <= (target_zone + tolerance): hit_retest = True
            elif target_dir == 'SHORT' and current_price >= (target_zone - tolerance): hit_retest = True
            
            if hit_retest:
                logger.info(f"⚡ [WAIT_RETEST -> EXECUTE] Retest alcanzado ({target_zone:.2f}). Ejecutando Orden.")
                self.position.strategy_state['status'] = 'MANAGE' # Posición se abrirá
                
                if target_dir == 'LONG':
                    sl_price = target_zone - current_atr * 1.5
                    sl_price *= (1 - self.params['sl_buffer_pct'])
                    risk_dist = target_zone - sl_price
                    tp_targets = []
                    for tp_conf in self.params['take_profits']:
                        tp_targets.append({"price": target_zone + (risk_dist * tp_conf['rr']), "amount_pct": tp_conf['pct'], "order_id": "", "hit": False})
                    return {'action': 'LONG', 'price': target_zone, 'sl': sl_price, 'tp_targets': tp_targets}
                else:
                    sl_price = target_zone + current_atr * 1.5
                    sl_price *= (1 + self.params['sl_buffer_pct'])
                    risk_dist = sl_price - target_zone
                    tp_targets = []
                    for tp_conf in self.params['take_profits']:
                        tp_targets.append({"price": target_zone - (risk_dist * tp_conf['rr']), "amount_pct": tp_conf['pct'], "order_id": "", "hit": False})
                    return {'action': 'SHORT', 'price': target_zone, 'sl': sl_price, 'tp_targets': tp_targets}
                    
        return {'action': 'NONE'}

    def manage_open_position(self, current_price: float, dfs: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        # Logica Break Even al tocar TP1
        if self.params.get('breakeven_on_tp1', False) and not self.position.breakeven_activated:
            if len(self.position.tp_targets) > 0 and self.position.tp_targets[0].get('hit', False):
                logger.info("🛡️ TP1 Alcanzado. Solicitando Break Even de la posición restante.")
                # Buffer ligero para cubrir fees (0.1%)
                be_price = self.position.entry_price * 1.001 if self.position.side == "LONG" else self.position.entry_price * 0.999
                return {'action': 'UPDATE_SL', 'new_sl': be_price, 'reason': 'BREAKEVEN_ON_TP1'}
                
        # Trailing Stop (Opcional)
        if self.params.get('trailing_stop', False):
            # Implementar un ATR trailing básico aquí si es necesario
            pass

        return {'action': 'NONE'}
