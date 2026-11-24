"""
Módulo: rsi.py
=================================================
Módulo rsi.py del sistema Indicadores.
"""
import pandas as pd

def calculate_rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """Calcula el Índice de Fuerza Relativa (RSI)."""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))
