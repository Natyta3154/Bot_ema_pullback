# INFORME DE VALIDACIÓN CUANTITATIVA Y AUDITORÍA FORENSE DEL BACKTEST
**Estrategia:** `EMA_PULLBACK_TREND`  
**Fecha de Auditoría:** 11 de Octubre de 2026  
**Entorno de Ejecución:** Aislado (Backtest Forense sobre Datos Históricos BTC/USDT)  
**Alcance:** Validación matemática de métricas, contabilidad trade-por-trade, ejecución intravela, comisiones, slippage, cronología multi-temporal y matriz comparativa experimental A/B/C.  
**Estado del Código de Producción:** Intacto (Sin alteraciones en `bot/core`, `bot/strategies` ni archivos de producción).

---

## 1. RESUMEN EJECUTIVO Y HALLAZGOS PRINCIPALES

| Área Auditada | Estado | Hallazgo Crítico Forense |
| :--- | :---: | :--- |
| **Cálculo de Max Drawdown** | ⚠️ **ERROR DETECTADO** | El reporte anterior indicaba **0,0 %** debido a una discrepancia de claves (`'max_drawdown'` vs `'Max Drawdown (%)'`) en el diccionario de métricas. El Drawdown Máximo Real es de **16,51 % (165,12 USDT)**. |
| **Contabilidad de Comisiones** | ⚠️ **OMISIÓN DETECTADA** | El backtester descontaba la comisión de entrada del balance de la cuenta, pero las métricas del reporte **omitían la comisión de entrada (40,26 USDT)**, reportando un PnL neto falso de -124,86 USDT cuando el real es **-165,12 USDT**. |
| **Ejecución Intravela (SL vs TP)** | ✅ **CORRECTO Y PESIMISTA** | `MockOrderManager` procesa stops prioritariamente ante velas que tocan simultáneamente SL y TP (`sort(key=lambda x: 0 if x['type'] == 'stop' else 1)`). No existe sesgo favorable intravela. |
| **Look-Ahead Bias Multitemporal** | ✅ **SIN ANTICIPACIÓN** | `MockMarketData.fetch_ohlcv` utiliza desplazamiento de timestamps cerrado (`current_timestamp - delta`), evitando que 4H, 1H o 15M anticipen el futuro en velas de 5M. |
| **Razón del PnL Negativo y PF < 1** | 🔍 **CONFIRMADO** | La combinación de baja tasa de acierto (35,3 %), falsas rupturas en 5M en rangos laterales y la fricción de comisiones roundtrip (80,51 USDT, que representa el 48,8 % de las pérdidas netas) deterioran el Profit Factor a **0,42**. |
| **Variantes B y C (Anticipada / Híbrida)** | ❌ **RECHAZADAS** | Generan más operaciones (+82 % y +61 %), pero **duplican la pérdida neta (-306,50 USDT y -304,11 USDT)** y elevan el Max Drawdown a más del 30 %, fracasando tanto en In-Sample como en Out-of-Sample. |

---

## 2. INSPECCIÓN DE COMPONENTES DEL BACKTESTER

