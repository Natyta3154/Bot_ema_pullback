"""
Módulo: optimizer.py
=================================================
Módulo optimizer.py del sistema Backtesting.
"""
import itertools
from bot.core.trade_logger import logger
from bot.config import settings
from bot.backtest.engine import BacktestEngine
from bot.backtest.metrics import calculate_metrics
from bot.core.profiler import profile_method

class GridOptimizer:
    """
    Motor simple de Grid Search para optimizar parámetros.
    El método real requeriría ejecutar un BacktestEngine entero en cada iteración.
    (Implementación preparada para futuras expansiones asíncronas / multiprocesamiento).
    """
    def __init__(self, strategy_name: str, param_grid: dict):
        self.strategy_name = strategy_name
        self.param_grid = param_grid
        
    def _generate_combinations(self):
        keys = self.param_grid.keys()
        values = (self.param_grid[key] for key in keys)
        for combination in itertools.product(*values):
            yield dict(zip(keys, combination))

    @profile_method(category="Research Lab")
    def run_optimization(self, historical_dfs: dict) -> dict:
        logger.info(f"⚙️ Iniciando Optimización (Grid Search) para {self.strategy_name}")
        
        best_sharpe = -999
        best_params = None
        
        # Iterar combinaciones (pseudo-código de estructura)
        # Import local para evitar ciclos
        
        for params in self._generate_combinations():
            # Inyectar configuración temporal
            original_params = settings.STRATEGY_PARAMS[self.strategy_name].copy()
            settings.STRATEGY_PARAMS[self.strategy_name].update(params)
            
            # Correr engine
            engine = BacktestEngine(historical_dfs)
            history = engine.run()
            
            # Medir
            metrics = calculate_metrics(history, settings.BACKTEST_PARAMS['initial_balance'])
            if metrics:
                sharpe = metrics.get('Sharpe Ratio', 0)
                if sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_params = params
                    
            # Restaurar originales
            settings.STRATEGY_PARAMS[self.strategy_name] = original_params
            
        logger.info(f"✅ Optimización finalizada. Mejor Sharpe: {best_sharpe}")
        logger.info(f"Mejores Parámetros: {best_params}")
        return best_params
