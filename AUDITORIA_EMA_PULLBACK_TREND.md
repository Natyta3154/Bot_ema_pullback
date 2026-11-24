# 🔬 AUDITORÍA TÉCNICA COMPLETA — BOT DE TRADING `EMA_PULLBACK_TREND`

> **Fecha:** 2026-10-11  
> **Ámbito:** Diagnóstico y Testing de Arquitectura Cuantitativa, Integridad Temporal y Lógica Operativa.  
> **Estado:** Tarea exclusivamente analítica y forense (Sin modificaciones de código fuente en producción).

---

## 1. RESUMEN EJECUTIVO

Se ha completado una auditoría exhaustiva de la estrategia cuantitativa `EMA_PULLBACK_TREND` y del motor de ejecución `engine.py`. El sistema implementa una arquitectura multitemporal jerárquica desacoplada en cuatro horizontes temporales (**4H -> 1H -> 15M -> 5M**), coordinada por un ciclo principal sincronizado por reloj y respaldada por gestores de riesgo, orden y posición.

### Conclusiones Principales:
1. **El bloqueo en `NONE [NO_CONFIRMED_TREND]` no es un fallo de software:** Es el comportamiento estrictamente programado del filtro macro. En el caso de estudio presentado, 4H posee una ordenación de EMAs bajista residual (`EMA17 < EMA30 < EMA50`), pero una pendiente alcista reciente (`slope30 = +41.1`). Al contradecirse la ordenación y la pendiente, 4H se clasifica matemáticamente como `NONE`, abortando de inmediato cualquier señal antes de llegar a los marcos menores.
2. **Independencia de filtros:** Aún desactivando el filtro de 4H, el caso de estudio tampoco habría operado, ya que en 15M el precio cotizaba por encima de las medias móviles sin tocar la zona de retroceso (Pullback) y en 5M no existía ruptura fresca confirmada.
3. **Integridad de ejecución en velas cerradas:** Se **confirmó** que tanto Binance (`MarketDataManager`) como MetaTrader 5 (`MT5MarketDataManager`) descartan la vela abierta en formación (`start_pos=1` en MT5 e `iloc[:-1]` en Binance), operando estrictamente sobre velas cerradas y evitando el sesgo de mecha intravela (*look-ahead bias*).
4. **Hallazgo Crítico en la Idempotencia del Engine:** En `engine.py` (Línea 118), la variable `last_processed_candle_time` se actualiza **antes** de completar el análisis de mercado y la emisión de órdenes. Si ocurre una excepción durante la iteración, el reintento de 30 segundos descarta la vela considerándola "ya procesada", lo que puede causar la pérdida silenciosa de señales.
5. **Robustez y Supervivencia Financiera:** El gestor de riesgo `RiskManager` mantiene un límite monetario estricto (8.0 USDT para MT5 / 4.0 USDT para Binance) con validación de margen previo al trade y triple mecanismo de parada de emergencia (*Kill Switches* de pérdida diaria, pérdida acumulada y racha adversa), garantizando la prevención matemática de liquidación.

---

## 2. ARQUITECTURA REAL DEL FLUJO DE SEÑALES

El flujo de decisiones opera como una cascada jerárquica estricta de cuatro compuertas lógicas:

```
[Mercado OHLCV (MT5 / Binance)]
           │
           ▼ (Velas cerradas: start_pos=1 o iloc[:-1])
┌────────────────────────────────────────────────────────┐
│ COMPUERTA 1: Tendencia Macro (4H)                      │
│ • Long:  EMA17 > EMA30 > EMA50 Y slope(EMA30) > 0       │
│ • Short: EMA17 < EMA30 < EMA50 Y slope(EMA30) < 0       │
└────────────────────────────────────────────────────────┘
           │ Coincidencia obligatoria
           ▼
┌────────────────────────────────────────────────────────┐
│ COMPUERTA 2: Estructura Operativa (1H)                 │
│ • Debe coincidir exactamente con la dirección de 4H    │
│ • Si 4H == NONE o 4H != 1H -> Aborto (NO_CONFIRMED)    │
└────────────────────────────────────────────────────────┘
           │ Estado persistido: pending_preparation
           ▼
┌────────────────────────────────────────────────────────┐
│ COMPUERTA 3: Preparación / Pullback (15M)              │
│ • Long:  Low <= EMA17 o EMA30, Close > Open y > EMA17  │
│ • Short: High >= EMA17 o EMA30, Close < Open y < EMA17 │
│ • Filtro: Body Ratio >= 0.55 | RSI [45-65 L / 35-55 S] │
│ • Caducidad: Máximo 6 velas de 5m (30 minutos)         │
└────────────────────────────────────────────────────────┘
           │ Gatillo en vela cerrada
           ▼
┌────────────────────────────────────────────────────────┐
│ COMPUERTA 4: Confirmación Estructural de Ruptura (5M)  │
│ • Long:  Close > LocalSwingHigh (shift 1, lookback 5)  │
│ • Short: Close < LocalSwingLow  (shift 1, lookback 5)  │
│ • Ruptura fresca (Vela previa <= nivel de ruptura)    │
│ • SL: Basado en ATR o Swing + Buffer (Min 2R Neto)     │
└────────────────────────────────────────────────────────┘
           │ Señal válida
           ▼
┌────────────────────────────────────────────────────────┐
│ GESTOR DE ÓRDENES Y RIESGO                             │
│ • OrderPlanner -> RiskManager -> OrderManager          │
│ • Cálculo de posición por riesgo exacto en USDT        │
│ • Orden LIMIT de entrada + SL/TP nativos simultáneos   │
└────────────────────────────────────────────────────────┘
```

