"""
Módulo: mock_order_manager.py
=================================================
Módulo mock_order_manager.py del sistema Backtesting.
"""
import time
from typing import Dict, List, Any, Optional
from datetime import datetime
from bot.core.trade_logger import logger
from bot.config import settings
from bot.core.profiler import profile_method

class MockOrderManager:
    """
    Simula ejecuciones cruzando órdenes pendientes con los precios 
    High/Low de la vela actual (pasada por el motor).
    Maneja saldos, fees y slippage simulados.
    """
    def __init__(self):
        self.balance = settings.BACKTEST_PARAMS['initial_balance']
        self.position_amt = 0.0
        self.position_side = None
        self.entry_price = 0.0
        self.mfe_price = 0.0
        self.mae_price = 0.0
        self.entry_time = None
        self.initial_risk_usdt = 0.0
        self.exit_reason = "UNKNOWN"
        
        # Diccionario para emular órdenes en la bolsa
        self.orders: Dict[str, dict] = {}
        self.order_counter = 1
        
        self.commission = settings.BACKTEST_PARAMS['commission_pct']
        self.slippage = settings.BACKTEST_PARAMS['slippage_pct']
        self.history: List[dict] = [] # Registro para reporte
        self.current_price = 0.0

    def get_balance(self) -> float:
        return self.balance

    def get_free_usdt(self) -> float:
        # Simplificación: en el simulador consideramos el balance entero como libre
        # ya que el apalancamiento no bloquea todo el margen.
        return self.balance

    def get_position_amount(self) -> float:
        return self.position_amt

    def cancel_order(self, order_id: str):
        if order_id in self.orders:
            self.orders[order_id]['status'] = 'canceled'

    def check_order_status(self, order_id: str) -> dict:
        return self.orders.get(order_id, None)
        
    def setup_account(self):
        pass # No requiere Binance

    def _generate_id(self) -> str:
        res = f"sim_order_{self.order_counter}"
        self.order_counter += 1
        return res

    # Removed _extract_decision_features

    def place_limit_long(self, amount: float, price: float, features: dict = None) -> str:
        oid = self._generate_id()
        self.orders[oid] = {
            'id': oid, 'type': 'limit', 'side': 'buy', 'amount': amount, 'price': price, 'status': 'open', 'reduceOnly': False,
            'features': features or {}
        }
        return oid

    def place_limit_short(self, amount: float, price: float, features: dict = None) -> str:
        oid = self._generate_id()
        self.orders[oid] = {
            'id': oid, 'type': 'limit', 'side': 'sell', 'amount': amount, 'price': price, 'status': 'open', 'reduceOnly': False,
            'features': features or {}
        }
        return oid

    def place_stop_market(self, side: str, amount: float, stop_price: float) -> str:
        order_side = 'sell' if side == 'LONG' else 'buy'
        oid = self._generate_id()
        self.orders[oid] = {'id': oid, 'type': 'stop', 'side': order_side, 'amount': amount, 'price': stop_price, 'status': 'open', 'reduceOnly': True}
        return oid

    def place_limit_close(self, side: str, amount: float, price: float) -> str:
        order_side = 'sell' if side == 'LONG' else 'buy'
        oid = self._generate_id()
        self.orders[oid] = {'id': oid, 'type': 'limit', 'side': order_side, 'amount': amount, 'price': price, 'status': 'open', 'reduceOnly': True}
        return oid

    def place_take_profit_market(self, side: str, amount: float, tp_price: float) -> str:
        order_side = 'sell' if side == 'LONG' else 'buy'
        oid = self._generate_id()
        self.orders[oid] = {'id': oid, 'type': 'tp_market', 'side': order_side, 'amount': amount, 'price': tp_price, 'status': 'open', 'reduceOnly': True}
        return oid

    def execute_market_close(self, side: str, amount: float) -> dict:
        """Cierra una posición a mercado instantáneamente (simulado al precio actual)."""
        order_side = 'sell' if side == 'LONG' else 'buy'
        oid = self._generate_id()
        amount = min(float(amount), self.position_amt)
        price = self.current_price or self.entry_price
        fee = amount * price * self.commission
        if self.position_side == "LONG":
            pnl = (price - self.entry_price) * amount
        else:
            pnl = (self.entry_price - price) * amount
        self.balance += pnl - fee
        order = {
            'id': oid, 'type': 'market', 'side': order_side, 'amount': amount,
            'status': 'closed', 'reduceOnly': True, 'average': price,
            'price': price, 'fee': {'cost': fee}, 'pnl': pnl
        }
        
        self.position_amt -= amount
        if self.position_amt <= 0.0001:
            self.position_amt = 0.0
            self.position_side = None
            self.entry_price = 0.0
            self.mfe_price = 0.0
            self.mae_price = 0.0
            self.entry_time = None
            self.initial_risk_usdt = 0.0
            
        return order

    @profile_method(category="Trading Engine")
    def process_candle(self, high: float, low: float, ts_str: str) -> List[dict]:
        """
        Llamado en cada tick por el BacktestEngine. Cruza las órdenes con High y Low.
        Devuelve lista de ejecuciones para este tick.
        """
        self.current_price = (float(high) + float(low)) / 2.0
        if self.position_amt > 0:
            if self.position_side == "LONG":
                self.mfe_price = max(self.mfe_price, high) if self.mfe_price else high
                self.mae_price = min(self.mae_price, low) if self.mae_price else low
            else:
                self.mfe_price = min(self.mfe_price, low) if self.mfe_price else low
                self.mae_price = max(self.mae_price, high) if self.mae_price else high

        executions = []
        
        # Evaluar órdenes y ordenarlas para ejecución pesimista (Stops primero)
        # Si una vela toca TP y SL, asumimos que tocó SL primero.
        open_orders = [o for o in self.orders.values() if o['status'] == 'open']
        open_orders.sort(key=lambda x: 0 if x['type'] == 'stop' else 1)
        
        for order in open_orders:
            if order['status'] != 'open':
                continue
                
            # Si es reduceOnly pero la posición ya se cerró en esta misma vela (ej. por un Stop)
            if order['reduceOnly'] and self.position_amt <= 0.0001:
                order['status'] = 'canceled'
                continue

            oid = order['id']
            filled = False
            exec_price = 0.0

            if order['type'] == 'limit' and order['side'] == 'buy':
                if low <= order['price']:
                    filled = True
                    exec_price = order['price'] * (1 + self.slippage)
            elif order['type'] == 'limit' and order['side'] == 'sell':
                if high >= order['price']:
                    filled = True
                    exec_price = order['price'] * (1 - self.slippage)
            elif order['type'] == 'stop' and order['side'] == 'buy':
                if high >= order['price']:
                    filled = True
                    exec_price = order['price'] * (1 + self.slippage)
            elif order['type'] == 'stop' and order['side'] == 'sell':
                if low <= order['price']:
                    filled = True
                    exec_price = order['price'] * (1 - self.slippage)
            elif order['type'] == 'tp_market' and order['side'] == 'buy':
                if low <= order['price']:
                    filled = True
                    exec_price = order['price'] * (1 + self.slippage)
            elif order['type'] == 'tp_market' and order['side'] == 'sell':
                if high >= order['price']:
                    filled = True
                    exec_price = order['price'] * (1 - self.slippage)

            if filled:
                order['status'] = 'closed'
                order['exec_price'] = exec_price
                
                # Actualizar posición y balance simulado
                value = order['amount'] * exec_price
                fee = value * self.commission
                self.balance -= fee # Restar fee inmediatamente

                if order['reduceOnly']:
                    # Cierre de posición (total o parcial)
                    if self.position_side == "LONG":
                        pnl = (exec_price - self.entry_price) * order['amount']
                        mfe_pct = (self.mfe_price - self.entry_price) / self.entry_price if self.entry_price > 0 else 0
                        mae_pct = (self.mae_price - self.entry_price) / self.entry_price if self.entry_price > 0 else 0
                    else:
                        pnl = (self.entry_price - exec_price) * order['amount']
                        mfe_pct = (self.entry_price - self.mfe_price) / self.entry_price if self.entry_price > 0 else 0
                        mae_pct = (self.entry_price - self.mae_price) / self.entry_price if self.entry_price > 0 else 0
                    self.balance += pnl
                    
                    # R value
                    r_value = 0.0
                    if self.initial_risk_usdt > 0:
                        r_value = pnl / self.initial_risk_usdt
                        
                    import pandas as pd
                    current_dt = pd.to_datetime(ts_str)
                    duration_mins = 0
                    if self.entry_time:
                        duration_mins = int((current_dt - self.entry_time).total_seconds() / 60)
                        
                    order['mfe_pct'] = mfe_pct
                    order['mae_pct'] = mae_pct
                    order['duration_mins'] = duration_mins
                    order['r_value'] = r_value
                    
                    self.position_amt -= order['amount']
                    if self.position_amt <= 0.0001: # Tolerancia
                        self.position_amt = 0.0
                        self.position_side = None
                        self.entry_price = 0.0
                        self.mfe_price = 0.0
                        self.mae_price = 0.0
                        self.entry_time = None
                        self.initial_risk_usdt = 0.0
                else:
                    # Apertura de posición
                    self.position_side = "LONG" if order['side'] == 'buy' else "SHORT"
                    self.position_amt = order['amount']
                    self.entry_price = exec_price
                    self.mfe_price = exec_price
                    self.mae_price = exec_price
                    import pandas as pd
                    self.entry_time = pd.to_datetime(ts_str)
                    
                    # Calcular riesgo inicial basado en el SL (si existe)
                    sl = order.get('features', {}).get('sl_price', 0.0)
                    if sl > 0:
                        self.initial_risk_usdt = abs(exec_price - sl) * order['amount']
                    else:
                        self.initial_risk_usdt = 0.0
                        
                    self.active_position_features = order.get('features', {})

                # Registrar historial para el reporte
                entry_feats = (getattr(self, 'active_position_features', {}) if order['reduceOnly'] else order.get('features', {})).copy()
                try:
                    import pandas as pd
                    dt = pd.to_datetime(ts_str)
                    entry_feats['utc_hour'] = int(dt.hour)
                except:
                    entry_feats['utc_hour'] = -1

                trade_record = {
                    'order_id': oid,
                    'timestamp': ts_str,
                    'side': order['side'],
                    'type': order['type'],
                    'amount': order['amount'],
                    'price': exec_price,
                    'fee': fee,
                    'reduceOnly': order['reduceOnly'],
                    'pnl': pnl if order['reduceOnly'] else 0.0,
                    'balance': self.balance,
                    'mfe_pct': order.get('mfe_pct', 0.0),
                    'mae_pct': order.get('mae_pct', 0.0),
                    'duration_mins': order.get('duration_mins', 0),
                    'r_value': order.get('r_value', 0.0),
                    'exit_reason': order.get('type', 'unknown') if order['reduceOnly'] else '',
                    'entry_features': entry_feats
                }
                self.history.append(trade_record)
                executions.append(trade_record)

        return executions
