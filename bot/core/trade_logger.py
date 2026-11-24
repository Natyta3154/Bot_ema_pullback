"""
Módulo: trade_logger.py
=================================================
Sistema centralizado de registro de logs y persistencia del historial de trades (trading_log.json).
"""
import logging
import json
import os
from datetime import datetime
import colorama
from colorama import Fore, Style
from bot.config import settings

# Inicializar colorama para soporte multiplataforma (Windows/Linux)
colorama.init(autoreset=True)

# Constantes de colores para usar en todo el bot
class Colors:
    GREEN = Fore.GREEN
    RED = Fore.RED
    YELLOW = Fore.YELLOW
    BLUE = Fore.BLUE
    MAGENTA = Fore.MAGENTA
    CYAN = Fore.CYAN
    RESET = Style.RESET_ALL

def setup_logging():
    logger = logging.getLogger('IntradayFuturesBot')
    if not logger.handlers:
        level = logging.WARNING if getattr(settings, 'ENVIRONMENT', '') == 'BACKTEST' else logging.INFO
        logger.setLevel(level)
        formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s')
        ch = logging.StreamHandler()
        ch.setLevel(level)
        ch.setFormatter(formatter)
        logger.addHandler(ch)
    return logger

logger = setup_logging()

def log_trade(trade_data: dict):
    if settings.ENVIRONMENT == "BACKTEST":
        return
        
    try:
        logs = []
        if os.path.exists(settings.TRADING_LOG_FILE):
            with open(settings.TRADING_LOG_FILE, 'r') as f:
                logs = json.load(f)
        
        trade_data['timestamp'] = datetime.now().isoformat()
        logs.append(trade_data)
        
        with open(settings.TRADING_LOG_FILE, 'w') as f:
            json.dump(logs, f, indent=4)
    except Exception as e:
        logger.error(f"Error al guardar el log de trading: {e}")

def log_live_signal(timestamp: str, action: str, price: float, reason: str, features: dict):
    """
    Guarda todas las señales evaluadas en tiempo real (aceptadas o rechazadas)
    en un CSV idéntico al generado por el laboratorio cuantitativo.
    """
    if settings.ENVIRONMENT == "BACKTEST":
        return
        
    import csv
    file_exists = os.path.isfile(settings.LIVE_RAW_TRADES_CSV)
    
    fieldnames = [
        'timestamp', 'action', 'price', 'reason', 
        'ema17', 'ema30', 'atr', 'vol_ratio',
        'body_ratio', 'slope_ema30', 'dist_ema30_atr', 'rsi',
        'pullback_dist_atr'
    ]
    
    try:
        with open(settings.LIVE_RAW_TRADES_CSV, 'a', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
                
            row = {
                'timestamp': timestamp,
                'action': action,
                'price': price,
                'reason': reason
            }
            # Llenar las features asegurando que existan
            for f in fieldnames[4:]:
                row[f] = features.get(f, 0.0)
                
            writer.writerow(row)
    except Exception as e:
        logger.error(f"Error guardando señal en vivo en CSV: {e}")