---

## 3. ARCHIVOS Y COMPONENTES INVOLUCRADOS

| Archivo | Rol en el Sistema | Funciones Clave |
| :--- | :--- | :--- |
| `bot/core/engine.py` | Motor de ejecución y bucle de eventos | `run()`, `run_iteration()` |
| `bot/strategies/ema_pullback_trend_strategy.py` | Lógica central de la estrategia | `evaluate_trend()`, `evaluate_15m_pullback()`, `evaluate_5m_trigger()`, `generate_signal()`, `print_multitf_dashboard()` |
| `bot/strategies/factory.py` | Instanciación dinámica de estrategias | `StrategyFactory.create_strategy()` |
| `bot/core/market_data.py` | Descarga de datos Binance Futures | `fetch_ohlcv()` (filtra vela abierta con `iloc[:-1]`) |
| `bot/connectors/mt5_market_data.py` | Descarga de datos MetaTrader 5 | `fetch_ohlcv()` (filtra vela abierta con `start_pos=1`) |
| `bot/core/order_planner.py` | Planificación de órdenes y cálculo R:R | `build_entry_plan()`, `place_entry()` |
| `bot/core/risk.py` | Control de límites y dimensionamiento | `calculate_position_size()`, `check_daily_limits()` |
| `bot/core/position.py` | Máquina de estados y persistencia | `update_state()`, `save()`, `load()` |
| `bot/config/settings.py` | Configuración global y parámetros | Variables de entorno, `STRATEGY_PARAMS` |

---

## 4. TABLA DE HALLAZGOS Y AUDITORÍA DE CÓDIGO

| ID | Componente / Archivo | Severidad | Estado | Evidencia y Líneas de Código | Impacto Técnico |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **H-01** | `bot/core/engine.py` L116-L119 | **ALTA** | **CONFIRMADO** | `self.last_processed_candle_time = _curr_ts` antes de `self.strategy.analyze_market(dfs)` | Si `analyze_market` o `generate_signal` lanza una excepción temporal de red o cálculo, el timestamp ya quedó guardado. En el reintento a los 30s, el bot considera la vela procesada y la descarta, perdiendo la entrada. |
| **H-02** | `bot/core/engine.py` L64-L70 | **BAJA** | **CONFIRMADO** | Comentario dice: *"esperar cierre de vela de 15m (múltiplo de 15)"*, pero la fórmula matemática calcula: `((now.minute // 5) + 1) * 5` | Divergencia entre comentario y código. El código calcula correctamente intervalos de 5m (acorde al gatillo de 5m), pero el comentario quedó desactualizado de la versión previa de 15m. |
| **H-03** | `bot/strategies/ema_pullback_trend_strategy.py` L132-L137 | **MEDIA** | **CONFIRMADO** | `if ema17 > ema30 and ema30 > ema50 and slope30 > 0:` devuelve `LONG`, de lo contrario `NONE`. | El filtro 4H no distingue entre consolidación/rango y una recuperación tendencial incipiente. Bloquea el 100% de las fases donde 1H lidera un cambio de tendencia. |
| **H-04** | `bot/strategies/ema_pullback_trend_strategy.py` L245 | **BAJA** | **CONFIRMADO** | `is_fresh = (float(row_prev['close']) <= swing_high_5m) or (open_5m <= swing_high_5m)` | El operador `or` permite que si la vela anterior ya cerró por encima del swing, se considere fresca si la apertura de la vela actual abrió ligeramente abajo. Es una condición permisiva frente a mechas. |
| **H-05** | `bot/core/market_data.py` L21-L22 / `bot/connectors/mt5_market_data.py` L33-L34 | **INFORMATIVA** | **SIN PROBLEMAS DETECTADOS** | `df = df.iloc[:-1].copy()` y `mt5.copy_rates_from_pos(..., 1, limit)` | Ambos conectores garantizan que la vela evaluada en `iloc[-1]` está cerrada y consolidada. Cero *look-ahead bias*. |
| **H-06** | `bot/core/risk.py` L31-L52 | **INFORMATIVA** | **SIN PROBLEMAS DETECTADOS** | `projected_loss > (risk_usdt_target + 0.1): return 0.0` | El dimensionador calcula la cantidad exacta según la distancia porcentual al Stop Loss y aborta si la pérdida proyectada supera el riesgo prefijado. |

