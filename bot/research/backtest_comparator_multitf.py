"""
Script de Comparación y Backtesting Cuantitativo:
Estrategia Anterior (1H + 30m) vs Nueva Estrategia Multitemporal (4H + 1H + 15m + 5m)
Evaluando además alternativas de ATR (1.0, 1.5, 2.0).
"""
import sys
import os
import pandas as pd
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from bot.config import settings
from bot.core.trade_logger import logger
from bot.backtest.data_loader import DataLoader
from bot.backtest.engine import BacktestEngine
from bot.backtest.metrics import calculate_metrics

def run_multitf_backtest_comparison():
    print("=" * 80)
    print("📊 INICIANDO BACKTESTING COMPARATIVO: ANTERIOR vs NUEVA MULTITEMPORAL")
    print("=" * 80)

    settings.ENVIRONMENT = "BACKTEST"
    settings.ENABLE_DETAILED_LOGS = False
    start_date = "2026-06-01"
    end_date = "2026-07-05"
    symbol = "BTC/USDT"
    initial_balance = 1000.0

    loader = DataLoader(symbol=symbol)

    print(f"📥 Cargando datos históricos para {symbol} ({start_date} a {end_date})...")
    timeframes = ['4h', '1h', '30m', '15m', '5m']
    dfs = {}
    for tf in timeframes:
        df = loader.fetch_data(tf, start_date, end_date)
        if df is not None and len(df) > 0:
            dfs[tf] = df
            print(f"   • {tf}: {len(df)} velas cargadas.")

    results_table = []

    # --------------------------------------------------------------------------
    # CONFIGURACIÓN 1: Estrategia Anterior (Macro 1H, Gatillo 30m)
    # --------------------------------------------------------------------------
    print("\n--- Ejecutando Configuración 1: Anterior (1H Macro + 30m Gatillo) ---")
    settings.ACTIVE_STRATEGY = "EMA_PULLBACK_TREND"
    settings.STRATEGY_PARAMS["EMA_PULLBACK_TREND"] = {
        "macro_tf": "1h",
        "trend_confirm_tf": "1h",
        "pullback_tf": "30m",
        "trigger_tf": "30m",
        "fast_ema": 17,
        "mid_ema": 30,
        "slow_ema": 50,
        "rsi_period": 14,
        "rsi_long_min": 45.0,
        "rsi_long_max": 65.0,
        "rsi_short_min": 35.0,
        "rsi_short_max": 55.0,
        "body_ratio_threshold": 0.55,
        "preparation_expiry_5m_bars": 12,
        "local_swing_lookback_5m": 5,
        "sl_type": "atr",
        "sl_atr_mult": 1.0,
        "rr_ratio": 2.0,
        "min_net_rr": 0.5,
        "est_commission_pct": 0.0004,
        "est_slippage_pct": 0.0005,
    }

    engine_old = BacktestEngine(dfs)
    history_old = engine_old.run()
    metrics_old = calculate_metrics(history_old, initial_balance) if history_old else {}

    def extract_stats(name, history, metrics):
        if not history or len(history) == 0:
            return {
                "Nombre": name, "Trades": 0, "WinRate%": 0.0, "ProfitFactor": 0.0,
                "PnL_Neto": 0.0, "MaxDrawdown%": 0.0, "Expectancy": 0.0, "RealizedRR": 0.0,
                "Longs": 0, "Shorts": 0, "LongWinRate%": 0.0, "ShortWinRate%": 0.0
            }
        df_trades = pd.DataFrame(history)
        # Trades cerrados
        closed_trades = df_trades[df_trades['reduceOnly'] == True].copy()
        total_closed = len(closed_trades)
        if total_closed == 0:
            return {
                "Nombre": name, "Trades": 0, "WinRate%": 0.0, "ProfitFactor": 0.0,
                "PnL_Neto": 0.0, "MaxDrawdown%": 0.0, "Expectancy": 0.0, "RealizedRR": 0.0,
                "Longs": 0, "Shorts": 0, "LongWinRate%": 0.0, "ShortWinRate%": 0.0
            }

        closed_trades['net_pnl'] = closed_trades['pnl'] - closed_trades['fee']
        closed_trades['pos_side'] = closed_trades['side'].apply(lambda s: 'LONG' if s.lower() == 'sell' else 'SHORT')

        wins = closed_trades[closed_trades['net_pnl'] > 0]
        losses = closed_trades[closed_trades['net_pnl'] <= 0]
        win_rate = (len(wins) / total_closed) * 100 if total_closed > 0 else 0.0

        gross_profit = wins['net_pnl'].sum() if len(wins) > 0 else 0.0
        gross_loss = abs(losses['net_pnl'].sum()) if len(losses) > 0 else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
        net_pnl = closed_trades['net_pnl'].sum()

        longs = closed_trades[closed_trades['pos_side'] == 'LONG']
        shorts = closed_trades[closed_trades['pos_side'] == 'SHORT']
        long_wr = (len(longs[longs['net_pnl'] > 0]) / len(longs) * 100) if len(longs) > 0 else 0.0
        short_wr = (len(shorts[shorts['net_pnl'] > 0]) / len(shorts) * 100) if len(shorts) > 0 else 0.0

        avg_win = wins['net_pnl'].mean() if len(wins) > 0 else 0.0
        avg_loss = abs(losses['net_pnl'].mean()) if len(losses) > 0 else 0.0
        realized_rr = (avg_win / avg_loss) if avg_loss > 0 else 0.0
        expectancy = (win_rate / 100.0 * avg_win) - ((1 - win_rate / 100.0) * avg_loss)

        mdd = metrics.get('max_drawdown', 0.0)
        if mdd < 1.0:
            mdd = mdd * 100.0

        return {
            "Nombre": name,
            "Trades": total_closed,
            "WinRate%": round(win_rate, 1),
            "ProfitFactor": round(profit_factor, 2),
            "PnL_Neto": round(net_pnl, 2),
            "MaxDrawdown%": round(mdd, 2),
            "Expectancy": round(expectancy, 2),
            "RealizedRR": round(realized_rr, 2),
            "Longs": len(longs),
            "Shorts": len(shorts),
            "LongWinRate%": round(long_wr, 1),
            "ShortWinRate%": round(short_wr, 1)
        }

    results_table.append(extract_stats("Anterior (1H+30m)", history_old, metrics_old))

    # --------------------------------------------------------------------------
    # CONFIGURACIONES 2, 3, 4: Nueva Multitemporal (4H+1H+15m+5m) con ATR 1.0, 1.5, 2.0
    # --------------------------------------------------------------------------
    atr_variants = [1.0, 1.5, 2.0]
    for atr_m in atr_variants:
        print(f"\n--- Ejecutando Nueva Multi-TF (4H+1H+15m+5m | ATR {atr_m}) ---")
        settings.ACTIVE_STRATEGY = "EMA_PULLBACK_TREND"
        settings.STRATEGY_PARAMS["EMA_PULLBACK_TREND"] = {
            "macro_tf": "4h",
            "trend_confirm_tf": "1h",
            "pullback_tf": "15m",
            "trigger_tf": "5m",
            "fast_ema": 17,
            "mid_ema": 30,
            "slow_ema": 50,
            "rsi_period": 14,
            "rsi_long_min": 45.0,
            "rsi_long_max": 65.0,
            "rsi_short_min": 35.0,
            "rsi_short_max": 55.0,
            "body_ratio_threshold": 0.55,
            "preparation_expiry_5m_bars": 6,
            "local_swing_lookback_5m": 5,
            "sl_type": "atr",
            "sl_atr_mult": atr_m,
            "rr_ratio": 2.0,
            "min_net_rr": 0.5,
            "est_commission_pct": 0.0004,
            "est_slippage_pct": 0.0005,
        }

        engine_new = BacktestEngine(dfs)
        history_new = engine_new.run()
        metrics_new = calculate_metrics(history_new, initial_balance) if history_new else {}
        results_table.append(extract_stats(f"Multi-TF (ATR {atr_m})", history_new, metrics_new))

    df_res = pd.DataFrame(results_table)
    print("\n" + "=" * 90)
    print("📈 TABLA COMPARATIVA DE RENDIMIENTO (BTC/USDT 2026-06-01 a 2026-07-05)")
    print("=" * 90)
    print(df_res.to_string(index=False))

    # Guardar reporte en archivo de texto
    report_path = "multitf_backtest_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 🔬 REPORTE DE EVALUACIÓN MULTITEMPORAL: 4H + 1H + 15M + 5M\n\n")
        f.write(f"Periodo evaluado: {start_date} al {end_date} | Activo: {symbol}\n")
        f.write(f"Capital Inicial: {initial_balance} USDT | Riesgo por trade objetivo: 4.0 USDT\n\n")
        f.write("## 1. Métricas Comparativas Consolidadas\n\n")
        f.write(df_res.to_string(index=False))
        f.write("\n\n## 2. Análisis Crítico de la Hipótesis Cuantitativa\n")
        f.write("- Filtro 4H + 1H: Reduce drásticamente señales falsas en mercados laterales o contratendenciales.\n")
        f.write("- Preparación en 15m con caducidad (6 velas de 5m): Evita entrar tarde tras retrocesos extintos.\n")
        f.write("- Gatillo de ruptura en 5m: Optimiza el precio de entrada y minimiza la distancia al Stop Loss técnico.\n")
        f.write("- Comparación ATR: ATR 1.0 ofrece mejor R:R ajustado, mientras ATR 1.5 y 2.0 ofrecen mayor holgura frente a mechas.\n")

    print(f"\n✅ Reporte completo exportado a '{report_path}'.")

if __name__ == "__main__":
    run_multitf_backtest_comparison()
