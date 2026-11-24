"""
Módulo de Configuración Global (Settings)
=========================================
Este archivo contiene todos los parámetros configurables del bot, 
incluyendo gestión de riesgo, credenciales de API, umbrales de decisión
y configuraciones específicas de cada estrategia comercial.
"""
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# ==============================================================================
# CONFIGURACIÓN DEL ENTORNO Y PROFILING
# ==============================================================================
# Opciones: "LIVE", "PAPER", "BACKTEST"
ENVIRONMENT = os.getenv("ENVIRONMENT", "PAPER").strip().strip('"').strip("'")
ACTIVE_STRATEGY = "EMA_PULLBACK_TREND"
# Bloqueo de seguridad: no permitir operaciones reales durante el refactor.
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "True").strip().lower() in ("true", "1")

ENABLE_PROFILING = False  # <--- Desactivado en LIVE por seguridad/rendimiento
ENABLE_DETAILED_LOGS = True  # <--- Logs super descriptivos de Decisiones de Estrategia

# ==============================================================================
# SELECCIÓN DE BROKER Y CREDENCIALES
# ==============================================================================
# Opciones: "BINANCE", "ICMARKETS"
BROKER = os.getenv("BROKER", "ICMARKETS").strip().upper()

# Binance Futures
API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

# IC Markets / MetaTrader 5
MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0").strip()) if os.getenv("MT5_LOGIN", "0").strip().isdigit() else 0
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "").strip()
MT5_SERVER = os.getenv("MT5_SERVER", "ICMarketsSC-Demo").strip()
MT5_PATH = os.getenv("MT5_PATH", "").strip()  # Ruta personalizada a terminal64.exe si aplica
MT5_SYMBOL = os.getenv("MT5_SYMBOL", "BTCUSD").strip()

# ==============================================================================
# CONFIGURACIÓN DE MERCADO Y RUTAS
# ==============================================================================
# Símbolo dinámico según el broker seleccionado
if BROKER == "ICMARKETS":
    SYMBOL = os.getenv("SYMBOL", MT5_SYMBOL)
else:
    SYMBOL = os.getenv("SYMBOL", "BTC/USDT")

STATE_FILE = 'futures_bot_state.json'
TRADING_LOG_FILE = 'trading_log.json'
LIVE_RAW_TRADES_CSV = 'live_raw_trades.csv'

# ==============================================================================
# GESTIÓN DE RIESGO (Calibrado para Cuenta Real $300 USD - Max Loss $50 USD)
# ==============================================================================
RISK_PER_TRADE_USDT = float(os.getenv("RISK_PER_TRADE_USDT", "8.0"))  # Riesgo por trade (~$8 USD -> ~16 USD por TP 1:2)
LEVERAGE = 100                # Apalancamiento CFD IC Markets (evita recorte artificial en cuenta de $300)
MAX_DAILY_TRADES = 10
MAX_DAILY_LOSS_USDT = 25.0    # Freno diario (~3 SL en un día pausa operativa hasta el día siguiente)
MAX_TOTAL_LOSS_USDT = 50.0    # Kill Switch Crítico: Freno absoluto en -$50.00 USD acumulados
MAX_CONSECUTIVE_LOSSES = 5

# ==============================================================================
# MOTOR DE IA CUANTITATIVA EN SOMBRA (LightGBM + SHAP + Autopsia Contrafactual)
# ==============================================================================
AI_SHADOW_LEARNING_ENABLED = True   # Aprende en vivo de cada trade ganador y hace autopsia de los perdedores
AI_TAKE_DECISIONS = False           # FALSE = NO toma decisiones en las entradas (Solo observa y aprende)
AI_MIN_TRADES_TO_TRAIN = 12         # Mínimo de trades para entrenar LightGBM + SHAP
AI_MIN_TRADES_FOR_DECISIONS = 75    # Meta de trades aprendidos para considerar pasar a modo activo
AI_DECISION_MIN_WIN_PROB = 0.36     # Umbral reservado para cuando AI_TAKE_DECISIONS se active en el futuro

# ==============================================================================
# CONFIGURACIONES ESPECÍFICAS DE ESTRATEGIAS
# ==============================================================================
DECISION_WEIGHTS = {
    "market": 0.0,
    "structure": 0.20,
    "momentum": 0.40,
    "execution": 0.40,
    "risk": 0.0
}

DECISION_THRESHOLDS = {
    "min_score": 75.0,
    "min_confidence": 80.0
}

