"""
Módulo: montecarlo.py
=================================================
Módulo montecarlo.py del sistema Backtesting.
"""
import pandas as pd
import numpy as np
import random
import os
import json
from bot.config import settings
from bot.core.trade_logger import logger
from bot.core.profiler import profile_method

class MonteCarloSimulator:
    def __init__(self, history: list, initial_balance: float):
        self.history = history
        self.initial_balance = initial_balance
        self.params = settings.MONTE_CARLO_PARAMS
        self.reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(self.reports_dir, exist_ok=True)
        
        # Filtrar solo trades cerrados (reduceOnly)
        self.trades = [t for t in self.history if t.get('reduceOnly') == True]

    def _apply_uncertainty(self, pnl: float) -> float:
        """Introduce variación aleatoria en comisiones y slippage."""
        if not self.params.get('simulate_uncertainty', False):
            return pnl
            
        # Simular una degradación (peor escenario) o leve mejora
        slip_var = random.uniform(0, self.params['max_slippage_var'])
        comm_var = random.uniform(0, self.params['max_commission_var'])
        
        # Reducimos el pnl simulando que los costos fueron mayores
        # (Esto es una aproximación, ya que pnl = bruto - fees)
        uncertainty_cost = abs(pnl) * (slip_var + comm_var)
        return pnl - uncertainty_cost

    def _generate_sequence(self) -> list:
        method = self.params.get('method', 'shuffle')
        n = len(self.trades)
        
        if method == 'shuffle':
            seq = self.trades.copy()
            random.shuffle(seq)
            return seq
            
        elif method == 'bootstrap':
            return [random.choice(self.trades) for _ in range(n)]
            
        elif method == 'block_bootstrap':
            block_size = self.params.get('block_size', 5)
            blocks = [self.trades[i:i + block_size] for i in range(0, n, block_size)]
            seq = []
            while len(seq) < n:
                b = random.choice(blocks)
                seq.extend(b)
            return seq[:n]
            
        return self.trades

    def _simulate_run(self) -> dict:
        seq = self._generate_sequence()
        
        balance = self.initial_balance
        peak = balance
        max_dd = 0.0
        
        gross_profit = 0.0
        gross_loss = 0.0
        ret_pct_list = []
        
        ruined = False
        ruin_threshold = self.params.get('ruin_drawdown_threshold', 0.3)
        ruin_limit = self.initial_balance * (1 - ruin_threshold)
        
        for trade in seq:
            # Recomputar PNL con incertidumbre
            net_pnl = self._apply_uncertainty(trade['pnl'] - trade['fee'])
            
            # Profit Factor
            if net_pnl > 0:
                gross_profit += net_pnl
            else:
                gross_loss += abs(net_pnl)
                
            # Retornos
            ret_pct = net_pnl / balance if balance > 0 else 0
            ret_pct_list.append(ret_pct)
                
            balance += net_pnl
            
            if balance > peak:
                peak = balance
                
            dd = (peak - balance) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
                
            if balance <= ruin_limit:
                ruined = True

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0)
        total_return = (balance - self.initial_balance) / self.initial_balance
        
        # Sharpe simplificado
        ret_arr = np.array(ret_pct_list)
        std_ret = ret_arr.std()
        sharpe = (ret_arr.mean() / std_ret) * np.sqrt(len(ret_arr)) if std_ret > 0 else 0
        
        return {
            "total_return": total_return,
            "max_drawdown": max_dd,
            "profit_factor": profit_factor,
            "sharpe_ratio": sharpe,
            "ruined": 1 if ruined else 0
        }

    @profile_method(category="Research Lab")
    def run_monte_carlo(self):
        if not self.trades:
            logger.warning("No hay trades suficientes para simulación Monte Carlo.")
            return
            
        logger.info(f"🎲 Iniciando Monte Carlo ({self.params['num_simulations']} iteraciones) | Método: {self.params['method']}")
        
        results = []
        for _ in range(self.params['num_simulations']):
            results.append(self._simulate_run())
            
        df = pd.DataFrame(results)
        
        # Calcular Estadísticas
        percentiles = [0.05, 0.25, 0.50, 0.75, 0.95]
        
        report = {
            "Simulations": self.params['num_simulations'],
            "Method": self.params['method'],
            "Uncertainty_Simulated": self.params['simulate_uncertainty'],
            "Risk_of_Ruin_Prob (%)": round(df['ruined'].mean() * 100, 2),
            "Metrics": {}
        }
        
        for col in ['total_return', 'max_drawdown', 'profit_factor', 'sharpe_ratio']:
            desc = df[col].describe(percentiles=percentiles).to_dict()
            report["Metrics"][col] = {
                "mean": round(desc['mean'], 4),
                "std": round(desc['std'], 4),
                "min": round(desc['min'], 4),
                "5%": round(desc['5%'], 4),
                "25%": round(desc['25%'], 4),
                "median": round(desc['50%'], 4),
                "75%": round(desc['75%'], 4),
                "95%": round(desc['95%'], 4),
                "max": round(desc['max'], 4)
            }
            
        logger.info(f"📉 Riesgo de Ruina (> {self.params['ruin_drawdown_threshold']*100}% DD): {report['Risk_of_Ruin_Prob (%)']}%")
        logger.info(f"📊 Retorno Medio Esperado: {report['Metrics']['total_return']['mean']*100:.2f}% (P5: {report['Metrics']['total_return']['5%']*100:.2f}%)")
        logger.info(f"📉 Max Drawdown Medio: {report['Metrics']['max_drawdown']['mean']*100:.2f}% (P95: {report['Metrics']['max_drawdown']['95%']*100:.2f}%)")

        # Guardar reporte
        timestamp_str = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
        mc_file = os.path.join(self.reports_dir, f"montecarlo_{timestamp_str}.json")
        with open(mc_file, 'w') as f:
            json.dump(report, f, indent=4)
        
        logger.info(f"💾 Reporte Monte Carlo guardado en: {mc_file}")
        return report
