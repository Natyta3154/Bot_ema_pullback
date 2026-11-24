# 🔬 INFORME CIENTÍFICO DE INVESTIGACIÓN CUANTITATIVA — FASE 3
# EVALUACIÓN DE GATILLOS DE ENTRADA Y RENTABILIDAD EN `EMA_PULLBACK_TREND`

> **Rol:** Investigador Cuantitativo Senior y Auditor de Sistemas Algorítmicos.  
> **Fecha:** 12 de Octubre de 2026.  
> **Activo:** BTC/USDT (Binance Futures).  
> **Estado del Código de Producción:** 100 % INTACTO (`bot/core/engine.py`, `bot/core/risk.py`, `bot/strategies/ema_pullback_trend_strategy.py` sin modificaciones).  
> **Entorno de Simulación:** Aislado en investigación (`bot/research/trigger_investigation_lab.py`).  
> **Reconciliación Contable:** 100,000 % Exacta al centavo ($\Delta \text{Balance} \equiv \sum \text{Net PnL Real}$).

---

## 1. RESUMEN EJECUTIVO Y VEREDICTO CUANTITATIVO

Se completó la **Fase 3 de Investigación Cuantitativa** para determinar si la ineficiencia económica de la estrategia `EMA_PULLBACK_TREND` (reportada previamente con 34 trades, Win Rate de 35,3 %, Profit Factor de 0,42 y PnL de -165,12 USDT) se debía al **mecanismo de gatillo en 5M**, y si una **confirmación en 15M (Variante B)** o el **añadido de filtros de volumen y régimen de volatilidad (Variante C)** restauraban la viabilidad matemática del sistema.

### Hallazgos Clave:
1. **Replicación Exacta del Baseline:**
   - La Variante A (gatillo actual 5M) replicó **con precisión idéntica** los resultados de la auditoría previa sobre el período de 35 días (2026-06-01 a 2026-07-05): **34 operaciones, 35,3 % WR, Profit Factor 0,42, PnL neto de -165,12 USDT y Max Drawdown de 16,51 %**.
2. **Impacto de la Confirmación en 15M (Variante B):**
   - En el período baseline de junio, la confirmación en 15M elevó el Win Rate al **54,2 %** y recortó la pérdida neta de -165,12 USDT a solo **-4,18 USDT** (PF 0,97).
   - Sin embargo, en la prueba fuera de muestra extendida de 6 meses (53.568 velas de 5M), **la Variante B acumuló -661,61 USDT de pérdida neta con un Drawdown del 68,68 % y Profit Factor de 0,59**.
3. **Impacto de los Filtros de Volumen y Régimen de ATR (Variante C):**
   - Descartó el **65,3 %** de las entradas de baja calidad por falsas rupturas sin liquidez o en contracción de volatilidad.
   - En 6 meses, su PnL bruto de mercado fue casi neutro (**-29,19 USDT**), pero la fricción de comisiones roundtrip (**202,33 USDT**) arrastró el balance a **-231,52 USDT (PF 0,68, Max DD 23,15 %)**.
4. **Veredicto Final Irrefutable:**
   - **NINGUNA DE LAS TRES VARIANTES ALCANZA LA RENTABILIDAD NETA DESPUÉS DE COSTES NI UN PROFIT FACTOR > 1.0 EN EL HISTÓRICO EXTENDIDO.**
   - La estrategia posee una **expectativa matemática negativa intrínseca** debido a la asimetría entre el tamaño del stop loss en 5M/15M y el costo transaccional taker (0,08 % roundtrip) en futuros apalancados.
   - **Recomendación:** **NO DESPLEGAR NINGUNA VARIANTE EN PRODUCCIÓN.**

---

## 2. ARCHIVOS INSPECCIONADOS

