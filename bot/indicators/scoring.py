"""
Módulo: scoring.py
=================================================
Módulo scoring.py del sistema Indicadores.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, Tuple
from bot.indicators.market_regime import MarketRegimeDetector
from bot.indicators.price_action import detect_market_structure, detect_support_resistance
from bot.core.structure_research import StructureResearcher

class InstitutionalScorer:
    """
    Motor Base para los módulos de Scoring.
    Cada método retorna (Score_Long, Conf_Long), (Score_Short, Conf_Short)
    Valores entre 0 y 100.
    """
    
    @staticmethod
    def evaluate_market(df_macro: pd.DataFrame) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        if df_macro is None or len(df_macro) < 50:
            return (50.0, 10.0), (50.0, 10.0)
            
        regime = MarketRegimeDetector.evaluate(df_macro)
        estado = regime.get('estado', '')
        confianza_reg = regime.get('confianza', 50.0)
        
        score_long = 50.0
        score_short = 50.0
        
        # Long Scoring
        if "STRONG TREND UP" in estado or "PARABOLIC" in estado: score_long = 100.0
        elif "TREND UP" in estado: score_long = 85.0
        elif "WEAK TREND" in estado and regime.get('adx', 0) > 20: score_long = 70.0
        elif "ACCUMULATION" in estado: score_long = 65.0
        elif "SIDEWAYS" in estado or "RANGE" in estado: score_long = 50.0
        elif "VOLATILE" in estado: score_long = 30.0
        else: score_long = 10.0 # PANIC, DISTRIBUTION, DOWNTREND
            
        # Short Scoring
        if "PANIC" in estado or "STRONG TREND DOWN" in estado: score_short = 100.0
        elif "DISTRIBUTION" in estado: score_short = 85.0
        elif "WEAK TREND" in estado and regime.get('adx', 0) > 20: score_short = 70.0 
        elif "SIDEWAYS" in estado or "RANGE" in estado: score_short = 50.0
        elif "VOLATILE" in estado: score_short = 30.0
        else: score_short = 10.0
            
        # Refinar si la EMA es claramente bajista
        try:
            ema_slope = df_macro['ema_fast'].iloc[-1] - df_macro['ema_fast'].iloc[-3]
            if ema_slope < 0 and score_short == 70.0: score_short = 80.0
            if ema_slope < 0 and score_long > 50: score_long -= 20
        except:
            pass

        return (score_long, confianza_reg), (score_short, confianza_reg)

    @staticmethod
    def evaluate_structure(df_macro: pd.DataFrame, current_price: float) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        if df_macro is None or len(df_macro) < 50:
            return (50.0, 10.0), (50.0, 10.0)
            
        trad_trend = detect_market_structure(df_macro)
        research = StructureResearcher.evaluate(df_macro, current_price, trad_trend)
        
        bos_trend = research.get('bos', 'SIDEWAYS')
        choch_trend = research.get('choch', 'SIDEWAYS')
        dow = research.get('dow_theory', 'SIDEWAYS')
        
        conf = research.get('robustness_score', 50.0)
        
        # Cortocircuito Jerárquico: Si BOS o CHoCH detectan lateralización, anular
        if bos_trend == "SIDEWAYS" or choch_trend == "SIDEWAYS":
            return (0.0, conf), (0.0, conf)
        
        score_l = 50.0
        score_s = 50.0
        
        # Scoring Long
        if trad_trend == "UPTREND": score_l += 30
        if bos_trend == "UPTREND": score_l += 20
        if choch_trend == "UPTREND": score_l += 15
        if dow == "UPTREND": score_l += 15
        
        # Scoring Short
        if trad_trend == "DOWNTREND": score_s += 30
        if bos_trend == "DOWNTREND": score_s += 20
        if choch_trend == "DOWNTREND": score_s += 15
        if dow == "DOWNTREND": score_s += 15
        
        # Penalizaciones
        if bos_trend == "DOWNTREND": score_l -= 30
        if bos_trend == "UPTREND": score_s -= 30
        
        score_l = max(0.0, min(100.0, score_l))
        score_s = max(0.0, min(100.0, score_s))
        
        return (score_l, conf, research), (score_s, conf, research)

    @staticmethod
    def evaluate_momentum(df_entry: pd.DataFrame) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        if df_entry is None or len(df_entry) < 20:
            return (50.0, 10.0), (50.0, 10.0)
            
        if 'rsi' not in df_entry.columns:
            delta = df_entry['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df_entry['rsi'] = 100 - (100 / (1 + rs))
            
        rsi = df_entry['rsi'].iloc[-1]
        roc = (df_entry['close'].iloc[-1] / df_entry['close'].iloc[-5]) - 1.0
        
        score_l = 50.0
        score_s = 50.0
        conf = 80.0
        
        if rsi > 55: score_l += 20
        if rsi > 65: score_l += 20
        if rsi > 85: score_l -= 30 # Overbought
        
        if rsi < 45: score_s += 20
        if rsi < 35: score_s += 20
        if rsi < 15: score_s -= 30 # Oversold
        
        if roc > 0.005: score_l += 20
        if roc < -0.005: score_s += 20
        
        score_l = max(0.0, min(100.0, score_l))
        score_s = max(0.0, min(100.0, score_s))
        
        return (score_l, conf), (score_s, conf)

    @staticmethod
    def evaluate_execution(df_entry: pd.DataFrame, current_price: float, atr: float, vol_mult: float = 1.5) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        if df_entry is None or len(df_entry) < 20:
            return (50.0, 10.0), (50.0, 10.0)
            
        last_candle = df_entry.iloc[-2]
        vol_ratio = last_candle['volume'] / last_candle['vol_sma'] if last_candle['vol_sma'] > 0 else 0
        
        sr_zones = detect_support_resistance(df_entry, atr, 0.5)
        resistances = sr_zones['resistances']
        supports = sr_zones['supports']
        
        score_l = 40.0
        score_s = 40.0
        conf = min(100.0, vol_ratio * 40.0) 
        
        # LONG EXECUTION
        if len(resistances) > 0:
            closest_res = resistances[0]
            dist_res = (closest_res - current_price) / current_price
            
            if dist_res < (atr / current_price) * 0.5: 
                score_l += 20
                
            if last_candle['close'] > closest_res: 
                score_l += 30
                if vol_ratio > vol_mult:
                    score_l += 30
                    
        # SHORT EXECUTION
        if len(supports) > 0:
            closest_sup = supports[0]
            dist_sup = (current_price - closest_sup) / current_price
            
            if dist_sup < (atr / current_price) * 0.5:
                score_s += 20
                
            if last_candle['close'] < closest_sup:
                score_s += 30
                if vol_ratio > vol_mult:
                    score_s += 30
                    
        score_l = max(0.0, min(100.0, score_l))
        score_s = max(0.0, min(100.0, score_s))
        
        return (score_l, conf), (score_s, conf)

    @staticmethod
    def evaluate_risk(df_entry: pd.DataFrame, current_price: float, atr: float, params: dict) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        volatility_pct = atr / current_price
        min_v = params.get('atr_min_volatility', 0.001)
        max_v = params.get('atr_max_volatility', 0.03)
        
        score = 80.0
        conf = 90.0
        
        if volatility_pct < min_v:
            score -= 50 
        elif volatility_pct > max_v:
            score -= 50 
            conf -= 30
            
        score = max(0.0, min(100.0, score))
        return (score, conf), (score, conf)
