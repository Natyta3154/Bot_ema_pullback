"""
Módulo: atr.py
=================================================
Módulo atr.py del sistema Indicadores.
"""
import pandas as pd
import numpy as np
from bot.core.profiler import profile_method

@profile_method(category="Indicators")
def calculate_atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Calcula el Average True Range (ATR)."""
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    
    # np.maximum es órdenes de magnitud más rápido que pd.concat
    true_range = np.maximum(high_low, np.maximum(high_close, low_close))
    return true_range.rolling(window).mean()
