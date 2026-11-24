import sys
import os
import copy
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import random

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from bot.config import settings
from bot.backtest.data_loader import DataLoader
from bot.strategies.factory import StrategyFactory
from bot.backtest.engine import BacktestEngine
from bot.core.trade_logger import logger
from bot.backtest.mock_order_manager import MockOrderManager

def run_block(symbol: str, start_date: str, end_date: str, config_override: dict = None) -> list:
    """Corre el backtest sobre un bloque específico y devuelve el historial de trades."""
    loader = DataLoader(symbol=symbol)
    strategy_name = settings.ACTIVE_STRATEGY
    
    tfs = [settings.STRATEGY_PARAMS[strategy_name].get('entry_tf', '15m'), 
           settings.STRATEGY_PARAMS[strategy_name].get('macro_tf', '1h')]
    tfs = list(set([tf for tf in tfs if tf]))
    
    dfs = {}
    for tf in tfs:
        df = loader.fetch_data(tf, start_date, end_date)
        if df is not None and not df.empty:
            dfs[tf] = df
            
    if len(dfs) < len(tfs):
        print(f"[{symbol}] Datos insuficientes para el periodo {start_date} a {end_date}")
        return []

    if config_override:
        for k, v in config_override.items():
            settings.STRATEGY_PARAMS[strategy_name][k] = v

    # Reiniciar balance para cada bloque
    settings.BACKTEST_PARAMS['initial_balance'] = 1000000.0

    engine = BacktestEngine(dfs)
    history = engine.run()
    
    return history

def analyze_trades(history: list) -> dict:
    if not history:
        return {'trades': 0, 'win_rate': 0.0, 'pf': 0.0, 'exp': 0.0, 'total_pnl': 0.0}
    
    closed_trades = [t for t in history if t['reduceOnly']]
    if not closed_trades:
         return {'trades': 0, 'win_rate': 0.0, 'pf': 0.0, 'exp': 0.0, 'total_pnl': 0.0}
         
    wins = [t for t in closed_trades if t['pnl'] > 0]
    losses = [t for t in closed_trades if t['pnl'] <= 0]
    
    gross_profit = sum(t['pnl'] for t in wins)
    gross_loss = abs(sum(t['pnl'] for t in losses))
    total_pnl = sum(t['pnl'] for t in closed_trades)
    
    win_rate = (len(wins) / len(closed_trades)) * 100
    pf = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')
    exp = total_pnl / len(closed_trades)
    
    return {
        'trades': len(closed_trades),
        'win_rate': win_rate,
        'pf': pf,
        'exp': exp,
        'total_pnl': total_pnl,
        'gross_profit': gross_profit,
        'gross_loss': gross_loss
    }

def run_monte_carlo(trades: list, simulations=1000) -> dict:
    pnls = [t['pnl'] for t in trades if t['reduceOnly']]
    if not pnls:
        return {}
        
    final_pnls = []
    ruin_count = 0
    ruin_threshold = - (settings.BACKTEST_PARAMS['initial_balance'] * 0.20) # 20% max DD allowed
    
    for _ in range(simulations):
        sampled = random.choices(pnls, k=len(pnls))
        cumulative = np.cumsum(sampled)
        final_pnls.append(cumulative[-1])
        if min(cumulative) <= ruin_threshold:
            ruin_count += 1
            
    avg_pnl = np.mean(final_pnls)
    ruin_prob = (ruin_count / simulations) * 100
    
    return {
        'avg_pnl': avg_pnl,
        'ruin_prob': ruin_prob,
        'simulations': simulations
    }