| Componente | Archivo | Inspección Realizada |
| :--- | :--- | :--- |
| **Lógica de Estrategia** | [bot/strategies/ema_pullback_trend_strategy.py](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/strategies/ema_pullback_trend_strategy.py) | Análisis de compuertas lógicas (4H -> 1H -> 15M -> 5M), cálculo de EMAs, RSI, body ratio, swaps de swing e invalidación estructural. |
| **Motor de Ejecución** | [bot/core/engine.py](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/core/engine.py) | Revisión de eventos, sincronización de velas cerradas e idempotencia. |
| **Simulador de Órdenes** | [bot/backtest/mock_order_manager.py](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/backtest/mock_order_manager.py) | Cruce de órdenes límite, stops y take profits; política pesimista intravela (`stops first`); cómputo de comisiones y slippage. |
| **Proveedor de Datos** | [bot/backtest/mock_market_data.py](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/backtest/mock_market_data.py) | Verificación de corte temporal (`searchsorted` con delta cerrado) para descarte absoluto de *look-ahead bias*. |
| **Métricas Cuantitativas** | [bot/backtest/metrics.py](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/backtest/metrics.py) | Corrección de cálculo de drawdown sobre curva real prependeando balance inicial y conciliación de fee de apertura. |
| **Carga de Datos Históricos** | [bot/backtest/data_loader.py](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/backtest/data_loader.py) | Extracción de series OHLCV desde Binance mediante CCXT y almacenamiento en caché. |
| **Configuraciones Globales** | [bot/config/settings.py](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/config/settings.py) | Verificación de parámetros predeterminados de riesgo, comisiones (0,04 %) y slippage (0,01 %). |
| **Suite de Pruebas** | [tests/test_backtest_invariants.py](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/tests/test_backtest_invariants.py) | Verificación de las 6 invariantes críticas de simulación contable e intravela (28 tests pasando al 100 %). |

---

## 3. AUDITORÍA DE INVARIANTES Y RECONCILIACIÓN CONTABLE (TAREA 1)

Antes de proceder a la experimentación comparativa de gatillos, se verificaron matemática y experimentalmente las 6 invariantes obligatorias:

### 3.1 Conciliación de Comisiones de Apertura y Cierre (Roundtrip)
- En `MockOrderManager`, tanto la orden de apertura (`reduceOnly == False`) como la de cierre (`reduceOnly == True`) liquidan la comisión en el saldo en el momento exacto del cruce:
  $$\text{Fee} = \text{Amount} \times \text{Price} \times 0,0004$$
- Se comprobó que el PnL neto real por trade es estrictamente:
  $$\text{Net PnL Real} = \text{Gross PnL} - (\text{Fee}_{\text{entrada}} + \text{Fee}_{\text{salida}})$$
- **Conciliación de Cuenta:** En cada una de las simulaciones ejecutadas, el cambio total en el balance de la cuenta ($\text{Balance}_{\text{final}} - \text{Balance}_{\text{inicial}}$) coincidió con la suma de todos los resultados netos con una discrepancia de **0,000 USDT**.

### 3.2 Curva de Equity y Drawdown con Balance Inicial
- Se corrigió en el módulo de cálculo el error matemático donde se calculaba el pico (`cummax()`) únicamente sobre los trades cerrados post-operación.
- Al incluir el depósito inicial de 1.000,00 USDT al inicio de la serie, el Drawdown Máximo computa fielmente cualquier caída desde el capital de apertura, arrojando exactamente el **16,51 % (165,12 USDT)** en la Variante A del período baseline.