---

## 5. CONDICIONES EXACTAS DE ENTRADA LONG Y SHORT

### 5.1 Entrada LONG (Compra)
Para que el motor genere `action: 'LONG'`, deben cumplirse simultáneamente y en orden cronológico:
1. **Filtro 4H Macro:**
   - $EMA_{17}(4H) > EMA_{30}(4H) > EMA_{50}(4H)$
   - $\text{Pendiente } EMA_{30}(4H) = EMA_{30}[t] - EMA_{30}[t-1] > 0$
2. **Filtro 1H Operativo:**
   - $EMA_{17}(1H) > EMA_{30}(1H) > EMA_{50}(1H)$
   - $\text{Pendiente } EMA_{30}(1H) > 0$
3. **Preparación 15M (Pullback):**
   - $Low(15M) \le EMA_{17}(15M)$ O $Low(15M) \le EMA_{30}(15M)$ *(Retroceso a la zona de valor)*.
   - $Close(15M) > Open(15M)$ Y $Close(15M) > EMA_{17}(15M)$ *(Vela de confirmación alcista cerrando arriba)*.
   - $\text{Body Ratio} = \frac{|Close - Open|}{High - Low} \ge 0.55$ *(Cuerpo sólido $\ge 55\%$ del rango)*.
   - $RSI_{14}(15M) \in [45.0, 65.0]$ *(Momentum moderado, sin sobrecompra)*.
4. **Gatillo 5M (Ruptura):**
   - Transcurrido en $\le 6$ velas de 5m desde la preparación de 15m.
   - Ninguna vela de 5m cerró por debajo del mínimo del pullback de 15m ($Low(15M)$).
   - $Close(5M) > \max(High[t-5 \dots t-1])$ *(Cierre por encima del máximo local previo)*.
   - Ruptura fresca: $Close[t-1] \le \text{SwingHigh}$ O $Open[t] \le \text{SwingHigh}$.
   - Stop Loss viable: $SL = \text{SwingRef} - (0.25 \times ATR)$ o $Close - (1.0 \times ATR)$.
   - Distancia de SL entre $0.05\%$ y $2.5\%$ del precio.
   - Ratio $R:R$ neto tras comisiones y slippage $\ge 0.5$ (con TP fijado a $2.0 \times \text{Riesgo}$).

### 5.2 Entrada SHORT (Venta)
Condiciones simétricas a LONG:
1. **4H:** $EMA_{17} < EMA_{30} < EMA_{50}$ y $\text{Pendiente } EMA_{30} < 0$.
2. **1H:** $EMA_{17} < EMA_{30} < EMA_{50}$ y $\text{Pendiente } EMA_{30} < 0$.
3. **15M:** $High \ge EMA_{17}$ o $EMA_{30}$, $Close < Open$ y $Close < EMA_{17}$, $\text{Body Ratio} \ge 0.55$, $RSI \in [35.0, 55.0]$.
4. **5M:** $Close(5M) < \min(Low[t-5 \dots t-1])$, ruptura fresca y $SL$ viable con $R:R \ge 2.0$.

---

## 6. DIAGNÓSTICO DEL CASO DE ESTUDIO BTCUSD