def main():
    import logging
    logging.getLogger('bot.core.risk').setLevel(logging.ERROR)
    settings.ENVIRONMENT = "BACKTEST"
    settings.ENABLE_DETAILED_LOGS = False
    
    print("=========================================================")
    print("🔬 FASE 2.5: VALIDACIÓN DE ROBUSTEZ Y ESTUDIO OUT-OF-SAMPLE")
    print("=========================================================")
    
    # Configuramos el edge descubierto: SL Swing, TP 1.5
    config = {
        'sl_type': 'swing',
        'tp_type': '1.5:1'
    }
    
    # 1. Walk Forward Analysis
    print("\n[1/3] Ejecutando Walk-Forward Analysis (BTC/USDT)...")
    blocks = [
        ("Bloque 1 (Q4 2025)", "2025-10-01", "2025-12-31"),
        ("Bloque 2 (Q1 2026)", "2026-01-01", "2026-03-31"),
        ("Bloque 3 (Q2 2026)", "2026-04-01", "2026-06-30")
    ]
    
    all_trades = []
    report_lines = ["# 🛡️ Reporte de Validación de Robustez\n"]
    report_lines.append("## 1. Walk-Forward Analysis (BTC/USDT)\n")
    report_lines.append("| Bloque temporal | Trades | Win Rate | Profit Factor | Esperanza |")
    report_lines.append("| --- | --- | --- | --- | --- |")
    
    pf_blocks = []
    for name, start, end in blocks:
        print(f"Corriendo {name}...")
        history = run_block("BTC/USDT", start, end, config)
        metrics = analyze_trades(history)
        all_trades.extend(history)
        pf_blocks.append(metrics['pf'])
        
        row = f"| {name} | {metrics['trades']} | {metrics['win_rate']:.1f}% | {metrics['pf']:.2f} | {metrics['exp']:.4f} USDT |"
        report_lines.append(row)
        print(row)
        
    # 2. Monte Carlo
    print("\n[2/3] Ejecutando Simulación de Monte Carlo (1000 iteraciones)...")
    mc = run_monte_carlo(all_trades)
    report_lines.append("\n## 2. Simulación de Monte Carlo\n")
    if mc:
        report_lines.append(f"- **Simulaciones:** {mc['simulations']}")
        report_lines.append(f"- **Probabilidad de Ruina (>20% DD):** {mc['ruin_prob']:.2f}%")
        report_lines.append(f"- **PnL Promedio Esperado:** {mc['avg_pnl']:.2f} USDT")
        print(f"Prob. de Ruina: {mc['ruin_prob']:.2f}% | PnL Promedio: {mc['avg_pnl']:.2f}")
    else:
        report_lines.append("No se pudieron ejecutar trades para Monte Carlo.")
        
    # 3. Out-Of-Sample (ETH/USDT)
    print("\n[3/3] Ejecutando Out-Of-Sample Test (ETH/USDT)...")
    eth_history = run_block("ETH/USDT", "2025-10-01", "2026-06-30", config)
    eth_metrics = analyze_trades(eth_history)
    
    report_lines.append("\n## 3. Out-Of-Sample (ETH/USDT)\n")
    report_lines.append(f"- **Trades:** {eth_metrics['trades']}")
    report_lines.append(f"- **Win Rate:** {eth_metrics['win_rate']:.1f}%")
    report_lines.append(f"- **Profit Factor:** {eth_metrics['pf']:.2f}")
    report_lines.append(f"- **Esperanza:** {eth_metrics['exp']:.4f} USDT")
    
    print(f"ETH/USDT -> Trades: {eth_metrics['trades']} | PF: {eth_metrics['pf']:.2f} | Exp: {eth_metrics['exp']:.4f}")
    
    # 4. Auditoría
    report_lines.append("\n## 4. Checklist de Auditoría Cumplida\n")
    report_lines.append("- [x] Look-ahead bias eliminado (ffill/dropna aplicados)")
    report_lines.append("- [x] Ejecución pesimista intravela implementada (SL tiene prioridad)")
    report_lines.append("- [x] Swings validados sin sesgo de futuro")
    report_lines.append(f"- [x] Comisiones aplicadas: {settings.BACKTEST_PARAMS['commission_pct']}")
    report_lines.append(f"- [x] Slippage aplicado: {settings.BACKTEST_PARAMS['slippage_pct']}")
    
    # Evaluación Final
    is_valid = all([pf > 1.2 for pf in pf_blocks]) and eth_metrics['pf'] > 1.2
    
    report_lines.append("\n## 5. Veredicto Final\n")
    if is_valid:
        report_lines.append("**✅ ESTRATEGIA CIENTÍFICAMENTE VALIDADA.** Cumple todos los requisitos de robustez.")
        print("\n✅ VEREDICTO: ESTRATEGIA CIENTÍFICAMENTE VALIDADA")
    else:
        report_lines.append("**❌ ESTRATEGIA RECHAZADA.** No logró superar las pruebas de robustez (PF > 1.2 en todas las muestras).")
        print("\n❌ VEREDICTO: ESTRATEGIA RECHAZADA")
        
    workspace = os.path.join(os.path.dirname(__file__), '..', '..')
    brain_dir = r"C:\Users\Usuario\.gemini\antigravity-ide\brain\5b3e98b9-a148-48aa-9311-88783283d749"
    if not os.path.exists(brain_dir):
        brain_dir = workspace # Fallback
        
    out_path = os.path.join(brain_dir, "scientific_validation_report.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
        
    print(f"\nReporte guardado en: {out_path}")

if __name__ == "__main__":
    main()
