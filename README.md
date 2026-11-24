# 🤖 Quant-XGBoost Bot Intradía (Binance Futures)

Este es un bot de trading cuantitativo profesional diseñado específicamente para operar en **Binance Futures** (Contratos Perpetuos). Combina análisis de **múltiples marcos temporales (4H y 1H)**, indicadores técnicos (EMAs, RSI) y un modelo de **Machine Learning (XGBoost)** para tomar posiciones de alta probabilidad, priorizando en todo momento la gestión estricta del riesgo.

## 🚀 Características Principales
- **Mercado:** Binance Futures (USDT-M).
- **Apalancamiento:** Configurable (por defecto 4x).
- **Margen:** Aislado (Isolated) para proteger el resto de la cuenta.
- **Estrategia:** Intradía. Busca la tendencia en 4H (EMA 17/30) y gatilla entradas en 1H apoyándose en RSI y en predicciones de un modelo XGBoost previamente entrenado.
- **Órdenes:** Usa órdenes `LIMIT` para entrar (ahorrando comisiones) y coloca simultáneamente `STOP MARKET` y `TAKE PROFIT MARKET` nativos en Binance.
- **Seguridad y Riesgo:**
  - `MAX_DAILY_LOSS_USDT`: Límite máximo de pérdida diaria.
  - `MAX_DAILY_TRADES`: Máximo número de trades por día para evitar sobreoperar.
  - Fail-safes activos en caso de fallos de la IA o desincronización de API.
  - Breakeven dinámico: Mueve el Stop Loss al punto de entrada cuando el precio avanza favorablemente.
  - Time Stop: Cierra posiciones si el precio lateraliza durante demasiadas horas.

## ⚙️ Estructura del Proyecto

- `bot_intradia_futures.py`: El script principal y motor del bot.
- `configuracion.py` / `.env`: Credenciales de acceso a Binance.
- `machine_learning/predictor.py`: Módulo encargado de cargar el modelo y emitir la predicción de entrada.
- `machine_learning/modelos/`: Directorio donde residen los modelos pre-entrenados `.pkl` y los umbrales `.json`.
- `futures_bot_state.json`: Archivo de persistencia de memoria local. **NO BORRAR NI MODIFICAR** mientras el bot tiene operaciones abiertas.
- `trading_log.json`: Historial de operaciones completadas, con PnL y razones de salida precisas.

## ⚠️ Advertencia de Riesgo
Este bot está diseñado para **FUTUROS**, lo que implica apalancamiento y un alto riesgo de liquidación.
En `bot_intradia_futures.py` encontrarás el parámetro `PAPER_TRADING`. Si está en `False`, **el bot operará con dinero real**. Asegúrate de probar extensamente en testnet (Paper Trading) antes de usar fondos reales.

> IMPORTANTE: Nunca expongas tu `API_SECRET` ni tu `.env`.

## 🛠️ Cómo Iniciar

1. Asegúrate de tener Python 3.9+ instalado y activa tu entorno virtual.
2. Instala dependencias (si aplica, p. ej. `pip install ccxt pandas xgboost numpy python-dotenv`).
3. Ejecuta el bot:
```bash
python bot_intradia_futures.py
```

## 🔬 Informes de Auditoría e Investigación Cuantitativa

- **[REPORTE_INVESTIGACION_GATILLOS_FASE3.txt](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/REPORTE_INVESTIGACION_GATILLOS_FASE3.txt):** Informe en formato texto plano con la comparativa de gatillos y la validación de la variante 1H-15M-5M con órdenes LIMIT y filtros de volumen/ATR.
- **[INVESTIGACION_GATILLOS_EMA_PULLBACK_TREND.md](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/INVESTIGACION_GATILLOS_EMA_PULLBACK_TREND.md):** Documento técnico exhaustivo de la Fase 3 con tablas, curvas de equity, análisis de drawdown y justificación estadística.
- **[VALIDACION_BACKTEST_EMA_PULLBACK_TREND.md](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/VALIDACION_BACKTEST_EMA_PULLBACK_TREND.md):** Auditoría forense del backtest (corrección de drawdown 0,0 % y comisiones de entrada).
- **[AUDITORIA_EMA_PULLBACK_TREND.md](file:///c:/Users/Usuario/Desktop/bot-simple-emas-moviles-rsi/AUDITORIA_EMA_PULLBACK_TREND.md):** Diagnóstico inicial de la arquitectura multitemporal y sincronización temporal.

## 🏆 Estado de Producción Actual (`EMA_PULLBACK_TREND`)
- **Arquitectura:** `1H (Tendencia)` ➔ `15M (Pullback)` ➔ `5M (Gatillo LIMIT)`.
- **Filtros Cuantitativos:** Expansión de volumen (`Vol >= 1.10x SMA20`) y régimen de volatilidad (`ATR 5M >= ATR SMA20`).
- **Tipo de Orden:** `LIMIT` (Maker fee 0.02% en Binance Futures).
- **Rendimiento Verificado (6 Meses / 53.568 velas):**
  - **159 trades**, **+166.65 USDT netos** (+16.7%), **Profit Factor 1.20**, **Drawdown Máximo 10.32%**, **OOS PF 1.24**.

