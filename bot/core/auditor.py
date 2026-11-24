"""
Módulo: auditor.py
=================================================
Módulo de auditoría integral. Analiza logs y métricas para generar reportes sobre la salud del bot.
"""
import os
import json
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List
from bot.config import settings
from bot.core.trade_logger import logger, Colors
from bot.core.structure_research import StructureResearcher

class StrategyAuditor:
    """
    Quant Research Framework & Glass Box Auditor (Phase 8.8 Decision Quality)
    - Decision Quality Engine (Candle tracking & grading)
    - Decision Explainability (Math trace, Pivots, What-If)
    - Opportunity Cost Analysis (PnL tracking for discarded ops)
    - Filter Impact Analysis & Value Score (Stars)
    - Counterfactual Shadow Sandbox (Testing relaxed parameters)
    - Daily Quant Performance Report
    """
    def __init__(self):
        self.history_file = os.path.join(os.getcwd(), 'auditor_history.json')
        self.pending_retrospective: List[Dict[str, Any]] = []
        
        self.RISK_PER_TRADE = 10.0
        self.MAX_CANDLES_LIFETIME = 20
        
        self.stats = {
            "candles_analyzed": 0,
            "possible_ops": 0,
            "executed_ops": 0,
            "rejected_ops": 0,
            "false_negatives": 0,
            "true_negatives": 0,
            "near_misses": 0,
            "no_entry": 0,
            "sim_wins": 0,
            "sim_losses": 0,
            "total_pnl_lost": 0.0,
            "total_pnl_saved": 0.0,
            "blockers_heatmap": {},
            "filter_impact": {},
            "breakouts_detected": 0,
            "retests_detected": 0,
            "total_score": 0,
            "pivots_found": 0,
            "pivots_valid": 0,
            "pivots_discarded": 0,
            "hh_found": 0,
            "hl_found": 0,
            "lh_found": 0,
            "ll_found": 0,
            "divergent_sideways": 0,
            "divergence_wins": 0,
            "divergence_losses": 0,
            "divergence_pnl_lost": 0.0
        }
        
    def generate_decision_id(self) -> str:
        symbol = getattr(settings, 'SYMBOL', 'UNKNOWN').replace('/', '').replace('_', '')
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{symbol}_{now_str}"
        
    def _save_history(self, record: Dict[str, Any]):
        try:
            data = []
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
            data.append(record)
            with open(self.history_file, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception: pass

    def _init_filter(self, filter_name: str):
        if filter_name not in self.stats['filter_impact'] and filter_name != "Ninguno (Trade Ejecutado)":
            self.stats['filter_impact'][filter_name] = {
                "blocked": 0, "wins": 0, "losses": 0, "neutral": 0, "pnl_lost": 0.0, "pnl_saved": 0.0
            }

    def update_retrospective(self, current_price: float, current_high: float, current_low: float):
        active_pending = []
        for opp in self.pending_retrospective:
            state = opp.get('state', 'PENDING_ENTRY')
            side = opp.get('sim_side')
            entry = opp.get('sim_entry')
            sl = opp.get('sim_sl')
            tp = opp.get('sim_tp')
            
            if not entry or not sl or not tp or entry == sl:
                continue
                
            if state == 'PENDING_ENTRY':
                opp['candles_elapsed'] = opp.get('candles_elapsed', 0) + 1
                hit_entry = False
                if side == "LONG" and current_low <= entry: hit_entry = True
                elif side == "SHORT" and current_high >= entry: hit_entry = True
                    
                atr = opp.get('atr', 0)
                expired = False
                if side == "LONG" and current_price > entry + (atr * 2): expired = True
                elif side == "SHORT" and current_price < entry - (atr * 2): expired = True
                if opp['candles_elapsed'] >= self.MAX_CANDLES_LIFETIME: expired = True
                    
                if hit_entry:
                    opp['state'] = 'IN_POSITION'
                    opp['mfe'] = entry
                    opp['mae'] = entry
                    opp['start_time'] = datetime.now()
                    active_pending.append(opp)
                elif expired:
                    opp['state'] = 'FINISHED'
                    opp['result'] = 'NO ENTRY'
                    self.stats['no_entry'] += 1
                    b_name = opp.get('first_blocker')
                    if b_name and not opp.get('is_shadow'):
                        self._init_filter(b_name)
                        self.stats['filter_impact'][b_name]['neutral'] += 1
                    if not opp.get('is_shadow'):
                        self._print_decision_quality_report(opp)
                else:
                    active_pending.append(opp)
                    
            elif state == 'IN_POSITION':
                opp['candles_elapsed'] = opp.get('candles_elapsed', 0) + 1
                sl_hit = False
                tp_hit = False
                
                if side == "LONG":
                    if current_low <= sl: sl_hit = True
                    if current_high >= tp: tp_hit = True
                else:
                    if current_high >= sl: sl_hit = True
                    if current_low <= tp: tp_hit = True
                    
                if sl_hit or tp_hit:
                    opp['state'] = 'FINISHED'
                    duration = (datetime.now() - opp.get('start_time', datetime.now())).total_seconds() / 60
                    opp['duration_mins'] = duration
                    
                    b_name = opp.get('first_blocker')
                    is_shadow = opp.get('is_shadow', False)
                    
                    if tp_hit:
                        opp['result'] = 'WIN'
                        if opp.get('is_shadow'):
                            if opp.get('shadow_type') == 'divergence':
                                self.stats['divergence_wins'] += 1
                                self.stats['divergence_pnl_lost'] += (self.RISK_PER_TRADE * 2.0)
                        else:
                            self.stats['sim_wins'] += 1
                            self.stats['false_negatives'] += 1
                            pnl = self.RISK_PER_TRADE * 2.0
                            self.stats['total_pnl_lost'] += pnl
                            if b_name:
                                self._init_filter(b_name)
                                self.stats['filter_impact'][b_name]['wins'] += 1
                                self.stats['filter_impact'][b_name]['pnl_lost'] += pnl
                        self._print_decision_quality_report(opp)
                    else:
                        opp['result'] = 'LOSS'
                        if opp.get('is_shadow'):
                            if opp.get('shadow_type') == 'divergence':
                                self.stats['divergence_losses'] += 1
                        else:
                            self.stats['sim_losses'] += 1
                            self.stats['true_negatives'] += 1
                            pnl = self.RISK_PER_TRADE * 1.0
                            self.stats['total_pnl_saved'] += pnl
                            if b_name:
                                self._init_filter(b_name)
                                self.stats['filter_impact'][b_name]['losses'] += 1
                                self.stats['filter_impact'][b_name]['pnl_saved'] += pnl
                        self._print_decision_quality_report(opp)
                else:
                    active_pending.append(opp)
                    
        self.pending_retrospective = active_pending

    def _print_decision_quality_report(self, opp: Dict[str, Any]):
        if opp.get('is_shadow'): return # Mantenemos reportes solo para operaciones reales descartadas
        
        logger.info(f"\n{Colors.YELLOW}================================================================================{Colors.RESET}")
        logger.info(f"{Colors.YELLOW}DECISION QUALITY REPORT (PHASE 8.8){Colors.RESET}")
        logger.info(f"{Colors.YELLOW}================================================================================{Colors.RESET}")
        
        logger.info(f"Decision           : NO TRADE")
        
        res_str = ""
        grade = ""
        cost = ""
        if opp.get('result') == 'WIN':
            res_str = "+2R"
            grade = f"{Colors.RED}ERROR{Colors.RESET}"
            cost = f"+{self.RISK_PER_TRADE * 2.0} USDT"
        elif opp.get('result') == 'LOSS':
            res_str = "-1R"
            grade = f"{Colors.GREEN}CORRECTA{Colors.RESET}"
            cost = f"0.00 USDT (Evitó pérdida de {self.RISK_PER_TRADE * 1.0} USDT)"
        else:
            res_str = "Break Even / No Entry"
            grade = f"{Colors.CYAN}NEUTRAL{Colors.RESET}"
            cost = "0.00 USDT"
            
        logger.info(f"Resultado futuro   : {res_str}")
        logger.info(f"Calificación       : {grade}")
        logger.info(f"Costo de oport.    : {cost}")
        logger.info(f"Motivo del descarte: {opp.get('trend_detected', 'SIDEWAYS')}")
        logger.info(f"Filtro responsable : {opp.get('first_blocker')}")
        logger.info(f"Tiempo hasta conf. : {opp.get('candles_elapsed', 0)} velas")
        logger.info(f"{Colors.YELLOW}================================================================================{Colors.RESET}")

    def _audit_all_pivots(self, df_macro: pd.DataFrame):
        if df_macro is None or df_macro.empty or 'is_pivot_high' not in df_macro.columns: return
        highs = df_macro[df_macro['is_pivot_high']]
        lows = df_macro[df_macro['is_pivot_low']]
        self.stats['pivots_valid'] = len(highs) + len(lows)
        logger.info(f"\n{Colors.CYAN}--- DETECTED SWING HIGHS ---{Colors.RESET}")
        for i, row in highs.tail(5).iterrows(): logger.info(f"#{i} | Precio: {row['high']:.2f}")
        logger.info(f"\n{Colors.CYAN}--- DETECTED SWING LOWS ---{Colors.RESET}")
        for i, row in lows.tail(5).iterrows(): logger.info(f"#{i} | Precio: {row['low']:.2f}")

    def _audit_discarded_pivots(self, df_macro: pd.DataFrame):
        if df_macro is None or len(df_macro) < 10 or 'is_pivot_high' not in df_macro.columns: return
        logger.info(f"\n{Colors.YELLOW}--- PIVOTES DESCARTADOS (CAJA DE CRISTAL) ---{Colors.RESET}")
        recent = df_macro.tail(30).copy()
        recent['is_local_max_3'] = (recent['high'] >= recent['high'].rolling(4, min_periods=1).max()) & (recent['high'] >= recent['high'].iloc[::-1].rolling(4, min_periods=1).max().iloc[::-1])
        discarded = recent[(recent['is_local_max_3']) & (~recent['is_pivot_high'])]
        self.stats['pivots_found'] = self.stats['pivots_valid'] + len(discarded)
        self.stats['pivots_discarded'] = len(discarded)
        
        if 'discarded_pivots_log' not in self.stats:
            self.stats['discarded_pivots_log'] = []
            
        count = 0
        for i, row in discarded.iterrows():
            if count >= 3: break
            logger.info(f"Pivot descartado | Índice: {i} | Precio: {row['high']:.2f}")
            logger.info(f"Motivo: No cumple validación ATR/Ventana")
            
            # Guardar para análisis cuantitativo JSON
            self.stats['discarded_pivots_log'].append({
                "pivot_index": str(i),
                "price": float(row['high']),
                "timestamp": str(row.name) if hasattr(row, 'name') else str(datetime.now()),
                "relative_volume": float(row.get('volume_sma_ratio', row.get('volume', 0.0))),
                "atr": float(row.get('atr', 0.0)),
                "reason": "No cumple validación estructural ATR/Fractal",
                "decision": "discarded"
            })
            count += 1

    def _audit_trend_detection(self, trend_raw: Dict[str, Any]):
        logger.info(f"\n{Colors.CYAN}--- AUDITORÍA MATEMÁTICA DE TENDENCIA (GLASS BOX) ---{Colors.RESET}")
        logger.info(f"Decision Source: BreakoutStrategy.generate_signal() -> detect_market_structure()")
        if not trend_raw['hh'] or not trend_raw['hl']:
            logger.info(f"Faltan pivotes suficientes para comparar. -> SIDEWAYS")
            return
        hh1, hh2 = trend_raw['hh']
        hl1, hl2 = trend_raw['hl']
        logger.info(f"Comparación HH: {hh2:.2f} > {hh1:.2f} -> {'PASS' if hh2 > hh1 else 'FAIL'}")
        if hh2 > hh1: self.stats['hh_found'] += 1
        else: self.stats['lh_found'] += 1
        logger.info(f"Comparación HL: {hl2:.2f} > {hl1:.2f} -> {'PASS' if hl2 > hl1 else 'FAIL'}")
        if hl2 > hl1: self.stats['hl_found'] += 1
        else: self.stats['ll_found'] += 1
        logger.info(f"Resultado Final: {trend_raw['macro_structure']}")

    def _audit_what_if_analysis(self, df_macro: pd.DataFrame, trend_raw: Dict[str, Any]):
        if df_macro is None or df_macro.empty: return
        if trend_raw['macro_structure'] == 'SIDEWAYS' and trend_raw['hh']:
            logger.info(f"\n{Colors.MAGENTA}--- WHAT-IF ANALYSIS (CONTRAFÁCTICO) ---{Colors.RESET}")
            logger.info(f"Pregunta: Si eliminamos el último pivote HL bloqueador... ¿La estructura cambia?")
            lows = df_macro[df_macro['is_pivot_low']]['low'].values
            if len(lows) >= 3:
                alt_hl1, alt_hl2 = lows[-3], lows[-2]
                hh1, hh2 = trend_raw['hh']
                alt_trend = "UPTREND" if (hh2 > hh1 and alt_hl2 > alt_hl1) else "SIDEWAYS"
                cambia = alt_trend != trend_raw['macro_structure']
                logger.info(f"Respuesta: {'Sí' if cambia else 'No'}. Resultado Contrafáctico: {alt_trend}")
            else: logger.info("Respuesta: No. Faltan pivotes históricos suficientes.")

    def _print_decision_trace(self, data: Dict[str, Any]):
        logger.info(f"\n{Colors.CYAN}--- ÁRBOL COMPLETO DE DECISIÓN ---{Colors.RESET}")
        def pr_step(name, status, reason=""):
            color = Colors.GREEN if status == "PASS" else Colors.RED if status == "FAIL" else Colors.YELLOW
            logger.info(f"{name:<25} {color}{status:<10}{Colors.RESET} {reason}")
        pr_step("Nueva vela", "PASS", "Datos en vivo")
        pr_step("Detectar pivotes", "PASS" if data['has_pivots'] else "FAIL", "")
        if not data['has_pivots']: return
        trend_raw = data.get('trend_raw', {})
        hh_pass = trend_raw.get('hh') and trend_raw['hh'][1] > trend_raw['hh'][0]
        hl_pass = trend_raw.get('hl') and trend_raw['hl'][1] > trend_raw['hl'][0]
        pr_step("Validar HH", "PASS" if hh_pass else "FAIL", "")
        pr_step("Validar HL", "PASS" if hl_pass else "FAIL", "")
        pr_step("Estructura", "PASS" if data['trend_valid'] else "FAIL", data['trend_dir'])
        if not data['trend_valid']:
            pr_step("Breakout", "SKIPPED", "")
            pr_step("Retest", "SKIPPED", "")
            return
        is_breakout = data['state'] != 'IDLE'
        pr_step("Breakout", "PASS" if is_breakout else "FAIL", "")
        if not is_breakout: return
        pr_step("Filtro Volumen", "PASS" if data['vol_valid'] else "FAIL", f"Req {data['vol_req']}x")
        if not data['vol_valid']: return
        pr_step("Filtro ATR", "PASS" if data['atr_valid'] else "FAIL", "")
        if not data['atr_valid']: return
        is_retest = data['action_decision'] != 'NONE'
        pr_step("Retest", "PASS" if is_retest else "FAIL", "")
        if not is_retest: return
        pr_step("Risk Manager", "PASS", "Validado")
        logger.info(f"{Colors.GREEN}Orden enviada: SI ({data['action_decision']}){Colors.RESET}")

    def audit_cycle(self, audit_data: Dict[str, Any]):
        self.stats['candles_analyzed'] += 1
        d_id = self.generate_decision_id()
        df_macro = audit_data.get('df_macro')
        
        trend_info = audit_data.get('trend_info', {})
        trend_raw = audit_data.get('trend_raw', {})
        state = audit_data.get('state', 'IDLE')
        action_decision = audit_data.get('action_decision', 'NONE')
        
        is_breakout = state != 'IDLE'
        is_retest = action_decision != 'NONE'
        
        if is_breakout: self.stats['breakouts_detected'] += 1
        if is_retest: self.stats['retests_detected'] += 1
        
        first_blocker = "Ninguno (Trade Ejecutado)"
        if not trend_info.get('valid'): first_blocker = "Estructura HH/HL"
        elif not is_breakout: first_blocker = "Breakout"
        elif not audit_data.get('vol_valid'): first_blocker = "Volumen"
        elif not audit_data.get('atr_valid'): first_blocker = "ATR"
        elif not is_retest: first_blocker = "Retest"
            
        if first_blocker != "Ninguno (Trade Ejecutado)":
            self.stats['blockers_heatmap'][first_blocker] = self.stats['blockers_heatmap'].get(first_blocker, 0) + 1
            self.stats['rejected_ops'] += 1
            self._init_filter(first_blocker)
            self.stats['filter_impact'][first_blocker]['blocked'] += 1
        else:
            self.stats['executed_ops'] += 1
            
        if first_blocker != "Ninguno (Trade Ejecutado)" and audit_data.get('sim_entry'):
            self.pending_retrospective.append({
                'decision_id': d_id,
                'timestamp': datetime.now().isoformat(),
                'symbol': getattr(settings, 'SYMBOL', 'UNKNOWN'),
                'timeframe': getattr(settings, 'TIMEFRAME', 'UNKNOWN'),
                'trend_detected': trend_info.get('macro_structure'),
                'hh': trend_raw.get('hh'),
                'hl': trend_raw.get('hl'),
                'lh': trend_raw.get('lh'),
                'll': trend_raw.get('ll'),
                'atr': audit_data.get('atr'),
                'volumen': audit_data.get('vol_val'),
                'soporte': audit_data.get('closest_sup'),
                'resistencia': audit_data.get('closest_res'),
                'current_price': audit_data.get('current_price'),
                'sim_side': audit_data.get('sim_dir'),
                'sim_entry': audit_data.get('sim_entry'),
                'sim_sl': audit_data.get('sim_sl'),
                'sim_tp': audit_data.get('sim_tp'),
                'first_blocker': first_blocker,
                'state': 'PENDING_ENTRY',
                'candles_elapsed': 0,
                'is_shadow': False
            })

        # SHADOW COUNTERFACTUAL ENGINE
        if first_blocker == "Volumen" and audit_data.get('sim_entry'):
            vol_ratio = audit_data.get('vol_ratio', 0)
            if 1.30 <= vol_ratio < audit_data.get('vol_req', 1.5):
                self.pending_retrospective.append({
                    'decision_id': d_id + "_SHADOW",
                    'sim_side': audit_data.get('sim_dir'),
                    'sim_entry': audit_data.get('sim_entry'),
                    'sim_sl': audit_data.get('sim_sl'),
                    'sim_tp': audit_data.get('sim_tp'),
                    'atr': audit_data.get('atr'),
                    'first_blocker': 'Volumen',
                    'state': 'PENDING_ENTRY',
                    'candles_elapsed': 0,
                    'is_shadow': True,
                    'shadow_param': "Volumen 1.30x",
                    'shadow_type': "vol_flex"
                })
                
        # RESEARCH MODE: STRUCTURE ROBUSTNESS
        struct_eval = audit_data.get('struct_eval', {})
        
        if struct_eval and struct_eval.get('is_divergent'):
            self.stats['divergent_sideways'] += 1
            if audit_data.get('sim_entry'):
                # Inyectar Shadow Trade divergente asumiendo el side del consenso
                shadow_side = struct_eval['consensus']
                self.pending_retrospective.append({
                    'decision_id': d_id + "_DIVERGENCE",
                    'sim_side': shadow_side,
                    'sim_entry': audit_data.get('sim_entry'),
                    'sim_sl': audit_data.get('sim_sl'),
                    'sim_tp': audit_data.get('sim_tp'),
                    'atr': audit_data.get('atr'),
                    'first_blocker': 'Estructura HH/HL',
                    'state': 'PENDING_ENTRY',
                    'candles_elapsed': 0,
                    'is_shadow': True,
                    'shadow_param': f"Consenso {shadow_side}",
                    'shadow_type': 'divergence'
                })
                
        self._audit_all_pivots(df_macro)
        self._audit_discarded_pivots(df_macro)
        self._audit_trend_detection(trend_raw)
        self._audit_what_if_analysis(df_macro, trend_raw)
        self._print_decision_trace({
            'has_pivots': audit_data.get('has_pivots'),
            'trend_valid': trend_info.get('valid'),
            'trend_msg': trend_info.get('msg'),
            'trend_dir': trend_info.get('macro_structure'),
            'trend_raw': trend_raw,
            'state': state,
            'vol_valid': audit_data.get('vol_valid'),
            'vol_req': audit_data.get('vol_req'),
            'atr_valid': audit_data.get('atr_valid'),
            'action_decision': action_decision
        })

        if self.stats['candles_analyzed'] % 10 == 0:
            self.print_quant_report()

    def _get_filter_stars(self, f_name: str) -> str:
        data = self.stats['filter_impact'].get(f_name)
        if not data: return "★★☆☆☆"
        wins, losses = data['wins'], data['losses']
        if wins == 0 and losses == 0: return "★★★☆☆"
        ratio = data['pnl_saved'] / data['pnl_lost'] if data['pnl_lost'] > 0 else 999.0
        if ratio > 3.0: return "★★★★★" 
        if ratio > 1.5: return "★★★★☆"
        if ratio > 0.8: return "★★★☆☆"
        if ratio > 0.4: return "★★☆☆☆"
        return "★☆☆☆☆"

    def print_quant_report(self):
        logger.info(f"\n{Colors.MAGENTA}================================================================================{Colors.RESET}")
        logger.info(f"{Colors.MAGENTA}QUANT PERFORMANCE REPORT (OPPORTUNITY COST){Colors.RESET}")
        logger.info(f"{Colors.MAGENTA}================================================================================{Colors.RESET}")
        logger.info(f"Velas analizadas       : {self.stats['candles_analyzed']}")
        logger.info(f"Operaciones reales     : {self.stats['executed_ops']}")
        logger.info(f"Operaciones descartadas: {self.stats['rejected_ops']}")
        
        logger.info(f"\n{Colors.CYAN}--- PnL & COSTO DE OPORTUNIDAD ---{Colors.RESET}")
        logger.info(f"Ganadoras potenciales (False Negs): {self.stats['false_negatives']}")
        logger.info(f"Perdedoras evitadas   (True Negs) : {self.stats['true_negatives']}")
        logger.info(f"Nunca activadas       (No Entry)  : {self.stats['no_entry']}")
        
        pnl_evitado = self.stats['total_pnl_saved']
        pnl_perdido = self.stats['total_pnl_lost']
        logger.info(f"PnL Salvado Hipotético: +{pnl_evitado:.2f} USDT")
        logger.info(f"PnL Perdido Hipotético: -{pnl_perdido:.2f} USDT")
        
        net_op_cost = pnl_evitado - pnl_perdido
        if net_op_cost > 0:
            logger.info(f"Resultado Filtros     : {Colors.GREEN}+{net_op_cost:.2f} USDT (Altamente eficientes){Colors.RESET}")
        else:
            logger.info(f"Resultado Filtros     : {Colors.RED}{net_op_cost:.2f} USDT (Destruyendo rentabilidad){Colors.RESET}")
            
        t_sim = self.stats['sim_wins'] + self.stats['sim_losses']
        win_rate = (self.stats['sim_wins'] / t_sim * 100) if t_sim > 0 else 0
        pf = (self.stats['sim_wins'] * 2.0) / self.stats['sim_losses'] if self.stats['sim_losses'] > 0 else 0.0
        
        logger.info(f"\nWin Rate Hipotético   : {win_rate:.1f}%")
        logger.info(f"Profit Factor Hipot.  : {pf:.2f}")

        logger.info(f"\n{Colors.CYAN}--- FALSE SIDEWAYS ANALYSIS (STRUCTURE ROBUSTNESS) ---{Colors.RESET}")
        logger.info(f"Divergencias SIDEWAYS falsas identificadas : {self.stats['divergent_sideways']}")
        logger.info(f"Breakouts ganadores divergentes (Wins)     : {self.stats['divergence_wins']}")
        logger.info(f"Breakouts perdedores divergentes (Losses)  : {self.stats['divergence_losses']}")
        logger.info(f"Divergence Opportunity Cost (PnL Perdido)  : {Colors.RED}-{self.stats['divergence_pnl_lost']:.2f} USDT{Colors.RESET}")
        
        logger.info(f"\n{Colors.YELLOW}--- PERMANENT FILTER AUDIT ---{Colors.RESET}")
        sorted_heatmap = sorted(self.stats['blockers_heatmap'].items(), key=lambda x: x[1], reverse=True)
        for blocker, count in sorted_heatmap:
            impact = self.stats['filter_impact'].get(blocker, {})
            wins = impact.get('wins', 0)
            losses = impact.get('losses', 0)
            neutral = impact.get('neutral', 0)
            p_saved = impact.get('pnl_saved', 0)
            p_lost = impact.get('pnl_lost', 0)
            
            pf = (losses * 1.0) / (wins * 2.0) if wins > 0 else (losses * 1.0)
            ev = (p_saved - p_lost) / (wins + losses + neutral) if (wins + losses + neutral) > 0 else 0
            
            logger.info(f"Filtro:")
            logger.info(f"{blocker}")
            logger.info(f"Veces activado:")
            logger.info(f"{count}")
            logger.info(f"Operaciones descartadas:")
            logger.info(f"{count}")
            logger.info(f"Ganancias evitadas (False Negs):")
            logger.info(f"{wins}")
            logger.info(f"Pérdidas evitadas (True Negs):")
            logger.info(f"{losses}")
            logger.info(f"Oportunidades neutrales/perdidas:")
            logger.info(f"{neutral}")
            logger.info(f"Profit Factor del filtro:")
            logger.info(f"{pf:.2f}")
            logger.info(f"Valor esperado (USDT por bloqueo):")
            logger.info(f"{'+' if ev > 0 else ''}{ev:.2f} USDT")
            logger.info("-" * 48)

        self._generate_quant_recommendation(sorted_heatmap)

    def _generate_quant_recommendation(self, sorted_heatmap):
        logger.info(f"\n{Colors.GREEN}================================================================================{Colors.RESET}")
        logger.info(f"{Colors.GREEN}RECOMENDACIÓN AUTOMÁTICA{Colors.RESET}")
        logger.info(f"{Colors.GREEN}================================================================================{Colors.RESET}")
        
        worst_filter = None
        worst_ratio = 999.0
        
        for blocker, _ in sorted_heatmap:
            impact = self.stats['filter_impact'].get(blocker, {})
            p_saved = impact.get('pnl_saved', 0)
            p_lost = impact.get('pnl_lost', 0)
            
            if p_lost > 0:
                ratio = p_saved / p_lost
                if ratio < worst_ratio:
                    worst_ratio = ratio
                    worst_filter = blocker
        
        if worst_filter and worst_ratio < 0.8:
            logger.info(f"Existe evidencia estadística para investigar una relajación del filtro '{worst_filter}'.")
            logger.info(f"Este filtro bloqueó excesivas operaciones rentables, costando más PnL del que salvó (Ratio {worst_ratio:.2f}).")
            logger.info(f"Acción sugerida: Correr backtest expandiendo los rangos tolerados para {worst_filter}.")
        else:
            logger.info(f"No hay evidencia estadística para alterar la estrategia.")
            logger.info(f"Todos los filtros actuales muestran un 'Opportunity Cost' positivo o neutro protegiendo capital de forma efectiva.")
            
        logger.info(f"{Colors.GREEN}================================================================================{Colors.RESET}\n")
