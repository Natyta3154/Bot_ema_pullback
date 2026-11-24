"""
Módulo: diagnostics.py
=================================================
Herramientas de diagnóstico y auditoría en tiempo real para verificar la integridad del sistema.
"""
from typing import Dict, Any, List, Tuple, Optional
import pandas as pd
import numpy as np
from datetime import datetime
from bot.config import settings
from bot.core.trade_logger import logger, Colors
from bot.core.structure_research import StructureResearcher
from bot.indicators.market_regime import MarketRegimeDetector
from bot.indicators.price_action import detect_market_structure, detect_support_resistance

class DiagnosticsReporter:
    """
    Sistema de Observabilidad y Diagnóstico Cuantitativo Profesional (Phase 8.2).
    Genera reportes de nivel institucional analizando estructura, velas, y simulando
    trades sin intervenir en la lógica de ejecución del Trading Engine.
    """
    def __init__(self, engine):
        self.engine = engine
        self.prev_state: Dict[str, Any] = {}
        self.timeline: List[Tuple[str, str]] = []
        from bot.core.auditor import StrategyAuditor
        self.auditor = StrategyAuditor()
        self.add_timeline_event("Bot iniciado. Diagnóstico cuantitativo activado.")

    def add_timeline_event(self, msg: str):
        now_str = datetime.now().strftime("%H:%M")
        if not self.timeline or self.timeline[-1][1] != msg:
            self.timeline.append((now_str, msg))
            if len(self.timeline) > 10:
                self.timeline.pop(0)

    def _analyze_candle(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Análisis completo de la vela actual/cerrada."""
        if df.empty:
            return {}
            
        last_candle = df.iloc[-1]
        o = last_candle['open']
        h = last_candle['high']
        l = last_candle['low']
        c = last_candle['close']
        v = last_candle['volume'] if 'volume' in last_candle else 0
        v_sma = last_candle['vol_sma'] if 'vol_sma' in last_candle else 1
        atr = last_candle['atr'] if 'atr' in last_candle else 0
        
        c_range = h - l
        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        
        body_pct = (body / c_range * 100) if c_range > 0 else 0
        upper_pct = (upper_wick / c_range * 100) if c_range > 0 else 0
        lower_pct = (lower_wick / c_range * 100) if c_range > 0 else 0
        
        atr_ratio = c_range / atr if atr > 0 else 0
        
        color = "Bullish" if c > o else "Bearish" if c < o else "Neutral"
        
        # Reconocimiento básico de patrones
        ctype = "Normal Candle"
        reason = "Cuerpo y mechas en proporciones habituales."
        
        if body_pct > 85:
            ctype = f"{color} Marubozu"
            reason = "Cuerpo cubre más del 85% del rango, indicando extrema fuerza."
        elif body_pct < 10 and lower_pct > 60 and upper_pct < 10:
            ctype = "Hammer" if color == "Bullish" else "Hanging Man"
            reason = "Cuerpo muy pequeño arriba, mecha inferior muy larga (rechazo)."
        elif body_pct < 10 and upper_pct > 60 and lower_pct < 10:
            ctype = "Shooting Star" if color == "Bearish" else "Inverted Hammer"
            reason = "Cuerpo muy pequeño abajo, mecha superior muy larga (rechazo)."
        elif body_pct < 5 and c_range > 0:
            if lower_pct > 40 and upper_pct > 40:
                ctype = "Long Legged Doji"
                reason = "Apertura igual al cierre, alta indecisión con largas mechas."
            else:
                ctype = "Doji"
                reason = "Apertura casi igual al cierre. Indecisión."
        elif body_pct < 25 and lower_pct > 25 and upper_pct > 25:
            ctype = "Spinning Top"
            reason = "Cuerpo pequeño con mechas en ambos lados. Consolidación."
            
        strength = "Alta" if body_pct > 70 else "Media" if body_pct > 30 else "Baja"
        
        return {
            'open': o, 'high': h, 'low': l, 'close': c,
            'range': c_range, 'body': body,
            'upper_wick': upper_wick, 'lower_wick': lower_wick,
            'body_pct': body_pct, 'upper_pct': upper_pct, 'lower_pct': lower_pct,
            'atr_ratio': atr_ratio, 'vol_ratio': v/v_sma if v_sma > 0 else 0,
            'color': color, 'type': ctype, 'strength': strength, 'reason': reason
        }

    def _get_trend_explanation(self, df_macro: pd.DataFrame) -> Dict[str, Any]:
        """Extrae la estructura matemática exacta (HH1, HH2, HL1, HL2) y su validación."""
        if 'is_pivot_high' not in df_macro.columns or 'is_pivot_low' not in df_macro.columns:
            return {
                "valid": False, "macro_structure": "UNKNOWN",
                "hh": [], "hl": [], "lh": [], "ll": [],
                "msg": "Estrategia no genera pivotes estructurales."
            }
            
        highs = df_macro[df_macro['is_pivot_high']]['high'].values
        lows = df_macro[df_macro['is_pivot_low']]['low'].values
        info = {
            "valid": False, "macro_structure": "SIDEWAYS",
            "hh": [], "hl": [], "lh": [], "ll": [],
            "msg": "No hay suficientes pivotes para evaluar."
        }
        
        if len(highs) < 2 or len(lows) < 2:
            return info
            
        info["hh"] = [highs[-2], highs[-1]]  # [HH1, HH2]
        info["hl"] = [lows[-2], lows[-1]]    # [HL1, HL2]
        info["lh"] = [highs[-2], highs[-1]]  # Strategy context LH = HH
        info["ll"] = [lows[-2], lows[-1]]    # Strategy context LL = HL
        
        hh1, hh2 = info["hh"]
        hl1, hl2 = info["hl"]
        
        if hh2 > hh1 and hl2 > hl1:
            info["macro_structure"] = "UPTREND"
            info["valid"] = True
            info["msg"] = "La estructura alcista es válida porque HH2 y HL2 son superiores a sus predecesores."
        elif hh2 < hh1 and hl2 < hl1:
            info["macro_structure"] = "DOWNTREND"
            info["valid"] = True
            info["msg"] = "La estructura bajista es válida porque LH2 y LL2 son inferiores a sus predecesores."
        else:
            info["macro_structure"] = "SIDEWAYS"
            info["valid"] = False
            # Explicación matemática de la invalidación
            if hh2 <= hh1 and hl2 >= hl1:
                info["msg"] = f"Estructura invalidada (Inside/Squeeze): El HH2 ({hh2:.2f}) no superó al HH1 ({hh1:.2f}) y el HL2 ({hl2:.2f}) no cayó bajo HL1 ({hl1:.2f})."
            elif hh2 >= hh1 and hl2 <= hl1:
                info["msg"] = f"Estructura invalidada (Expansion): HH2 ({hh2:.2f}) > HH1, pero HL2 ({hl2:.2f}) < HL1. Alta volatilidad bidireccional."
            elif hh2 <= hh1:
                info["msg"] = f"Estructura alcista invalidada: El último pico HH2 ({hh2:.2f}) no logró superar al HH1 ({hh1:.2f}). {hh2:.2f} <= {hh1:.2f} ✖"
            elif hl2 >= hl1:
                info["msg"] = f"Estructura bajista invalidada: El último valle HL2 ({hl2:.2f}) quedó por encima del HL1 ({hl1:.2f}). {hl2:.2f} >= {hl1:.2f} ✖"
            else:
                info["msg"] = "Patrón mixto no operativo."
                
        return info

    def print_report(self, dfs: Dict[str, pd.DataFrame], current_price: float, saldo: float, signal: Dict[str, Any]):
        if not getattr(settings, 'ENABLE_DETAILED_LOGS', True):
            return
            
        if getattr(settings, 'ENVIRONMENT', '') == 'BACKTEST':
            return

        strategy = self.engine.strategy
        if not hasattr(strategy, 'params'):
            return

        macro_tf = strategy.params.get('macro_tf')
        entry_tf = strategy.params.get('entry_tf')
        df_macro = dfs.get(macro_tf)
        df_entry = dfs.get(entry_tf)
        
        if df_macro is None or df_entry is None:
            return

        # --- CÁLCULOS MATEMÁTICOS ---
        trend_info = self._get_trend_explanation(df_macro)
        candle_info = self._analyze_candle(df_entry)
        
        current_atr = df_entry['atr'].iloc[-1] if 'atr' in df_entry else 0.0
        min_v = strategy.params.get('atr_min_volatility', 0.001)
        max_v = strategy.params.get('atr_max_volatility', 0.03)
        volatility_pct = current_atr / current_price if current_price > 0 else 0
        atr_valid = min_v <= volatility_pct <= max_v
        
        sr_zones = detect_support_resistance(df_entry, current_atr, 0.5)
        resistances = sr_zones['resistances']
        supports = sr_zones['supports']
        closest_res = resistances[0] if resistances else None
        closest_sup = supports[0] if supports else None
        
        last_candle = df_entry.iloc[-2] if len(df_entry) > 1 else None
        vol_val = last_candle['volume'] if last_candle is not None else 0
        vol_sma = last_candle['vol_sma'] if last_candle is not None and 'vol_sma' in last_candle else 1
        vol_ratio = vol_val / vol_sma if vol_sma > 0 else 0
        vol_req = strategy.params.get('vol_multiplier', 1.5)
        vol_valid = vol_ratio >= vol_req
        
        state = self.engine.position_manager.strategy_state.get('status', 'IDLE')
        action_decision = signal.get('action', 'NONE')
        
        is_breakout = state != 'IDLE'
        is_retest = action_decision != 'NONE'
        
        # -------------------------------------------------------------
        # IMPRESIÓN DEL REPORTE INSTITUCIONAL
        # -------------------------------------------------------------
        print("")
        logger.info(f"\n{Colors.CYAN}================================================================================{Colors.RESET}")
        logger.info(f"{Colors.CYAN}QUANTITATIVE DIAGNOSTICS REPORT (INSTITUTIONAL SCORING){Colors.RESET}")
        logger.info(f"{Colors.CYAN}================================================================================{Colors.RESET}")
        logger.info(f"Symbol : {getattr(settings, 'SYMBOL', 'UNKNOWN')} | State: {state}")
        
        last_decision = self.engine.position_manager.strategy_state.get('last_decision')
        
        if last_decision:
            direction = last_decision.get('direction', 'NONE')
            score = last_decision.get('score', 0.0)
            conf = last_decision.get('confidence', 0.0)
            bd = last_decision.get('breakdown', {})
            weights = last_decision.get('weights', {})
            
            logger.info(f"\n{Colors.MAGENTA}================================================================================{Colors.RESET}")
            logger.info(f"{Colors.MAGENTA}GLOBAL DECISION SCORE{Colors.RESET}")
            logger.info(f"{Colors.MAGENTA}================================================================================{Colors.RESET}")
            
            if direction != 'NONE':
                logger.info(f"Target Direction : {Colors.GREEN if direction == 'LONG' else Colors.RED}{direction}{Colors.RESET}")
                logger.info(f"Decision Score   : {score:.1f} / 100.0")
                logger.info(f"Confidence       : {conf:.1f} / 100.0")
                
                logger.info(f"\n--- INSTITUTIONAL MATRIX ({direction}) ---")
                
                d_key = direction.lower()
                def prt_score(name, w_key):
                    if w_key in bd and d_key in bd[w_key]:
                        val = bd[w_key][d_key]
                        s, c = val[0], val[1]
                        w = weights.get(w_key, 0)
                        logger.info(f"[+] {name:<12}: Score {s:>5.1f} | Conf {c:>5.1f} | Weight {w:.2f} -> {(s*w):>5.1f} pts")
                        
                prt_score('Market', 'market')
                prt_score('Structure', 'structure')
                prt_score('Momentum', 'momentum')
                prt_score('Execution', 'execution')
                prt_score('Risk', 'risk')
            else:
                logger.info(f"Target Direction : NONE (Scores por debajo de threshold o divergentes)")
                logger.info(f"Decision Score   : {score:.1f}")
                logger.info(f"Confidence       : {conf:.1f}")
                
        else:
            logger.info("\nEsperando datos del Decision Engine...")

        # -------------------------------------------------------------
        # PHASE 8.6 & 8.7 - STRUCTURE SENSITIVITY & STABILITY
        # -------------------------------------------------------------
        struct_eval = StructureResearcher.evaluate(df_macro, current_price, trend_info['macro_structure'])
        
        logger.info(f"\n{Colors.BLUE}================================================================================{Colors.RESET}")
        logger.info(f"{Colors.BLUE}STRUCTURE SENSITIVITY REPORT (PHASE 8.7){Colors.RESET}")
        logger.info(f"{Colors.BLUE}================================================================================{Colors.RESET}")
        sens = struct_eval['sensitivity']
        logger.info(f"Window 3             : {sens['w3']}")
        logger.info(f"Window 5 (Base)      : {sens['w5']}")
        logger.info(f"Window 7             : {sens['w7']}")
        logger.info(f"Window 9             : {sens['w9']}")
        
        if struct_eval['diff_info']:
            d_info = struct_eval['diff_info']
            logger.info(f"\n{struct_eval['explanation']}")
            logger.info(f"Predominant Trend: {d_info['predominant_trend']}")
            logger.info(f"Dispersion: {d_info['dispersion_pct']:.1f}%")
        else:
            logger.info(f"\n{struct_eval['explanation']}")
            
        logger.info(f"\nStructure Stability Score: {struct_eval['stability_score']:.1f}%")
        logger.info(f"Decision Robustness      : {struct_eval['decision_robustness']}")
        
        logger.info(f"\n{Colors.YELLOW}--- PIVOT INFLUENCE ANALYSIS (KNOCK-OUT TESTING) ---{Colors.RESET}")
        for ko in struct_eval['knock_out']:
            logger.info(f"Pivote {ko['p_type']} #{ko['p_idx']}")
            logger.info(f"¿Si desaparece cambia la tendencia?: {'SI' if ko['changed'] else 'NO'}")
            if ko['changed']:
                logger.info(f"Nueva tendencia: {ko['new_trend']}")
                logger.info(f"Por qué: {ko['reason']}")
            logger.info("-" * 40)
            
        logger.info(f"\n{Colors.GREEN}--- RECOMMENDATION ENGINE ---{Colors.RESET}")
        if struct_eval['stability_score'] == 100.0:
            logger.info("Todas las configuraciones llegan a la misma conclusión.")
            logger.info("La estructura es matemáticamente robusta. No existen indicios de sobreajuste.")
        elif struct_eval['stability_score'] <= 50.0:
            logger.info(f"La clasificación {sens['w5']} es altamente inestable.")
            logger.info("La decisión presenta baja robustez y depende de pivotes críticos vulnerables al ruido.")
            logger.info("Se recomienda revisar el detector de pivotes antes de modificar la estrategia.")
        else:
            logger.info(f"La decisión presenta una robustez aceptable, aunque presenta divergencias mínimas.")
            
        logger.info(f"\n{Colors.BLUE}================================================================================{Colors.RESET}")
        logger.info(f"{Colors.BLUE}STRUCTURE ROBUSTNESS (ALTERNATIVE MODELS){Colors.RESET}")
        logger.info(f"{Colors.BLUE}================================================================================{Colors.RESET}")
        logger.info(f"Dow Theory Proxy     : {struct_eval['dow_theory']}")
        logger.info(f"BOS (Break of Struct): {struct_eval['bos']}")
        logger.info(f"CHoCH (Character)    : {struct_eval['choch']}")
        logger.info(f"\nResultado Estrategia : {trend_info['macro_structure']}")
        logger.info(f"Consenso Alternativo : {struct_eval['consensus']}")
        logger.info(f"Alternative Score    : {struct_eval['robustness_score']:.1f}%")
        
        if struct_eval['is_divergent']:
            logger.info(f"{Colors.YELLOW}DIVERGENCIA DETECTADA: Estrategia detecta {trend_info['macro_structure']} pero consenso es {struct_eval['consensus']}{Colors.RESET}")
        
        logger.info(f"{Colors.BLUE}================================================================================{Colors.RESET}")

        score = last_decision.get('score', 0.0) if last_decision else 0.0
        direction = last_decision.get('direction', 'NONE') if last_decision else 'NONE'
        
        audit_data = {
            'df_macro': df_macro,
            'struct_eval': struct_eval,
            'has_pivots': len(df_macro[df_macro['is_pivot_high']]) > 0 if df_macro is not None and 'is_pivot_high' in df_macro.columns else False,
            'total_score': score,
            'trend_info': trend_info,
            'trend_raw': trend_info,
            'atr_valid': atr_valid,
            'atr_min': min_v,
            'atr_max': max_v,
            'vol_valid': vol_valid,
            'vol_req': vol_req,
            'state': state,
            'action_decision': action_decision,
            'sim_dir': direction,
            'sim_entry': closest_res if direction == 'LONG' else closest_sup,
            'sim_sl': 0,
            'sim_tp': 0,
            'rr_target': 0,
            'current_atr': current_atr,
            'atr': current_atr,
            'vol_ratio': vol_ratio,
            'vol_val': vol_val,
            'vol_sma': vol_sma,
            'volatility_pct': volatility_pct,
            'current_price': current_price,
            'current_high': last_candle['high'] if last_candle is not None else current_price,
            'current_low': last_candle['low'] if last_candle is not None else current_price,
            'res_list': resistances,
            'sup_list': supports,
            'closest_res': closest_res,
            'closest_sup': closest_sup
        }
        self.auditor.audit_cycle(audit_data)

        # -------------------------------------------------------------
        # ACTUALIZAR ESTADO PREVIO
        # -------------------------------------------------------------
        self.prev_state = {
            'atr': current_atr,
            'vol': vol_ratio,
            'state': state,
            'closest_res': closest_res,
            'closest_sup': closest_sup
        }
