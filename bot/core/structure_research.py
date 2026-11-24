"""
Módulo: structure_research.py
=================================================
Herramientas de investigación y análisis de la estructura de mercado.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Set, Tuple

class StructureResearcher:
    """
    Phase 8.6 & 8.7 - Quant Research (Structure Robustness & Stability)
    Evaluates market structure using multiple alternative algorithms
    and deep stability analysis (Knock-Out Testing, Sensitivity Analysis).
    """
    
    @staticmethod
    def _find_pivots_custom(df: pd.DataFrame, window: int) -> pd.DataFrame:
        df_temp = df.copy()
        df_temp['is_pivot_high'] = (df_temp['high'] >= df_temp['high'].rolling(window, min_periods=1).max()) & \
                                   (df_temp['high'] >= df_temp['high'].iloc[::-1].rolling(window, min_periods=1).max().iloc[::-1])
                                   
        df_temp['is_pivot_low'] = (df_temp['low'] <= df_temp['low'].rolling(window, min_periods=1).min()) & \
                                  (df_temp['low'] <= df_temp['low'].iloc[::-1].rolling(window, min_periods=1).min().iloc[::-1])
                                  
        # Excluir los bordes para evitar bias y falsos pivotes no confirmados en tiempo real
        if window > 0 and len(df_temp) > window:
            df_temp.loc[df_temp.index[:window], 'is_pivot_high'] = False
            df_temp.loc[df_temp.index[:window], 'is_pivot_low'] = False
            df_temp.loc[df_temp.index[-window:], 'is_pivot_high'] = False
            df_temp.loc[df_temp.index[-window:], 'is_pivot_low'] = False
            
        return df_temp

    @staticmethod
    def _detect_trend_custom(df: pd.DataFrame, ignored_indices: List[int] = None) -> Dict[str, Any]:
        if ignored_indices is None:
            ignored_indices = []
            
        highs = df[df['is_pivot_high'] & (~df.index.isin(ignored_indices))].copy()
        lows = df[df['is_pivot_low'] & (~df.index.isin(ignored_indices))].copy()
        
        high_vals = highs['high'].values
        high_idx = highs.index.values
        low_vals = lows['low'].values
        low_idx = lows.index.values
        
        trend = "SIDEWAYS"
        hh_pass = False
        hl_pass = False
        
        hh1 = hh2 = hl1 = hl2 = 0.0
        hh1_idx = hh2_idx = hl1_idx = hl2_idx = -1
        
        if len(high_vals) >= 2 and len(low_vals) >= 2:
            hh1, hh2 = high_vals[-2], high_vals[-1]
            hh1_idx, hh2_idx = high_idx[-2], high_idx[-1]
            hl1, hl2 = low_vals[-2], low_vals[-1]
            hl1_idx, hl2_idx = low_idx[-2], low_idx[-1]
            
            if hh2 > hh1: hh_pass = True
            if hl2 > hl1: hl_pass = True
            
            if hh_pass and hl_pass:
                trend = "UPTREND"
            elif (not hh_pass) and (not hl_pass):
                trend = "DOWNTREND"
                
        return {
            "trend": trend,
            "hh_pass": hh_pass,
            "hl_pass": hl_pass,
            "hh": (hh1, hh2),
            "hh_idx": (hh1_idx, hh2_idx),
            "hl": (hl1, hl2),
            "hl_idx": (hl1_idx, hl2_idx),
            "all_high_idx": list(high_idx),
            "all_low_idx": list(low_idx)
        }

    @classmethod
    def evaluate(cls, df_macro: pd.DataFrame, current_price: float, original_trend: str) -> Dict[str, Any]:
        if df_macro is None or len(df_macro) < 10:
            return cls._empty_result()
            
        # 1. Sensitivity Analysis (Fractal Windows) & Deep Pivot Tracing
        eval_w3 = cls._detect_trend_custom(cls._find_pivots_custom(df_macro, 3))
        eval_w5 = cls._detect_trend_custom(cls._find_pivots_custom(df_macro, 5))
        eval_w7 = cls._detect_trend_custom(cls._find_pivots_custom(df_macro, 7))
        eval_w9 = cls._detect_trend_custom(cls._find_pivots_custom(df_macro, 9))
        
        trends = [eval_w3['trend'], eval_w5['trend'], eval_w7['trend'], eval_w9['trend']]
        
        # 1. Cálculo real del score de estabilidad (Frecuencia del modo sobre el total)
        from collections import Counter
        trend_counts = Counter(trends)
        most_common_trend, matches = trend_counts.most_common(1)[0]
        
        stability_score = (matches / len(trends)) * 100
        
        # 2. Clasificación matemática de la robustez
        if stability_score == 100.0:
            decision_robustness = "Robust Decision"
            explanation = f"Consenso absoluto de mercado. Todas las ventanas confirman {most_common_trend}."
        elif stability_score == 75.0:
            decision_robustness = "Weak Decision"
            explanation = f"Consenso minoritario. El mercado tiende a {most_common_trend}, pero se detectan divergencias por ruido local."
        else:
            decision_robustness = "Highly Sensitive Decision"
            explanation = f"Estructura en conflicto crítico. Alta dispersión de tendencias: {dict(trend_counts)}."

        # 3. Diferenciador analítico expandido
        diff_info = {
            "predominant_trend": most_common_trend,
            "dispersion_pct": 100.0 - stability_score,
            "unique_trends": len(trend_counts)
        }
        
        # Knock-Out Simulator (Pivot Influence Analysis)
        df_w5 = cls._find_pivots_custom(df_macro, 5)
        knock_out = []
        last_4_pivots = [eval_w5['hh_idx'][0], eval_w5['hh_idx'][1], eval_w5['hl_idx'][0], eval_w5['hl_idx'][1]]
        for p_idx in set(last_4_pivots):
            if p_idx == -1: continue
            ko_eval = cls._detect_trend_custom(df_w5, ignored_indices=[p_idx])
            ko_changed = ko_eval['trend'] != eval_w5['trend']
            is_h = p_idx in eval_w5['all_high_idx']
            p_type = "HH" if is_h else "HL"
            knock_out.append({
                "p_idx": p_idx,
                "p_type": p_type,
                "changed": ko_changed,
                "new_trend": ko_eval['trend'],
                "reason": f"Altera validación {p_type}2 > {p_type}1" if ko_changed else "Redundante"
            })
        
        # Phase 8.6 Alternative Models
        dow_theory = cls._detect_trend_custom(cls._find_pivots_custom(df_macro, 2))['trend']
        df_base = df_w5
        base_highs = df_base[df_base['is_pivot_high']]['high'].values
        base_lows = df_base[df_base['is_pivot_low']]['low'].values
        bos_trend = "SIDEWAYS"
        choch_trend = "SIDEWAYS"
        if len(base_highs) >= 1 and len(base_lows) >= 1:
            last_high = base_highs[-1]
            last_low = base_lows[-1]
            if current_price > last_high: bos_trend = "UPTREND"
            elif current_price < last_low: bos_trend = "DOWNTREND"
            if original_trend == "UPTREND" and current_price < last_low: choch_trend = "DOWNTREND"
            elif original_trend == "DOWNTREND" and current_price > last_high: choch_trend = "UPTREND"
            else: choch_trend = bos_trend
                
        models = [eval_w3['trend'], eval_w7['trend'], eval_w9['trend'], dow_theory, bos_trend, choch_trend]
        uptrend_votes, downtrend_votes, sideways_votes = models.count("UPTREND"), models.count("DOWNTREND"), models.count("SIDEWAYS")
        total_models = len(models)
        
        if original_trend == "UPTREND": confidence = (uptrend_votes / total_models) * 100
        elif original_trend == "DOWNTREND": confidence = (downtrend_votes / total_models) * 100
        else: confidence = (sideways_votes / total_models) * 100
        
        consensus = "SIDEWAYS"
        if uptrend_votes > downtrend_votes and uptrend_votes > sideways_votes: consensus = "UPTREND"
        elif downtrend_votes > uptrend_votes and downtrend_votes > sideways_votes: consensus = "DOWNTREND"

        # Extract swing highs and lows for external use
        detected_swing_highs = [{"index": int(idx), "price": float(df_macro.loc[idx, 'high'])} for idx in eval_w5.get('all_high_idx', [])]
        detected_swing_lows = [{"index": int(idx), "price": float(df_macro.loc[idx, 'low'])} for idx in eval_w5.get('all_low_idx', [])]

        return {
            "sensitivity": {"w3": eval_w3['trend'], "w5": eval_w5['trend'], "w7": eval_w7['trend'], "w9": eval_w9['trend']},
            "stability_score": stability_score,
            "decision_robustness": decision_robustness,
            "diff_info": diff_info,
            "explanation": explanation,
            "knock_out": knock_out,
            "dow_theory": dow_theory,
            "bos": bos_trend,
            "choch": choch_trend,
            "robustness_score": confidence,
            "consensus": consensus,
            "is_divergent": (original_trend == "SIDEWAYS" and consensus != "SIDEWAYS"),
            "divergent_trend": consensus if (original_trend == "SIDEWAYS" and consensus != "SIDEWAYS") else None,
            "detected_swing_highs": detected_swing_highs,
            "detected_swing_lows": detected_swing_lows
        }

    @staticmethod
    def _empty_result():
        return {
            "sensitivity": {"w3": "SIDEWAYS", "w5": "SIDEWAYS", "w7": "SIDEWAYS", "w9": "SIDEWAYS"},
            "stability_score": 100.0,
            "decision_robustness": "Robust Decision",
            "diff_info": None,
            "explanation": "No data",
            "knock_out": [],
            "dow_theory": "SIDEWAYS",
            "bos": "SIDEWAYS",
            "choch": "SIDEWAYS",
            "robustness_score": 100.0,
            "consensus": "SIDEWAYS",
            "is_divergent": False,
            "divergent_trend": None
        }
