import pandas as pd
import os
import sys

# Agregar path raiz
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from bot.config import settings

def run_comparator():
    print("==========================================================")
    print("   🔍 INICIANDO COMPARADOR: LIVE VS BACKTEST")
    print("==========================================================")
    
    live_csv_path = settings.LIVE_RAW_TRADES_CSV
    backtest_csv_path = 'lab_raw_trades.csv'
    
    if not os.path.exists(live_csv_path):
        print(f"❌ No se encontró el archivo de Live Trading: {live_csv_path}")
        print("💡 Sugerencia: Deja corriendo el bot en modo PAPER durante algunas horas/días.")
        return
        
    if not os.path.exists(backtest_csv_path):
        print(f"❌ No se encontró el archivo de Backtest: {backtest_csv_path}")
        print("💡 Sugerencia: Ejecuta quantitative_lab.py primero para generar los datos.")
        return

    # Cargar DataFrames
    try:
        df_live = pd.read_csv(live_csv_path)
        df_backtest = pd.read_csv(backtest_csv_path)
    except Exception as e:
        print(f"❌ Error leyendo CSVs: {e}")
        return
        
    if df_live.empty:
        print("⚠️ El archivo de Live Trading está vacío. Espera a que procese algunas velas.")
        return

    # Normalizar timestamps para cruce
    df_live['timestamp'] = pd.to_datetime(df_live['timestamp']).dt.round('min')
    df_backtest['timestamp'] = pd.to_datetime(df_backtest['timestamp']).dt.round('min')
    
    # Hacer merge (Inner join) por timestamp
    # Solo comparamos las velas donde el bot EN VIVO estuvo encendido.
    merged = pd.merge(df_live, df_backtest, on='timestamp', suffixes=('_live', '_bt'))
    
    if merged.empty:
        print("⚠️ No hay timestamps coincidentes entre el archivo en Vivo y el Backtest.")
        print("Esto es normal si el bot en vivo acaba de empezar y el backtest no incluye hoy.")
        print("👉 Asegúrate de que settings.BACKTEST_PARAMS['end_date'] incluya hoy.")
        return
        
    print(f"\n📊 Se encontraron {len(merged)} velas coincidentes para comparar.")
    
    total = len(merged)
    divergencias = 0
    divergencias_detalle = []
    
    for idx, row in merged.iterrows():
        ts = row['timestamp']
        
        # Comparar Acciones
        action_live = str(row['action_live'])
        action_bt = str(row['action_bt'])
        if action_live != action_bt:
            divergencias += 1
            divergencias_detalle.append(f"[{ts}] Acción diverge: Live={action_live}, Backtest={action_bt}")
            continue # Si difieren aquí, las features seguro difieren por otra cosa
            
        # Si la acción fue LONG o SHORT, comparar precios teóricos vs reales
        if action_live in ['LONG', 'SHORT']:
            price_live = float(row.get('price_live', 0))
            price_bt = float(row.get('price_bt', 0))
            diff_pct = abs(price_live - price_bt) / price_bt * 100 if price_bt > 0 else 0
            
            if diff_pct > 0.05: # Tolerancia de 0.05% de slippage en la detección de la señal
                divergencias_detalle.append(f"[{ts}] Slippage Anormal en Precio Señal: Live={price_live}, Backtest={price_bt} (Diff {diff_pct:.3f}%)")
                
        # Comparar Features Matemáticas Clave
        # RSI
        rsi_live = float(row.get('rsi_live', 0))
        rsi_bt = float(row.get('rsi_bt', 0))
        if abs(rsi_live - rsi_bt) > 0.1: # Tolerancia decimal
            divergencias += 1
            divergencias_detalle.append(f"[{ts}] RSI diverge: Live={rsi_live:.2f}, Backtest={rsi_bt:.2f}")
            
        # ATR
        atr_live = float(row.get('atr_live', 0))
        atr_bt = float(row.get('atr_bt', 0))
        # Para ATR una tolerancia porcentual porque el valor absoluto depende del precio
        if atr_bt > 0 and abs(atr_live - atr_bt) / atr_bt > 0.05:
            divergencias += 1
            divergencias_detalle.append(f"[{ts}] ATR diverge: Live={atr_live:.2f}, Backtest={atr_bt:.2f}")

    match_rate = ((total - divergencias) / total) * 100
    
    print("\n==========================================================")
    print("   📈 REPORTE DE COMPARACIÓN")
    print("==========================================================")
    print(f"Total Velas Comparadas: {total}")
    print(f"Divergencias Encontradas: {divergencias}")
    print(f"Tasa de Precisión (Match Rate): {match_rate:.2f}%")
    print("==========================================================")
    
    if divergencias > 0:
        print("\n📝 Detalle de Divergencias:")
        for div in divergencias_detalle[:20]: # Mostrar top 20
            print(f"  - {div}")
        if len(divergencias_detalle) > 20:
            print(f"  ... y {len(divergencias_detalle) - 20} divergencias más.")
    else:
        print("\n✅ EXCELENTE: El bot en vivo es 100% idéntico al motor de Backtest.")
        
    # Guardar reporte a TXT
    report_path = 'live_vs_backtest_report.txt'
    try:
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("=== REPORTE DE COMPARACIÓN LIVE VS BACKTEST ===\n")
            f.write(f"Velas Comparadas: {total}\n")
            f.write(f"Match Rate: {match_rate:.2f}%\n\n")
            if divergencias_detalle:
                f.write("Divergencias:\n")
                for div in divergencias_detalle:
                    f.write(f"{div}\n")
            else:
                f.write("Sin divergencias. El motor en vivo coincide 100% con el backtest.\n")
        print(f"\nReporte detallado guardado en: {report_path}")
    except Exception as e:
        print(f"No se pudo guardar el reporte TXT: {e}")

if __name__ == "__main__":
    run_comparator()
