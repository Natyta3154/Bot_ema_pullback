"""
Módulo: binance_state_sync.py
=================================================
Módulo de sincronización de estado. Se asegura de que el estado local del bot coincida con el estado real en Binance.
"""
import time
from bot.core.trade_logger import logger
from bot.core.order import OrderManager
from bot.core.position import PositionManager
from bot.config import settings

class BinanceStateSync:
    """
    Sincroniza el estado local del bot (PositionManager) con la realidad de Binance Futures al arranque.
    Previene estados corruptos y evita abrir posiciones duplicadas.
    """
    def __init__(self, order_manager: OrderManager, position_manager: PositionManager):
        self.om = order_manager
        self.pm = position_manager

    def sync(self):
        if self.om.paper_trading:
            logger.info("Modo PAPER TRADING: Saltando sincronización con Binance.")
            return

        logger.info("🔄 Iniciando sincronización de estado con Binance Futures...")
        
        try:
            # 1. Traer posición actual
            positions = self.om.client.fetch_positions([self.om.symbol])
            active_position = None
            for pos in positions:
                if self.om.symbol in pos['symbol']:
                    # pos['info'] tiene la data raw de binance
                    amt = float(pos['info'].get('positionAmt', 0))
                    if amt != 0:
                        active_position = pos
                        break
            
            if not active_position:
                logger.info("🔄 SINCRONIZACIÓN BINANCE | Posición: NINGUNA | Órdenes Abiertas: 0 | Estado: LIMPIO")
                self.pm.reset_position()
                self._cancel_all_open_orders()
                return

            # 2. Si hay posición en Binance, reconstruir PositionManager
            amt = float(active_position['info']['positionAmt'])
            side = 'LONG' if amt > 0 else 'SHORT'
            entry_price = float(active_position['info']['entryPrice'])
            
            logger.warning(f"⚠️ POSICIÓN ABIERTA DETECTADA EN BINANCE: {side} {abs(amt)} @ {entry_price}")
            
            self.pm.is_open = True
            self.pm.side = side
            self.pm.amount = abs(amt)
            self.pm.entry_price = entry_price
            
            # 3. Mapear Órdenes Abiertas (SL y TPs)
            open_orders = self.om.client.fetch_open_orders(self.om.symbol)
            
            # Limpiar IDs viejos
            self.pm.sl_order_id = ""
            self.pm.tp_order_id = ""
            self.pm.tp_targets = []
            
            has_sl = False
            for order in open_orders:
                o_type = order['type'].lower()
                o_side = order['side'].upper() # BUY o SELL
                
                # SL
                if 'stop' in o_type:
                    self.pm.sl_order_id = str(order['id'])
                    self.pm.stop_loss = float(order['stopPrice'])
                    has_sl = True
                    logger.info(f"🔄 Recuperado SL: ID {order['id']} @ {order['stopPrice']}")
                
                # TPs parciales (limit reduce-only) o TP Market
                elif o_type == 'limit' and order['info'].get('reduceOnly', False):
                    self.pm.tp_targets.append({
                        "price": float(order['price']),
                        "amount": float(order['amount']),
                        "order_id": str(order['id']),
                        "hit": False
                    })
                    logger.info(f"🔄 Recuperado TP Parcial: ID {order['id']} @ {order['price']}")
                    
                elif 'take_profit' in o_type:
                    self.pm.tp_order_id = str(order['id'])
                    self.pm.take_profit = float(order['stopPrice'])
                    logger.info(f"🔄 Recuperado TP Market: ID {order['id']} @ {order['stopPrice']}")

            if not has_sl:
                logger.error("🚨 CRÍTICO: La posición en Binance NO tiene un Stop Loss activo.")
                # En un entorno de verdad, aquí el usuario debería entrar manual o el bot poner uno de emergencia.
            
            self.pm.save()
            logger.info(f"🔄 SINCRONIZACIÓN BINANCE | Posición: {side} {abs(amt)} | Entrada: {entry_price} | Órdenes Abiertas: {len(open_orders)} | Estado: SINCRONIZADO")

        except Exception as e:
            logger.error(f"❌ Error crítico durante la sincronización: {e}")
            raise RuntimeError("Fallo en sincronización. Abortando arranque del bot por seguridad.")
            
    def _cancel_all_open_orders(self):
        """Cancela cualquier orden huérfana en Binance si no tenemos posición activa."""
        try:
            orders = self.om.client.fetch_open_orders(self.om.symbol)
            if orders:
                logger.warning(f"🧹 Limpiando {len(orders)} órdenes huérfanas en Binance...")
                self.om.client.cancel_all_orders(self.om.symbol)
        except Exception as e:
            logger.error(f"Error limpiando órdenes huérfanas: {e}")
