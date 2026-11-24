"""
Módulo: position.py
=================================================
Gestor de posiciones. Rastrea y gestiona las operaciones abiertas (tamaño, PNL, breakeven).
"""
import json
import os
from bot.config import settings
from bot.core.trade_logger import logger

class PositionManager:
    """
    Maneja la memoria persistente del bot.
    Guarda precios de entrada, estado de órdenes, niveles de TP/SL, etc.
    """
    def __init__(self):
        self.is_open: bool = False
        self.side: str = ""
        self.entry_price: float = 0.0
        self.amount: float = 0.0
        self.stop_loss: float = 0.0
        self.take_profit: float = 0.0 # Mantenemos por retrocompatibilidad (TP nativo)
        self.tp_targets: list = [] # Lista de diccionarios: [{"price": X, "amount": Y, "order_id": "", "hit": False}]
        self.entry_time: str = ""
        self.lowest_price = None
        self.highest_price: float = 0.0
        self.breakeven_activated: bool = False
        self.pending_order_id: str = ""
        self.pending_order_price: float = 0.0
        self.last_candle_1h_time: str = ""
        self.sl_order_id: str = ""
        self.tp_order_id: str = ""
        self.strategy_state: dict = {} # Para persistir estado de la estrategia (ej. "esperando_retesteo")
        self.load()

    def load(self):
        """Carga el estado previo desde el disco."""
        if settings.ENVIRONMENT == "BACKTEST":
            return
            
        if os.path.exists(settings.STATE_FILE):
            try:
                with open(settings.STATE_FILE, 'r') as f:
                    data = json.load(f)
                    for k, v in data.items():
                        setattr(self, k, v)
                logger.info("Memoria del bot (estado local) cargada exitosamente.")
            except Exception as e:
                logger.error(f"Error al cargar la memoria del bot: {e}")

    def save(self):
        """Guarda el estado actual en el disco."""
        if settings.ENVIRONMENT == "BACKTEST":
            return
            
        try:
            with open(settings.STATE_FILE, 'w') as f:
                json.dump(self.__dict__, f, indent=4)
        except Exception as e:
            logger.error(f"Error al guardar la memoria del bot: {e}")

    def open_from_fill(self, side: str, amount: float, entry_price: float, entry_time: str):
        """Transiciona una entrada pendiente a una posicion abierta."""
        self.is_open = True
        self.side = side
        self.amount = max(float(amount), 0.0)
        self.entry_price = float(entry_price)
        self.entry_time = entry_time
        self.pending_order_id = ""
        self.pending_order_price = 0.0

    def apply_partial_exit(self, amount: float) -> float:
        """Descuenta una salida parcial y devuelve la cantidad aplicada."""
        applied = min(max(float(amount), 0.0), self.amount)
        self.amount = max(self.amount - applied, 0.0)
        return applied

    def has_remaining_amount(self) -> bool:
        return self.amount > 0.0000001

    def reset_position(self):
        """Limpia completamente el estado al cerrar una posición."""
        self.is_open = False
        self.side = ""
        self.entry_price = 0.0
        self.amount = 0.0
        self.stop_loss = 0.0
        self.take_profit = 0.0
        self.tp_targets = []
        self.lowest_price = None
        self.highest_price = 0.0
        self.breakeven_activated = False
        self.entry_time = ""
        self.pending_order_id = ""
        self.pending_order_price = 0.0
        self.last_candle_1h_time = ""
        self.sl_order_id = ""
        self.tp_order_id = ""
        self.strategy_state = {}
        self.save()
