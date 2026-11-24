import pandas as pd
from bot.core.trade_logger import logger
from bot.config import settings
from bot.backtest.engine import BacktestEngine
from bot.backtest.metrics import calculate_metrics
from bot.backtest.data_loader import DataLoader
from bot.research.experiment_manager import ExperimentManager
from bot.core.profiler import profile_method
import traceback

class PortfolioTester:
    """
    Ejecuta una estrategia a través de múltiples activos de forma automática.
    """
    def __init__(self, assets: list, strategy_name: str):
        self.assets = assets
        self.strategy_name = strategy_name
        self.exp_manager = ExperimentManager()
        
    @profile_method(category="Research Lab")
    def run_portfolio(self):
        logger.info(f"💼 Iniciando Portfolio Testing | Activos: {self.assets} | Estrategia: {self.strategy_name}")
        
        # Registrar experimento Padre
        exp_id = self.exp_manager.start_experiment(
            name=f"PORTFOLIO_{self.strategy_name}",
            strategy=self.strategy_name,
            description=f"Portfolio Test en {len(self.assets)} activos",
            tags=["portfolio", "multi_asset", self.strategy_name.lower()]
        )
        
        results = {}
        all_histories = []
        
        start_date = settings.BACKTEST_PARAMS['start_date']
        end_date = settings.BACKTEST_PARAMS['end_date']
        initial_balance = settings.BACKTEST_PARAMS['initial_balance']
        
        tfs = [settings.STRATEGY_PARAMS[self.strategy_name].get('entry_tf', '15m'), 
               settings.STRATEGY_PARAMS[self.strategy_name].get('macro_tf', '1h')]
        tfs = list(set([tf for tf in tfs if tf]))
        
        for asset in self.assets:
            logger.info(f"▶️ Procesando activo: {asset}")
            try:
                # 1. Cargar datos específicos del activo
                loader = DataLoader(symbol=asset)
                dfs = {}
                for tf in tfs:
                    df = loader.fetch_data(tf, start_date, end_date)
                    if df is not None and not df.empty:
                        dfs[tf] = df
                        
                if not dfs:
                    logger.error(f"   ❌ No se pudieron cargar datos para {asset}.")
                    continue
                    
                # 2. Correr Backtest aislado para el activo
                engine = BacktestEngine(dfs)
                history = engine.run()
                
                # Para diferenciar en los logs unificados, marcamos el activo en los trades
                for trade in history:
                    trade['asset'] = asset
                    
                all_histories.extend(history)
                
                # 3. Métricas individuales
                metrics = calculate_metrics(history, initial_balance)
                if metrics:
                    results[asset] = metrics
                    # Registrar Run por activo
                    self.exp_manager.log_run(
                        run_type="portfolio_asset",
                        run_parameters={"asset": asset},
                        history=history,
                        metrics=metrics
                    )
                    logger.info(f"   ✅ {asset} procesado. Retorno: {metrics.get('Total Return (%)', 0)}%")
                else:
                    logger.warning(f"   ⚠️ {asset} no generó operaciones.")
                    
            except Exception as e:
                logger.error(f"Error procesando {asset}: {e}")
                traceback.print_exc()
                
        # 4. Consolidar el Portfolio
        logger.info("=== RESULTADOS DEL PORTAFOLIO ===")
        avg_ret = 0
        avg_pf = 0
        valid_assets = len(results)
        
        if valid_assets > 0:
            avg_ret = sum(m.get("Total Return (%)", 0) for m in results.values()) / valid_assets
            avg_pf = sum(m.get("Profit Factor", 0) for m in results.values()) / valid_assets
            
        logger.info(f"Activos evaluados: {valid_assets}/{len(self.assets)}")
        logger.info(f"Retorno Promedio: {avg_ret:.2f}%")
        logger.info(f"Profit Factor Promedio: {avg_pf:.2f}")
        
        # Registrar métrica global
        self.exp_manager.log_run(
            run_type="portfolio_summary",
            run_parameters={"assets": self.assets},
            history=[],
            metrics={"Avg Return (%)": avg_ret, "Avg Profit Factor": avg_pf},
            extra_data={"individual_results": results}
        )
        
        return results, all_histories
