"""
Módulo: execution.py
=================================================
Capa de ejecución de bajo nivel para interactuar con la API del exchange y gestionar órdenes complejas.
"""
import pandas as pd
from datetime import datetime
from bot.core.order import OrderManager
from bot.core.position import PositionManager
from bot.core.trade_logger import logger, log_trade

class ExecutionManager:
    def __init__(self, order_manager: OrderManager, position_manager: PositionManager):
        self.order_manager = order_manager
        self.position = position_manager

    def handle_pending_order(self, current_candle_time: str):
        if not self.position.pending_order_id:
            return

        try:
            order = self.order_manager.check_order_status(self.position.pending_order_id)
            if order and order['status'] == 'closed':
                logger.info(f"🎯 ¡ORDEN LÍMITE EJECUTADA! Entramos al mercado en {self.position.side}.")
                
                real_entry_price = float(order.get('average') or order.get('price') or self.position.pending_order_price)
                if real_entry_price == 0.0 or pd.isna(real_entry_price):
                    real_entry_price = self.position.pending_order_price

                planned_entry = float(self.position.pending_order_price or 0.0)
                if planned_entry > 0 and abs(real_entry_price - planned_entry) > 1e-6:
                    delta = real_entry_price - planned_entry
                    if self.position.stop_loss > 0:
                        self.position.stop_loss = round(self.position.stop_loss + delta, 2)
                    if self.position.take_profit > 0:
                        self.position.take_profit = round(self.position.take_profit + delta, 2)
                    for target in self.position.tp_targets:
                        if target.get('price', 0) > 0:
                            target['price'] = round(float(target['price']) + delta, 2)
                    
                entry_time = current_candle_time
                try:
                    entry_time = pd.to_datetime(current_candle_time).isoformat()
                except Exception:
                    entry_time = datetime.now().isoformat()
                self.position.open_from_fill(
                    self.position.side,
                    self.position.amount,
                    real_entry_price,
                    entry_time,
                )
                
                # SL
                self.position.sl_order_id = self.order_manager.place_stop_market(self.position.side, self.position.amount, self.position.stop_loss)
                
                # Multiples TPs o TP único
                if len(self.position.tp_targets) > 0:
                    for i, target in enumerate(self.position.tp_targets):
                        t_id = self.order_manager.place_limit_close(self.position.side, target['amount'], target['price'])
                        self.position.tp_targets[i]['order_id'] = t_id
                elif self.position.take_profit > 0:
                    self.position.tp_order_id = self.order_manager.place_take_profit_market(self.position.side, self.position.amount, self.position.take_profit)
                
                self.position.save()
                
                log_trade({
                    "action": "ENTRY",
                    "side": self.position.side,
                    "entry_price": self.position.entry_price,
                    "amount": self.position.amount,
                    "stop_loss": self.position.stop_loss,
                    "take_profit": self.position.take_profit,
                    "sl_order_id": self.position.sl_order_id,
                    "tp_order_id": self.position.tp_order_id,
                    "commission": (order.get('fee') or {}).get('cost', 0.0),
                    "order_id": order.get('id', 'N/A'),
                    "entry_time": self.position.entry_time
                })
                
            elif current_candle_time != self.position.last_candle_1h_time:
                logger.info(f"⏳ Cambio a nueva vela detectado. Cancelando orden límite antigua por caducidad.")
                self.order_manager.cancel_order(self.position.pending_order_id)
                self.position.reset_position()
                
        except Exception as e:
            logger.error(f"Error monitoreando estado de la orden pendiente: {e}")
