"""
Módulo: engine.py
=================================================
Motor de Backtesting. Simula la ejecución de estrategias sobre datos históricos de forma aislada.
"""
import pandas as pd
from datetime import timedelta
from bot.core.engine import TradingEngine
from bot.backtest.mock_order_manager import MockOrderManager
from bot.backtest.mock_market_data import MockMarketData
from bot.core.trade_logger import logger
from bot.config import settings
import traceback

class BacktestEngine:
    """
    Wrapper del TradingEngine nativo que inyecta los administradores mockeados (MockOrderManager, MockMarketData).
    Itera tick por tick sobre los datos históricos y fuerza al TradingEngine a procesarlos.
    """
    def __init__(self, historical_dfs: dict):
        self.historical_dfs = historical_dfs
        self.mock_order_manager = MockOrderManager()
        self.mock_market_data = MockMarketData(historical_dfs)
        
        # Instanciar el motor real pero reemplazar sus dependencias
        self.engine = TradingEngine()
        self.engine.order_manager = self.mock_order_manager
        self.engine.market_data = self.mock_market_data
        
        # Inyectar referencia de position_manager en mock_order_manager para poder registrar features
        self.mock_order_manager.position_manager = self.engine.position_manager
        
        # Re-inyectar en los otros sub-managers
        self.engine.execution.order_manager = self.mock_order_manager
        self.engine.risk_manager.balance = self.mock_order_manager.get_balance() # Fallback for risk
        
        # Limpiar el estado de memoria del position manager para que empiece limpio
        self.engine.position_manager.reset_position()

    def _get_sorted_timestamps(self):
        """Obtiene la lista única de timestamps ordenados basándose en el timeframe base (ej. 15m)"""
        trigger_tf = settings.STRATEGY_PARAMS[settings.ACTIVE_STRATEGY].get('entry_tf', '15m')
        if trigger_tf not in self.historical_dfs:
            logger.error(f"Falta el timeframe de entrada {trigger_tf} en los datos.")
            return []
            
        df = self.historical_dfs[trigger_tf]
        return sorted(df['timestamp'].unique())

    def run(self):
        logger.info("==========================================================")
        logger.info(f"   INICIANDO BACKTEST | ESTRATEGIA: {settings.ACTIVE_STRATEGY}   ")
        logger.info("==========================================================")
        
        strategy_params = settings.STRATEGY_PARAMS[settings.ACTIVE_STRATEGY]
        trigger_tf = strategy_params.get('trigger_tf', '15m')
        
        if trigger_tf not in self.historical_dfs:
            logger.error(f"Falta {trigger_tf} en datos.")
            return None
            
        df_trigger = self.historical_dfs[trigger_tf].set_index('timestamp').sort_index()
        
        minutes = int(trigger_tf.replace('m', '')) if 'm' in trigger_tf else 60 * int(trigger_tf.replace('h', ''))
        trigger_delta = pd.Timedelta(minutes=minutes)
        
        # Iterar eficientemente con itertuples sin alocar diccionarios
        for row in df_trigger.itertuples():
            try:
                ts = row.Index
                high = row.high
                low = row.low
                
                # Momento de cierre de la vela (cuando la data se vuelve consultable lógicamente)
                ts_end = ts + trigger_delta
                
                # Avanzamos MarketData al momento FINAL de la vela
                self.mock_market_data.current_timestamp = ts_end
                
                # Las órdenes pendientes se cruzan *durante* esta vela
                ts_str = str(ts_end)
                self.mock_order_manager.process_candle(high, low, ts_str)
                
                # Forzar al TradingEngine a procesar nuevas señales asumiendo que estamos en ts_end
                self.engine.run_iteration()
                
            except Exception as e:
                print(e)
                traceback.print_exc()

        logger.info("🏁 Simulación de Backtest Finalizada.")
        return self.mock_order_manager.history