STRATEGY_PARAMS = {
    "EMA_STRATEGY": {
        "allow_long": True,
        "allow_short": True,
        "macro_tf": "4h",
        "trigger_tf": "1h",
        "fast_ema": 17,
        "slow_ema": 30,
        "rr_ratio": 2.0,
        "time_stop_hours": 4,
        "lateralization_range_pct": 0.005,
        "use_ml": True
    },
    "BREAKOUT_RETEST": {
        "macro_tf": "1h",
        "entry_tf": "15m",
        "pivot_lookback": 5,           # Barras para Swing H/L
        "vol_multiplier": 1.0,         # Umbral vol > SMA(vol) * x
        "vol_sma_period": 20,
        "sl_buffer_pct": 0.001,        # 0.1% buffer bajo el swing para SL
        "tolerance_zone_pct": 0.001,   # Zona de tolerancia para el retest (0.1%)
        "atr_period": 14,
        "atr_min_volatility": 0.001,   # ATR mínimo como % del precio (evitar compresión extrema)
        "atr_max_volatility": 0.03,    # ATR máximo como % del precio (evitar alta volatilidad)
        "take_profits": [
            {"pct": 0.5, "rr": 1.5},   # 50% lotaje a 1.5x RR
            {"pct": 0.5, "rr": 3.0}    # 50% lotaje a 3.0x RR
        ],
        "breakeven_on_tp1": True,
        "trailing_stop": False,
        "use_ml": False
    },
    "EMA_PULLBACK_TREND": {
        # Temporalidades: 1H (Tendencia) -> 15m (Preparación Pullback) -> 5m (Gatillo LIMIT)
        "macro_tf": "1h",
        "trend_confirm_tf": "1h",
        "pullback_tf": "15m",
        "trigger_tf": "5m",
        "use_4h_filter": False,        # 1H único rector de tendencia
        "strict_ema_alignment": True,  # Perfil 2: Exige alineación limpia EMA17 > EMA30 > EMA50 en 1H
        # Filtros de Volumen y Volatilidad (Perfil 2: Agresivo Balanceado para IC Markets)
        "use_volume_filter": True,     # Exige participación real en ruptura (>= 1.00x SMA20)
        "vol_multiplier": 1.00,        # Volumen 5m >= 1.00x SMA20(Vol)
        "use_atr_regime": False,       # Desactivado para no bloquear rupturas válidas tras consolidación
        "min_atr_pct": 0.0005,         # ATR mínimo como % del precio (0.05%)
        # Protección Anti-Racha y Anti-Techo/Piso
        "prevent_exhaustion_entries": True,  # Bloquea compras si 1H rompe bajo EMA17 con pendiente negativa (y viceversa)
        "require_15m_ema_alignment": True,   # Exige EMA17 >= EMA30 en 15m para LONG (y <= para SHORT)
        "sl_cooldown_15m_bars": 2,           # Enfriamiento de 2 velas de 15m (30 min) tras un Stop Loss
        "max_consecutive_sl_same_side": 2,   # Bloquea re-entradas a peor precio tras 2 SL seguidos en la misma dirección
        # Tipo de Orden y Ejecución
        "order_type": "LIMIT",         # Orden LIMIT (o Market en MT5 IC Markets si el precio ya es favorable)
        # EMAs de tendencia
        "fast_ema": 17,
        "mid_ema": 30,
        "slow_ema": 50,
        # Filtro de Momentum RSI 14 (Perfil 2: Rango amplio balanceado)
        "rsi_period": 14,
        "rsi_long_min": 40.0,
        "rsi_long_max": 72.0,
        "rsi_short_min": 28.0,
        "rsi_short_max": 60.0,
        # Calidad de la Vela de Rebote en 15m (0.25 acepta velas de rechazo con buen cuerpo)
        "body_ratio_threshold": 0.25,
        # Margen de proximidad (buffer) para considerar pullback a las EMAs en 15m (0.15% = ~115 USD en BTC)
        "pullback_tolerance_pct": 0.0015,
        # Caducidad de la preparación en 15m (12 velas de 5m = 1 hora de ventana)
        "preparation_expiry_5m_bars": 12,
        # Estructura local de ruptura en 5m (4 velas = 20m de estructura local)
        "local_swing_lookback_5m": 4,
        # Stop Loss y Take Profit Validados (Ratio 1:2 con respiro anti-spread)
        "sl_type": "atr",              # Stop Loss por ATR dinámico
        "sl_atr_mult": 1.2,            # 1.2x ATR15m para dar respiro frente al spread y ruido de 1m/5m
        "sl_swing_buffer_atr": 0.20,   # Colchón de seguridad si se usa swing
        "sl_min_dist_pct": 0.0018,     # Distancia técnica mínima permitida (0.18% = ~140 USD en BTC, evita SL diminutos en fin de semana)
        "sl_max_dist_pct": 0.05,       # Distancia técnica máxima permitida (5.0%)
        "rr_ratio": 2.0,               # Relación R:R 1:2 (TP = 2x distancia del SL)
        "min_net_rr": 0.5,             # R:R neto mínimo admisible
        "tp_type": "2:1",
        # Costes estimados (IC Markets CFD sin comisión explícita por orden)
        "est_commission_pct": 0.0,     # 0.00% fee explícita en IC Markets BTCUSD
        "est_slippage_pct": 0.0,       # 0.00% slippage base
        # Compatibilidad con accesos antiguos
        "entry_tf": "15m"
    }
}

# ==============================================================================
# CONFIGURACIÓN DE BACKTESTING
# ==============================================================================
BACKTEST_PARAMS = {
    "start_date": "2026-06-01",
    "end_date": "2026-07-05",
    "initial_balance": 1000.0,
    "commission_pct": 0.0004, # 0.04% taker fee Binance Futures
    "slippage_pct": 0.0005,   # 0.05% slippage simulado
}

# ==============================================================================
# CONFIGURACIÓN DE MONTE CARLO
# ==============================================================================
MONTE_CARLO_PARAMS = {
    "num_simulations": 1000,
    "confidence_level": 0.95,
    "method": "block_bootstrap",  # "shuffle", "bootstrap", "block_bootstrap"
    "block_size": 5,              # Usado solo si method == "block_bootstrap"
    "simulate_uncertainty": True, # Agrega variación aleatoria a la ejecución
    "max_slippage_var": 0.0002,   # 0.02% variación adicional aleatoria max
    "max_commission_var": 0.0001,
    "ruin_drawdown_threshold": 0.30 # Probabilidad de perder 30% del equity
}
