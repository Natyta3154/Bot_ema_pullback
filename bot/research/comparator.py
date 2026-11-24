import pandas as pd
from bot.research.db_manager import DatabaseManager
from bot.core.trade_logger import logger
import json
import os

class StrategyComparator:
    """
    Compara y rankea diferentes ejecuciones (runs) registradas en la base de datos.
    """
    def __init__(self):
        self.db = DatabaseManager()
        
    def _calculate_advanced_metrics(self, run_metrics: dict) -> dict:
        """
        Extiende las métricas base con:
        - Recovery Factor = Total Net Profit / Max Drawdown
        - Calmar Ratio = Annualized Return / Max Drawdown (Simplificado a Total Return / MDD)
        """
        mdd = run_metrics.get("Max Drawdown (%)", 0.0) / 100.0
        total_return = run_metrics.get("Total Return (%)", 0.0) / 100.0
        gross_profit = run_metrics.get("Gross Profit", 0.0)
        gross_loss = run_metrics.get("Gross Loss", 0.0)
        net_profit = gross_profit - gross_loss
        
        recovery_factor = net_profit / mdd if mdd > 0 else (net_profit if net_profit > 0 else 0)
        calmar_ratio = total_return / mdd if mdd > 0 else (total_return if total_return > 0 else 0)
        
        extended = run_metrics.copy()
        extended["Recovery Factor"] = round(recovery_factor, 2)
        extended["Calmar Ratio"] = round(calmar_ratio, 2)
        return extended
        
    def compare_runs(self, experiment_ids: list = None, run_type: str = 'single_backtest', sort_by: str = "Sharpe Ratio", ascending: bool = False):
        """
        Genera una tabla comparativa de los runs encontrados.
        Si experiment_ids es None, evalúa toda la base de datos de los experimentos.
        """
        logger.info(f"📊 Generando Tabla Comparativa. Criterio de Ordenamiento: {sort_by} ({'Asc' if ascending else 'Desc'})")
        catalog = self.db._load_catalog()
        
        runs_data = []
        
        target_exps = experiment_ids if experiment_ids else catalog.keys()
        
        for exp_id in target_exps:
            if exp_id not in catalog:
                continue
                
            exp_info = catalog[exp_id]
            strategy_name = exp_info.get("metadata", {}).get("strategy", "UNKNOWN")
            
            # Cargar los JSON individuales de cada run para extraer info completa
            exp_dir = os.path.join(self.db.base_dir, 'experiments', exp_id)
            if not os.path.exists(exp_dir):
                continue
                
            for filename in os.listdir(exp_dir):
                if not filename.endswith('.json'):
                    continue
                    
                filepath = os.path.join(exp_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        run_payload = json.load(f)
                        
                    if run_payload.get('run_type') != run_type:
                        continue
                        
                    raw_metrics = run_payload.get('metrics', {})
                    if not raw_metrics:
                        continue
                        
                    ext_metrics = self._calculate_advanced_metrics(raw_metrics)
                    
                    row = {
                        "Experiment": exp_id,
                        "Run ID": run_payload.get('run_id'),
                        "Strategy": strategy_name,
                        "Timestamp": run_payload.get('timestamp')
                    }
                    row.update(ext_metrics)
                    runs_data.append(row)
                    
                except Exception as e:
                    logger.error(f"Error procesando run {filepath}: {e}")
                    
        if not runs_data:
            logger.warning("No se encontraron corridas para comparar con esos filtros.")
            return None
            
        df = pd.DataFrame(runs_data)
        
        if sort_by in df.columns:
            df = df.sort_values(by=sort_by, ascending=ascending)
        else:
            logger.warning(f"La métrica '{sort_by}' no existe en las columnas. Ordenando por defecto (Timestamp).")
            
        df = df.reset_index(drop=True)
        return df
