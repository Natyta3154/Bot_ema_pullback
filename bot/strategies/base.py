"""
Módulo: base.py
=================================================
Clase base para todas las estrategias de trading. Define la interfaz común que deben implementar.
"""
from abc import ABC, abstractmethod
import pandas as pd
from typing import Dict, Any

class BaseStrategy(ABC):
    def __init__(self, position_manager, risk_manager):
        self.position = position_manager
        self.risk = risk_manager

    @abstractmethod
    def analyze_market(self, dfs: Dict[str, pd.DataFrame]) -> None:
        """
        Calcula indicadores (EMA, RSI, etc) sobre los DataFrames inyectados.
        """
        pass
        
    @abstractmethod
    def generate_signal(self, current_price: float, saldo: float, dfs: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """
        Decide si entrar al mercado.
        Retorna: {'action': 'LONG'|'SHORT'|'NONE', 'price': float, 'sl': float, 'tp': float}
        """
        pass
        
    @abstractmethod
    def manage_open_position(self, current_price: float, dfs: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """
        Gestiona la posición abierta (Trailing Stop, Breakeven, Time Stop).
        Retorna si debe forzarse salida a mercado: {'action': 'EXIT'|'NONE', 'reason': str}
        """
        pass
