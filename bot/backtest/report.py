"""
Módulo: report.py
=================================================
Módulo report.py del sistema Backtesting.
"""
import json
import pandas as pd
import os
from bot.core.trade_logger import logger
from bot.backtest.metrics import calculate_metrics

class BacktestReporter:
    def __init__(self):
        self.reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(self.reports_dir, exist_ok=True)
        
    def generate_report(self, history: list, initial_balance: float, strategy_name: str, quiet: bool = False):
        if not quiet:
            logger.info("📊 Generando reporte de backtest...")
        
        metrics = calculate_metrics(history, initial_balance)
        
        if not metrics:
            if not quiet:
                logger.warning("No hay suficientes operaciones para generar reporte.")
            return None
            
        timestamp_str = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
        prefix = f"{strategy_name}_{timestamp_str}"
        
        # Omitir escritura y logs pesados si quiet=True
        if not quiet:
            # Guardar JSON de métricas
            json_path = os.path.join(self.reports_dir, f"{prefix}_metrics.json")
            with open(json_path, 'w') as f:
                json_metrics = {**metrics, "strategy": strategy_name}
                json.dump(json_metrics, f, indent=4)
                
            # Guardar trades en CSV
            df = pd.DataFrame(history)
            csv_path = os.path.join(self.reports_dir, f"{prefix}_trades.csv")
            df.to_csv(csv_path, index=False)
            
            logger.info(f"Reporte guardado en: {self.reports_dir}")
            for k, v in metrics.items():
                logger.info(f"   {k}: {v}")
            
        return metrics
