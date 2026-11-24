"""
Módulo: metrics.py
=================================================
Módulo metrics.py del sistema Backtesting.
"""
import pandas as pd
import numpy as np
from typing import List, Dict
from bot.core.profiler import profile_method

@profile_method(category="Metrics")
def calculate_metrics(history: list, initial_balance: float) -> dict:
    if not history:
        return {}

    df = pd.DataFrame(history)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Filtrar cierres y aperturas para calcular comisiones totales roundtrip
    closes = df[df['reduceOnly'] == True].copy()
    opens = df[df['reduceOnly'] == False].copy()
    
    if len(closes) == 0:
        return {}
        
    if len(opens) == len(closes) and len(opens) > 0:
        closes['entry_fee'] = opens['fee'].values
        closes['total_fees'] = closes['entry_fee'] + closes['fee']
    else:
        closes['total_fees'] = closes['fee']

    closes['net_profit'] = closes['pnl'] - closes['total_fees']
    
    winning_trades = closes[closes['net_profit'] > 0]
    losing_trades = closes[closes['net_profit'] <= 0]
    
    total_trades = len(closes)
    win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0
    
    gross_profit = winning_trades['net_profit'].sum()
    gross_loss = abs(losing_trades['net_profit'].sum())
    
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0)
    
    avg_win = winning_trades['net_profit'].mean() if len(winning_trades) > 0 else 0
    avg_loss = abs(losing_trades['net_profit'].mean()) if len(losing_trades) > 0 else 0
    
    avg_rr = avg_win / avg_loss if avg_loss > 0 else 0
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
    
    # Curva de Equity y Drawdown incluyendo balance inicial
    equity_series = [float(initial_balance)] + [float(b) for b in closes['balance']]
    eq_s = pd.Series(equity_series)
    peak_s = eq_s.cummax()
    dd_s = (eq_s - peak_s) / peak_s
    
    max_drawdown = abs(dd_s.min())
    avg_drawdown = abs(dd_s[dd_s < 0].mean()) if len(dd_s[dd_s < 0]) > 0 else 0.0
    
    net_profit = closes['net_profit'].sum()
    total_return = net_profit / initial_balance
    
    # Sharpe simplificado (asumiendo risk free rate = 0 y retornos por trade)
    closes['ret_pct'] = closes['net_profit'] / initial_balance
    sharpe = (closes['ret_pct'].mean() / closes['ret_pct'].std()) * np.sqrt(total_trades) if closes['ret_pct'].std() > 0 else 0
    
    # Sortino simplificado
    downside_returns = closes[closes['ret_pct'] < 0]['ret_pct']
    downside_std = downside_returns.std()
    sortino = (closes['ret_pct'].mean() / downside_std) * np.sqrt(total_trades) if not pd.isna(downside_std) and downside_std > 0 else 0

    return {
        "Total Trades": total_trades,
        "Win Rate (%)": round(win_rate * 100, 2),
        "Profit Factor": round(profit_factor, 2),
        "Expectancy (USDT)": round(expectancy, 2),
        "Avg RR": round(avg_rr, 2),
        "Avg Win": round(avg_win, 2),
        "Avg Loss": round(avg_loss, 2),
        "Total Return (%)": round(total_return * 100, 2),
        "Max Drawdown (%)": round(max_drawdown * 100, 2),
        "max_drawdown": round(max_drawdown * 100, 2),
        "Avg Drawdown (%)": round(avg_drawdown * 100, 2),
        "Sharpe Ratio": round(sharpe, 2),
        "Sortino Ratio": round(sortino, 2),
        "Gross Profit": round(gross_profit, 2),
        "Gross Loss": round(gross_loss, 2),
        "Final Balance": round(closes['balance'].iloc[-1], 2)
    }
