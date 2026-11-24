"""
Módulo: order.py
=================================================
Gestor de órdenes. Encargado de la creación, seguimiento y cancelación de órdenes en el exchange.
"""
import ccxt
import pandas as pd
import time
from typing import Optional, Dict
from bot.config import settings
from bot.core.trade_logger import logger

class OrderManager:
    """
    Clase que encapsula toda la comunicación con los servidores de Binance.
    Maneja obtención de saldos, colocación y cancelación de órdenes.
    """
    def __init__(self):
        if settings.ENVIRONMENT == "LIVE" and not settings.LIVE_TRADING_ENABLED:
            raise RuntimeError(
                "LIVE trading bloqueado por seguridad. Use PAPER o BACKTEST."
            )
        self.paper_trading = (settings.ENVIRONMENT == "PAPER")
        self.symbol = settings.SYMBOL

        # Paper y backtest deben compartir exactamente las mismas reglas de
        # fills, comisiones, slippage y estado de posición.
        self.simulator = None
        if self.paper_trading:
            from bot.backtest.mock_order_manager import MockOrderManager
            self.simulator = MockOrderManager()

        params = {
            'apiKey': settings.API_KEY,
            'secret': settings.API_SECRET,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future', 
                'adjustForTimeDifference': True,
            }
        }
        self.client = ccxt.binance(params)
        
        if self.paper_trading:
            logger.info("MODO: PAPER TRADING (Binance Futures Testnet - Dinero Ficticio)")
            self.client.set_sandbox_mode(True)
        elif settings.ENVIRONMENT == "LIVE":
            logger.warning("MODO: LIVE TRADING (¡Atención: Operando con Dinero Real!)")
        
        try:
            self.client.load_time_difference()
        except Exception as e:
            logger.warning(f"No se pudo cargar la diferencia de tiempo con Binance: {e}")

        # En backtest no llamaremos a setup_account (se inyectará otro OrderManager si es necesario)
        if settings.ENVIRONMENT != "BACKTEST":
            self.setup_account()

    def setup_account(self):
        """Asegura modo Aislado y Apalancamiento correcto."""
        try:
            self.client.load_markets()
            try:
                self.client.set_margin_mode('isolated', self.symbol)
                logger.info(f"Margen configurado como AISLADO para {self.symbol}")
            except Exception as e:
                logger.error(f"Error al configurar margen (quizás ya está aislado): {e}")

            try:
                self.client.set_leverage(settings.LEVERAGE, self.symbol)
                logger.info(f"Apalancamiento ajustado a {settings.LEVERAGE}x para {self.symbol}")
            except Exception as e:
                logger.error(f"Error al configurar apalancamiento: {e}")
                
        except Exception as e:
            logger.error(f"Error crítico en setup_account: {e}")

    def cancel_order(self, order_id: str) -> bool:
        if self.paper_trading:
            self.simulator.cancel_order(order_id)
            logger.info(f"[PAPER] Orden {order_id} cancelada simuladamente.")
            return True
        try:
            self.client.cancel_order(order_id, self.symbol)
            logger.info(f"Orden {order_id} cancelada exitosamente en Binance.")
            return True
        except Exception as e:
            error_str = str(e).lower()
            if "-2011" in error_str or "unknown order" in error_str:
                logger.info(f"[INFO] La orden protectora {order_id} ya no existe en Binance (limpieza completada).")
            else:
                logger.error(f"Error al cancelar la orden {order_id}: {e}")
            return False

    def place_limit_short(self, amount: float, price: float, features: dict = None) -> str:
        if self.paper_trading:
            return self.simulator.place_limit_short(amount, price, features)
        try:
            order = self.client.create_limit_sell_order(self.symbol, amount, price)
            logger.info(f"Orden Limit SHORT creada en Binance. ID: {order['id']}")
            return order['id']
        except Exception as e:
            logger.error(f"Error al crear orden Limit SHORT: {e}")
            return ""

    def place_limit_long(self, amount: float, price: float, features: dict = None) -> str:
        if self.paper_trading:
            return self.simulator.place_limit_long(amount, price, features)
        try:
            order = self.client.create_limit_buy_order(self.symbol, amount, price)
            logger.info(f"Orden Limit LONG creada en Binance. ID: {order['id']}")
            return order['id']
        except Exception as e:
            logger.error(f"Error al crear orden Limit LONG: {e}")
            return ""

    def place_stop_market(self, side: str, amount: float, stop_price: float) -> str:
        if self.paper_trading:
            return self.simulator.place_stop_market(side, amount, stop_price)
        try:
            order_side = 'sell' if side == 'LONG' else 'buy'
            params = {'stopPrice': stop_price, 'reduceOnly': True}
            order = self.client.create_order(self.symbol, type='stop_market', side=order_side, amount=amount, price=None, params=params)
            logger.info(f"Orden STOP_MARKET (SL) creada en Binance. ID: {order['id']}")
            return order['id']
        except Exception as e:
            logger.error(f"Error al crear orden STOP_MARKET: {e}")
            return ""

    def place_limit_close(self, side: str, amount: float, price: float) -> str:
        """Crea una orden Limit Reduce Only para Take Profits parciales."""
        if self.paper_trading:
            return self.simulator.place_limit_close(side, amount, price)
        try:
            order_side = 'sell' if side == 'LONG' else 'buy'
            params = {'reduceOnly': True}
            order = self.client.create_order(self.symbol, type='limit', side=order_side, amount=amount, price=price, params=params)
            logger.info(f"Orden Limit Close (TP) creada en Binance. ID: {order['id']}")
            return order['id']
        except Exception as e:
            logger.error(f"Error al crear orden Limit Close (TP): {e}")
            return ""

    def place_take_profit_market(self, side: str, amount: float, tp_price: float) -> str:
        if self.paper_trading:
            return self.simulator.place_take_profit_market(side, amount, tp_price)
        try:
            order_side = 'sell' if side == 'LONG' else 'buy'
            params = {'stopPrice': tp_price, 'reduceOnly': True}
            order = self.client.create_order(self.symbol, type='take_profit_market', side=order_side, amount=amount, price=None, params=params)
            logger.info(f"Orden TAKE_PROFIT_MARKET (TP) creada en Binance. ID: {order['id']}")
            return order['id']
        except Exception as e:
            logger.error(f"Error al crear orden TAKE_PROFIT_MARKET: {e}")
            return ""

    def check_order_status(self, order_id: str) -> Optional[Dict]:
        if self.paper_trading:
            return self.simulator.check_order_status(order_id)
        try:
            order = self.client.fetch_order(order_id, self.symbol)
            return order
        except Exception as e:
            logger.error(f"Error consultando el estado de la orden {order_id}: {e}")
            return None

    def execute_market_close(self, side: str, amount: float) -> Optional[Dict]:
        try:
            logger.info(f"Cerrando posición {side} de {amount} BTC a precio de MERCADO.")
            close_side = 'sell' if side == 'LONG' else 'buy'
            if self.paper_trading:
                return self.simulator.execute_market_close(side, amount)
            else:
                params = {'reduceOnly': True}
                order = self.client.create_market_order(self.symbol, close_side, amount, params=params)
                # Fetchear detalles de la orden cerrada para tener fill_price y comisiones
                try:
                    time.sleep(1) # Pequeña pausa para asegurar que el motor de Binance haga match y reporte fees
                    order = self.client.fetch_order(order['id'], self.symbol)
                except:
                    pass
                return order
        except Exception as e:
            error_str = str(e)
            if "-2022" in error_str or "ReduceOnly" in error_str:
                logger.warning("Alerta ReduceOnly: La orden fue rechazada porque la posición ya no existe en Binance. Forzando limpieza local.")
                return {'status': 'closed'}
            logger.error(f"Error crítico al intentar cerrar la posición: {e}")
            return None

    def get_free_usdt(self) -> float:
        if self.paper_trading:
            return self.simulator.get_free_usdt()
        try:
            balance = self.client.fetch_balance()
            return float(balance.get('USDT', {}).get('free', 0.0))
        except Exception as e:
            logger.error(f"Error consultando saldo de USDT: {e}")
            return 0.0

    def get_position_amount(self) -> float:
        """Chequea en Binance si realmente hay una posición abierta"""
        if self.paper_trading:
            return self.simulator.get_position_amount()
        try:
            positions = self.client.fetch_positions([self.symbol])
            for pos in positions:
                if self.symbol in pos['symbol']:
                    return abs(float(pos['info']['positionAmt']))
            return 0.0
        except Exception as e:
            logger.error(f"Error obteniendo posición real: {e}")
            return 0.0

    def process_candle(self, high: float, low: float, ts_str: str):
        """Procesa fills simulados en paper; no tiene efecto en live."""
        if self.paper_trading:
            return self.simulator.process_candle(high, low, ts_str)
        return []
