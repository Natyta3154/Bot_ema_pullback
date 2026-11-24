import pandas as pd
import numpy as np

class DashboardDataGenerator:
    """
    Estructura la información raw de los trades en formatos tabulares o 
    agrupados listos para ser consumidos por librerías de visualización
    (Dash, Streamlit, React, etc.).
    """
    def __init__(self, history: list, initial_balance: float):
        self.history = history
        self.initial_balance = initial_balance
        self.df = pd.DataFrame(self.history)
        if not self.df.empty:
            self.df['timestamp'] = pd.to_datetime(self.df['timestamp'])
            
    def generate_all_data(self) -> dict:
        if self.df.empty:
            return {}
            
        closes = self.df[self.df['reduceOnly'] == True].copy()
        if closes.empty:
            return {}
            
        closes['net_profit'] = closes['pnl'] - closes['fee']
        
        return {
            "equity_curve": self._generate_equity_curve(closes),
            "drawdown_curve": self._generate_drawdown_curve(closes),
            "returns_distribution": self._generate_returns_distribution(closes),
            "heatmap_day_of_week": self._generate_heatmap(closes, 'day_of_week'),
            "heatmap_hour": self._generate_heatmap(closes, 'hour')
        }
        
    def _generate_equity_curve(self, closes: pd.DataFrame) -> list:
        # Formato: [{"t": "2024-01-01", "balance": 1050}, ...]
        curve = closes[['timestamp', 'balance']].copy()
        curve['timestamp'] = curve['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
        return curve.to_dict('records')
        
    def _generate_drawdown_curve(self, closes: pd.DataFrame) -> list:
        curve = closes[['timestamp', 'balance']].copy()
        curve['peak'] = curve['balance'].cummax()
        curve['drawdown'] = (curve['balance'] - curve['peak']) / curve['peak']
        curve['timestamp'] = curve['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
        return curve[['timestamp', 'drawdown']].to_dict('records')
        
    def _generate_returns_distribution(self, closes: pd.DataFrame) -> list:
        # Devuelve la distribución de PNL neto
        # Podría ser agrupada en bins o simplemente los valores raw
        return closes['net_profit'].tolist()
        
    def _generate_heatmap(self, closes: pd.DataFrame, time_unit: str) -> dict:
        """
        Agrupa el Profit Factor o PnL Total según el día de la semana o la hora del día
        """
        df_hm = closes.copy()
        if time_unit == 'day_of_week':
            df_hm['unit'] = df_hm['timestamp'].dt.day_name()
        elif time_unit == 'hour':
            df_hm['unit'] = df_hm['timestamp'].dt.hour
            
        grouped = df_hm.groupby('unit')['net_profit'].sum().to_dict()
        return grouped
