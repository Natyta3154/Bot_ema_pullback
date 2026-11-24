import copy
from bot.core.trade_logger import logger
from bot.config import settings
from bot.backtest.engine import BacktestEngine
from bot.backtest.metrics import calculate_metrics
from bot.research.experiment_manager import ExperimentManager
from bot.core.profiler import profile_method

class StressTester:
    """
    Ejecuta simulaciones inyectando condiciones adversas progresivas 
    para evaluar la resiliencia de la estrategia.
    """
    def __init__(self, historical_dfs: dict, strategy_name: str):
        self.historical_dfs = historical_dfs
        self.strategy_name = strategy_name
        self.exp_manager = ExperimentManager()
        
    @profile_method(category="Research Lab")
    def execute_stress_test(self):
        logger.info(f"💥 Iniciando Stress Testing | Estrategia: {self.strategy_name}")
        
        # Registrar experimento Padre
        exp_id = self.exp_manager.start_experiment(
            name=f"STRESS_{self.strategy_name}",
            strategy=self.strategy_name,
            description="Stress Testing con condiciones adversas progresivas",
            tags=["stress", "robustness", self.strategy_name.lower()]
        )
        
        # Definir los escenarios de estrés (modificadores sobre los settings base)
        base_comm = settings.BACKTEST_PARAMS.get('commission_pct', 0.0004)
        base_slip = settings.BACKTEST_PARAMS.get('slippage_pct', 0.0005)
        
        scenarios = [
            {"name": "1. Baseline (Normal)", "comm": base_comm, "slip": base_slip},
            {"name": "2. High Slippage (Flash Crash)", "comm": base_comm, "slip": base_slip * 3},
            {"name": "3. High Fees (Tier 0)", "comm": base_comm * 2, "slip": base_slip},
            {"name": "4. Nightmare (Altos Fees + Alto Slippage)", "comm": base_comm * 2, "slip": base_slip * 3},
        ]
        
        results = []
        original_params = copy.deepcopy(settings.BACKTEST_PARAMS)
        
        for scenario in scenarios:
            logger.info(f"Ejecutando escenario: {scenario['name']}")
            
            # Aplicar configuración de estrés
            settings.BACKTEST_PARAMS['commission_pct'] = scenario['comm']
            settings.BACKTEST_PARAMS['slippage_pct'] = scenario['slip']
            
            try:
                engine = BacktestEngine(self.historical_dfs)
                history = engine.run()
                metrics = calculate_metrics(history, settings.BACKTEST_PARAMS['initial_balance'])
                
                res = {
                    "scenario": scenario['name'],
                    "commission": scenario['comm'],
                    "slippage": scenario['slip'],
                    "metrics": metrics
                }
                results.append(res)
                
                if metrics:
                    self.exp_manager.log_run(
                        run_type="stress_test",
                        run_parameters={"scenario": scenario['name'], "comm": scenario['comm'], "slip": scenario['slip']},
                        history=history,
                        metrics=metrics
                    )
                    
            except Exception as e:
                logger.error(f"Error en escenario {scenario['name']}: {e}")
                
        # Restaurar configuración original
        settings.BACKTEST_PARAMS = original_params
        
        logger.info("=== RESUMEN DE STRESS TESTING ===")
        for res in results:
            m = res.get('metrics')
            if m:
                logger.info(f"{res['scenario']} -> Retorno: {m.get('Total Return (%)', 0)}% | Max DD: {m.get('Max Drawdown (%)', 0)}% | Sharpe: {m.get('Sharpe Ratio', 0)}")
            else:
                logger.warning(f"{res['scenario']} -> Sin operaciones.")
                
        return results