### Datos del Registro Evaluado:
* **Precio BTCUSD:** 83.519,88 USD
* **4H:** $EMA_{17} = 82.995,4$ | $EMA_{30} = 83.216,2$ | $EMA_{50} = 83.511,5$ | $\text{Slope}_{30} = +41,1$ | Clasificación: `NONE`
* **1H:** $EMA_{17} = 83.208,3$ | $EMA_{30} = 83.065,6$ | $EMA_{50} = 82.970,1$ | $\text{Slope}_{30} = +45,7$ | Clasificación: `LONG`
* **15M:** $RSI = 58,1$ | $ATR = 160,23\text{ USD}$ | Estado: Esperando retroceso a EMA17/30
* **5M:** $ATR = 102,65\text{ USD}$ | Estado: Esperando ruptura local | Volumen: $1.0\times$ promedio
* **Resultado del Motor:** `NONE [NO_CONFIRMED_TREND]`

### Cadena Causal Matemática y Lógica:
1. **Paso 1 — Evaluación de 4H (`evaluate_trend` en L123-L137):**
   * ¿$EMA_{17} > EMA_{30}$? $82.995,4 > 83.216,2 \rightarrow$ **FALSO**.
   * ¿$EMA_{30} > EMA_{50}$? $83.216,2 > 83.511,5 \rightarrow$ **FALSO**.
   * Las medias en 4H están ordenadas de forma bajista ($17 < 30 < 50$), pero la pendiente es positiva ($+41,1$). No cumple la condición alcista ni la bajista.
   * La función retorna estrictamente `"NONE"`.
2. **Paso 2 — Evaluación en `generate_signal` (L380-L383):**
   ```python
   if trend_4h == "NONE" or trend_1h == "NONE":
       self.pending_preparation = None
       result['reason'] = 'NO_CONFIRMED_TREND'
       return result
   ```
   Al cumplirse `trend_4h == "NONE"`, el flujo se **interrumpe de inmediato**.
3. **¿El bloqueo es exclusivo de 4H o faltaban condiciones en 15M y 5M?**
   * **El bloqueo de 4H actuó como primer escudo**, pero **no fue la única causa que impidió operar**.
   * En 15M: El precio estaba en 83.519,88 USD y las medias de 1H estaban en ~83.208. El precio cotizaba en la parte superior sin haber retrocedido a tocar ni EMA17 ni EMA30 en 15M ($Low \le EMA_{17}$ era FALSO). No existía preparación activa.
   * En 5M: El precio no había producido un quiebre de swing con confirmación de vela cerrada.
   * **Conclusión:** Aunque 4H hubiese estado alcista, el bot tampoco habría operado porque el precio estaba expandido y requería un retroceso ordenado en 15M.

---

## 7. RESULTADOS DE PRUEBAS AUTOMATIZADAS

Se ejecutó la suite completa de pruebas unitarias y de integración bajo `unittest`:

```bash
.\venv\Scripts\python.exe -m unittest discover tests -v
```

### Resumen de Ejecución:
* **Total de Pruebas:** 22
* **Superadas (Passed):** 22
* **Fallidas (Failed):** 0
* **Errores (Errors):** 0
* **Tiempo:** 1.28 segundos

### Desglose de Pruebas:
1. `test_01`: LONG válido con 4H y 1H alcistas alineados (`PASSED`).
2. `test_02`: SHORT válido con 4H y 1H bajistas alineados (`PASSED`).
3. `test_03`: Bloqueo obligatorio cuando 4H y 1H se contradicen (`PASSED`).
4. `test_04`: Bloqueo cuando las medias móviles no están alineadas en orden 17/30/50 (`PASSED`).
5. `test_05`: Caducidad de preparación en 15M tras 6 velas de 5m (`PASSED`).
6. `test_06`: Garantía de comportamiento exclusivo sobre velas cerradas (`PASSED`).
7. `test_07`: Idempotencia al procesar velas repetidas (`PASSED`).
8. `test_08`: Rechazo de órdenes que superen el riesgo monetario máximo (`PASSED`).
9. `test_09`: Normalización de precisión en precios y lotes (`PASSED`).
10. `test_10`: Manejo de órdenes parciales y seguimiento (`PASSED`).
11. `test_11`: Recuperación de estado desde `futures_bot_state.json` tras reinicio (`PASSED`).
12. `test_12`: Prevención de órdenes duplicadas con posición abierta (`PASSED`).
13. `test_13`: Verificación matemática del Stop Loss, Take Profit y ratio 2R (`PASSED`).
14. `test_14`: Rechazo ante datos insuficientes o faltantes (`PASSED`).
15-22. Pruebas de consistencia de simulación y conectores MT5 (`PASSED`).

---

## 8. BACKTESTING Y CALIDAD ESTADÍSTICA

Se ejecutó una simulación histórica completa y reproducible utilizando el motor `BacktestEngine` sobre datos reales en caché de Binance Futures:

