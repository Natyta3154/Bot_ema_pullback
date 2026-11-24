"""
Módulo: risk.py
=================================================
Gestor de riesgo. Implementa los controles de límites de pérdidas diarias, drawdown y tamaño de posición estricto.
"""
import os
import json
from datetime import datetime
from bot.config import settings
from bot.core.trade_logger import logger
import pandas as pd

class RiskManager:
    def calculate_position_size(self, current_price: float, sl_price: float, available_balance: float, side: str) -> float:
        if side == "SHORT":
            if sl_price <= current_price:
                logger.error("Stop Loss inválido para SHORT: Debe ser mayor al precio de entrada.")
                return 0.0
            risk_pct = (sl_price - current_price) / current_price
        elif side == "LONG":
            if sl_price >= current_price:
                logger.error("Stop Loss inválido para LONG: Debe ser menor al precio de entrada.")
                return 0.0
            risk_pct = (current_price - sl_price) / current_price
        else:
            return 0.0

        if risk_pct == 0:
            return 0.0
            
        # El riesgo MÁXIMO ABSOLUTO PERMITIDO es settings.RISK_PER_TRADE_USDT
        risk_usdt_target = settings.RISK_PER_TRADE_USDT
        
        # El tamaño de posición (amount en USDT nominal sin apalancamiento) = risk_usdt / risk_pct
        nominal_position_usdt = risk_usdt_target / risk_pct
        
        # Validación de margen disponible
        real_margin = nominal_position_usdt / settings.LEVERAGE
        max_allowed_margin = available_balance * 0.90
        
        if real_margin > max_allowed_margin:
            logger.warning(f"⚠️ El margen requerido excede el límite del 90% del balance. Recortando posición para mantener seguridad.")
            real_margin = max_allowed_margin
            nominal_position_usdt = real_margin * settings.LEVERAGE
            
        amount_btc = nominal_position_usdt / current_price
        
        # --- VALIDACIÓN ESTRICTA FINAL ---
        projected_loss = (amount_btc * current_price) * risk_pct
        if projected_loss > (risk_usdt_target + 0.1): # Margen de error de redondeo 10 centavos
            logger.error(f"🚨 CRÍTICO: El trade proyecta una pérdida de {projected_loss:.2f} USDT, excediendo el límite fijo de {risk_usdt_target}. BLOQUEANDO TRADE.")
            return 0.0
        
        if nominal_position_usdt < 10.0:
            logger.warning("Trade abortado: La posición nominal es muy pequeña (< 10 USDT) y será rechazada por Binance.")
            return 0.0
            
        if getattr(settings, 'ENABLE_DETAILED_LOGS', False):
            logger.info(f"🛡️ CHECK DE RIESGO | Riesgo: {risk_usdt_target} USDT | Dist SL: {risk_pct*100:.2f}% | Tamaño: {amount_btc} {settings.SYMBOL.replace('USDT','')} | Apalancamiento: {settings.LEVERAGE}x")
            
        return round(amount_btc, 4)

    def check_daily_limits(self) -> bool:
        try:
            if getattr(settings, 'ENVIRONMENT', '') == 'BACKTEST':
                return False
            if not os.path.exists(settings.TRADING_LOG_FILE):
                return False
                
            with open(settings.TRADING_LOG_FILE, 'r') as f:
                logs = json.load(f)
                
            hoy_str = datetime.now().date().isoformat()
            trades_hoy = [t for t in logs if t.get('action') == 'EXIT' and t.get('timestamp', '').startswith(hoy_str)]
            
            if len(trades_hoy) >= settings.MAX_DAILY_TRADES:
                logger.info(f"🚫 [KILL SWITCH] Máximo de operaciones diarias ({settings.MAX_DAILY_TRADES}) alcanzado.")
                return True
                
            pnl_hoy = sum([float(t.get('pnl_usdt', t.get('pnl', 0.0))) for t in trades_hoy])
            if pnl_hoy <= -settings.MAX_DAILY_LOSS_USDT:
                logger.info(f"🚫 [KILL SWITCH] Pérdida diaria máxima superada. (Actual: {pnl_hoy:.2f} USDT)")
                return True
                
            pnl_total = sum([float(t.get('pnl_usdt', t.get('pnl', 0.0))) for t in logs if t.get('action') == 'EXIT'])
            if pnl_total <= -settings.MAX_TOTAL_LOSS_USDT:
                logger.error(f"🚨 [KILL SWITCH CRÍTICO] PÉRDIDA TOTAL DEL BOT SUPERADA. (Actual: {pnl_total:.2f} USDT)")
                return True
                
            salidas = [t for t in logs if t.get('action') == 'EXIT']
            if len(salidas) >= settings.MAX_CONSECUTIVE_LOSSES:
                ultimas = salidas[-settings.MAX_CONSECUTIVE_LOSSES:]
                if all((float(t.get('pnl_usdt', t.get('pnl', 0.0))) < 0) for t in ultimas):
                    logger.info(f"🚫 [LÍMITE] Racha de pérdidas consecutivas alcanzada.")
                    return True
                    
            return False
        except Exception as e:
            logger.error(f"Error comprobando límites de riesgo: {e}")
            return False
            
    def get_recent_high(self, df: pd.DataFrame, lookback: int = 10) -> float:
        return df['high'].iloc[-lookback:].max() * 1.001
        
    def get_recent_low(self, df: pd.DataFrame, lookback: int = 10) -> float:
        return df['low'].iloc[-lookback:].min() * 0.999
