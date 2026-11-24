"""
Módulo: engine.py
=================================================
Motor de Backtesting. Simula la ejecución de estrategias sobre datos históricos de forma aislada.
"""
import time
from bot.config import settings
from bot.core.order import OrderManager
from bot.core.position import PositionManager
from bot.core.risk import RiskManager
from bot.core.market_data import MarketDataManager
from bot.core.execution import ExecutionManager
from bot.core.order_planner import OrderPlanner
from bot.strategies.factory import StrategyFactory
from bot.core.trade_logger import logger, log_trade, log_live_signal, Colors
from bot.core.profiler import profile_method
from bot.core.diagnostics import DiagnosticsReporter

class TradingEngine:
    def __init__(self):
        if getattr(settings, 'BROKER', 'BINANCE') == "ICMARKETS":
            from bot.connectors.mt5_order import MT5OrderManager
            from bot.connectors.mt5_market_data import MT5MarketDataManager
            self.order_manager = MT5OrderManager()
            self.market_data = MT5MarketDataManager(self.order_manager)
        else:
            self.order_manager = OrderManager()
            self.market_data = MarketDataManager(self.order_manager)
        self.position_manager = PositionManager()
        self.risk_manager = RiskManager()
        # Market data initialized above per broker
        self.execution = ExecutionManager(self.order_manager, self.position_manager)
        self.order_planner = OrderPlanner(self.risk_manager)
        
        self.strategy = StrategyFactory.create_strategy(
            settings.ACTIVE_STRATEGY, 
            self.position_manager, 
            self.risk_manager
        )
        
        self.shadow_ai = None
        if getattr(settings, 'AI_SHADOW_LEARNING_ENABLED', True) and getattr(settings, 'ENVIRONMENT', '') != 'BACKTEST':
            try:
                from bot.ml.shadow_learner import ShadowAILearner
                self.shadow_ai = ShadowAILearner()
                self.strategy.shadow_ai = self.shadow_ai
            except Exception as e:
                logger.warning(f"[IA SHADOW] No se pudo inicializar ShadowAILearner: {e}")
        
        self.diagnostics = DiagnosticsReporter(self)
        
    def cancel_protective_orders(self):
        if self.position_manager.sl_order_id:
            self.order_manager.cancel_order(self.position_manager.sl_order_id)
            self.position_manager.sl_order_id = ""
        if self.position_manager.tp_order_id:
            self.order_manager.cancel_order(self.position_manager.tp_order_id)
            self.position_manager.tp_order_id = ""
        for tp in self.position_manager.tp_targets:
            if tp.get('order_id') and not tp.get('hit'):
                self.order_manager.cancel_order(tp['order_id'])
                tp['order_id'] = ""

    def run(self):
        logger.info("==========================================================")
        logger.info(f"   INICIANDO MOTOR DE TRADING | ESTRATEGIA: {settings.ACTIVE_STRATEGY}   ")
        logger.info(f"   ENTORNO: {settings.ENVIRONMENT} ")
        logger.info("==========================================================")
        
        while True:
            self.run_iteration()
            if settings.ENVIRONMENT != "BACKTEST":
                # Sincronización del reloj: Esperar exactamente al cierre de la siguiente vela de 15m
                import time
                from datetime import datetime, timedelta
                
                now = datetime.utcnow()
                # Calcular el próximo minuto que sea múltiplo de 15 (0, 15, 30, 45)
                next_minute = ((now.minute // 5) + 1) * 5
                
                if next_minute == 60:
                    next_run = now.replace(hour=(now.hour + 1) % 24, minute=0, second=5, microsecond=0)
                    if now.hour == 23:
                        next_run += timedelta(days=1)
                else:
                    next_run = now.replace(minute=next_minute, second=5, microsecond=0)
                
                # Dormir los segundos exactos que faltan para ese momento
                sleep_seconds = (next_run - now).total_seconds()
                logger.info(f"⏳ Ciclo finalizado. Durmiendo {sleep_seconds:.0f}s hasta el próximo cierre de vela ({next_run.strftime('%H:%M:%S')} UTC).")
                time.sleep(sleep_seconds)

    @profile_method(category="Trading Engine")
    def run_iteration(self):
        try:
            # 1. Cargar Market Data
            tfs = []
            if hasattr(self.strategy, 'params'):
                tfs = self.strategy.get_required_timeframes() if hasattr(self.strategy, 'get_required_timeframes') else [
                    self.strategy.params.get('pullback_tf'),
                    self.strategy.params.get('trend_confirm_tf'),
                    self.strategy.params.get('trigger_tf'),
                    self.strategy.params.get('entry_tf'),
                    self.strategy.params.get('macro_tf')
                ]
            tfs = list(set([tf for tf in tfs if tf]))
            
            dfs = {}
            for tf in tfs:
                df = self.market_data.fetch_ohlcv(tf)
                if df is not None and len(df) >= 60:
                    dfs[tf] = df
            
            if len(dfs) < len(tfs):
                if settings.ENVIRONMENT != "BACKTEST":
                    logger.warning("Faltan datos históricos. Reintentando...")
                    time.sleep(30)
                return

            # 2. Análisis del mercado (Indicadores delegados a la estrategia)
            # Idempotencia: evitar reprocesar la misma vela cerrada en Live/Paper
            _chk_tf = getattr(self.strategy, 'params', {}).get('trigger_tf') or getattr(self.strategy, 'params', {}).get('entry_tf') or tfs[0]
            _curr_ts = str(dfs[_chk_tf]['timestamp'].iloc[-1]) if _chk_tf in dfs else ""
            if settings.ENVIRONMENT != "BACKTEST":
                if getattr(self, 'last_processed_candle_time', None) == _curr_ts:
                    return
                self.last_processed_candle_time = _curr_ts

            self.strategy.analyze_market(dfs)
            
            # trigger_tf o entry_tf será el TF menor para el snapshot
            trigger_tf = None
            if hasattr(self.strategy, 'params'):
                trigger_tf = self.strategy.params.get('trigger_tf') or self.strategy.params.get('entry_tf') or tfs[0]
            
            current_price = dfs[trigger_tf]['close'].iloc[-1] if trigger_tf in dfs else 0
            current_high = dfs[trigger_tf]['high'].iloc[-1] if trigger_tf in dfs else current_price
            current_low = dfs[trigger_tf]['low'].iloc[-1] if trigger_tf in dfs else current_price
            current_candle_time = str(dfs[trigger_tf]['timestamp'].iloc[-1]) if trigger_tf in dfs else ""

            # En paper, los fills ocurren antes de consultar el estado de las
            # órdenes. Backtest hace este paso desde su reloj histórico.
            if settings.ENVIRONMENT == "PAPER" and current_price > 0:
                self.order_manager.process_candle(current_high, current_low, current_candle_time)
            
            # --- AUDITORÍA RETROSPECTIVA Y SEGUIMIENTO IA EN SOMBRA ---
            if current_price > 0 and hasattr(self.diagnostics, 'auditor'):
                self.diagnostics.auditor.update_retrospective(current_price, current_high, current_low)
            if current_price > 0 and getattr(self, 'shadow_ai', None) is not None:
                self.shadow_ai.on_price_update(current_high, current_low, current_price)
            
            saldo = self.order_manager.get_free_usdt() if not self.position_manager.is_open else "N/A"
            
            # --- LOG: RESUMEN DE MERCADO ---
            if trigger_tf and getattr(settings, 'ENABLE_DETAILED_LOGS', False):
                last_row = dfs[trigger_tf].iloc[-1]
                vol_val = last_row.get('volume', 0)
                vol_sma = last_row.get('vol_sma', vol_val)
                vol_ratio = (vol_val / vol_sma) if vol_sma > 0 else 0
                atr_str = f" | ATR: {last_row['atr']:.2f}" if 'atr' in last_row else ""
                wallet_str = f" | Billetera: {saldo:.2f} USDT" if isinstance(saldo, float) else ""
                
                logger.info(f"{Colors.CYAN}[MARKET]{Colors.RESET} RESUMEN DE MERCADO | {settings.SYMBOL} | Precio: {current_price:.2f}{atr_str} | Volumen: {vol_ratio:.1f}x prom{wallet_str}")

            # --- LOG: ESTADO DE POSICIÓN ---
            if self.position_manager.is_open and getattr(settings, 'ENABLE_DETAILED_LOGS', False):
                pnl_pct = 0.0
                pnl_usdt = 0.0
                if self.position_manager.entry_price > 0:
                    if self.position_manager.side == "LONG":
                        pnl_pct = ((current_price - self.position_manager.entry_price) / self.position_manager.entry_price) * 100
                        pnl_usdt = (current_price - self.position_manager.entry_price) * self.position_manager.amount
                    else:
                        pnl_pct = ((self.position_manager.entry_price - current_price) / self.position_manager.entry_price) * 100
                        pnl_usdt = (self.position_manager.entry_price - current_price) * self.position_manager.amount
                
                estado_visual = f"{Colors.GREEN}🟢 GANANDO{Colors.RESET}" if pnl_usdt > 0 else (f"{Colors.RED}🔴 PERDIENDO{Colors.RESET}" if pnl_usdt < 0 else "⚪ EMPATE")
                
                tp_str = f"TP1: {self.position_manager.tp_targets[0]['price']}" if self.position_manager.tp_targets else f"TP: {self.position_manager.take_profit}"
                logger.info(f"{Colors.MAGENTA}[POSITION]{Colors.RESET} {self.position_manager.side} {settings.SYMBOL} | Entrada: {self.position_manager.entry_price:.2f} | SL: {self.position_manager.stop_loss:.2f} | {tp_str} | PnL No Realizado: {pnl_usdt:+.2f} USDT ({pnl_pct:+.2f}%) {estado_visual}")

            # 3. Detección de Desincronización y TPs parciales
            if self.position_manager.is_open:
                
                # Chequear TPs Parciales
                for tp in self.position_manager.tp_targets:
                    if not tp.get('hit') and tp.get('order_id'):
                        order_stat = self.order_manager.check_order_status(tp['order_id'])
                        if order_stat and order_stat['status'] == 'closed':
                            logger.info(f"{Colors.GREEN}[ORDERS]{Colors.RESET} 🎯 TAKE PROFIT ALCANZADO: {tp['amount']} a {tp['price']}")
                            tp['hit'] = True
                            applied_amount = self.position_manager.apply_partial_exit(tp['amount'])
                            self.position_manager.save()
                            log_trade({
                                "action": "PARTIAL_TP",
                                "side": self.position_manager.side,
                                "exit_price": tp['price'],
                                "amount": applied_amount,
                                "timestamp": current_candle_time
                            })
                            # Si queda posición, recrear SL con el amount actualizado
                            if self.position_manager.sl_order_id:
                                self.order_manager.cancel_order(self.position_manager.sl_order_id)
                            if self.position_manager.has_remaining_amount():
                                self.position_manager.sl_order_id = self.order_manager.place_stop_market(
                                    self.position_manager.side, self.position_manager.amount, self.position_manager.stop_loss)
                                self.position_manager.save()
                            else:
                                logger.info(f"{Colors.MAGENTA}[POSITION]{Colors.RESET} Todos los TPs alcanzados. Cerrando posición.")
                                self.cancel_protective_orders()
                                self.position_manager.reset_position()
                                return

                pos_amt = self.order_manager.get_position_amount()
                if pos_amt == 0.0 and self.position_manager.is_open:
                    if getattr(settings, 'ENVIRONMENT', '') != 'BACKTEST':
                        logger.warning(f"{Colors.YELLOW}[SYNC]{Colors.RESET} DESINCRONIZACIÓN DETECTADA: Binance indica posición cerrada, pero el bot cree estar dentro.")
                    
                    # Chequear cuál orden se ejecutó antes de cancelar
                    closed_sl_order = None
                    closed_tp_order = None
                    
                    if self.position_manager.sl_order_id:
                        closed_sl_order = self.order_manager.check_order_status(self.position_manager.sl_order_id)
                    if self.position_manager.tp_order_id:
                        closed_tp_order = self.order_manager.check_order_status(self.position_manager.tp_order_id)
                        
                    sl_order_id = self.position_manager.sl_order_id
                    tp_order_id = self.position_manager.tp_order_id
                    self.cancel_protective_orders()
                    
                    real_exit = current_price
                    commission = 0.0
                    broker_pnl = None
                    order_id = "N/A"
                    reason = "EXTERNAL_CLOSE"
                    
                    if closed_tp_order and closed_tp_order.get('status') == 'closed':
                        real_exit = closed_tp_order.get('average') or closed_tp_order.get('price') or current_price
                        commission = (closed_tp_order.get('fee') or {}).get('cost', 0.0)
                        broker_pnl = closed_tp_order.get('pnl')
                        order_id = str(closed_tp_order.get('id') or tp_order_id).replace('TP_', '')
                        reason = "NATIVE_TP_HIT"
                        logger.info(f"{Colors.GREEN}[SYNC]{Colors.RESET} 🎯 TAKE PROFIT alcanzado en Broker (Precio: {real_exit:.2f})")
                    elif closed_sl_order and closed_sl_order.get('status') == 'closed':
                        real_exit = closed_sl_order.get('average') or closed_sl_order.get('price') or current_price
                        commission = (closed_sl_order.get('fee') or {}).get('cost', 0.0)
                        broker_pnl = closed_sl_order.get('pnl')
                        order_id = str(closed_sl_order.get('id') or sl_order_id).replace('SL_', '')
                        reason = "NATIVE_SL_HIT"
                        logger.info(f"{Colors.RED}[SYNC]{Colors.RESET} 💥 STOP LOSS alcanzado en Broker (Precio: {real_exit:.2f})")
                    else:
                        logger.info(f"{Colors.YELLOW}[SYNC]{Colors.RESET} Posición cerrada manualmente o por otro motivo externo.")

                    if broker_pnl is not None:
                        pnl_usdt = round(float(broker_pnl), 2)
                    else:
                        raw_diff = (
                            (real_exit - self.position_manager.entry_price)
                            if self.position_manager.side == "LONG"
                            else (self.position_manager.entry_price - real_exit)
                        )
                        pnl_usdt = round((raw_diff * self.position_manager.amount) - commission, 2)

                    if hasattr(self.strategy, 'register_trade_outcome'):
                        is_win_outcome = (reason == "NATIVE_TP_HIT") or (
                            reason != "NATIVE_SL_HIT" and pnl_usdt > 0
                        )
                        self.strategy.register_trade_outcome(
                            side=self.position_manager.side,
                            is_win=is_win_outcome,
                            entry_price=self.position_manager.entry_price,
                            exit_price=real_exit,
                            timestamp_str=current_candle_time
                        )

                    if getattr(self, 'shadow_ai', None) is not None:
                        self.shadow_ai.on_trade_exit(
                            order_id=order_id,
                            side=self.position_manager.side,
                            entry_price=self.position_manager.entry_price,
                            exit_price=real_exit,
                            pnl_usdt=pnl_usdt,
                            reason=reason,
                            timestamp_str=current_candle_time
                        )

                    log_trade({
                        "action": "EXIT",
                        "side": self.position_manager.side,
                        "reason": reason,
                        "entry_price": self.position_manager.entry_price,
                        "exit_price": real_exit,
                        "amount": self.position_manager.amount,
                        "commission": commission,
                        "pnl_usdt": pnl_usdt,
                        "pnl": pnl_usdt,
                        "order_id": order_id,
                        "timestamp": current_candle_time
                    })
                    self.position_manager.reset_position()
                    return

            # 4. Árbol de decisiones principal
            if self.position_manager.is_open:
                action_res = self.strategy.manage_open_position(current_price, dfs)
                
                if action_res.get('action') == 'EXIT':
                    logger.info(f"{Colors.MAGENTA}[STRATEGY]{Colors.RESET} 🚨 SALIDA ORDENADA POR ESTRATEGIA: {action_res.get('reason')}")
                    exit_order = self.order_manager.execute_market_close(self.position_manager.side, self.position_manager.amount)
                    if exit_order:
                        real_exit_price = exit_order.get('average') or exit_order.get('price') or current_price
                        commission = (exit_order.get('fee') or {}).get('cost', 0.0)
                        raw_diff = (
                            (real_exit_price - self.position_manager.entry_price)
                            if self.position_manager.side == "LONG"
                            else (self.position_manager.entry_price - real_exit_price)
                        )
                        pnl_usdt = round((raw_diff * self.position_manager.amount) - commission, 2)

                        if getattr(self, 'shadow_ai', None) is not None:
                            self.shadow_ai.on_trade_exit(
                                order_id=exit_order.get('id', 'N/A'),
                                side=self.position_manager.side,
                                entry_price=self.position_manager.entry_price,
                                exit_price=real_exit_price,
                                pnl_usdt=pnl_usdt,
                                reason=action_res.get('reason', 'STRATEGY_EXIT'),
                                timestamp_str=current_candle_time
                            )
                        
                        log_trade({
                            "action": "EXIT",
                            "side": self.position_manager.side,
                            "reason": action_res.get('reason'),
                            "entry_price": self.position_manager.entry_price,
                            "exit_price": real_exit_price,
                            "amount": self.position_manager.amount,
                            "commission": commission,
                            "pnl_usdt": pnl_usdt,
                            "pnl": pnl_usdt,
                            "order_id": exit_order.get('id', 'N/A'),
                            "timestamp": current_candle_time
                        })
                        self.cancel_protective_orders()
                        self.position_manager.reset_position()
                        
                elif action_res.get('action') == 'UPDATE_SL':
                    new_sl = action_res.get('new_sl')
                    self.position_manager.stop_loss = new_sl
                    self.position_manager.breakeven_activated = True
                    if self.position_manager.sl_order_id:
                        self.order_manager.cancel_order(self.position_manager.sl_order_id)
                    self.position_manager.sl_order_id = self.order_manager.place_stop_market(
                        self.position_manager.side, self.position_manager.amount, new_sl)
                    self.position_manager.save()
                    logger.info(f"{Colors.BLUE}[RISK]{Colors.RESET} 🛡️ SL Actualizado a {new_sl} ({action_res.get('reason')})")
                    
            elif self.position_manager.pending_order_id:
                self.execution.handle_pending_order(current_candle_time)
                
            else:
                if self.risk_manager.check_daily_limits():
                    logger.info(f"{Colors.RED}[RISK]{Colors.RESET} Operativa pausada por límites diarios.")
                    time.sleep(300)
                    return
                    
                # Ya obtuvimos saldo arriba (si is_open era falso)
                # Para evitar doble llamada API en la misma iteración
                if not isinstance(saldo, float):
                    saldo = self.order_manager.get_free_usdt()
                    
                signal = self.strategy.generate_signal(current_price, saldo, dfs)
                
                # Guardar siempre en CSV para auditoría (Paper/Live vs Backtest)
                log_live_signal(
                    timestamp=current_candle_time,
                    action=signal.get('action', 'WAIT'),
                    price=signal.get('price', current_price),
                    reason=signal.get('reason', 'N/A'),
                    features=signal.get('features', {})
                )
                
                # Tablero visual multi-temporal informativo en consola
                if hasattr(self.strategy, 'print_multitf_dashboard') and getattr(settings, 'ENABLE_DETAILED_LOGS', True):
                    self.strategy.print_multitf_dashboard(current_price, saldo, dfs, signal)
                
                if signal.get('action') in ['LONG', 'SHORT']:
                    plan = self.order_planner.build_entry_plan(signal, saldo)
                    
                    if plan:
                        target_entry = plan.price
                        order_id = self.order_planner.place_entry(self.order_manager, plan)
                            
                        if order_id:
                            self.position_manager.pending_order_id = order_id
                            self.position_manager.side = plan.side
                            self.position_manager.pending_order_price = plan.price
                            self.position_manager.amount = plan.amount
                            self.position_manager.stop_loss = plan.stop_loss
                            
                            # Soporte retrocompatible (un TP o Múltiples TPs)
                            self.position_manager.tp_targets = plan.tp_targets
                            self.position_manager.take_profit = plan.take_profit
                                
                            self.position_manager.last_candle_1h_time = current_candle_time
                            self.position_manager.save()
                            self.execution.handle_pending_order(current_candle_time)

                            # Registrar radiografía de la entrada en la IA en Sombra (sin bloquear ni alterar la orden)
                            if getattr(self, 'shadow_ai', None) is not None:
                                prior_sl = getattr(self.strategy, 'consecutive_sl', {}).get(plan.side, 0)
                                actual_entry = self.position_manager.entry_price if self.position_manager.entry_price > 0 else plan.price
                                self.shadow_ai.on_trade_entry(
                                    order_id=order_id,
                                    side=plan.side,
                                    entry_price=actual_entry,
                                    sl_price=self.position_manager.stop_loss,
                                    tp_price=self.position_manager.take_profit,
                                    amount=self.position_manager.amount,
                                    dfs=dfs,
                                    signal_features=signal.get('features', {}),
                                    consecutive_sl_prior=prior_sl
                                )

                            logger.info(f"{Colors.GREEN}[ORDERS]{Colors.RESET} 🚀 Orden encolada: {signal['action']} a {target_entry:.2f}")

        except Exception as e:
            logger.error(f"⚠️ Error crítico en iteración del motor: {e}")
            import traceback
            traceback.print_exc()
            if settings.ENVIRONMENT != "BACKTEST":
                time.sleep(30)
