"""
Módulo: market_regime.py
=================================================
Módulo market_regime.py del sistema Indicadores.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any

class MarketRegimeDetector:
    """
    Phase 8.11 - Automatic Market Regime Detector (Institutional Grade)
    Física del Precio: Hurst Exponent, Fractal Dimension, Volatility, Directionality.
    """
    
    @staticmethod
    def _calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df['high']
        low = df['low']
        close = df['close'].shift(1)
        tr = pd.concat([high - low, (high - close).abs(), (low - close).abs()], axis=1).max(axis=1)
        return tr.rolling(period).mean()
        
    @staticmethod
    def _calc_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df['high']
        low = df['low']
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        
        plus_dm = pd.Series(plus_dm, index=df.index).rolling(period).mean()
        minus_dm = pd.Series(minus_dm, index=df.index).rolling(period).mean()
        
        tr = MarketRegimeDetector._calc_atr(df, 1).rolling(period).mean()
        
        plus_di = 100 * (plus_dm / tr)
        minus_di = 100 * (minus_dm / tr)
        
        dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10))
        adx = dx.rolling(period).mean()
        return adx

    @staticmethod
    def _calc_hurst(df: pd.DataFrame, lags: int = 20) -> float:
        """
        Estimador simplificado del exponente de Hurst usando la varianza de los retornos logarítmicos.
        H > 0.5: Persistencia (Tendencia)
        H < 0.5: Anti-persistencia (Reversión a la media / Choppy)
        """
        if len(df) < 50: return 0.5
        prices = df['close'].values[-100:] # Tomar últimos 100
        lags_arr = range(2, lags)
        tau = [np.sqrt(np.std(np.subtract(prices[lag:], prices[:-lag]))) for lag in lags_arr]
        poly = np.polyfit(np.log(lags_arr), np.log(tau), 1)
        hurst = poly[0] * 2.0
        return float(np.clip(hurst, 0.0, 1.0))

    @staticmethod
    def _calc_choppiness(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """ Proxy para Fractal Dimension (100 = puro ruido, 0 = pura tendencia lineal) """
        tr = MarketRegimeDetector._calc_atr(df, 1)
        atr_sum = tr.rolling(period).sum()
        max_high = df['high'].rolling(period).max()
        min_low = df['low'].rolling(period).min()
        
        chop = 100 * np.log10(atr_sum / (max_high - min_low + 1e-10)) / np.log10(period)
        return chop

    @classmethod
    def evaluate(cls, df: pd.DataFrame) -> Dict[str, Any]:
        if df is None or len(df) < 50:
            return cls._empty_result()
            
        df = df.copy()
        
        # 1. Cálculos de indicadores
        df['ATR'] = cls._calc_atr(df, 14)
        df['ADX'] = cls._calc_adx(df, 14)
        df['CHOP'] = cls._calc_choppiness(df, 14)
        
        df['SMA20'] = df['close'].rolling(20).mean()
        df['EMA20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['STD20'] = df['close'].rolling(20).std()
        df['BB_WIDTH'] = (df['STD20'] * 4) / df['SMA20']
        
        df['HIST_VOL'] = np.log(df['close'] / df['close'].shift(1)).rolling(20).std() * np.sqrt(365 * 24) # asumiendo horas

        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        adx = last['ADX']
        atr = last['ATR']
        atr_trend = "creciendo" if last['ATR'] > prev['ATR'] else "contrayéndose"
        bb_width = last['BB_WIDTH']
        bb_trend = "expandiéndose" if last['BB_WIDTH'] > prev['BB_WIDTH'] else "comprimiéndose"
        
        ema_slope = (last['EMA20'] - prev['EMA20']) / prev['EMA20']
        sma_slope = (last['SMA20'] - prev['SMA20']) / prev['SMA20']
        ema_slope_str = "positiva" if ema_slope > 0 else "negativa"
        
        hurst = cls._calc_hurst(df)
        chop = last['CHOP']
        
        # 2. Motor Heurístico de Clasificación (Scoring System)
        scores = {
            "STRONG TREND UP": 0, "TREND UP": 0, "WEAK TREND": 0, 
            "SIDEWAYS": 0, "RANGE": 0, "VOLATILE": 0, 
            "ACCUMULATION": 0, "DISTRIBUTION": 0, "PANIC": 0, "PARABOLIC": 0
        }
        
        # Evaluar fuerza
        if adx > 40:
            scores["STRONG TREND UP"] += 1
            scores["PARABOLIC"] += 1
        elif adx > 25:
            scores["TREND UP"] += 1
        elif adx < 20:
            scores["SIDEWAYS"] += 1
            scores["RANGE"] += 1
            scores["ACCUMULATION"] += 1
            
        # Evaluar persistencia (Hurst y Chop)
        if hurst > 0.6 and chop < 38:
            scores["STRONG TREND UP"] += 2
            scores["PARABOLIC"] += 1
        elif hurst < 0.45 or chop > 61.8:
            scores["SIDEWAYS"] += 2
            scores["RANGE"] += 2
            
        # Evaluar volatilidad (ATR y Bollinger)
        if bb_trend == "expandiéndose" and atr_trend == "creciendo":
            scores["VOLATILE"] += 2
            scores["PANIC"] += 1 if ema_slope < -0.005 else 0
            scores["PARABOLIC"] += 1 if ema_slope > 0.005 else 0
        elif bb_trend == "comprimiéndose":
            scores["ACCUMULATION"] += 1
            scores["DISTRIBUTION"] += 1
            
        # Evaluar dirección
        if ema_slope > 0.001 and sma_slope > 0.001:
            scores["TREND UP"] += 2
            scores["STRONG TREND UP"] += 1
        elif ema_slope < -0.001 and sma_slope < -0.001:
            scores["PANIC"] += 2
            
        # Modificador base de dirección
        if ema_slope > 0:
            scores["WEAK TREND"] += 1
            scores["ACCUMULATION"] += 1
        else:
            scores["DISTRIBUTION"] += 1
            
        # Identificar ganador
        max_score = max(scores.values())
        if max_score == 0:
            regime = "SIDEWAYS"
            confidence = 50.0
        else:
            # Obtener el régimen con mayor puntaje (en caso de empate, el primero)
            regime = [k for k, v in scores.items() if v == max_score][0]
            # Confianza heurística basada en cuántos puntos sacó sobre el máximo posible de una tesis (aprox 6)
            confidence = min(100.0, (max_score / 6.0) * 100.0)
            
        # Si es volátil pero direccional, juntar etiquetas
        if scores["VOLATILE"] >= 2 and regime in ["TREND UP", "STRONG TREND UP"]:
            regime = f"VOLATILE {regime}"
            
        # 3. Explicación Narrativa
        explanation = [
            f"ADX = {adx:.1f}",
            f"ATR {atr_trend}",
            f"Pendiente EMA {ema_slope_str}",
            f"Bollinger {bb_trend}",
            f"Hurst = {hurst:.2f}",
            f"Fractal Dim = {chop:.1f}"
        ]
        
        # 4. Conclusión Orientada a Breakout
        conclusion = ""
        if "TREND" in regime or "PARABOLIC" in regime:
            conclusion = "Mercado direccional apto para Breakout."
        elif "SIDEWAYS" in regime or "RANGE" in regime or "ACCUMULATION" in regime or "DISTRIBUTION" in regime:
            conclusion = "Mercado hostil para Breakout (alto riesgo de falsos rompimientos)."
        else:
            conclusion = "Entorno altamente inestable o en pánico. Precaución extrema."

        return {
            "estado": regime,
            "confianza": confidence,
            "explicacion": explanation,
            "conclusion": conclusion
        }

    @classmethod
    def _empty_result(cls):
        return {
            "estado": "UNKNOWN",
            "confianza": 0.0,
            "explicacion": ["Datos insuficientes"],
            "conclusion": "No se puede determinar."
        }
