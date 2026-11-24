"""
Módulo: volume.py
=================================================
Módulo volume.py del sistema Indicadores.
"""
import pandas as pd

def calculate_sma(series: pd.Series, window: int) -> pd.Series:
    """Calcula la Media Móvil Simple (SMA), usada para promediar volumen."""
    return series.rolling(window=window).mean()
