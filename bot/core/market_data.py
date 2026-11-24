"""
Módulo: market_data.py
=================================================
Gestor de datos de mercado. Encargado de descargar y estructurar los precios y volúmenes.
"""
import pandas as pd
from typing import Optional
from bot.core.order import OrderManager
from bot.core.trade_logger import logger

class MarketDataManager:
    def __init__(self, order_manager: OrderManager):
        self.order_manager = order_manager

    def fetch_ohlcv(self, timeframe: str, limit: int = 250) -> Optional[pd.DataFrame]:
        try:
            ohlcv = self.order_manager.client.fetch_ohlcv(self.order_manager.symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp_dt'] = pd.to_datetime(df['timestamp'], unit='ms')
            from bot.config import settings
            if settings.ENVIRONMENT != "BACKTEST" and len(df) > 1:
                df = df.iloc[:-1].copy()
            return df
        except Exception as e:
            logger.error(f"Error al obtener datos OHLCV de {timeframe}: {e}")
            return None