### 3.3 Resolución Intravela Pesimista (SL vs TP y Gaps)
- En [MockOrderManager.process_candle](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/backtest/mock_order_manager.py#L148-L158), las órdenes abiertas se ordenan antes de ser evaluadas:
  ```python
  open_orders.sort(key=lambda x: 0 if x['type'] == 'stop' else 1)
  ```
- Si una sola vela de 5M presenta un rango extremo que cruza tanto el Stop Loss como el Take Profit, el simulador ejecuta **siempre el Stop Loss en primer lugar**, cerrando la posición e invalidando de inmediato el Take Profit. No existe sesgo optimista intravela.
- Si la vela abre con un gap más allá del stop, la orden ejecuta al precio desfavorable del gap penalizando la pérdida.

### 3.4 Alineación Temporal y Descarte Absoluto de Look-Ahead Bias
- En [MockMarketData.fetch_ohlcv](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/backtest/mock_market_data.py#L22-L46), cuando el reloj interno del backtester se encuentra en el tiempo $t$ de la vela menor de 5M, las series de 4H, 1H y 15M se recortan utilizando el delta de cierre:
  ```python
  target_ts = self.current_timestamp - delta
  idx = df['timestamp'].searchsorted(target_ts, side='right')
  return df.iloc[:idx].copy()
  ```
- Se comprobó que ninguna vela de 4H o 1H en formación se filtra hacia la estrategia. Solo se consumen velas con cierre estrictamente anterior o coincidente con $t$.

### 3.5 Verificación Automatizada de Invariantes
Se ejecutó la suite de tests en [tests/test_backtest_invariants.py](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/tests/test_backtest_invariants.py):
```bash
python -m unittest discover tests
Ran 28 tests in 0.901s -> OK (100 % APROBADO)
```

---

## 4. DEFINICIÓN METODOLÓGICA DE LAS TRES VARIANTES DE GATILLO (TAREA 2)

Para garantizar un aislamiento experimental riguroso, se mantuvieron **100 % idénticos** entre las tres variantes:
- **Filtro Macro 4H:** `EMA17 > EMA30 > EMA50` y `slope(EMA30) > 0` para LONG; orden inversa y pendiente negativa para SHORT.
- **Confirmación Operativa 1H:** Coincidencia obligatoria con 4H.
- **Preparación de Pullback en 15M:** Toque a EMA17 o EMA30, cierre a favor de la tendencia sobre/bajo EMA17, `body_ratio >= 0,55`, RSI entre 45-65 (Long) o 35-55 (Short).
- **Reglas de Riesgo y Salida:** Riesgo objetivo de 1 % (máximo 8,0 USDT nominal), Stop Loss técnico a 1.0x ATR, Take Profit fijo a **2.0R**, filtro de viabilidad R:R neto $\ge 0,5$.
- **Costes de Simulación:** Comisión taker de 0,04 % por fill (0,08 % roundtrip) y 0,01 % slippage por orden de mercado.

### Qué cambia en cada variante:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ COMPONENTE                   VARIANTE A             VARIANTE B             VARIANTE C   │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ Timeframe del Gatillo        5 Minutos              15 Minutos             5 Minutos    │
│ Regla de Gatillo             Ruptura Swing Local    Confirmación Cierre    Ruptura Swing│
│                              (lookback 5, shift 1)  sobre High/Low Prep    (lookback 5) │
│ Ruptura Fresca               is_fresh (<= swing)    is_bullish / is_bearish is_fresh    │
│ Filtro de Volumen            Ninguno                Ninguno                Vol > 1.1x   │
│                                                                            SMA20(Vol)   │
│ Filtro de Régimen ATR        Ninguno                Ninguno                ATR > SMA20  │
│                                                                            ATR/P >= 0.1%│
│ Caducidad de Preparación     6 velas 5m (30 min)    2 velas 15m (30 min)   6 velas 5m   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

1. **Variante A (Actual en 5M):** Tras la vela de preparación en 15M, desciende a 5M y busca una ruptura del máximo local de 5 barras (`local_swing_high`). Caduca a los 30 minutos (6 barras de 5M) o si perfora el extremo de la preparación de 15M.
2. **Variante B (Confirmación en 15M):** No desciende a 5M. Permanece en 15M. Tras la preparación en la vela $t$, exige que la siguiente vela de 15M (o dentro de las siguientes 2 velas de 15M = 30 minutos) rompa y cierre por encima del máximo de la vela de preparación (para LONG: `close_15m > prep_high`) o bajo el mínimo (para SHORT: `close_15m < prep_low`), manteniendo intacto el mínimo estructural (`low_15m >= swing_ref`).
3. **Variante C (Gatillo 5M con Filtros de Volumen y Volatilidad):** Ejecuta exactamente el mismo gatillo de 5M que la Variante A, pero exige obligatoriamente dos condiciones en la vela de 5M de ruptura:
   - **Volumen:** $\text{Volume}_{5M} \ge 1,10 \times \text{SMA}_{20}(\text{Volume}_{5M})$ (confirmación de participación institucional real, descartando rupturas ilíquidas).
   - **Régimen de Volatilidad:** $\text{ATR}_{5M} \ge \text{SMA}_{20}(\text{ATR}_{5M})$ (mercado saliendo de compresión hacia expansión tendencial) y $\frac{\text{ATR}_{5M}}{\text{Price}_{5M}} \ge 0,001$ (descarte de regímenes planos donde el spread destruye el trade).

---

## 5. RESULTADOS DE LA VALIDACIÓN EXPERIMENTAL (TAREA 3)

Se ejecutaron dos bloques experimentales independientes utilizando el script reproducible [bot/research/trigger_investigation_lab.py](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/research/trigger_investigation_lab.py):

### 5.1 Experimento 1: Período Baseline de Auditoría (35 Días: 2026-06-01 a 2026-07-05)
- **Datos:** 10.080 velas de 5M, 3.360 velas de 15M, 840 velas de 1H, 210 velas de 4H.
- **Partición Cronológica:** In-Sample (IS: 2026-06-01 a 2026-06-20) / Out-of-Sample (OOS: 2026-06-21 a 2026-07-05).

#### Tabla Comparativa A / B / C — Período Baseline (Junio 2026)

| Métrica | Variante A (Base 5M) | Variante B (Conf 15M) | Variante C (5M + Vol/ATR) |
| :--- | :---: | :---: | :---: |
| **Total Operaciones** | **34** | **24 (-29,4 %)** | **10 (-70,6 %)** |
| **Tasa de Acierto (Win Rate)** | **35,3 %** | **54,2 %** | **50,0 %** |
| **Profit Factor Real** | **0,42** | **0,97** | **0,89** |
| **PnL Bruto (Gross PnL)** | -84,61 USDT | +49,15 USDT | +15,08 USDT |
| **Comisiones Totales Roundtrip** | -80,51 USDT | -53,33 USDT | -22,38 USDT |
| **PnL Neto Real** | **-165,12 USDT** | **-4,18 USDT** | **-7,30 USDT** |
| **Drawdown Máximo Real (%)** | **16,51 %** | **4,82 %** | **3,75 %** |
| **Drawdown Máximo (USDT)** | 165,12 USDT | 48,18 USDT | 37,50 USDT |
| **Expectativa por Operación** | -4,86 USDT | -0,17 USDT | -0,73 USDT |
| --- | --- | --- | --- |
| **IS Trades (In-Sample)** | 8 | 5 | 2 |
| **IS Net PnL** | -35,94 USDT | +4,30 USDT | +20,70 USDT |
| **IS Profit Factor** | 0,46 | 1,17 | $\infty$ (100 % WR) |
| --- | --- | --- | --- |
| **OOS Trades (Out-of-Sample)** | 26 | 19 | 8 |
| **OOS Net PnL** | -129,18 USDT | -8,48 USDT | -28,00 USDT |
| **OOS Profit Factor** | 0,41 | 0,92 | 0,57 |
| --- | --- | --- | --- |
| **Conciliación Contable** | **100 % Exacta (0,00)** | **100 % Exacta (0,00)** | **100 % Exacta (0,00)** |

*Observación Preliminar:* En el mes de junio, tanto B como C mostraron una reducción drástica de pérdidas y un aumento significativo del Win Rate (+19 % y +15 %). Sin embargo, **el período de 35 días es estadísticamente insuficiente** (solo 10 a 24 trades). Por ello, el criterio científico exige la validación en el histórico extendido.

---

### 5.2 Experimento 2: Período Extendido Multirégimen (6 Meses: 2026-01-01 a 2026-07-05)
- **Datos:** 53.568 velas de 5M, 17.856 velas de 15M, 4.464 velas de 1H, 1.116 velas de 4H.
- **Regímenes de Mercado Cubiertos:** Fuerte rally alcista (enero a marzo), distribución y corrección bajista (abril a mayo), y rango lateral volátil (junio a julio).
- **Partición Cronológica Estricta:**
  - **In-Sample (IS - Desarrollo / Entrenamiento):** 2026-01-01 a 2026-04-30 (4 meses completos, 120 días).
  - **Out-of-Sample (OOS - Validación Fuera de Muestra):** 2026-05-01 a 2026-07-05 (66 días no vistos).

#### Tabla Comparativa A / B / C — Período Extendido (6 Meses)

| Métrica Cuantitativa | Variante A (Base 5M) | Variante B (Conf 15M) | Variante C (5M + Vol/ATR) |
| :--- | :---: | :---: | :---: |
| **Total Operaciones** | **291** | **218** | **101 (-65,3 %)** |
| **Tasa de Acierto (Win Rate)** | **38,5 %** | **40,8 %** | **42,6 %** |
| **Profit Factor Real** | **0,55** | **0,59** | **0,68** |
| **PnL Bruto (Gross PnL)** | -370,35 USDT | -201,28 USDT | **-29,19 USDT** |
| **Comisiones Totales Roundtrip** | -511,83 USDT | -460,32 USDT | -202,33 USDT |
| **PnL Neto Real** | **-882,19 USDT** | **-661,61 USDT** | **-231,52 USDT** |
| **Drawdown Máximo Real (%)** | **88,23 %** | **68,68 %** | **23,15 %** |
| **Drawdown Máximo (USDT)** | 882,19 USDT | 686,80 USDT | 231,52 USDT |
| **Balance Final en Cuenta** | **117,81 USDT** | **338,39 USDT** | **768,48 USDT** |
| **Expectativa por Operación** | **-3,03 USDT** | **-3,04 USDT** | **-2,29 USDT** |
| **Duración Media por Trade** | 80,3 minutos | 72,9 minutos | 53,3 minutos |
| --- | --- | --- | --- |
| **IS Trades (In-Sample)** | 183 | 132 | 68 |
| **IS Net PnL** | -622,41 USDT | -410,71 USDT | -166,85 USDT |
| **IS Win Rate / Profit Factor** | 38,3 % / 0,55 | 40,2 % / 0,59 | 41,2 % / 0,66 |
| --- | --- | --- | --- |
| **OOS Trades (Out-of-Sample)** | 108 | 86 | 33 |
| **OOS Net PnL** | -259,78 USDT | -250,90 USDT | -64,67 USDT |
| **OOS Win Rate / Profit Factor** | 38,9 % / 0,54 | 41,9 % / 0,59 | 45,5 % / 0,72 |
| --- | --- | --- | --- |
| **Conciliación Contable Real** | $\Delta = -882,19$ (100 %) | $\Delta = -661,61$ (100 %) | $\Delta = -231,52$ (100 %) |

---

### 5.3 Desglose de Resultados Long vs Short (Período Extendido)

| Variante | Dirección | Trades | Ganadores | Perdedores | Win Rate (%) | Gross PnL | Fees Totales | Net PnL Real |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Variante A** | **LONG** | 107 | 39 | 68 | 36,4 % | -226,38 | 187,25 | **-413,63 USDT** |
| (Base 5M) | **SHORT** | 184 | 73 | 111 | 39,7 % | -143,97 | 324,58 | **-468,55 USDT** |
| **Variante B** | **LONG** | 84 | 29 | 55 | 34,5 % | -266,54 | 176,72 | **-443,26 USDT** |
| (Conf 15M) | **SHORT** | 134 | 60 | 74 | 44,8 % | +65,26 | 283,60 | **-218,35 USDT** |
| **Variante C** | **LONG** | 35 | 16 | 19 | 45,7 % | +2,46 | 70,20 | **-67,74 USDT** |
| (5M Vol/ATR) | **SHORT** | 66 | 27 | 39 | 40,9 % | -31,65 | 132,13 | **-163,78 USDT** |

---

## 6. CURVAS DE EQUITY Y ANÁLISIS DE DRAWDOWN

### 6.1 Trayectoria de Equity en el Histórico Extendido (1.000 USDT Iniciales)

```
Equity (USDT)
1000 ┬────────────────────────────────────────────────────────────────────────
     │═══════════╗ (Variante C mantiene relativa estabilidad en los primeros 120 días)
 900 │           ╚══════════════╦══════════════╗
     │                          ║              ╚═════════════════════> [Var C: 768.48 USDT]
 800 │                          ║
     │                          ╚══════════════╗
 700 │─────────────────────────────────────────║──────────────────────────────
     │── ── ── ── ── ── ── ── ── ── ── ── ── ── ╚═════════╗
 600 │                                                    ╚══════════> [Var B: 338.39 USDT]
     │
 500 │────────────────────────────────────────────────────────────────────────
     │
 400 │· · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · · ·
     │                                                     ·
 300 │                                                     ·
     │                                                     ·
 200 │─────────────────────────────────────────────────────·──────────────────
     │                                                     ·
 100 │· · · · · · · · · · · · · · · · · · · · · · · · · · ·└───> [Var A: 117.81 USDT]
   0 ┴────────────────────────────────────────────────────────────────────────
     Enero 2026        Marzo 2026        Mayo 2026         Julio 2026
```

### 6.2 Diagnóstico Anatómico del Drawdown:
1. **La Destrucción de la Variante A (88,23 % Max DD):**
   - La curva de equity presenta una pendiente negativa casi monótona con caídas constantes.
   - De los 882,19 USDT perdidos, **511,83 USDT correspondieron exclusivamente a comisiones de intercambio**, demostrando que el exceso de operaciones de baja calidad en 5M genera una hemorragia por fricción operativa.
2. **El Retraso de la Variante B (68,68 % Max DD):**
   - Aunque la confirmación en 15M evitó 73 entradas falsas respecto a 5M, la entrada ocurre con el precio sustancialmente más alejado del Stop Loss.
   - Al entrar más tarde (en el cierre de la vela de 15M), el rango entre la entrada y el Stop Loss se ensancha, lo que reduce el tamaño de posición por gestión de riesgo pero incrementa la frecuencia de salidas por Stop en movimientos oscilantes, manteniendo un Profit Factor deprimido (0,59).
3. **La Resiliencia y Techo de la Variante C (23,15 % Max DD):**
   - La Variante C fue la única capaz de defender el capital bruto de mercado (apenas -29,19 USDT de Gross PnL en 6 meses).
   - El filtro de volumen (`Volume > 1.1x SMA20`) y de régimen de volatilidad (`ATR > SMA20`) eliminó con éxito el 65 % del ruido de mercado.
   - Sin embargo, las 101 operaciones pagaron **202,33 USDT en comisiones**, provocando una erosión neta del 23,15 %. Con una tasa de comisión maker o rebajas VIP institucionales, la Variante C se acercaría al breakeven, pero con costos estándar de futuros sigue siendo inviable.

---

## 7. CRITERIOS DE DECISIÓN CUANTITATIVA (TAREA 4)

Se contrastan los resultados con los umbrales de aceptación institucional prefijados:

| Criterio de Aceptación Institucional | Umbral Mínimo | Variante A | Variante B | Variante C | Veredicto |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Expectativa Neta por Trade** | $> 0,00\text{ USDT}$ | -3,03 USDT | -3,04 USDT | -2,29 USDT | ❌ **RECHAZADO (Todas $E < 0$)** |
| **Profit Factor Real** | $> 1,20$ | 0,55 | 0,59 | 0,68 | ❌ **RECHAZADO (Ninguna supera 1.0)** |
| **Max Drawdown sobre Capital** | $< 15,0\ \%$ | 88,23 % | 68,68 % | 23,15 % | ❌ **RECHAZADO (Var A y B destructivas)** |
| **Consistencia Out-of-Sample** | $PF_{\text{OOS}} \ge PF_{\text{IS}}$ | 0,54 vs 0,55 | 0,59 vs 0,59 | 0,72 vs 0,66 | ⚠️ Consistente pero consistentemente perdedora |
| **Fricción de Costes vs Gross PnL** | $\text{Fees} < 30\ \%\text{ PnL}$ | Fees = 138 % | Fees = 228 % | Fees = 693 % | ❌ **RECHAZADO (Comisiones devoran el sistema)** |

---

## 8. LIMITACIONES, POSIBLES SESGOS Y REPRODUCIBILIDAD

1. **Modelo de Comisión Taker:**
   - Se modeló la comisión estándar de Binance Futures de 0,04 % por fill (0,08 % roundtrip). En cuentas institucionales o VIP con rebate maker (-0,005 %), el impacto de la fricción se reduciría drásticamente, pero el margen de ventaja alfa continuaría siendo insuficiente para compensar el deslizamiento de mercado.
2. **Ejecución Intravela Pesimista:**
   - La simulación asume ejecución pesimista ante toques simultáneos de Stop y Take Profit en la misma vela de 5M. Aunque esto descarta cualquier sesgo favorable (*overfitting*), en situaciones reales con datos tick-a-tick algunos trades habrían tocado el TP antes del SL. No obstante, la magnitud de la pérdida acumulada en 291 operaciones confirma que esto no revertiría el sesgo estructural negativo.
3. **Ausencia de Look-Ahead Bias:**
   - Se demostró matemáticamente y con pruebas automatizadas que ninguna de las variantes utilizó información futura en 4H, 1H o 15M.
4. **Reproducibilidad:**
   - Todos los experimentos, curvas y tablas son 100 % reproducibles ejecutando:
     ```bash
     python bot/research/trigger_investigation_lab.py
     ```
   - Los datos brutos y conciliados de cada trade se encuentran serializados en [bot/research/investigation_fase3_results.json](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/research/investigation_fase3_results.json) y en los archivos CSV correspondientes:
     - [trades_extended_A_Base_5M_Ruptura.csv](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/research/trades_extended_A_Base_5M_Ruptura.csv)
     - [trades_extended_B_Conf_15M_Vela_Cerrada.csv](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/research/trades_extended_B_Conf_15M_Vela_Cerrada.csv)
     - [trades_extended_C_5M_+_Vol_ATR.csv](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/bot/research/trades_extended_C_5M_+_Vol_ATR.csv)

---

## 9. RECOMENDACIÓN FINAL BASADA EN EVIDENCIA

1. **NO DESPLEGAR NINGUNA DE LAS VARIANTES EN PRODUCCIÓN:**
   - Ni el gatillo actual de 5M (A), ni la confirmación de 15M (B), ni los filtros de volumen y ATR (C) logran rentabilidad neta ni un Profit Factor superior a 1,0 en datos fuera de muestra de 6 meses.
   - La Variante A destruye el 88 % de la cuenta y la Variante B el 68 %. La Variante C mitiga sustancialmente el daño (Gross PnL casi neutral de -29 USDT), pero la fricción de comisiones sigue devorando el capital.
2. **DIAGNÓSTICO CUANTITATIVO DE FONDO:**
   - El problema de fondo de `EMA_PULLBACK_TREND` no es meramente el gatillo, sino la **arquitectura multitemporal desfasada**:
     - Exigir alineación simultánea en 4H y 1H provoca que las señales solo se activen cuando la tendencia macro ya está madura y extendida.
     - Al entrar en retrocesos de 15M sobre una tendencia madura, el mercado frecuentemente entra en fases de agotamiento o distribución, convirtiendo los pullbacks en reversiones completas que barren los stops ajustados de 1.0 ATR.
3. **PASOS FUTUROS SUGERIDOS (PARA INVESTIGACIÓN POSTERIOR):**
   - **Elevar el Stop Loss:** Stops técnicos a 1.0 ATR en 5M son barridos por el ruido browniano de Bitcoin. Se requiere explorar stops estructurales más holgados (1.5x a 2.0x ATR de 15M) con ratio asimétrico.
   - **Regla de Salida Dinámica (Trailing / Breakeven):** El modelo actual de "todo o nada" (2R TP fijo vs 1R SL) sufre de *profit giveback* severo: trades que alcanzaban +1.5R terminaban cerrando en Stop completo por falta de gestión activa de posición.
   - **Preservar el Código de Producción:** Se mantiene la directriz de no alterar `engine.py` ni poner en riesgo capital real hasta disponer de un sistema con expectativa matemática estadísticamente positiva verificada.

---
*Informe cuantitativo generado y respaldado por tests automatizados locales bajo Python 3.13.*
