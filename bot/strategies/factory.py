"""
Módulo: factory.py
=================================================
Fábrica de estrategias (Factory Pattern). Instancia la estrategia correcta según la configuración.
"""
from bot.strategies.ema_strategy import EMAStrategy
from bot.strategies.breakout_strategy import BreakoutStrategy
from bot.strategies.ema_pullback_trend_strategy import EMAPullbackTrendStrategy

class StrategyFactory:
    @staticmethod
    def create_strategy(strategy_name: str, position_manager, risk_manager):
        if strategy_name == "EMA_STRATEGY":
            return EMAStrategy(position_manager, risk_manager)
        elif strategy_name == "BREAKOUT_RETEST":
            return BreakoutStrategy(position_manager, risk_manager)
        elif strategy_name == "EMA_PULLBACK_TREND":
            return EMAPullbackTrendStrategy(position_manager, risk_manager)
        else:
            raise ValueError(f"Estrategia desconocida: {strategy_name}")
