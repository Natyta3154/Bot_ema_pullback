"""
Módulo: ema.py
=================================================
Módulo ema.py del sistema Indicadores.
"""
import pandas as pd

def calculate_ema(series: pd.Series, window: int) -> pd.Series:
    """Calcula la Media Móvil Exponencial (EMA)."""
    return series.ewm(span=window, adjust=False).mean()
