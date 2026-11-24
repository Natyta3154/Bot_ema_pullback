"""
Módulo: decision_engine.py
=================================================
Motor de decisiones. Evalúa las señales de las estrategias y del modelo de ML para decidir si abrir o no una posición.
"""
import pandas as pd
from typing import Dict, Any, Tuple
from bot.indicators.scoring import InstitutionalScorer
from bot.config import settings
from bot.indicators.market_regime import MarketRegimeDetector
from datetime import datetime

class DecisionEngine:
    """
    Motor Institucional de Decisiones (Decision Scoring Engine).
    Agrega los 5 puntajes (Market, Structure, Momentum, Execution, Risk)
    y retorna un puntaje unificado para LONG y SHORT con su Confianza.
    """
    _cache = {}
    
    @staticmethod
    def evaluate(dfs: Dict[str, pd.DataFrame], current_price: float, atr: float, params: dict) -> Dict[str, Any]:
        df_macro = dfs.get(params.get('macro_tf', '1h'))
        df_entry = dfs.get(params.get('entry_tf', '15m'))
        
        ts = df_entry['timestamp'].iloc[-1] if (df_entry is not None and 'timestamp' in df_entry) else None
        
        if getattr(settings, 'ENVIRONMENT', '') == 'BACKTEST' and ts is not None and ts in DecisionEngine._cache:
            base_scores = DecisionEngine._cache[ts]
            market_l, market_s = base_scores['market']
            struct_l, struct_s = base_scores['structure']
            mom_l, mom_s = base_scores['momentum']
            exec_l, exec_s = base_scores['execution']
            risk_l, risk_s = base_scores['risk']
        else:
            # Optimization: Only process the recent window to avoid O(N^2) slowdown in backtests
            if df_macro is not None and len(df_macro) > 250:
                df_macro = df_macro.iloc[-250:]
            if df_entry is not None and len(df_entry) > 250:
                df_entry = df_entry.iloc[-250:]
            
            # 1. Obtener Scores de los 5 Módulos
            market_l, market_s = InstitutionalScorer.evaluate_market(df_macro)
            struct_l, struct_s = InstitutionalScorer.evaluate_structure(df_macro, current_price)
            mom_l, mom_s = InstitutionalScorer.evaluate_momentum(df_entry)
            exec_l, exec_s = InstitutionalScorer.evaluate_execution(df_entry, current_price, atr, params.get('vol_multiplier', 1.5))
            risk_l, risk_s = InstitutionalScorer.evaluate_risk(df_entry, current_price, atr, params)
            
            if getattr(settings, 'ENVIRONMENT', '') == 'BACKTEST' and ts is not None:
                DecisionEngine._cache[ts] = {
                    'market': (market_l, market_s),
                    'structure': (struct_l, struct_s),
                    'momentum': (mom_l, mom_s),
                    'execution': (exec_l, exec_s),
                    'risk': (risk_l, risk_s)
                }
        
        # 2. Cargar Pesos de settings.py
        weights = params.get('decision_weights', getattr(settings, 'DECISION_WEIGHTS', {
            'market': 0.22, 'structure': 0.20, 'momentum': 0.12, 'execution': 0.18, 'risk': 0.28
        }))
        
        # 3. Calcular Puntaje Ponderado LONG
        score_long = (
            market_l[0] * weights['market'] +
            struct_l[0] * weights['structure'] +
            mom_l[0] * weights['momentum'] +
            exec_l[0] * weights['execution'] +
            risk_l[0] * weights['risk']
        )
        conf_long = (
            market_l[1] * weights['market'] +
            struct_l[1] * weights['structure'] +
            mom_l[1] * weights['momentum'] +
            exec_l[1] * weights['execution'] +
            risk_l[1] * weights['risk']
        )
        
        # 4. Calcular Puntaje Ponderado SHORT
        score_short = (
            market_s[0] * weights['market'] +
            struct_s[0] * weights['structure'] +
            mom_s[0] * weights['momentum'] +
            exec_s[0] * weights['execution'] +
            risk_s[0] * weights['risk']
        )
        conf_short = (
            market_s[1] * weights['market'] +
            struct_s[1] * weights['structure'] +
            mom_s[1] * weights['momentum'] +
            exec_s[1] * weights['execution'] +
            risk_s[1] * weights['risk']
        )
        
        # Gating Logic (V2 Pura)
        current_utc_hour = int(df_entry['utc_hour'].iloc[-1]) if (df_entry is not None and 'utc_hour' in df_entry) else datetime.utcnow().hour
        vol_ratio = float(df_entry['volume'].iloc[-2] / df_entry['vol_sma'].iloc[-2]) if (df_entry is not None and 'vol_sma' in df_entry and df_entry['vol_sma'].iloc[-2] > 0) else 1.0
        market_regime = str(MarketRegimeDetector.evaluate(df_macro).get('estado', 'SIDEWAYS')) if df_macro is not None else "SIDEWAYS"

        # 5. Elegir la Dirección Dominante
        direction = "NONE"
        best_score = 0.0
        best_conf = 0.0
        
        if score_long > score_short and score_long > 50:
            direction = "LONG"
            best_score = score_long
            best_conf = conf_long
        elif score_short > score_long and score_short > 50:
            direction = "SHORT"
            best_score = score_short
            best_conf = conf_short
            
        research_data = struct_l[2] if len(struct_l) > 2 else {}
        
        return {
            "direction": direction,
            "score": best_score,
            "confidence": best_conf,
            "breakdown": {
                "market": {"long": market_l, "short": market_s},
                "structure": {"long": struct_l, "short": struct_s},
                "momentum": {"long": mom_l, "short": mom_s},
                "execution": {"long": exec_l, "short": exec_s},
                "risk": {"long": risk_l, "short": risk_s},
                "consensus_alternativo": research_data.get('consensus', 'SIDEWAYS'),
                "detected_swing_highs": research_data.get('detected_swing_highs', []),
                "detected_swing_lows": research_data.get('detected_swing_lows', [])
            },
            "weights": weights,
            "raw_features": {
                "utc_hour": current_utc_hour,
                "vol_ratio": vol_ratio,
                "volatility_pct": float(atr / current_price) if current_price > 0 else 0.0,
                "adx": float(df_entry['adx'].iloc[-1]) if (df_entry is not None and 'adx' in df_entry and not pd.isna(df_entry['adx'].iloc[-1])) else 20.0,
                "rsi": float(df_entry['rsi'].iloc[-1]) if (df_entry is not None and 'rsi' in df_entry and not pd.isna(df_entry['rsi'].iloc[-1])) else 50.0,
                "market_regime": market_regime
            }
        }
