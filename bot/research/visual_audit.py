import sys
import os
import random
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt

# Asegurar path correcto de importaciones
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from bot.config import settings
from bot.core.trade_logger import logger
from bot.backtest.data_loader import DataLoader
from bot.backtest.engine import BacktestEngine
from bot.strategies.factory import StrategyFactory
from bot.backtest.metrics import calculate_metrics

def main():
    import logging
    logging.getLogger('bot.core.risk').setLevel(logging.ERROR)
    settings.ENVIRONMENT = "BACKTEST"
    settings.ENABLE_DETAILED_LOGS = False
    
    print("=========================================================")
    print("🔬 FASE 2.6: AUDITORÍA VISUAL DEL MOTOR DE BACKTEST")
    print("=========================================================")
    
    symbol = "BTC/USDT"
    # Usaremos Q1 2026 para auditar, ya que tuvo un Win Rate increíble.
    start = "2026-01-01"
    end = "2026-03-31"
    config = {
        'initial_balance': 1000000.0,
        'commission': 0.0004,
        'slippage': 0.0005,
    }
    
    settings.BACKTEST_PARAMS.update(config)
    settings.ACTIVE_STRATEGY = 'EMA_PULLBACK_TREND'
    settings.STRATEGY_PARAMS['EMA_PULLBACK_TREND'] = {
        'macro_tf': '1h',
        'trigger_tf': '15m',
        'entry_tf': '30m',
        'sl_type': 'swing',
        'tp_type': '1.5:1',
        'body_ratio_threshold': 0.55
    }
    
    loader = DataLoader(symbol=symbol)
    tfs = ['15m', '30m', '1h']
    dfs = {}
    for tf in tfs:
        df = loader.fetch_data(tf, start, end)
        if df is not None and not df.empty:
            dfs[tf] = df
    temp_strat = StrategyFactory.create_strategy('EMA_PULLBACK_TREND', None, None)
    temp_strat.analyze_market(dfs)
    
    print("Corriendo motor para obtener operaciones...")
    engine = BacktestEngine(dfs)
    history = engine.run()
    
    # Parear trades
    trades = []
    current_entry = None
    for fill in history:
        if not fill['reduceOnly']:
            current_entry = fill
        else:
            if current_entry:
                trades.append({
                    'entry': current_entry,
                    'exit': fill
                })
                current_entry = None
                
    if not trades:
        print("No se encontraron operaciones.")
        return
        
    print(f"Se encontraron {len(trades)} operaciones. Seleccionando 100 aleatorias...")
    # Seleccionar 100 aleatorias o las que haya
    sample_size = min(100, len(trades))
    random.seed(42) # Fijo para reproducibilidad
    sample_trades = random.sample(trades, sample_size)
    
    # Crear directorio para gráficos
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "visual_audit_results")
    os.makedirs(out_dir, exist_ok=True)
    
    print(f"Generando gráficos en: {out_dir}")
    
    df_15m = dfs['15m'].copy()
    df_15m.set_index('timestamp', inplace=True)
    
    for i, t in enumerate(sample_trades):
        entry_ts = pd.to_datetime(t['entry']['timestamp'])
        exit_ts = pd.to_datetime(t['exit']['timestamp'])
        
        # Encontrar los índices en el dataframe
        try:
            entry_idx = df_15m.index.get_loc(entry_ts)
            exit_idx = df_15m.index.get_loc(exit_ts)
        except KeyError:
            continue
            
        start_idx = max(0, entry_idx - 20)
        end_idx = min(len(df_15m), exit_idx + 20)
        
        df_slice = df_15m.iloc[start_idx:end_idx].copy()
        
        # Precios
        entry_price = t['entry']['price']
        exit_price = t['exit']['price']
        side = "LONG" if t['entry']['side'] == "buy" else "SHORT"
        
        # Features (para sacar SL/TP si se puede)
        feats = t['entry'].get('entry_features', {})
        sl_price = feats.get('sl_price', 0.0)
        # El tp calculado no está en feats directamente si lo calcula la estrategia en result['tp']
        # Pero podemos deducirlo del risk o dibujarlo si lo tuviéramos. El exit_price fue el TP o SL.
        
        apds = []
        
        # Crear serie para marcadores de entrada y salida
        entry_series = pd.Series(index=df_slice.index, dtype=float)
        exit_series = pd.Series(index=df_slice.index, dtype=float)
        
        entry_series.loc[entry_ts] = entry_price
        exit_series.loc[exit_ts] = exit_price
        
        apds.append(mpf.make_addplot(entry_series, type='scatter', markersize=200, marker='^' if side=='LONG' else 'v', color='blue'))
        apds.append(mpf.make_addplot(exit_series, type='scatter', markersize=200, marker='X', color='black'))
        
        hlines = dict(hlines=[entry_price], colors=['b'], linestyle='-', linewidths=1)
        if sl_price > 0:
            hlines['hlines'].append(sl_price)
            hlines['colors'].append('r')
            
        # Si cerró en profit, probablemente el exit_price fue el TP
        is_profit = (side == 'LONG' and exit_price > entry_price) or (side == 'SHORT' and exit_price < entry_price)
        if is_profit:
            hlines['hlines'].append(exit_price)
            hlines['colors'].append('g')
            
        filename = os.path.join(out_dir, f"trade_{i+1:03d}_{side}_{entry_ts.strftime('%Y%m%d_%H%M')}.png")
        
        title = f"Trade #{i+1} | {side} | PnL: {t['exit']['pnl']:.2f} USDT"
        
        mpf.plot(
            df_slice, 
            type='candle', 
            style='charles', 
            addplot=apds,
            hlines=hlines,
            title=title,
            savefig=filename,
            warn_too_much_data=10000
        )
        
    print("✅ Gráficos generados correctamente.")

if __name__ == "__main__":
    main()