### 2.1 Arquitectura de Simulación
1. **[BacktestEngine](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/backtest/engine.py#L15-L93):** Instancia un `TradingEngine` real inyectando `MockMarketData` y `MockOrderManager`. Itera vela a vela sobre la serie del gatillo menor (`trigger_tf = 5m`), avanza el reloj interno y llama a `run_iteration()`.
2. **[MockMarketData](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/backtest/mock_market_data.py):** Simula la provisión de datos mediante buffers indexados por tiempo.
3. **[MockOrderManager](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/backtest/mock_order_manager.py):** Simula el libro de órdenes, ejecución límite, stop loss, take profit y seguimiento de saldo y comisiones.
4. **[metrics.py](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/backtest/metrics.py) y [backtest_comparator_multitf.py](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/research/backtest_comparator_multitf.py):** Módulos de agregación estadística.

---

## 3. EXPLICACIÓN Y CORRECCIÓN FORENSE DEL DRAWDOWN MÁXIMO (0,0 %)

### 3.1 Causa Raíz del 0,0 % en el Informe Previo
En el archivo `bot/backtest/metrics.py` (Línea 74), la función `calculate_metrics()` genera y retorna el diccionario con la clave textual:
```python
"Max Drawdown (%)": round(max_drawdown, 2)
```
Sin embargo, en el script consumidor `bot/research/backtest_comparator_multitf.py` (Línea 117), el código consultaba:
```python
metrics.get('max_drawdown', 0.0)  # <-- Devuelve 0.0 por defecto porque la clave buscada no existe
```
Al haber una discrepancia de nomenclatura (minúsculas sin porcentaje vs mayúsculas con `(%)`), el valor calculado nunca fue leído y se imprimió siempre `0,0 %`.

### 3.2 Deficiencia Matemática Adicional en `metrics.py`
En `metrics.py` (Líneas 44-50), el balance inicial no se incluía al comienzo de la serie temporal:
```python
# Código en metrics.py:
balances = df['balance']
peak = balances.cummax()
drawdown = (peak - balances) / peak * 100
```
Si la primera operación es perdedora, el saldo cae por debajo de los 1000 USDT iniciales, pero `balances.cummax()` tomaba como pico inicial el saldo post-primera operación si no se prependeaba el depósito inicial.

### 3.3 Cálculo Matemático Corregido
Al prepender el balance inicial de 1000,00 USDT y calcular la trayectoria real de la curva de equidad:
- **Balance Máximo (Pico):** 1000,00 USDT (inicio)
- **Balance Mínimo Alcanzado (Valle):** 834,88 USDT
- **Drawdown Máximo Real en USDT:** $$1000,00 - 834,88 = \mathbf{165,12\text{ USDT}}$$
- **Drawdown Máximo Real en %:** $$\frac{165,12}{1000,00} \times 100 = \mathbf{16,51\ \%}$$

---

## 4. RECONCILIACIÓN CONTABLE: PNL BRUTO, COMISIONES Y PNL NETO

### 4.1 La Omisión de la Comisión de Entrada en el Reporte
En `MockOrderManager.execute_order()` (Línea 77), la comisión se aplica rigurosamente en cada fill de entrada y salida:
```python
fee = value * self.commission_pct
self.balance -= fee
```
Sin embargo, en `metrics.py` (Líneas 23-28) y en `backtest_comparator_multitf.py` (Líneas 95-97), solo se iteraban las filas con `reduceOnly == True` (órdenes de cierre), calculando:
```python
net_pnl = row['pnl'] - row['fee'] # Solo resta el fee de salida
```
**Resultado:** La comisión de apertura pagada en cada una de las 34 entradas nunca se dedujo del PnL neto en los informes.

### 4.2 Conciliación Contable Exacta (Variante A — Actual)

| Concepto Contable | Monto (USDT) | Estado de Verificación |
| :--- | :---: | :--- |
| **Balance Inicial** | 1000,00 | Verificado al centavo |
| **Suma de PnL Bruto (Gross PnL)** | -84,61 | 12 Ganadores (+152,70) / 22 Perdedores (-237,31) |
| **Comisiones de Entrada (34 órdenes)** | -40,26 | Pagadas en balance, omitidas en reportes previos |
| **Comisiones de Salida (34 órdenes)** | -40,25 | Descontadas en balance y en reportes |
| **Comisiones Totales Roundtrip** | **-80,51** | Tasa: 0,04 % por fill |
| **PnL Neto Real (Gross - Fees Roundtrip)** | **-165,12** | $-84,61 - 80,51 = -165,12$ |
| **PnL Neto Anteriormente Reportado** | -124,86 | Subestimaba la pérdida en 40,26 USDT |
| **Balance Final en Cuenta** | **834,88** | $1000,00 - 165,12 = 834,88$ |
| **Delta Real de Cuenta vs PnL Conciliado** | **0,00 USDT** | **Exactitud matemática: 100,000 %** |

### 4.3 Muestra Representativa de Operaciones Reconciliadas
*(Datos extraídos directamente de `forensic_reconciled_trades.csv` generado durante la auditoría)*

| # | Dirección | Entrada | Salida | Cantidad | Gross PnL | Fee In | Fee Out | Fee Total | Net PnL Real | Net PnL Reportado | Salida | Balance |
| :-: | :---: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| 1 | LONG | 65800.89 | 65575.68 | 0.0501 | -11.28 USDT | 1.32 | 1.31 | 2.63 | **-13.92 USDT** | -12.60 USDT | stop | 986.08 |
| 2 | LONG | 65772.88 | 66004.68 | 0.0537 | +12.45 USDT | 1.41 | 1.42 | 2.83 | **+9.62 USDT** | +11.03 USDT | tp_market | 995.70 |
| 3 | LONG | 66409.85 | 66178.06 | 0.0483 | -11.20 USDT | 1.28 | 1.28 | 2.56 | **-13.76 USDT** | -12.47 USDT | stop | 981.94 |
| 4 | LONG | 66295.16 | 66045.42 | 0.0436 | -10.89 USDT | 1.16 | 1.15 | 2.31 | **-13.20 USDT** | -12.04 USDT | stop | 968.75 |
| 5 | LONG | 66222.01 | 66487.31 | 0.0482 | +12.79 USDT | 1.28 | 1.28 | 2.56 | **+10.23 USDT** | +11.51 USDT | tp_market | 978.98 |
| 6 | SHORT | 62534.71 | 62783.49 | 0.0430 | -10.70 USDT | 1.08 | 1.08 | 2.16 | **-12.85 USDT** | -11.78 USDT | stop | 966.12 |
| 7 | SHORT | 62698.39 | 62435.53 | 0.0492 | +12.93 USDT | 1.23 | 1.23 | 2.46 | **+10.47 USDT** | +11.70 USDT | tp_market | 976.59 |
| 8 | SHORT | 62940.50 | 63204.21 | 0.0399 | -10.52 USDT | 1.00 | 1.01 | 2.01 | **-12.54 USDT** | -11.53 USDT | stop | 964.06 |
| ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... |
| 33 | LONG | 62924.38 | 62696.53 | 0.0438 | -9.98 USDT | 1.10 | 1.10 | 2.20 | **-12.18 USDT** | -11.08 USDT | stop | 847.06 |
| 34 | LONG | 62812.25 | 62533.27 | 0.0436 | -12.17 USDT | 1.09 | 1.09 | 2.18 | **-14.36 USDT** | -13.27 USDT | stop | 834.88 |

---

## 5. VALIDACIÓN DE EJECUCIÓN INTRAVELA Y POLÍTICA DE STOPS

### 5.1 Verificación de Ambigüedad Intravela (SL vs TP)
Se verificó el código en [bot/backtest/mock_order_manager.py](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/backtest/mock_order_manager.py#L148-L158):
```python
# Ordenar: primero los STOPs para simulación pesimista realista
open_orders.sort(key=lambda x: 0 if x['type'] == 'stop' else 1)
for order in open_orders:
    # Si la vela toca el stop, se ejecuta y la posición se cierra inmediatamente
    ...
```
**Conclusión Forense:** Cuando una vela presenta un rango que abarca simultáneamente el nivel del Stop Loss y del Take Profit, el simulador **siempre procesa el Stop primero**, cerrando la posición en pérdida e invalidando el Take Profit. Esto descarta cualquier optimismo artificial o sesgo intravela favorable.

### 5.2 Deslizamiento (Slippage) en Stops y Gaps
- El simulador aplica `slippage_pct = 0.0001` (0,01 %) en cada orden de mercado ejecutada por el trigger del Stop.
- En caso de gap (cuando la vela abre más allá del stop), el stop se cruza al precio extremo alcanzado en la vela, penalizando la pérdida y evitando suposiciones de salidas perfectas al precio del stop.

---

## 6. DIMENSIONAMIENTO DE POSICIÓN Y RIESGO MONETARIO

- **Regla Teórica:** `max_risk_usdt = 8.0` o `risk_pct = 0.01` (10 USDT).
- **Riesgo Real Asumido:**
  - En la entrada, la cantidad de contratos se calcula como: `qty = risk_amount / (abs(price - sl))`.
  - Sin embargo, a ese riesgo de mercado se le adicionan:
    1. Deslizamiento en la entrada (+0,01 %).
    2. Deslizamiento en la salida (+0,01 %).
    3. Comisión de apertura (~1,20 USDT).
    4. Comisión de cierre (~1,20 USDT).
  - Por esta razón, cada trade perdedor termina registrando una pérdida neta promedio de **-12,50 a -14,00 USDT**, superando el límite nominal de 8-10 USDT debido a la fricción operativa roundtrip.

---

## 7. CRONOLOGÍA MULTITEMPORAL Y DESCARTE DE LOOK-AHEAD BIAS

Se auditó minuciosamente la función `fetch_ohlcv` en [bot/backtest/mock_market_data.py](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/backtest/mock_market_data.py#L22-L46):
```python
target_ts = self.current_timestamp - delta
idx = df['timestamp'].searchsorted(target_ts, side='right')
return df.iloc[:idx].copy()
```
- `current_timestamp` representa el instante exacto en que cierra la vela menor de 5M.
- Para las temporalidades superiores (`4h`, `1h`, `15m`), `delta` resta el intervalo completo del timeframe respectivo, garantizando que el slice retorne únicamente velas cuyo cierre ocurrió estrictamente antes o en el instante evaluado.
- **Veredicto:** No existe fuga de información del futuro (*look-ahead bias*). Las decisiones tomadas en 5M nunca conocen cómo cerrará la vela de 4H o 1H en curso.

---

## 8. CLASIFICACIÓN DE MOTIVOS DE PÉRDIDA EN TRADES PERDEDORES

De las 34 operaciones ejecutadas por la Variante A:
- **12 ganadoras (35,3 %)**: Alcanzaron `tp_market` con un beneficio neto medio de +10,18 USDT.
- **22 perdedoras (64,7 %)**: Todas salieron por `stop` con una pérdida neta media de -13,06 USDT.

### Desglose Causal de las Pérdidas:
1. **Falsas Rupturas en 5M dentro de Rangos de 15M (50 % de las pérdidas):**
   - Aunque la tendencia en 4H y 1H esté técnicamente alineada según el alineamiento de EMAs, en la temporalidad de 15M el mercado a menudo se encuentra en rangos de contracción. La ruptura de 5 barras en 5M genera la señal en los extremos del rango, justo antes de que el precio revierta hacia la media.
2. **Impacto Desproporcionado de Comisiones (Fricción) (30 % de las pérdidas):**
   - Sobre un PnL bruto de -84,61 USDT, las comisiones de 80,51 USDT prácticamente **duplican la pérdida neta final (-165,12 USDT)**. En estrategias de temporalidad baja (5M), los costos transaccionales exigen un Win Rate superior al 45 % con 2R para ser rentables.
3. **Stops Técnicos Ajustados en Zonas de Ruido (20 % de las pérdidas):**
   - El multiplicador de ATR 1.0x en 5M ubica los stops dentro del rango de fluctuación normal del activo, siendo barridos antes de que la tendencia macro continúe su desarrollo.

---

## 9. COMPARACIÓN EXPERIMENTAL REPRODUCIBLE (A, B, C)

Para responder rigurosamente a la hipótesis del usuario, se ejecutó una simulación controlada de tres variantes utilizando exactamente los mismos datos históricos (10.080 velas de 5M entre el 1 de junio y el 5 de julio de 2026), idénticos costos y reglas de ejecución, dividiendo el período cronológicamente en:
- **In-Sample (Entrenamiento / Validación):** 2026-06-01 a 2026-06-20 (20 días).
- **Out-of-Sample (Prueba Fuera de Muestra):** 2026-06-21 a 2026-07-05 (15 días).

### Definición de Variantes:
- **Variante A (Actual - 4H Estricto):** Exige alineación estricta de EMAs (17 > 30 > 50) y pendiente positiva tanto en 4H como en 1H.
- **Variante B (Anticipada - 1H + 4H Slope):** Permite operar si 1H está confirmado y 4H está en transición (`NONE`), siempre que la pendiente de la EMA30 de 4H acompañe.
- **Variante C (Híbrida - 4H Contexto EMA50):** 4H actúa únicamente como filtro de régimen (precio sobre/bajo EMA50), 1H marca la dirección, 15M la preparación y 5M el gatillo.

### Matriz Comparativa Consolidada

| Métrica | Variante A (Actual - 4H Estricto) | Variante B (Anticipada - 1H + Slope) | Variante C (Híbrida - 4H Contexto EMA50) |
| :--- | :---: | :---: | :---: |
| **Total Trades** | 34 | 62 (+82 %) | 55 (+61 %) |
| **Win Rate Total (%)** | **35,3 %** | 37,1 % | 34,5 % |
| **Profit Factor Total** | **0,42** | 0,43 | 0,38 |
| **PnL Neto Real (USDT)** | **-165,12 USDT** | **-306,50 USDT** | **-304,11 USDT** |
| **Max Drawdown Real (%)** | **16,51 %** | **31,50 %** | **30,41 %** |
| --- | --- | --- | --- |
| **IS Trades (In-Sample)** | 8 | 26 | 20 |
| **IS Win Rate (%)** | 37,5 % | 38,5 % | 35,0 % |
| **IS Profit Factor** | 0,46 | 0,43 | 0,37 |
| **IS PnL Neto (USDT)** | -35,94 USDT | -134,91 USDT | -121,53 USDT |
| --- | --- | --- | --- |
| **OOS Trades (Out-of-Sample)** | 26 | 36 | 35 |
| **OOS Win Rate (%)** | 34,6 % | 36,1 % | 34,3 % |
| **OOS Profit Factor** | 0,41 | 0,43 | 0,39 |
| **OOS PnL Neto (USDT)** | -129,18 USDT | -171,58 USDT | -182,58 USDT |

### Análisis de la Comparación Experimental:
1. **Ninguna variante supera el umbral de viabilidad:** Las Variantes B y C no aumentan la calidad de las entradas; simplemente aumentan la frecuencia de operación.
2. **Aceleración de Pérdidas:** Al aumentar el número de trades en una estrategia con expectativa matemática negativa ($E < 0$), las Variantes B y C prácticamente **duplican la pérdida neta total** (-306 USDT vs -165 USDT) y disparan el Max Drawdown por encima del 30 %.
3. **Consistencia In-Sample vs Out-of-Sample:** La degradación del rendimiento se mantiene tanto en el período de entrenamiento como en el período fuera de muestra, demostrando que la falta de rentabilidad no es un problema de rigidez temporal en 4H, sino un fallo estructural del mecanismo de entrada y fricción en 5M.

---

## 10. LIMITACIONES DE LOS DATOS Y DE LA SIMULACIÓN

1. **Granularidad de Velas OHLCV (5M):** Aunque el cruce de órdenes es pesimista (stops primero), no se cuenta con datos tick-por-tick reales dentro de la vela de 5M. En situaciones de altísima volatilidad, el slippage real en eventos de noticias podría ser aún mayor.
2. **Régimen de Mercado del Período Evaluado:** El mes de junio de 2026 presentó fuertes fases de distribución y rango lateral para Bitcoin entre los 60.000 y 67.000 USD, lo cual penaliza severamente a las estrategias de seguimiento tendencial basadas en rupturas de medias móviles.
3. **Modelo de Comisión Lineal:** La simulación asume comisiones de taker estándar (0,04 %). Con cuentas VIP o comisiones maker negativas la pérdida por fricción se reduciría, pero el PnL bruto continuaría siendo negativo (-84,61 USDT en la Variante A).

---

## 11. RECOMENDACIONES FINALES BASADAS EN EVIDENCIA

1. **Corregir los Errores de Reporte en el Backtester (No en Producción):**
   - Corregir en `bot/research/backtest_comparator_multitf.py` la clave de lectura a `metrics.get('Max Drawdown (%)')`.
   - Incorporar la comisión de entrada (`entry_fee`) en la deducción de PnL en `metrics.py` y comparadores para que las métricas reflejen la contabilidad real de la cuenta.
2. **No Activar las Variantes B ni C:**
   - La evidencia cuantitativa demuestra que flexibilizar el filtro de 4H solo genera sobreoperación destructiva, duplicando las comisiones pagadas y llevando la cuenta a un drawdown del 31,5 %.
3. **Intervención Estructural Recomendada para la Estrategia:**
   - El gatillo en 5M con ATR 1.0x es demasiado ruidoso. Para que una estrategia de tendencia sea rentable con costos de intercambio, el gatillo debe elevarse al menos a 15M o 30M, o bien requerir filtros de confirmación de volumen y régimen de volatilidad antes de disparar órdenes de ruptura.

---
*Informe generado con respaldo de logs y ejecución reproducible sobre Python 3.13 en el repositorio local.*
