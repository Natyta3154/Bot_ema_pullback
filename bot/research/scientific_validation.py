import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime
import scipy.stats as stats

# Asegurar path correcto de importaciones
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from bot.config import settings
from bot.core.trade_logger import logger
from bot.backtest.data_loader import DataLoader
from bot.backtest.engine import BacktestEngine
from bot.strategies.factory import StrategyFactory

def run_scientific_validation():
    print("==========================================================")
    print("🔬 INICIANDO PIPELINE DE VALIDACIÓN CIENTÍFICA CUANTITATIVA")
    print("==========================================================")
    
    # 1. CARGA DE DATOS HISTÓRICOS
    logger.info("[PASO 1] Cargando datos históricos...")
    strategy_name = settings.ACTIVE_STRATEGY
    loader = DataLoader()
    start = settings.BACKTEST_PARAMS['start_date']
    end = settings.BACKTEST_PARAMS['end_date']
    
    tfs = [settings.STRATEGY_PARAMS[strategy_name].get('entry_tf', '15m'), 
           settings.STRATEGY_PARAMS[strategy_name].get('macro_tf', '1h')]
    tfs = list(set([tf for tf in tfs if tf]))
    
    dfs = {}
    for tf in tfs:
        df = loader.fetch_data(tf, start, end)
        if df is not None and not df.empty:
            dfs[tf] = df
            
    if not dfs:
        logger.error("No se pudieron cargar datos históricos.")
        return
        
    # 2. CONFIGURAR AMBIENTE Y BAJAR UMBRALES DE DECISIÓN
    # Relajamos los umbrales para forzar la generación de una muestra grande de trades
    # y así responder si los filtros de volumen y estabilidad aportan ventaja estadística real.
    logger.info("[PASO 2] Relajando filtros de decisión para obtener muestra representativa...")
    orig_thresholds = getattr(settings, 'DECISION_THRESHOLDS', {"min_score": 75.0, "min_confidence": 80.0}).copy()
    settings.DECISION_THRESHOLDS = {"min_score": 45.0, "min_confidence": 45.0}
    
    settings.ENVIRONMENT = "PRE_BACKTEST"
    temp_strategy = StrategyFactory.create_strategy(strategy_name, None, None)
    temp_strategy.analyze_market(dfs)
    settings.ENVIRONMENT = "BACKTEST"
    
    # 3. EJECUTAR EL BACKTEST SENSITIVO
    logger.info("[PASO 3] Ejecutando simulación de backtest sensitivo...")
    engine = BacktestEngine(dfs)
    history = engine.run()
    
    # Restaurar umbrales
    settings.DECISION_THRESHOLDS = orig_thresholds
    
    if not history:
        logger.warning("No se generó ninguna operación incluso con filtros relajados.")
        return
        
    # 4. RECONSTRUIR OPERACIONES Y EXTRAER CARACTERÍSTICAS
    logger.info("[PASO 4] Reconstruyendo operaciones y consolidando dataset...")
    trades_data = []
    current_entry = None
    
    for fill in history:
        if not fill['reduceOnly']:
            current_entry = fill
        else:
            if current_entry:
                feats = fill.get('entry_features', {})
                if not feats and 'features' in current_entry:
                    feats = current_entry['features']
                
                trades_data.append({
                    'timestamp': fill['timestamp'],
                    'side': current_entry['side'],
                    'entry_price': current_entry['price'],
                    'exit_price': fill['price'],
                    'pnl_usdt': fill['pnl'],
                    'fee': fill['fee'] + current_entry['fee'],
                    'score': feats.get('score', 0.0),
                    'confidence': feats.get('confidence', 0.0),
                    'stability_score': feats.get('stability_score', 50.0),
                    'dispersion_pct': feats.get('dispersion_pct', 0.0),
                    'vol_ratio': feats.get('vol_ratio', 1.0),
                    'volatility_pct': feats.get('volatility_pct', 0.0)
                })
                current_entry = None
                
    df_trades = pd.DataFrame(trades_data)
    total_trades = len(df_trades)
    logger.info(f"Dataset consolidado con éxito. Total de operaciones completas: {total_trades}")
    
    if total_trades < 5:
        logger.warning("Muestra estadística demasiado pequeña para realizar pruebas significativas.")
        return

    # 5. PRUEBAS DE HIPÓTESIS ESTADÍSTICAS
    logger.info("[PASO 5] Corriendo pruebas de hipótesis científicas...")
    
    # HIPÓTESIS 1: Ventaja del Volumen de Ruptura (Welch's t-test)
    high_vol = df_trades[df_trades['vol_ratio'] >= 1.5]['pnl_usdt']
    low_vol = df_trades[df_trades['vol_ratio'] < 1.5]['pnl_usdt']
    
    h1_p_val = h1_t_stat = np.nan
    if len(high_vol) >= 2 and len(low_vol) >= 2:
        h1_t_stat, h1_p_val = stats.ttest_ind(high_vol, low_vol, equal_var=False)
    
    # HIPÓTESIS 2: Ventaja de Estabilidad Estructural (Welch's t-test)
    stable_struct = df_trades[df_trades['stability_score'] == 100.0]['pnl_usdt']
    unstable_struct = df_trades[df_trades['stability_score'] < 100.0]['pnl_usdt']
    
    h2_p_val = h2_t_stat = np.nan
    if len(stable_struct) >= 2 and len(unstable_struct) >= 2:
        h2_t_stat, h2_p_val = stats.ttest_ind(stable_struct, unstable_struct, equal_var=False)
        
    # HIPÓTESIS 3: Correlación del Score de Decisión (Spearman & Pearson)
    pearson_corr, pearson_p = stats.pearsonr(df_trades['score'], df_trades['pnl_usdt'])
    spearman_corr, spearman_p = stats.spearmanr(df_trades['score'], df_trades['pnl_usdt'])

    # 6. GENERAR INFORME CIENTÍFICO (MARKDOWN ARTIFACT)
    logger.info("[PASO 6] Generando Informe de Validación Científica...")
    
    # Crear estructura del reporte
    report_content = f"""# Informe de Validación Científica de Ventaja Estadística (BTC/USDT)
Generado el: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Estrategia Evaluada: `{strategy_name}`
Total de operaciones simuladas (filtros relajados): `{total_trades}`

## Resumen Ejecutivo
Este informe evalúa científicamente si los filtros de decisión propuestos en el bot (Volumen, Estabilidad Estructural y Puntuación Ponderada) representan una **ventaja estadística real** (alpha matemático) o si los resultados pasados se deben al azar (ruido).

---

## 🧪 Hipótesis 1: El Filtro de Volumen de Ruptura (Breakout Volume Edge)
* **Pregunta científica:** ¿El volumen superior a 1.5x de su SMA en la vela de ruptura produce operaciones con mayor PnL en el retesteo?
* **Muestra:**
  * Operaciones con Alto Volumen (`>= 1.5x`): `{len(high_vol)}` (PnL Medio: `{high_vol.mean():.4f} USDT`)
  * Operaciones con Bajo Volumen (`< 1.5x`): `{len(low_vol)}` (PnL Medio: `{low_vol.mean():.4f} USDT`)
* **Resultado del t-test de Welch:**
  * Estadístico t: `{h1_t_stat:.4f}`
  * **Valor p (p-value):** `{h1_p_val:.6f}`
* **Conclusión Científica:**
  {"**VENTAJA CONFIRMADA:** El valor p es menor que 0.05. Existe evidencia estadísticamente significativa de que operar con alto volumen de ruptura genera retornos superiores." if h1_p_val < 0.05 else "**SIN VENTAJA SIGNIFICATIVA:** El valor p es mayor que 0.05. No podemos rechazar la hipótesis nula; la diferencia en PnL puede deberse al azar."}

---

## 🧪 Hipótesis 2: El Filtro de Estabilidad Estructural (Structure Stability Edge)
* **Pregunta científica:** ¿Operar cuando hay consenso absoluto de tendencia macro (100% de estabilidad en todas las ventanas de pivotes) mejora la rentabilidad frente a estructuras inestables?
* **Muestra:**
  * Operaciones Estables (`Stability = 100.0`): `{len(stable_struct)}` (PnL Medio: `{stable_struct.mean():.4f} USDT`)
  * Operaciones Inestables (`Stability < 100.0`): `{len(unstable_struct)}` (PnL Medio: `{unstable_struct.mean():.4f} USDT`)
* **Resultado del t-test de Welch:**
  * Estadístico t: `{h2_t_stat:.4f}`
  * **Valor p (p-value):** `{h2_p_val:.6f}`
* **Conclusión Científica:**
  {"**VENTAJA CONFIRMADA:** El valor p es menor que 0.05. Operar bajo estabilidad estructural del 100% reduce el ruido local y tiene un impacto positivo estadísticamente significativo." if h2_p_val < 0.05 else "**SIN VENTAJA SIGNIFICATIVA:** El valor p es mayor que 0.05. La estabilidad estructural no muestra una ventaja estadísticamente significativa por sí sola en este conjunto de datos."}

---

## 🧪 Hipótesis 3: La Predictibilidad del Score Global de Decisión (Decision Score Edge)
* **Pregunta científica:** ¿A mayor puntaje del Decision Engine, mayor es la ganancia de la operación? (Correlación Score vs PnL).
* **Métricas de Correlación:**
  * **Coeficiente Pearson (Lineal):** `{pearson_corr:.4f}` (Valor p: `{pearson_p:.6f}`)
  * **Coeficiente Spearman (Rango/No lineal):** `{spearman_corr:.4f}` (Valor p: `{spearman_p:.6f}`)
* **Conclusión Científica:**
  {"**PREDICTIBILIDAD VALIDADA:** Existe una correlación estadísticamente significativa (p < 0.05). El Score del Decision Engine funciona como una variable predictora de la calidad del trade." if spearman_p < 0.05 else "**PREDICTIBILIDAD NO VALIDADA:** No hay correlación lineal ni monótona estadísticamente significativa (p > 0.05). El score por sí solo no garantiza proporcionalidad en ganancias."}

---

## 🔬 Matriz de Correlaciones Completa
Correlaciones de Pearson entre las variables del trade y el PnL:
"""
    # Computar matriz de correlación
    corr_matrix = df_trades[['pnl_usdt', 'score', 'confidence', 'stability_score', 'vol_ratio', 'volatility_pct']].corr()
    
    # Formatear tabla markdown para la matriz
    headers = ["Variable"] + list(corr_matrix.columns)
    report_content += "| " + " | ".join(headers) + " |\n"
    report_content += "| " + " | ".join(["---"] * len(headers)) + " |\n"
    for idx, row in corr_matrix.iterrows():
        row_vals = [idx] + [f"{val:.4f}" for val in row]
        report_content += "| " + " | ".join(row_vals) + " |\n"
        
    # Guardar en directorio de artefactos del Agente
    artifacts_dir = r"C:\Users\Usuario\.gemini\antigravity-ide\brain\5b3e98b9-a148-48aa-9311-88783283d749"
    os.makedirs(artifacts_dir, exist_ok=True)
    report_path = os.path.join(artifacts_dir, "scientific_validation_report.md")
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_content)
        
    print("\n" + "="*80)
    print("🧪 PIPELINE DE VALIDACIÓN CIENTÍFICA FINALIZADO CON ÉXITO")
    print("="*80)
    print(f"Informe guardado en: {report_path}")
    print("\nResumen de Pruebas Estadísticas:")
    print(f" -> Hipótesis 1 (Volumen): p-value = {h1_p_val:.6f} | {'Ventaja Confirmada' if h1_p_val < 0.05 else 'Sin ventaja significativa'}")
    print(f" -> Hipótesis 2 (Estabilidad): p-value = {h2_p_val:.6f} | {'Ventaja Confirmada' if h2_p_val < 0.05 else 'Sin ventaja significativa'}")
    print(f" -> Hipótesis 3 (Correlación Score): p-value = {spearman_p:.6f} | {'Predictibilidad Confirmada' if spearman_p < 0.05 else 'Sin predictibilidad'}")
    print("="*80 + "\n")

if __name__ == "__main__":
    run_scientific_validation()