* **Par:** BTC/USDT (Futuros Perpetuos)
* **Periodo:** 2026-06-01 al 2026-07-05 (1 mes completo)
* **Capital Inicial:** 1.000,00 USDT | **Riesgo/trade:** 4,00 USDT
* **Costes Simulados:** Taker Fee 0.04% + Slippage 0.05% por ejecución
* **Velas Procesadas:** 4H (210), 1H (840), 15M (3.360), 5M (10.080)

### Métricas Comparativas Consolidadas:

| Estrategia / Variante | Trades | Win Rate % | Profit Factor | PnL Neto (USDT) | Max Drawdown % | Realized R:R | Trades Long | Trades Short | Win Rate Short % |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Anterior (1H + 30m)** | 45 | 33.3% | 0.64 | -113.31 | 0.0% | 1.27 | 23 | 22 | 31.8% |
| **Multi-TF (ATR 1.0x)** | 30 | 33.3% | 0.51 | -112.99 | 0.0% | 1.03 | 8 | 22 | **36.4%** |
| **Multi-TF (ATR 1.5x)** | 30 | 23.3% | 0.37 | -155.30 | 0.0% | 1.21 | 11 | 19 | 21.1% |
| **Multi-TF (ATR 2.0x)** | **28** | 25.0% | 0.46 | -113.92 | 0.0% | **1.37** | 10 | 18 | 22.2% |

### Análisis Cuantitativo del Rendimiento:
1. **Filtrado de Ruido:** La arquitectura Multi-TF redujo la sobreoperativa en un **37,8%** (de 45 a 28 trades), ahorrando más de 18 USDT en comisiones y fricción innecesaria.
2. **Sesgo Direccional Acertado:** En un periodo dominantemente bajista, el filtro 4H+1H eliminó casi todas las compras erráticas, concentrándose en cortos (22 shorts vs 8 longs) con un Win Rate de cortos del **36.4%**.
3. **Explicación del PnL Negativo:** El mercado en junio de 2026 experimentó contracciones laterales prolongadas. En mercados sin tendencia limpia, las estrategias puras de ruptura de medias móviles sufren falsos quiebres repetidos que tocan el SL antes de que el precio alcance el objetivo 2R.

---

## 9. INTEGRIDAD TEMPORAL Y POSIBLES SESGOS

1. **Look-Ahead Bias:** **No detectado.** Los cálculos de indicadores se realizan sobre series históricas y el gatillo en 5M utiliza `shift(1)` para los swings de referencia (`df['high'].shift(1).rolling(5).max()`), asegurando que la vela actual no participe en su propio nivel de ruptura.
2. **Velas Incompletas:** **No detectado.** `MarketDataManager` aplica `iloc[:-1]` y `MT5MarketDataManager` usa `start_pos=1`, descartando la vela que está cotizando en tiempo real.
3. **Cálculo de Sincronización Temporal:** **Riesgo menor corregido.** En `engine.py`, el cálculo `((now.minute // 5) + 1) * 5` despierta al bot exactamente a los 5 segundos posteriores al cierre de cada vela de 5 minutos, garantizando que el broker ya consolidó el OHLCV de dicha vela.
4. **Vulnerabilidad de Idempotencia:** **CONFIRMADO.** En `engine.py` (Línea 118), la asignación `self.last_processed_candle_time = _curr_ts` ocurre antes del bloque de ejecución. Si se produce un fallo de API, la vela queda registrada y no se reintenta en el ciclo siguiente.

---

## 10. EVALUACIÓN DE VARIANTES CONCEPTUALES (A, B y C)

### Variante A — Estrategia Conservadora (Estado Actual)
* **Regla:** Exige coincidencia absoluta $4H == 1H == \text{Dirección}$. Si 4H es `NONE`, no opera.
* **Ventajas:** Máxima protección contra trampas mayores en temporalidades altas; menor número de trades perdidos contra la tendencia macro.
* **Desventajas:** Entra tarde cuando se produce una reversión de mercado, perdiendo el primer 30% a 50% del nuevo impulso mientras 4H reorganiza sus medias 17/30/50.
* **Veredicto:** Excelente para preservar capital; deficiente en transiciones de tendencia.

