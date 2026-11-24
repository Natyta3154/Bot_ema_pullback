import numpy as np
import itertools
import json
import math
from typing import Dict, List, Any
from bot.core.trade_logger import logger
from bot.config import settings

class WalkForwardOptimizer:
    """
    Optimizador Walk-Forward especializado en la calibración de Pesos Institucionales.
    Asegura consistencia matemática (Suma = 1.0) y maximiza la Esperanza Matemática (Expectancy).
    """
    def __init__(self, backtester_instance, step_size: float = 0.05):
        self.backtester = backtester_instance
        self.step_size = step_size
        self.matrix_keys = ['market', 'structure', 'momentum', 'execution', 'risk']

    def generate_weight_permutations(self) -> List[Dict[str, float]]:
        """
        Genera permutaciones vectorizadas de pesos que suman exactamente 1.0 utilizando pasos fijos.
        """
        print(f"🧬 Generando matriz de pesos con paso indexado: {self.step_size}")
        
        # Generar rango de pasos posibles convertidos a enteros para evitar imprecisiones de punto flotante
        steps = int(1.0 / self.step_size)
        options = [round(i * self.step_size, 2) for i in range(steps + 1)]
        
        valid_permutations = []
        
        # Producto cartesiano eficiente filtrado por suma exacta
        for combo in itertools.product(options, repeat=len(self.matrix_keys)):
            if math.isclose(sum(combo), 1.0, rel_tol=1e-5):
                valid_permutations.append(dict(zip(self.matrix_keys, combo)))
                
        print(f"📊 Total de combinaciones matemáticas válidas a evaluar: {len(valid_permutations)}")
        return valid_permutations

    def calculate_expectancy(self, stats: Dict[str, Any]) -> float:
        """
        Calcula la Esperanza Matemática pura: (WinRate * AvgWin) - (LossRate * AvgLoss)
        """
        total_trades = stats.get('total_trades', 0)
        if total_trades == 0:
            return -1.0 # Penalización por inactividad absoluta

        win_rate = stats.get('win_rate', 0.0) # Ej: 0.55
        avg_gain = stats.get('avg_gain_usdt', 0.0)
        avg_loss = abs(stats.get('avg_loss_usdt', 0.0))
        
        loss_rate = 1.0 - win_rate
        
        expectancy = (win_rate * avg_gain) - (loss_rate * avg_loss)
        return expectancy

    def run_weight_tuning(self, historical_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ejecuta el Grid Search Institucional sobre los datos históricos cargados.
        """
        permutations = self.generate_weight_permutations()
        best_expectancy = -9999.0
        best_weights = {}
        
        print("🏋️ Iniciando simulación In-Sample...")
        
        for index, weights in enumerate(permutations):
            # Inyectar pesos en los parámetros de la estrategia temporalmente
            current_params = settings.STRATEGY_PARAMS["BREAKOUT_RETEST"].copy()
            current_params['decision_weights'] = weights
            
            # Ejecutar el motor de backtesting pasándole las configuraciones inyectadas
            backtest_results = self.backtester.run(historical_data, current_params)
            
            # Evaluar métrica primaria de rendimiento (Expectancy)
            metric = self.calculate_expectancy(backtest_results)
            
            if metric > best_expectancy:
                best_expectancy = metric
                best_weights = weights
                print(f"🏆 Nuevo óptimo encontrado [{index}]: Expectancy: {best_expectancy:.4f} USDT/trade | Pesos: {weights}")

        # Guardar el set óptimo en el directorio de research
        output_path = "bot/research/optimized_weights.json"
        with open(output_path, 'w') as f:
            json.dump({"optimized_weights": best_weights, "expectancy": best_expectancy}, f, indent=4)
            
        print(f"💾 Calibración finalizada. Pesos óptimos guardados en {output_path}")
        return best_weights
