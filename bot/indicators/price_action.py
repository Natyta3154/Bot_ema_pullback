"""
Módulo: price_action.py
=================================================
Módulo de análisis de Price Action (Acción del Precio). Identifica patrones de velas y estructuras de mercado.
"""
import pandas as pd
import numpy as np
from typing import List, Dict
from bot.core.profiler import profile_method
from bot.indicators.atr import calculate_atr

@profile_method(category="Indicators")
def find_pivots(df: pd.DataFrame, left_bars: int = 5, right_bars: int = 5, atr_threshold: float = 0.5) -> pd.DataFrame:
    """
    Identifica Swing Highs y Swing Lows (pivotes).
    Retorna el mismo DataFrame con columnas booleanas 'is_pivot_high' y 'is_pivot_low'.
    Aplica un filtro de volatilidad (ATR) para evitar clasificar ruido como pivote.
    """
    df = df.copy()
    df['is_pivot_high'] = False
    df['is_pivot_low'] = False

    # Calcular ATR temporal si no existe
    if 'atr' not in df.columns:
        temp_atr = calculate_atr(df, 14)
    else:
        temp_atr = df['atr']

    # Vectorización para O(log N) o O(1) iterativo
    bwd_high = df['high'].rolling(window=left_bars + 1, min_periods=1).max()
    bwd_low = df['low'].rolling(window=left_bars + 1, min_periods=1).min()
    
    # fwd requiere invertir, calcular y volver a invertir
    fwd_high = df['high'].iloc[::-1].rolling(window=right_bars + 1, min_periods=1).max().iloc[::-1]
    fwd_low = df['low'].iloc[::-1].rolling(window=right_bars + 1, min_periods=1).min().iloc[::-1]
    
    # Filtro fractal base
    is_max = (df['high'] >= bwd_high) & (df['high'] >= fwd_high)
    is_min = (df['low'] <= bwd_low) & (df['low'] <= fwd_low)
    
    # Filtro de volatilidad (ATR): el swing debe ser significativo respecto al mínimo/máximo local
    local_min_for_high = df['low'].rolling(window=left_bars + right_bars + 1, min_periods=1, center=True).min()
    local_max_for_low = df['high'].rolling(window=left_bars + right_bars + 1, min_periods=1, center=True).max()
    
    df['is_pivot_high'] = is_max & ((df['high'] - local_min_for_high) >= (temp_atr * atr_threshold))
    df['is_pivot_low'] = is_min & ((local_max_for_low - df['low']) >= (temp_atr * atr_threshold))
    
    # Anular los bordes exactamente como lo hacía el bucle original
    if left_bars > 0 and len(df) > left_bars:
        df.loc[df.index[:left_bars], 'is_pivot_high'] = False
        df.loc[df.index[:left_bars], 'is_pivot_low'] = False
        
    if right_bars > 0 and len(df) > right_bars:
        df.loc[df.index[-right_bars:], 'is_pivot_high'] = False
        df.loc[df.index[-right_bars:], 'is_pivot_low'] = False
        
    return df

@profile_method(category="Indicators")
def detect_market_structure(df: pd.DataFrame) -> str:
    """
    Busca los últimos pivotes para definir la estructura de mercado.
    Retorna "UPTREND", "DOWNTREND", o "SIDEWAYS".
    Incorpora Propuesta C: Híbrido Institucional (HH/HL + BOS apoyado por Market Regime).
    """
    highs = df[df['is_pivot_high']]['high'].values
    lows = df[df['is_pivot_low']]['low'].values

    if len(highs) < 2 or len(lows) < 2:
        return "SIDEWAYS"

    last_h1, last_h2 = highs[-1], highs[-2]
    last_l1, last_l2 = lows[-1], lows[-2]
    current_price = df['close'].iloc[-1]

    # Confirmación clásica (Lagging)
    if last_h1 > last_h2 and last_l1 > last_l2:
        return "UPTREND"
    
    if last_h1 < last_h2 and last_l1 < last_l2:
        return "DOWNTREND"

    # PROPUESTA C: Híbrido Institucional (Leading BOS + Market Regime)
    from bot.indicators.market_regime import MarketRegimeDetector
    regime = MarketRegimeDetector.evaluate(df)
    estado = regime.get('estado', '')
    
    if current_price > last_h1:
        if "TREND UP" in estado or "PARABOLIC" in estado or "WEAK TREND" in estado:
            return "UPTREND"
            
    if current_price < last_l1:
        if "PANIC" in estado or "DISTRIBUTION" in estado:
            return "DOWNTREND"

    return "SIDEWAYS"

@profile_method(category="Indicators")
def detect_support_resistance(df: pd.DataFrame, atr: float, cluster_threshold_atr: float = 0.5) -> Dict[str, List[float]]:
    """
    Encuentra zonas de S/R agrupando pivotes recientes que estén cerca entre sí.
    'atr' es el valor actual del ATR para definir la tolerancia del clúster.
    """
    threshold = atr * cluster_threshold_atr
    
    if 'is_pivot_high' not in df.columns or 'is_pivot_low' not in df.columns:
        return {"supports": [], "resistances": []}
        
    recent_pivots = df[(df['is_pivot_high'] == True) | (df['is_pivot_low'] == True)].tail(20)
    
    if recent_pivots.empty:
        return {"supports": [], "resistances": []}
        
    prices = recent_pivots['high'].combine_first(recent_pivots['low']).values
    prices = np.sort(prices)

    zones = []
    if len(prices) == 0:
        return {"supports": [], "resistances": []}

    current_cluster = [prices[0]]
    for p in prices[1:]:
        if p - np.mean(current_cluster) <= threshold:
            current_cluster.append(p)
        else:
            zones.append(np.mean(current_cluster))
            current_cluster = [p]
    zones.append(np.mean(current_cluster))

    current_price = df['close'].iloc[-1]
    supports = [z for z in zones if z < current_price]
    resistances = [z for z in zones if z > current_price]

    return {
        "supports": sorted(supports, reverse=True),
        "resistances": sorted(resistances)
    }
