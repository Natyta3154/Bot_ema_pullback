import pandas as pd
from bot.core.trade_logger import logger
import json

class OverfittingDetector:
    """
    Evalúa la degradación de rendimiento entre el In-Sample (IS) y el Out-Of-Sample (OOS)
    a partir de los resultados de un Walk Forward Analysis.
    """
    def __init__(self, wf_results: list):
        self.wf_results = wf_results
        
    def analyze(self) -> dict:
        if not self.wf_results:
            logger.warning("No hay resultados de Walk Forward para analizar.")
            return {}
            
        degradations = []
        is_pf_list, oos_pf_list = [], []
        is_ret_list, oos_ret_list = [], []
        
        for win in self.wf_results:
            is_m = win.get('metrics_in_sample', {})
            oos_m = win.get('metrics_out_of_sample', {})
            
            # Saltamos si no hubo trades
            if not is_m or not oos_m:
                continue
                
            is_pf = is_m.get("Profit Factor", 1.0)
            oos_pf = oos_m.get("Profit Factor", 1.0)
            
            is_ret = is_m.get("Total Return (%)", 0.0)
            oos_ret = oos_m.get("Total Return (%)", 0.0)
            
            # Calculamos la degradación porcentual (positivo = degradó)
            pf_deg = ((is_pf - oos_pf) / is_pf) * 100 if is_pf > 0 else 0
            ret_deg = ((is_ret - oos_ret) / is_ret) * 100 if is_ret > 0 else 0
            
            degradations.append({
                "pf_degradation": pf_deg,
                "ret_degradation": ret_deg
            })
            
            is_pf_list.append(is_pf)
            oos_pf_list.append(oos_pf)
            is_ret_list.append(is_ret)
            oos_ret_list.append(oos_ret)
            
        if not degradations:
            return {"status": "INSUFFICIENT_DATA"}
            
        avg_pf_deg = sum([d['pf_degradation'] for d in degradations]) / len(degradations)
        avg_ret_deg = sum([d['ret_degradation'] for d in degradations]) / len(degradations)
        
        # Robustness Index (100 = perfecto, sin degradación, 0 = degradación extrema)
        # Una penalización simple basada en la caída media del retorno y PF
        penalty = max(0, avg_pf_deg) * 0.5 + max(0, avg_ret_deg) * 0.5
        robustness_index = max(0, 100 - penalty)
        
        logger.info("=== DETECCIÓN DE OVERFITTING ===")
        logger.info(f"Degradación media Profit Factor: {avg_pf_deg:.2f}%")
        logger.info(f"Degradación media Retorno: {avg_ret_deg:.2f}%")
        logger.info(f"Índice de Robustez: {robustness_index:.2f}/100")
        
        if robustness_index < 50:
            logger.warning("🚨 ESTRATEGIA CON ALTO RIESGO DE OVERFITTING. Degradación OOS excesiva.")
        elif robustness_index > 80:
            logger.info("✅ Estrategia robusta. Comportamiento consistente fuera de muestra.")
            
        return {
            "avg_profit_factor_degradation": avg_pf_deg,
            "avg_return_degradation": avg_ret_deg,
            "robustness_index": robustness_index
        }
