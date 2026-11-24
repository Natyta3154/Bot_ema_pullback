from bot.research.db_manager import DatabaseManager
from bot.core.trade_logger import logger
from bot.config import settings

class ExperimentManager:
    """
    Gestiona el ciclo de vida de los experimentos y registra automáticamente todas las corridas
    utilizando la Research Database (DatabaseManager).
    """
    def __init__(self):
        self.db = DatabaseManager()
        self.current_experiment_id = None
        
    def start_experiment(self, name: str, strategy: str, description: str = "", tags: list = None) -> str:
        """
        Inicializa un nuevo Experimento Principal en el laboratorio.
        """
        exp_id = self.db.generate_id(prefix=f"EXP_{name.upper()}")
        
        metadata = {
            "name": name,
            "strategy": strategy,
            "description": description,
            "environment": settings.ENVIRONMENT,
            "backtest_params": settings.BACKTEST_PARAMS,
            "global_strategy_params": settings.STRATEGY_PARAMS.get(strategy, {})
        }
        
        self.current_experiment_id = self.db.save_experiment(exp_id, metadata, tags)
        logger.info(f"🧪 Experimento Iniciado: {self.current_experiment_id} | Tags: {tags}")
        return self.current_experiment_id
        
    def log_run(self, run_type: str, run_parameters: dict, history: list, metrics: dict, extra_data: dict = None):
        """
        Registra una ejecución individual (Run) dentro del Experimento actual.
        run_type puede ser 'single_backtest', 'grid_iteration', 'walk_forward_window', 'portfolio_asset', 'stress_test'.
        """
        if not self.current_experiment_id:
            logger.error("No hay un experimento activo. Llama a start_experiment() primero.")
            return None
            
        run_id = self.db.generate_id(prefix="RUN")
        
        run_data = {
            "parameters": run_parameters,
            "metrics": metrics,
            "history_summary": {
                "total_trades": len(history),
                # No guardamos todo el array history en el json resumen si es muy grande, 
                # pero para este proyecto guardaremos la lista completa para poder plotear
                "trades": history 
            }
        }
        
        if extra_data:
            run_data["extra"] = extra_data
            
        success = self.db.save_run(self.current_experiment_id, run_id, run_data, run_type)
        if success:
            logger.info(f"   └── 📝 Run Registrado: {run_id} ({run_type}) | Return: {metrics.get('Total Return (%)', 0)}% | Sharpe: {metrics.get('Sharpe Ratio', 0)}")
            return run_id
        return None
