"""
Módulo: data_loader.py
=================================================
Módulo data_loader.py del sistema Backtesting.
"""
import os
import ccxt
import pandas as pd
from datetime import datetime
import time
from bot.core.trade_logger import logger
from bot.config import settings
from bot.core.profiler import profile_method

class DataLoader:
    def __init__(self, symbol: str = "BTC/USDT"):
        self.symbol = symbol
        self.cache_dir = os.path.join(os.path.dirname(__file__), 'cache')
        os.makedirs(self.cache_dir, exist_ok=True)
        self.exchange = ccxt.binance({'enableRateLimit': True})
        
    def _get_filename(self, timeframe: str, start: str, end: str) -> str:
        s = start.replace("-", "")
        e = end.replace("-", "")
        return os.path.join(self.cache_dir, f"{self.symbol.replace('/', '')}_{timeframe}_{s}_{e}.csv")

    @profile_method(category="Data")
    def fetch_data(self, timeframe: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Descarga o carga desde caché los datos históricos."""
        filename = self._get_filename(timeframe, start_date, end_date)
        if os.path.exists(filename):
            logger.info(f"Cargando {timeframe} desde caché local: {filename}")
            df = pd.read_csv(filename, parse_dates=['timestamp'])
            return df
            
        logger.info(f"Descargando {timeframe} desde Binance (puede tardar unos minutos)...")
        start_ts = self.exchange.parse8601(start_date + "T00:00:00Z")
        end_ts = self.exchange.parse8601(end_date + "T23:59:59Z")
        
        all_ohlcv = []
        current_ts = start_ts
        
        while current_ts < end_ts:
            try:
                ohlcv = self.exchange.fetch_ohlcv(self.symbol, timeframe, since=current_ts, limit=1500)
                if not ohlcv:
                    break
                all_ohlcv.extend(ohlcv)
                current_ts = ohlcv[-1][0] + 1
                time.sleep(0.2) # Respetar rate limit
            except Exception as e:
                logger.error(f"Error descargando datos: {e}")
                time.sleep(5)
                
        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # Filtrar exactamente hasta el end_date
        end_dt = pd.to_datetime(end_date + " 23:59:59")
        df = df[df['timestamp'] <= end_dt]
        df.drop_duplicates(subset=['timestamp'], inplace=True)
        df.reset_index(drop=True, inplace=True)
        
        df.to_csv(filename, index=False)
        logger.info(f"Guardado {timeframe} en caché: {len(df)} velas.")
        
        return df
