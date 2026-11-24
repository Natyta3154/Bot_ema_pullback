"""
Módulo: mt5_state_sync.py
=================================================
Módulo de sincronización de estado para MetaTrader 5 (IC Markets).
Asegura que el estado local (PositionManager) coincida con la realidad del terminal MT5 al arranque.
"""
import MetaTrader5 as mt5
from bot.core.trade_logger import logger
from bot.core.position import PositionManager
from bot.connectors.mt5_order import MT5OrderManager


class MT5StateSync:
    """
    Sincroniza el estado local del bot con las posiciones y órdenes activas en MT5 al inicio.
    """
    def __init__(self, order_manager: MT5OrderManager, position_manager: PositionManager):
        self.om = order_manager
        self.pm = position_manager

    def sync(self):
        if self.om.paper_trading:
            logger.info("[MT5] Modo PAPER TRADING: Saltando sincronización con broker.")
            return

        logger.info(f"🔄 Iniciando sincronización de estado con IC Markets MT5 ({self.om.symbol})...")

        try:
            positions = mt5.positions_get(symbol=self.om.symbol)

            if not positions or len(positions) == 0:
                logger.info("[MT5] Sincronización: Ninguna posición activa en MT5. Estado local limpio.")
                self.pm.reset_position()
                self._cancel_all_pending_orders()
                return

            pos = positions[0]
            side = 'LONG' if pos.type == mt5.ORDER_TYPE_BUY else 'SHORT'
            logger.warning(f"⚠️ [MT5] POSICIÓN ACTIVA DETECTADA: {side} {pos.volume} @ {pos.price_open} (Ticket: {pos.ticket})")

            self.pm.is_open = True
            self.pm.side = side
            self.pm.amount = float(pos.volume)
            self.pm.entry_price = float(pos.price_open)
            self.pm.stop_loss = float(pos.sl)
            self.pm.take_profit = float(pos.tp)
            self.pm.sl_order_id = str(pos.ticket) if pos.sl > 0 else ""
            self.pm.tp_order_id = str(pos.ticket) if pos.tp > 0 else ""
            self.pm.tp_targets = []

            # Mapear órdenes pendientes (por si hay TPs parciales colocados)
            pending_orders = mt5.orders_get(symbol=self.om.symbol)
            if pending_orders:
                for ord_info in pending_orders:
                    # Si es orden opuesta, puede ser un TP parcial
                    is_opp_limit = (side == 'LONG' and ord_info.type == mt5.ORDER_TYPE_SELL_LIMIT) or \
                                   (side == 'SHORT' and ord_info.type == mt5.ORDER_TYPE_BUY_LIMIT)
                    if is_opp_limit:
                        self.pm.tp_targets.append({
                            "price": float(ord_info.price_open),
                            "amount": float(ord_info.volume_current),
                            "order_id": str(ord_info.ticket),
                            "hit": False
                        })
                        logger.info(f"🔄 [MT5] Recuperado TP Parcial: Ticket {ord_info.ticket} @ {ord_info.price_open}")

            if pos.sl == 0.0:
                logger.warning("🚨 [MT5] ALERTA: La posición abierta en MT5 no tiene Stop Loss asignado.")

            self.pm.save()
            logger.info(f"🔄 [MT5] Sincronización exitosa: {side} {pos.volume} @ {pos.price_open}")

        except Exception as e:
            logger.error(f"❌ [MT5] Error durante la sincronización: {e}")
            raise RuntimeError(f"Fallo en sincronización MT5: {e}")

    def _cancel_all_pending_orders(self):
        """Limpia órdenes pendientes huérfanas si no hay posición activa."""
        try:
            orders = mt5.orders_get(symbol=self.om.symbol)
            if orders:
                logger.warning(f"🧹 [MT5] Limpiando {len(orders)} órdenes pendientes huérfanas...")
                for o in orders:
                    self.om.cancel_order(str(o.ticket))
        except Exception as e:
            logger.error(f"[MT5] Error al limpiar órdenes huérfanas: {e}")
