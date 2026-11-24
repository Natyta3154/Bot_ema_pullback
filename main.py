"""
Módulo Principal de Ejecución del Bot de Trading
=================================================
Este script es el punto de entrada principal para ejecutar el bot cuantitativo.
Se encarga de:
1. Configurar el entorno y las rutas.
2. Inicializar el motor de trading (`TradingEngine`).
3. Si no está en modo BACKTEST, sincronizar el estado local con la cuenta de Binance Futures.
4. Iniciar el bucle infinito del motor de ejecución.
"""
import sys
import os
import traceback

# Asegurar que el path raíz está en el system path para importaciones absolutas
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from bot.core.engine import TradingEngine
from bot.core.trade_logger import logger
from bot.config import settings
from bot.core.binance_state_sync import BinanceStateSync

if __name__ == "__main__":
    try:
        # En modo BACKTEST no queremos ejecutar BinanceStateSync porque usa la API
        engine = TradingEngine()
        
        if settings.ENVIRONMENT != "BACKTEST":
            # 1. Fase de Arranque: Sincronización Segura
            if getattr(settings, 'BROKER', 'BINANCE') == "ICMARKETS":
                from bot.connectors.mt5_state_sync import MT5StateSync
                sync_module = MT5StateSync(engine.order_manager, engine.position_manager)
            else:
                sync_module = BinanceStateSync(engine.order_manager, engine.position_manager)
            sync_module.sync()
            
            # 2. Kill Switch Anti-Duplicación de Arranque (Seguridad Extra)
            if engine.position_manager.is_open:
                logger.info(f"⚠️ El bot iniciará su ciclo MANTENIENDO y GESTIONANDO la posición actual en {settings.BROKER}.")
                
        # 3. Iniciar Engine Loop
        engine.run()
        
    except KeyboardInterrupt:
        logger.info("Bot detenido por el usuario.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error crítico en la ejecución del bot: {e}")
        traceback.print_exc()
