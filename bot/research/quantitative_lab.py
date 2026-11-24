import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime

# Asegurar path correcto de importaciones
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from bot.config import settings
from bot.core.trade_logger import logger
from bot.backtest.data_loader import DataLoader
from bot.backtest.engine import BacktestEngine
from bot.strategies.factory import StrategyFactory
from bot.backtest.metrics import calculate_metrics

def get_session_name(hour: int) -> str:
    if 0 <= hour < 8: return "Asia (00-08h UTC)"
    elif 8 <= hour < 16: return "Londres (08-16h UTC)"
    else: return "Nueva York (16-24h UTC)"

def run_quantitative_lab():
    logger.info("================================================================================")
    print("🔬 CONSTRUYENDO Y EJECUTANDO LABORATORIO DE INVESTIGACIÓN CUANTITATIVA (V3 AUDITADA)")
    logger.info("================================================================================")
    
    settings.ENVIRONMENT = "BACKTEST"
    orig_logs_flag = getattr(settings, 'ENABLE_DETAILED_LOGS', True)
    settings.ENABLE_DETAILED_LOGS = False
    import logging
    logging.getLogger('bot.core.risk').setLevel(logging.ERROR)
    
    start_date = "2026-05-01"
    end_date = "2026-07-05"
    settings.BACKTEST_PARAMS['initial_balance'] = 1000000.0
    strategy_name = settings.ACTIVE_STRATEGY
    
    loader = DataLoader(symbol="BTC/USDT")
    
    strategy_params = settings.STRATEGY_PARAMS[strategy_name]
    trigger_tf = strategy_params.get('trigger_tf', '15m')
    entry_tf = strategy_params.get('entry_tf', '30m')
    macro_tf = strategy_params.get('macro_tf', '1h')
    
    tfs = list(set([trigger_tf, entry_tf, macro_tf]))
    dfs = {}
    for tf in tfs:
        df = loader.fetch_data(tf, start_date, end_date)
        if df is not None and not df.empty:
            dfs[tf] = df
            
    if len(dfs) < len(tfs):
        logger.error("No se pudieron cargar suficientes datos históricos.")
        sys.exit(1)
        
    orig_params = strategy_params.copy()
    
    # ==========================================================================
    # FASE 1: EXPERIMENTOS DE EJECUCIÓN (CON BacktestEngine)
    # ==========================================================================
    logger.info("\n--- INICIANDO EXPERIMENTOS DE EJECUCIÓN ---")
    
    experiments = {}
    csv_export_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lab_raw_trades.csv')
    
    # CASO 0: Base
    settings.STRATEGY_PARAMS[strategy_name] = orig_params.copy()
    settings.STRATEGY_PARAMS[strategy_name]['sl_type'] = 'atr'
    settings.STRATEGY_PARAMS[strategy_name]['tp_type'] = '1:1'
    eng = BacktestEngine(dfs)
    hist_base = eng.run()
    experiments['Base (ATR, TP 1:1)'] = {'history': hist_base, 'metrics': calculate_metrics(hist_base, 1000000)}
    
    # Exportar Caso Base a CSV
    trades_data = []
    current_entry = None
    for fill in hist_base:
        if not fill['reduceOnly']:
            current_entry = fill
        else:
            if current_entry:
                feats = fill.get('entry_features', {})
                if not feats and 'features' in current_entry:
                    feats = current_entry['features']
                
                t_in = pd.to_datetime(current_entry['timestamp'])
                t_out = pd.to_datetime(fill['timestamp'])
                dur_mins = int((t_out - t_in).total_seconds() / 60)
                
                trades_data.append({
                    'timestamp_in': current_entry['timestamp'],
                    'timestamp_out': fill['timestamp'],
                    'utc_hour': t_in.hour,
                    'side': current_entry['side'],
                    'pnl_usdt': fill['pnl'],
                    'duration_mins': dur_mins,
                    'mae_pct': fill.get('mae_pct', 0.0),
                    'mfe_pct': fill.get('mfe_pct', 0.0),
                    'dist_ema17_30': feats.get('dist_ema17_30', 0.0),
                    'dist_price_ema30': feats.get('dist_price_ema30', 0.0),
                    'slope_ema30': feats.get('slope_ema30', 0.0),
                    'body_ratio': feats.get('body_ratio', 0.0),
                    'dist_swing': feats.get('dist_swing', 0.0),
                    'rsi': feats.get('rsi', 0.0)
                })
                current_entry = None
                
    df_trades = pd.DataFrame(trades_data)
    if len(df_trades) > 0:
        df_trades.to_csv(csv_export_path, index=False)
        logger.info(f"Trades exportados a CSV: {csv_export_path}")

    # Otros experimentos rápidos
    for name, tp, sl in [('ATR, TP 1.5:1', '1.5:1', 'atr'), ('ATR, TP 2:1', '2:1', 'atr'), ('SL Swing, TP 1:1', '1:1', 'swing')]:
        settings.STRATEGY_PARAMS[strategy_name] = orig_params.copy()
        settings.STRATEGY_PARAMS[strategy_name]['sl_type'] = sl
        settings.STRATEGY_PARAMS[strategy_name]['tp_type'] = tp
        eng = BacktestEngine(dfs)
        hist = eng.run()
        experiments[name] = {'history': hist, 'metrics': calculate_metrics(hist, 1000000)}

    settings.STRATEGY_PARAMS[strategy_name] = orig_params.copy()
    
    # ==========================================================================
    # FASE 2: EMBUDO DE SEÑALES APLICADO (ESCANEO PARALELO)
    # ==========================================================================
    logger.info("\n--- ESCANEANDO SEÑALES TEÓRICAS VS EJECUTADAS ---")
    
    # Simular la recolección de señales emulando el avance del MockMarketData
    temp_strat = StrategyFactory.create_strategy(strategy_name, None, None)
    
    # Usamos MockMarketData para garantizar que se procesa igual que el Engine
    from bot.backtest.mock_market_data import MockMarketData
    market_data = MockMarketData(dfs)
    df_trigger = dfs[trigger_tf].set_index('timestamp').sort_index()
    minutes = int(trigger_tf.replace('m', '')) if 'm' in trigger_tf else 60
    trigger_delta = pd.Timedelta(minutes=minutes)
    
    signal_counts = {
        'TOTAL_VELAS_EVALUADAS': 0, 'OK': 0, 'REJECT_BEARISH': 0, 'REJECT_BULLISH': 0, 
        'REJECT_BODY': 0, 'REJECT_CLOSE_BELOW_EMA': 0, 'REJECT_CLOSE_ABOVE_EMA': 0, 
        'REJECT_RSI': 0, 'NO_TREND': 0, 'NO_DATA': 0, 'NO_RANGE': 0, 'PULLBACK_MISS': 0
    }
    
    for row in df_trigger.itertuples():
        ts_end = row.Index + trigger_delta
        market_data.current_timestamp = ts_end
        current_data = {}
        for tf in tfs:
            df_tf = market_data.fetch_ohlcv(tf)
            if df_tf is not None:
                current_data[tf] = df_tf.copy()
        
        if current_data.get(entry_tf) is not None and len(current_data[entry_tf]) >= 60:
            # Procesar
            temp_strat.analyze_market(current_data)
            trigger_price = current_data[trigger_tf]['close'].iloc[-1]
            res = temp_strat.generate_signal(trigger_price, 1000.0, current_data)
            reason = res.get('reason', '')
            signal_counts['TOTAL_VELAS_EVALUADAS'] += 1
            if reason in signal_counts:
                signal_counts[reason] += 1
                
    total_signals_generated = signal_counts['OK']
    
    # ==========================================================================
    # FASE 3: AUDITORÍA Y ASERCIONES OBLIGATORIAS
    # ==========================================================================
    logger.info("\n--- EJECUTANDO ASERCIONES DE AUDITORÍA ---")
    
    if os.path.exists(csv_export_path):
        df_csv = pd.read_csv(csv_export_path)
    else:
        df_csv = pd.DataFrame()
        
    total_executed = experiments['Base (ATR, TP 1:1)']['metrics'].get('Total Trades', 0)
    
    # ASSERT 1: Trades <= Señales detectadas
    assert total_executed <= total_signals_generated, f"Inconsistencia: Trades ({total_executed}) > Señales ({total_signals_generated})"
    
    # ASSERT 2: Sin señales no puede haber trades
    assert not (total_signals_generated == 0 and total_executed > 0), "Inconsistencia: Trades generados con 0 señales detectadas."
    
    if len(df_csv) > 0:
        # ASSERT 3: Features numéricas no constantes ni vacías
        if 'dist_price_ema30' in df_csv.columns:
            assert not df_csv['dist_price_ema30'].eq(0.0).all(), "Inconsistencia: Feature 'dist_price_ema30' es toda 0.0"
        if 'rsi' in df_csv.columns:
            assert not df_csv['rsi'].eq(0.0).all(), "Inconsistencia: Feature 'rsi' es toda 0.0"
            
        # ASSERT 4: Columnas requeridas presentes
        required_cols = ['timestamp_in', 'timestamp_out', 'side', 'pnl_usdt', 'duration_mins', 'rsi', 'dist_price_ema30']
        for col in required_cols:
            assert col in df_csv.columns, f"Columna requerida faltante en CSV: {col}"
            
        # ASSERT 5: Duración
        assert df_csv['duration_mins'].mean() > 0, "Duración media 0, incompatible."
        
    logger.info("✔️ TODAS LAS ASERCIONES PASADAS EXITOSAMENTE.")

    # ==========================================================================
    # GENERAR REPORTE MD
    # ==========================================================================
    report_content = f"# 🔬 Reporte de Auditoría: {strategy_name}\n\n"
    
    report_content += "## 📊 1. Relación Señales vs Trades Ejecutados\n"
    report_content += "Pipeline auditado y aprobado. Trades registrados en CSV no superan a las señales teóricas, y conservan sus features inyectadas correctamente.\n\n"
    report_content += "| Configuración | Señales Detectadas | Trades Ejecutados |\n"
    report_content += "| --- | --- | --- |\n"
    for case, exp in experiments.items():
        texec = exp['metrics'].get('Total Trades', 0)
        report_content += f"| {case} | {total_signals_generated} | {texec} |\n"
        
    report_content += "\n## 🛑 2. Embudo de Señales (Cascada de Rechazos)\n"
    report_content += f"- **Velas Totales Evaluadas (Trigger):** {signal_counts['TOTAL_VELAS_EVALUADAS']}\n"
    report_content += f"- **Rechazo Macro (No Trend):** {signal_counts['NO_TREND']}\n"
    report_content += f"- **No hay Pullback:** {signal_counts['PULLBACK_MISS']}\n"
    report_content += f"- **Descartadas por Patrón de Vela Incorrecto:** {signal_counts['REJECT_BEARISH'] + signal_counts['REJECT_BULLISH']}\n"
    report_content += f"- **Descartadas por Cuerpo Pequeño (Body Ratio):** {signal_counts['REJECT_BODY']}\n"
    report_content += f"- **Descartadas por Cierre Invalido vs EMA:** {signal_counts['REJECT_CLOSE_BELOW_EMA'] + signal_counts['REJECT_CLOSE_ABOVE_EMA']}\n"
    report_content += f"- **Descartadas por Momentum (RSI Invalido):** {signal_counts['REJECT_RSI']}\n"
    report_content += f"- **Señales Finales Validadas (OK):** {signal_counts['OK']}\n"
    
    if len(df_csv) > 0:
        avg_metrics = {
            'Distancia a EMA30 (ATR)': df_csv['dist_price_ema30'].abs().mean(),
            'Body Ratio Medio': df_csv['body_ratio'].mean(),
            'Pendiente EMA30 Media': df_csv['slope_ema30'].abs().mean(),
            'Pullback Medio al Swing (ATR)': df_csv['dist_swing'].mean(),
            'Duración Promedio (Mins)': df_csv['duration_mins'].mean(),
            'MAE Medio (%)': df_csv['mae_pct'].mean(),
            'MFE Medio (%)': df_csv['mfe_pct'].mean(),
            'RSI Entrada Medio': df_csv['rsi'].mean()
        }
        report_content += "\n## ⏱️ 3. Métricas de Ejecución Avanzadas (Leídas del CSV Base)\n"
        report_content += "| Métrica | Promedio |\n"
        report_content += "| --- | --- |\n"
        for k, v in avg_metrics.items():
            report_content += f"| {k} | {v:.4f} |\n"
            
        df_csv['session'] = df_csv['utc_hour'].apply(get_session_name)
        report_content += "\n## 🌍 4. Sesiones de Trading (Leídas del CSV Base)\n"
        report_content += "| Sesión | Trades | Win Rate % | PnL Medio (USDT) |\n"
        report_content += "| --- | --- | --- | --- |\n"
        for name, group in df_csv.groupby('session'):
            tr = len(group)
            wr = float((group['pnl_usdt'] > 0).mean() * 100)
            pnl = float(group['pnl_usdt'].mean())
            report_content += f"| {name} | {tr} | {wr:.1f}% | {pnl:.4f} |\n"

    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'quantitative_lab_report.txt')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_content)
        
    project_txt_path = r"c:\Users\Usuario\Desktop\bot-simple-emas-moviles-rsi\quantitative_lab_report.txt"
    with open(project_txt_path, 'w', encoding='utf-8') as f:
        f.write(report_content)
        
    print("\n" + "="*80)
    print("🔬 LABORATORIO CUANTITATIVO (V3) COMPLETADO Y APROBADO")
    print(f"Reporte guardado en: {project_txt_path}")
    print("="*80 + "\n")
    settings.ENABLE_DETAILED_LOGS = orig_logs_flag

if __name__ == "__main__":
    run_quantitative_lab()
