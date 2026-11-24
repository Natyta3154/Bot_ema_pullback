"""
Módulo: mock_market_data.py
=================================================
Mock de datos de mercado para el motor de Backtesting.
"""
import pandas as pd
from typing import Dict, Optional

class MockMarketData:
    def __init__(self, full_data: Dict[str, pd.DataFrame]):
        """
        full_data: {'1h': df_1h, '15m': df_15m}
        """
        self.full_data = full_data
        self.current_timestamp: Optional[pd.Timestamp] = None
        
        # Calcular duraciones para evitar Look-Ahead Bias
        self.deltas = {}
        for tf in full_data.keys():
            if 'm' in tf:
                self.deltas[tf] = pd.Timedelta(minutes=int(tf.replace('m', '')))
            elif 'h' in tf:
                self.deltas[tf] = pd.Timedelta(hours=int(tf.replace('h', '')))
            elif 'd' in tf:
                self.deltas[tf] = pd.Timedelta(days=int(tf.replace('d', '')))

    def fetch_ohlcv(self, timeframe: str) -> Optional[pd.DataFrame]:
        """
        Retorna el DataFrame truncado hasta 'current_timestamp'.
        Solo se devuelven velas que ya CERRARON completamente antes o en el 'current_timestamp'.
        """
        if timeframe in self.full_data:
            df = self.full_data[timeframe]
            if self.current_timestamp is not None:
                delta = self.deltas.get(timeframe, pd.Timedelta(minutes=15))
                # La vela con apertura T cierra en T + delta.
                # Para ser visible, T + delta <= current_timestamp -> T <= current_timestamp - delta
                target_ts = self.current_timestamp - delta
                
                idx = df['timestamp'].searchsorted(target_ts, side='right')
                return df.iloc[:idx]
            else:
                return pd.DataFrame()
        return None
