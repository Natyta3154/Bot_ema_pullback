"""
Módulo: mt5_order.py
=================================================
Gestor de órdenes para MetaTrader 5 (IC Markets).
Encapsula la comunicación con la plataforma MT5:
- Envío, modificación y cancelación de órdenes
- Gestión de Stop Loss y Take Profit
- Sincronización de balances y posiciones
"""
import time
from typing import Optional, Dict
import MetaTrader5 as mt5
from bot.config import settings
from bot.core.trade_logger import logger


class MT5OrderManager:
    """
    Clase que encapsula toda la comunicación con el terminal MetaTrader 5 de IC Markets.
    Mantiene compatibilidad de interfaz con el OrderManager de Binance.
    """
    def __init__(self):
        if settings.ENVIRONMENT == "LIVE" and not settings.LIVE_TRADING_ENABLED:
            raise RuntimeError(
                "LIVE trading bloqueado por seguridad en settings.LIVE_TRADING_ENABLED. Use PAPER o BACKTEST."
            )
        self.paper_trading = (settings.ENVIRONMENT == "PAPER")
        self.symbol = settings.SYMBOL

        self.simulator = None
        if self.paper_trading:
            from bot.backtest.mock_order_manager import MockOrderManager
            self.simulator = MockOrderManager()

        if settings.ENVIRONMENT != "BACKTEST":
            self.setup_account()

    def setup_account(self):
        """Inicializa conexión con MT5 y verifica login."""
        try:
            init_kwargs = {}
            if settings.MT5_PATH:
                init_kwargs['path'] = settings.MT5_PATH
            if settings.MT5_LOGIN > 0:
                init_kwargs['login'] = int(settings.MT5_LOGIN)
                init_kwargs['password'] = settings.MT5_PASSWORD.strip()
                init_kwargs['server'] = settings.MT5_SERVER.strip()

            if not mt5.initialize(**init_kwargs):
                # Fallback: inicializar terminal primero y luego autenticar con mt5.login
                bare_kwargs = {'path': settings.MT5_PATH} if settings.MT5_PATH else {}
                if not mt5.initialize(**bare_kwargs):
                    logger.error(f"[MT5] Error al inicializar terminal MT5: {mt5.last_error()}")
                    return
                if settings.MT5_LOGIN > 0:
                    authorized = mt5.login(
                        login=int(settings.MT5_LOGIN),
                        password=settings.MT5_PASSWORD.strip(),
                        server=settings.MT5_SERVER.strip()
                    )
                    if not authorized:
                        logger.error(f"[MT5] Error de autenticación cuenta {settings.MT5_LOGIN}: {mt5.last_error()}")
                        return
            
            acc = mt5.account_info()
            if acc:
                credit_str = f" | Crédito/Bonus: {acc.credit:.2f} {acc.currency} | Equity: {acc.equity:.2f} {acc.currency}" if getattr(acc, 'credit', 0) > 0 else ""
                logger.info(f"[MT5] Conectado exitosamente | Cuenta: {acc.login} | Servidor: {acc.server} | Balance Real: {acc.balance:.2f} {acc.currency}{credit_str}")

            # Asegurar que el símbolo esté visible y habilitado
            if not mt5.symbol_select(self.symbol, True):
                logger.warning(f"[MT5] Advertencia: No se pudo seleccionar el símbolo {self.symbol} en MT5. Verifique el nombre exacto.")
            else:
                logger.info(f"[MT5] Símbolo activo configurado: {self.symbol}")

        except Exception as e:
            logger.error(f"[MT5] Excepción crítica durante setup_account: {e}")

    def get_symbol_info(self):
        info = mt5.symbol_info(self.symbol)
        if not info:
            mt5.symbol_select(self.symbol, True)
            info = mt5.symbol_info(self.symbol)
        return info

    def get_filling_mode(self) -> int:
        """Determina la política de llenado soportada por el broker para el símbolo."""
        info = self.get_symbol_info()
        if not info:
            return mt5.ORDER_FILLING_FOK
        filling = getattr(info, 'filling_mode', 0)
        # En MT5 symbol_info().filling_mode es una máscara de bits:
        # Bit 1 (valor 1) = SYMBOL_FILLING_FOK -> usar mt5.ORDER_FILLING_FOK
        # Bit 2 (valor 2) = SYMBOL_FILLING_IOC -> usar mt5.ORDER_FILLING_IOC
        if filling & 1:
            return mt5.ORDER_FILLING_FOK
        elif filling & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def _send_order_with_filling_fallback(self, request: dict):
        """
        Envía la orden a MT5 y, si el broker rechaza el modo de llenado (retcode 10030),
        reintenta automáticamente con los modos alternativos (FOK, IOC, RETURN).
        """
        res = mt5.order_send(request)
        invalid_fill_code = getattr(mt5, 'TRADE_RETCODE_INVALID_FILL', 10030)
        if res and getattr(res, 'retcode', None) == invalid_fill_code:
            initial_mode = request.get("type_filling")
            for fallback_mode in (mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN):
                if fallback_mode == initial_mode:
                    continue
                req_retry = dict(request)
                req_retry["type_filling"] = fallback_mode
                res_retry = mt5.order_send(req_retry)
                if res_retry and getattr(res_retry, 'retcode', None) != invalid_fill_code:
                    return res_retry
        return res

    def normalize_volume(self, volume: float) -> float:
        """Adapta y redondea el volumen según los límites y el paso de lote del símbolo."""
        info = self.get_symbol_info()
        if not info:
            return round(max(0.01, volume), 2)

        step = info.volume_step if info.volume_step > 0 else 0.01
        min_vol = info.volume_min if info.volume_min > 0 else 0.01
        max_vol = info.volume_max if info.volume_max > 0 else 100.0

        steps = round(volume / step)
        norm_vol = steps * step
        norm_vol = max(min_vol, min(norm_vol, max_vol))

        decimals = 2
        s = str(step)
        if '.' in s:
            decimals = len(s.split('.')[1])
        return round(norm_vol, decimals)

    def normalize_price(self, price: float) -> float:
        """Redondea el precio a los dígitos requeridos por el broker."""
        info = self.get_symbol_info()
        digits = info.digits if info else 2
        return round(price, digits)

    def cancel_order(self, order_id: str) -> bool:
        if self.paper_trading:
            self.simulator.cancel_order(order_id)
            logger.info(f"[PAPER] Orden {order_id} cancelada simuladamente.")
            return True
        try:
            oid_str = str(order_id)
            if oid_str.startswith(("SL_", "TP_")):
                # En MT5 el SL y TP son atributos de la posición, no órdenes pendientes independientes.
                return True
            order_ticket = int(oid_str)
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": order_ticket
            }
            res = mt5.order_send(request)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"[MT5] Orden {order_ticket} cancelada exitosamente.")
                return True
            else:
                err = res.comment if res else mt5.last_error()
                logger.warning(f"[MT5] No se pudo cancelar la orden {order_ticket}: {err}")
                return False
        except Exception as e:
            logger.error(f"[MT5] Error al cancelar orden {order_id}: {e}")
            return False

    def place_limit_short(self, amount: float, price: float, features: dict = None) -> str:
        if self.paper_trading:
            return self.simulator.place_limit_short(amount, price, features)
        try:
            vol = self.normalize_volume(amount)
            p = self.normalize_price(price)
            info = self.get_symbol_info()
            tick = mt5.symbol_info_tick(self.symbol)
            stops_level = (info.trade_stops_level * info.point) if (info and getattr(info, 'trade_stops_level', 0)) else 0.0

            features = features if features is not None else {}
            sl_price = features.get('sl_price') or features.get('stop_loss', 0.0)
            tp_price = features.get('take_profit', 0.0)
            p_sl = self.normalize_price(float(sl_price)) if sl_price and float(sl_price) > 0 else 0.0
            p_tp = self.normalize_price(float(tp_price)) if tp_price and float(tp_price) > 0 else 0.0

            # En MT5 una orden Sell Limit por debajo o igual al Ask actual devuelve error 10015 (Invalid price).
            # Si el mercado ya cruzó o está en nuestro precio objetivo de venta, ejecutamos a mercado (TRADE_ACTION_DEAL).
            min_limit_price = (tick.ask + stops_level) if tick else p
            if tick and p <= min_limit_price:
                exec_bid = float(tick.bid)
                if p_sl > p > 0:
                    risk_dist = p_sl - p
                    p_sl = self.normalize_price(exec_bid + risk_dist)
                    features['sl_price'] = p_sl
                    features['stop_loss'] = p_sl
                if 0 < p_tp < p:
                    reward_dist = p - p_tp
                    p_tp = self.normalize_price(exec_bid - reward_dist)
                    features['take_profit'] = p_tp

                logger.info(f"[MT5] Precio límite SHORT ({p}) <= mercado ({min_limit_price:.2f}). Ejecutando a mercado (Bid: {exec_bid} | SL: {p_sl} | TP: {p_tp}).")
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": self.symbol,
                    "volume": vol,
                    "type": mt5.ORDER_TYPE_SELL,
                    "price": exec_bid,
                    "type_filling": self.get_filling_mode(),
                    "type_time": mt5.ORDER_TIME_GTC,
                    "comment": "QuantBot Market Sell"
                }
                if p_sl > 0:
                    request["sl"] = p_sl
                if p_tp > 0:
                    request["tp"] = p_tp

                res = self._send_order_with_filling_fallback(request)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"[MT5] Orden Venta a Mercado ejecutada exitosamente. Ticket: {res.order} | Vol: {vol} @ {exec_bid}")
                    return str(res.order)
                else:
                    err = res.comment if res else mt5.last_error()
                    logger.error(f"[MT5] Error al ejecutar Venta a Mercado: {err} (retcode: {getattr(res, 'retcode', 'N/A')})")
                    return ""
            else:
                request = {
                    "action": mt5.TRADE_ACTION_PENDING,
                    "symbol": self.symbol,
                    "volume": vol,
                    "type": mt5.ORDER_TYPE_SELL_LIMIT,
                    "price": p,
                    "type_filling": self.get_filling_mode(),
                    "type_time": mt5.ORDER_TIME_GTC,
                    "comment": "QuantBot Sell Limit"
                }
                if p_sl > 0:
                    request["sl"] = p_sl
                if p_tp > 0:
                    request["tp"] = p_tp

                res = self._send_order_with_filling_fallback(request)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"[MT5] Orden Sell Limit colocada. Ticket: {res.order} | Vol: {vol} @ {p}")
                    return str(res.order)
                else:
                    err = res.comment if res else mt5.last_error()
                    logger.error(f"[MT5] Error al colocar Sell Limit: {err} (retcode: {getattr(res, 'retcode', 'N/A')})")
                    return ""
        except Exception as e:
            logger.error(f"[MT5] Excepción al crear Sell Limit: {e}")
            return ""

    def place_limit_long(self, amount: float, price: float, features: dict = None) -> str:
        if self.paper_trading:
            return self.simulator.place_limit_long(amount, price, features)
        try:
            vol = self.normalize_volume(amount)
            p = self.normalize_price(price)
            info = self.get_symbol_info()
            tick = mt5.symbol_info_tick(self.symbol)
            stops_level = (info.trade_stops_level * info.point) if (info and getattr(info, 'trade_stops_level', 0)) else 0.0

            features = features if features is not None else {}
            sl_price = features.get('sl_price') or features.get('stop_loss', 0.0)
            tp_price = features.get('take_profit', 0.0)
            p_sl = self.normalize_price(float(sl_price)) if sl_price and float(sl_price) > 0 else 0.0
            p_tp = self.normalize_price(float(tp_price)) if tp_price and float(tp_price) > 0 else 0.0

            # En MT5 una orden Buy Limit por encima o igual al Bid actual devuelve error 10015 (Invalid price).
            # Si el mercado ya cruzó o está en nuestro precio objetivo de compra, ejecutamos a mercado (TRADE_ACTION_DEAL).
            max_limit_price = (tick.bid - stops_level) if tick else p
            if tick and p >= max_limit_price:
                exec_ask = float(tick.ask)
                if 0 < p_sl < p:
                    risk_dist = p - p_sl
                    p_sl = self.normalize_price(exec_ask - risk_dist)
                    features['sl_price'] = p_sl
                    features['stop_loss'] = p_sl
                if p_tp > p > 0:
                    reward_dist = p_tp - p
                    p_tp = self.normalize_price(exec_ask + reward_dist)
                    features['take_profit'] = p_tp

                logger.info(f"[MT5] Precio límite LONG ({p}) >= mercado ({max_limit_price:.2f}). Ejecutando a mercado (Ask: {exec_ask} | SL: {p_sl} | TP: {p_tp}).")
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": self.symbol,
                    "volume": vol,
                    "type": mt5.ORDER_TYPE_BUY,
                    "price": exec_ask,
                    "type_filling": self.get_filling_mode(),
                    "type_time": mt5.ORDER_TIME_GTC,
                    "comment": "QuantBot Market Buy"
                }
                if p_sl > 0:
                    request["sl"] = p_sl
                if p_tp > 0:
                    request["tp"] = p_tp

                res = self._send_order_with_filling_fallback(request)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"[MT5] Orden Compra a Mercado ejecutada exitosamente. Ticket: {res.order} | Vol: {vol} @ {exec_ask}")
                    return str(res.order)
                else:
                    err = res.comment if res else mt5.last_error()
                    logger.error(f"[MT5] Error al ejecutar Compra a Mercado: {err} (retcode: {getattr(res, 'retcode', 'N/A')})")
                    return ""
            else:
                request = {
                    "action": mt5.TRADE_ACTION_PENDING,
                    "symbol": self.symbol,
                    "volume": vol,
                    "type": mt5.ORDER_TYPE_BUY_LIMIT,
                    "price": p,
                    "type_filling": self.get_filling_mode(),
                    "type_time": mt5.ORDER_TIME_GTC,
                    "comment": "QuantBot Buy Limit"
                }
                if p_sl > 0:
                    request["sl"] = p_sl
                if p_tp > 0:
                    request["tp"] = p_tp

                res = self._send_order_with_filling_fallback(request)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"[MT5] Orden Buy Limit colocada. Ticket: {res.order} | Vol: {vol} @ {p}")
                    return str(res.order)
                else:
                    err = res.comment if res else mt5.last_error()
                    logger.error(f"[MT5] Error al colocar Buy Limit: {err} (retcode: {getattr(res, 'retcode', 'N/A')})")
                    return ""
        except Exception as e:
            logger.error(f"[MT5] Excepción al crear Buy Limit: {e}")
            return ""

    def place_stop_market(self, side: str, amount: float, stop_price: float) -> str:
        """
        En MT5, el Stop Loss de una posición abierta se adjunta directamente al ticket de la posición.
        Retorna 'SL_<ticket>' para distinguir el cierre por SL del cierre por TP.
        """
        if self.paper_trading:
            return self.simulator.place_stop_market(side, amount, stop_price)
        try:
            positions = mt5.positions_get(symbol=self.symbol)
            if positions and len(positions) > 0:
                pos = positions[0]
                p_sl = self.normalize_price(stop_price)
                if abs(float(getattr(pos, 'sl', 0.0) or 0.0) - p_sl) < 1e-5:
                    return f"SL_{pos.ticket}"
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "symbol": self.symbol,
                    "sl": p_sl,
                    "tp": pos.tp
                }
                res = mt5.order_send(request)
                no_changes_code = getattr(mt5, 'TRADE_RETCODE_NO_CHANGES', 10025)
                if res and res.retcode in (mt5.TRADE_RETCODE_DONE, no_changes_code):
                    logger.info(f"[MT5] Stop Loss fijado a {p_sl} para la posición {pos.ticket}")
                    return f"SL_{pos.ticket}"
                else:
                    err = res.comment if res else mt5.last_error()
                    logger.error(f"[MT5] Error al actualizar Stop Loss: {err}")
                    return ""
            else:
                logger.warning("[MT5] No se encontró posición abierta para adjuntar Stop Loss.")
                return ""
        except Exception as e:
            logger.error(f"[MT5] Error en place_stop_market: {e}")
            return ""

    def place_take_profit_market(self, side: str, amount: float, tp_price: float) -> str:
        """
        En MT5, el Take Profit de una posición abierta se adjunta directamente al ticket de la posición.
        Retorna 'TP_<ticket>' para distinguir el cierre por TP del cierre por SL.
        """
        if self.paper_trading:
            return self.simulator.place_take_profit_market(side, amount, tp_price)
        try:
            positions = mt5.positions_get(symbol=self.symbol)
            if positions and len(positions) > 0:
                pos = positions[0]
                p_tp = self.normalize_price(tp_price)
                if abs(float(getattr(pos, 'tp', 0.0) or 0.0) - p_tp) < 1e-5:
                    return f"TP_{pos.ticket}"
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "symbol": self.symbol,
                    "sl": pos.sl,
                    "tp": p_tp
                }
                res = mt5.order_send(request)
                no_changes_code = getattr(mt5, 'TRADE_RETCODE_NO_CHANGES', 10025)
                if res and res.retcode in (mt5.TRADE_RETCODE_DONE, no_changes_code):
                    logger.info(f"[MT5] Take Profit fijado a {p_tp} para la posición {pos.ticket}")
                    return f"TP_{pos.ticket}"
                else:
                    err = res.comment if res else mt5.last_error()
                    logger.error(f"[MT5] Error al actualizar Take Profit: {err}")
                    return ""
            else:
                logger.warning("[MT5] No se encontró posición abierta para adjuntar Take Profit.")
                return ""
        except Exception as e:
            logger.error(f"[MT5] Error en place_take_profit_market: {e}")
            return ""

    def place_limit_close(self, side: str, amount: float, price: float) -> str:
        """
        Coloca una orden Limit para cierre parcial en MT5.
        """
        if self.paper_trading:
            return self.simulator.place_limit_close(side, amount, price)
        try:
            vol = self.normalize_volume(amount)
            p = self.normalize_price(price)
            order_type = mt5.ORDER_TYPE_SELL_LIMIT if side == "LONG" else mt5.ORDER_TYPE_BUY_LIMIT
            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": self.symbol,
                "volume": vol,
                "type": order_type,
                "price": p,
                "type_filling": self.get_filling_mode(),
                "type_time": mt5.ORDER_TIME_GTC,
                "comment": "QuantBot Partial TP"
            }
            res = self._send_order_with_filling_fallback(request)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"[MT5] TP Parcial colocado a {p} (Vol: {vol}). Ticket: {res.order}")
                return str(res.order)
            else:
                err = res.comment if res else mt5.last_error()
                logger.error(f"[MT5] Error al colocar TP Parcial Limit: {err}")
                return ""
        except Exception as e:
            logger.error(f"[MT5] Error en place_limit_close: {e}")
            return ""

    def check_order_status(self, order_id: str) -> Optional[Dict]:
        if self.paper_trading:
            return self.simulator.check_order_status(order_id)
        try:
            oid_str = str(order_id)
            # 0. ¿Es un identificador de SL o TP nativo adjunto a una posición ('SL_<ticket>' o 'TP_<ticket>')?
            if oid_str.startswith(("SL_", "TP_")):
                prefix, raw_ticket = oid_str.split("_", 1)
                pos_ticket = int(raw_ticket)

                # Si la posición sigue abierta, el SL/TP sigue activo
                positions = mt5.positions_get(ticket=pos_ticket)
                if positions and len(positions) > 0:
                    return {'id': str(pos_ticket), 'status': 'open'}

                # Si la posición ya se cerró, consultar el deal de salida en el historial de MT5
                deals = mt5.history_deals_get(position=pos_ticket)
                if deals and len(deals) > 0:
                    out_entries = (
                        getattr(mt5, 'DEAL_ENTRY_OUT', 1),
                        getattr(mt5, 'DEAL_ENTRY_INOUT', 2),
                        getattr(mt5, 'DEAL_ENTRY_OUT_BY', 3)
                    )
                    closing_deals = [d for d in deals if getattr(d, 'entry', None) in out_entries]
                    if closing_deals:
                        d_out = closing_deals[-1]
                        exec_price = float(getattr(d_out, 'price', 0.0) or 0.0)
                        comm = abs(float(getattr(d_out, 'commission', 0.0) or 0.0))
                        net_pnl = (
                            float(getattr(d_out, 'profit', 0.0) or 0.0)
                            + float(getattr(d_out, 'commission', 0.0) or 0.0)
                            + float(getattr(d_out, 'swap', 0.0) or 0.0)
                        )
                        comment = str(getattr(d_out, 'comment', '') or '').lower()
                        is_tp = ('tp' in comment) or ('sl' not in comment and net_pnl > 0)

                        if (prefix == "TP" and is_tp) or (prefix == "SL" and not is_tp):
                            return {
                                'id': str(pos_ticket),
                                'status': 'closed',
                                'price': exec_price,
                                'average': exec_price,
                                'fee': {'cost': comm},
                                'pnl': net_pnl
                            }
                        else:
                            return {
                                'id': str(pos_ticket),
                                'status': 'canceled',
                                'price': 0.0,
                                'average': 0.0,
                                'fee': {'cost': 0.0}
                            }
                return None

            ticket = int(oid_str)
            # 1. ¿Está activa entre las órdenes pendientes?
            active_orders = mt5.orders_get(ticket=ticket)
            if active_orders and len(active_orders) > 0:
                ord_info = active_orders[0]
                return {
                    'id': str(ticket),
                    'status': 'open',
                    'price': ord_info.price_open,
                    'average': ord_info.price_open,
                    'fee': {'cost': 0.0}
                }

            # 2. Si ya no está activa, buscar en historial de órdenes ejecutadas/canceladas
            h_orders = mt5.history_orders_get(ticket=ticket)
            if h_orders and len(h_orders) > 0:
                ord_info = h_orders[0]
                if ord_info.state == mt5.ORDER_STATE_FILLED:
                    exec_price = ord_info.price_current or ord_info.price_open
                    return {
                        'id': str(ticket),
                        'status': 'closed',
                        'price': ord_info.price_open,
                        'average': exec_price,
                        'fee': {'cost': 0.0}
                    }
                elif ord_info.state in (mt5.ORDER_STATE_CANCELED, mt5.ORDER_STATE_EXPIRED, mt5.ORDER_STATE_REJECTED):
                    return {
                        'id': str(ticket),
                        'status': 'canceled',
                        'price': ord_info.price_open,
                        'average': 0.0,
                        'fee': {'cost': 0.0}
                    }

            # 3. Si era el ticket de una posición
            positions = mt5.positions_get(ticket=ticket)
            if positions and len(positions) > 0:
                return {'id': str(ticket), 'status': 'open'}

            return None
        except Exception as e:
            logger.error(f"[MT5] Error verificando estado de orden {order_id}: {e}")
            return None

    def execute_market_close(self, side: str, amount: float) -> Optional[Dict]:
        if self.paper_trading:
            return self.simulator.execute_market_close(side, amount)
        try:
            positions = mt5.positions_get(symbol=self.symbol)
            if not positions or len(positions) == 0:
                logger.warning("[MT5] execute_market_close llamado pero no hay posiciones abiertas.")
                return {'status': 'closed'}

            pos = positions[0]
            tick = mt5.symbol_info_tick(self.symbol)
            if not tick:
                logger.error("[MT5] No se pudo obtener tick actual para cierre a mercado.")
                return None

            close_type = mt5.ORDER_TYPE_SELL if side == "LONG" else mt5.ORDER_TYPE_BUY
            price = tick.bid if side == "LONG" else tick.ask
            vol = self.normalize_volume(min(pos.volume, amount))

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": pos.ticket,
                "symbol": self.symbol,
                "volume": vol,
                "type": close_type,
                "price": price,
                "type_filling": self.get_filling_mode(),
                "type_time": mt5.ORDER_TIME_GTC,
                "comment": "QuantBot Market Close"
            }
            res = self._send_order_with_filling_fallback(request)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"[MT5] Posición {pos.ticket} cerrada a mercado exitosamente @ {price}")
                return {
                    'id': str(res.order),
                    'status': 'closed',
                    'price': price,
                    'average': price,
                    'fee': {'cost': 0.0}
                }
            else:
                err = res.comment if res else mt5.last_error()
                logger.error(f"[MT5] Error al cerrar a mercado: {err}")
                return None
        except Exception as e:
            logger.error(f"[MT5] Excepción en execute_market_close: {e}")
            return None

    def get_free_usdt(self) -> float:
        """Retorna el balance real disponible de la cuenta (sin sumar el crédito/bonus para mostrar el saldo real)."""
        if self.paper_trading:
            return self.simulator.get_free_usdt()
        try:
            acc = mt5.account_info()
            if acc:
                return float(acc.balance)
            return 0.0
        except Exception as e:
            logger.error(f"[MT5] Error obteniendo saldo de cuenta: {e}")
            return 0.0

    def get_position_amount(self) -> float:
        """Devuelve el volumen de la posición abierta actual en MT5."""
        if self.paper_trading:
            return self.simulator.get_position_amount()
        try:
            positions = mt5.positions_get(symbol=self.symbol)
            if positions and len(positions) > 0:
                return float(positions[0].volume)
            return 0.0
        except Exception as e:
            logger.error(f"[MT5] Error obteniendo posición abierta: {e}")
            return 0.0

    def process_candle(self, high: float, low: float, ts_str: str):
        if self.paper_trading:
            return self.simulator.process_candle(high, low, ts_str)
        return []
