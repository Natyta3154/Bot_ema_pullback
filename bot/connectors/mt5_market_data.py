"""
Módulo: mt5_market_data.py
=================================================
Gestor de datos de mercado para MetaTrader 5 (IC Markets).
Descarga y estructura velas OHLCV en el mismo formato compatible con las estrategias del bot.
"""
import pandas as pd
from typing import Optional
import MetaTrader5 as mt5
from bot.core.trade_logger import logger


class MT5MarketDataManager:
    def __init__(self, order_manager):
        self.order_manager = order_manager
        self.timeframe_map = {
            '1m': mt5.TIMEFRAME_M1,
            '5m': mt5.TIMEFRAME_M5,
            '15m': mt5.TIMEFRAME_M15,
            '30m': mt5.TIMEFRAME_M30,
            '1h': mt5.TIMEFRAME_H1,
            '4h': mt5.TIMEFRAME_H4,
            '1d': mt5.TIMEFRAME_D1,
        }

    def fetch_ohlcv(self, timeframe: str, limit: int = 250) -> Optional[pd.DataFrame]:
        try:
            mt5_tf = self.timeframe_map.get(timeframe.lower())
            if mt5_tf is None:
                logger.error(f"[MT5] Timeframe no soportado: {timeframe}")
                return None

            # start_pos=1 toma únicamente velas cerradas (la pos 0 es la vela abierta en formación)
            rates = mt5.copy_rates_from_pos(self.order_manager.symbol, mt5_tf, 1, limit)
            if rates is None or len(rates) == 0:
                logger.warning(f"[MT5] No se recibieron datos para {self.order_manager.symbol} ({timeframe}): {mt5.last_error()}")
                return None

            df = pd.DataFrame(rates)
            # En Forex/CFDs típicamente se usa tick_volume salvo que el broker provea real_volume
            vol_col = 'real_volume' if ('real_volume' in df.columns and df['real_volume'].sum() > 0) else 'tick_volume'
            df['volume'] = df[vol_col].astype(float)
            df['timestamp'] = df['time'] * 1000  # Formato en milisegundos idéntico a Binance/ccxt
            df['timestamp_dt'] = pd.to_datetime(df['time'], unit='s')

            # Retornar estructura idéntica a MarketDataManager de Binance
            return df[['timestamp', 'open', 'high', 'low', 'close', 'volume', 'timestamp_dt']]
        except Exception as e:
            logger.error(f"[MT5] Error al obtener datos OHLCV de {timeframe}: {e}")
            return None