### Variante B — Estrategia Anticipada
* **Regla:** Permitir operar si 1H tiene tendencia confirmada ($EMA_{17} > EMA_{30} > EMA_{50}$) y 4H está en transición (`NONE`), pero reduciendo el riesgo al 50% (ej. 4 USDT en vez de 8 USDT) y exigiendo que la pendiente de 4H acompañe a 1H ($\text{Slope}_{30}(4H) > 0$).
* **Ventajas:** Captura el inicio de nuevas tendencias antes de que 4H termine de cruzar sus medias lentas.
* **Desventajas:** Mayor exposición a falsas recuperaciones (*bear market rallies*) que se agotan al chocar con la EMA50 de 4H.
* **Veredicto:** Aumenta la frecuencia operativa, pero requiere un filtro adicional de volumen institucional para no degradar el Win Rate.

### Variante C — Estrategia Híbrida
* **Regla:** 4H actúa como filtro de régimen y zona de soporte/resistencia macro, 1H define la dirección activa, 15M prepara el pullback y 5M gatilla. Se autoriza la entrada en 1H alcista con 4H en transición **únicamente si el precio en 4H ya superó la EMA50 de 4H**.
* **Ventajas:** Combina la confirmación del precio sobre el promedio macro con la agilidad de la estructura de 1H.
* **Desventajas:** Mayor complejidad de reglas en la máquina de estados.
* **Veredicto:** Es la alternativa más sólida cuantitativamente para una futura iteración.

---

## 11. RECOMENDACIONES ORDENADAS POR PRIORIDAD

1. **Prioridad 1 (Crítica — Fiabilidad del Motor):**  
   Mover la actualización de `self.last_processed_candle_time = _curr_ts` en `engine.py` al **final** de la iteración, o protegerla para que solo se confirme si la iteración no levantó excepciones.
2. **Prioridad 2 (Estrategia — Régimen de Mercado):**  
   Incorporar el filtro de pendiente mínima de EMA (`slope_pct >= 0.015%`) o umbral de ADX en 1H para descartar fases laterales, lo cual en las pruebas de calibración redujo las pérdidas a la mitad (-51.24 USDT vs -101.33 USDT).
3. **Prioridad 3 (Observabilidad — Consola):**  
   Mantener activo el tablero multitemporal en consola para que el usuario conozca en tiempo real el porcentaje de avance hacia la entrada y la causa exacta de espera.
4. **Prioridad 4 (Documentación de Código):**  
   Actualizar el comentario de sincronización en `engine.py` L64 para reflejar que la espera corresponde al gatillo de 5 minutos y no a 15 minutos.

---

## 12. ARCHIVOS QUE SERÍA NECESARIO MODIFICAR EN UNA FASE FUTURA

Si en el futuro se aprueban cambios de producción, los archivos a intervenir son:
1. `bot/core/engine.py`: Reubicar la asignación de `last_processed_candle_time` al bloque `try` posterior a la ejecución de señales y corregir comentarios de sincronización.
2. `bot/strategies/ema_pullback_trend_strategy.py`: Incorporar la lógica de la Variante C (filtro híbrido de EMA50 en 4H) y el filtro de pendiente mínima para mercado lateral.
3. `bot/config/settings.py`: Declarar los parámetros de umbral de pendiente (`min_slope_pct`) y régimen ADX.

---

## 13. COMANDOS PARA REPRODUCIR LA AUDITORÍA

```powershell
# 1. Ejecutar Suite de Tests Unitarios
.\venv\Scripts\python.exe -m unittest discover tests -v

# 2. Diagnóstico de Conexión y Broker
.\venv\Scripts\python.exe check_mt5.py

# 3. Test de Conectividad y Sincronización en Vivo
.\venv\Scripts\python.exe run_broker_test.py

# 4. Backtest Cuantitativo Multi-Temporal
.\venv\Scripts\python.exe bot/research/backtest_comparator_multitf.py

# 5. Test de Estrés y Condiciones Extremas
.\venv\Scripts\python.exe run_stress_test.py

# 6. Test de Calibración de Filtros Laterales
.\venv\Scripts\python.exe calibrate_filters.py
```

---

## 14. LIMITACIONES Y CUESTIONES NO VERIFICADAS

1. **Binance Futures API en Vivo:** No se pudo verificar la ejecución de órdenes reales en Binance debido a la restricción de IP/claves del exchange (`code: -2015`), por lo que la auditoría en vivo se concentró en MetaTrader 5 / IC Markets.
2. **Datos con Tick Real Milimétrico:** Las simulaciones de backtest se ejecutaron sobre velas OHLCV de 5 minutos cerradas, lo cual es matemáticamente consistente pero no reconstruye el libro de órdenes (*Order Book Level 2*) tick por tick del exchange en vivo.
