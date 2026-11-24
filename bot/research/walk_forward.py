import pandas as pd
from bot.core.trade_logger import logger
from bot.config import settings
from bot.backtest.engine import BacktestEngine
from bot.backtest.metrics import calculate_metrics
from bot.research.experiment_manager import ExperimentManager
from bot.core.profiler import profile_method
import traceback

class WalkForwardAnalyzer:
    """
    Ejecuta simulaciones en múltiples ventanas de tiempo deslizantes
    para evaluar la estabilidad de una estrategia fuera de muestra (Out of Sample - OOS).
    """
    def __init__(self, historical_dfs: dict, strategy_name: str):
        self.historical_dfs = historical_dfs
        self.strategy_name = strategy_name
        self.exp_manager = ExperimentManager()
        
    def _create_windows(self, start_date: str, end_date: str, train_days: int, val_days: int, test_days: int, step_days: int) -> list:
        start_ts = pd.to_datetime(start_date)
        end_ts = pd.to_datetime(end_date)
        
        windows = []
        current_start = start_ts
        
        while True:
            train_end = current_start + pd.Timedelta(days=train_days)
            val_end = train_end + pd.Timedelta(days=val_days)
            test_end = val_end + pd.Timedelta(days=test_days)
            
            if test_end > end_ts:
                break
                
            windows.append({
                "train": (current_start, train_end),
                "validation": (train_end, val_end),
                "test": (val_end, test_end) # Out of sample
            })
            
            current_start += pd.Timedelta(days=step_days)
            
        return windows

    def _filter_df_by_date(self, df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        return df[(df['timestamp'] >= start) & (df['timestamp'] < end)].copy()

    @profile_method(category="Research Lab")
    def execute_walk_forward(self, start_date: str, end_date: str, train_days: int, val_days: int, test_days: int, step_days: int):
        logger.info(f"🚶 Iniciando Walk Forward Analysis | Strategy: {self.strategy_name}")
        
        windows = self._create_windows(start_date, end_date, train_days, val_days, test_days, step_days)
        if not windows:
            logger.error("El rango de fechas y los parámetros de ventana no generaron ninguna partición.")
            return None
            
        logger.info(f"Se evaluarán {len(windows)} ventanas temporales deslizantes.")
        
        # Registrar experimento Padre
        exp_id = self.exp_manager.start_experiment(
            name=f"WFA_{self.strategy_name}",
            strategy=self.strategy_name,
            description=f"Walk Forward: TR={train_days}d VAL={val_days}d TE={test_days}d",
            tags=["walk_forward", "robustness", self.strategy_name.lower()]
        )
        
        results = []
        
        for i, window in enumerate(windows):
            logger.info(f"--- Ventana {i+1}/{len(windows)} ---")
            logger.info(f"   [Train] {window['train'][0].date()} a {window['train'][1].date()}")
            logger.info(f"   [Val]   {window['validation'][0].date()} a {window['validation'][1].date()}")
            logger.info(f"   [Test]  {window['test'][0].date()} a {window['test'][1].date()} (Out of Sample)")
            
            # Ejecutar In-Sample (Train + Validation sumados por simplicidad, o separados si hay optimización)
            # Como aún no optimizamos hiperparámetros dentro de WF en este paso, evaluamos el Test (OOS) vs Train (IS)
            # para ver degradación.
            
            # Data Train
            dfs_train = {tf: self._filter_df_by_date(df, window['train'][0], window['train'][1]) for tf, df in self.historical_dfs.items()}
            # Data Test (Out of Sample)
            dfs_test = {tf: self._filter_df_by_date(df, window['test'][0], window['test'][1]) for tf, df in self.historical_dfs.items()}
            
            try:
                # Run In-Sample
                engine_is = BacktestEngine(dfs_train)
                history_is = engine_is.run()
                metrics_is = calculate_metrics(history_is, settings.BACKTEST_PARAMS['initial_balance'])
                
                # Run Out-Of-Sample
                engine_oos = BacktestEngine(dfs_test)
                history_oos = engine_oos.run()
                metrics_oos = calculate_metrics(history_oos, settings.BACKTEST_PARAMS['initial_balance'])
                
                window_data = {
                    "window_index": i,
                    "dates": {
                        "is_start": str(window['train'][0]),
                        "is_end": str(window['train'][1]),
                        "oos_start": str(window['test'][0]),
                        "oos_end": str(window['test'][1])
                    },
                    "metrics_in_sample": metrics_is,
                    "metrics_out_of_sample": metrics_oos
                }
                
                results.append(window_data)
                
                # Loggear el run de la ventana (Out of sample como representativo)
                if metrics_oos:
                    self.exp_manager.log_run(
                        run_type="walk_forward_window",
                        run_parameters=settings.STRATEGY_PARAMS[self.strategy_name],
                        history=history_oos,
                        metrics=metrics_oos,
                        extra_data=window_data
                    )
                
            except Exception as e:
                logger.error(f"Error en ventana {i+1}: {e}")
                traceback.print_exc()
                
        logger.info(f"✅ Walk Forward completado. Experimento guardado: {exp_id}")
        return results
