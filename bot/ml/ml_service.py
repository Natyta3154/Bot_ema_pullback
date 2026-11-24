"""
Módulo: ml_service.py
=================================================
Servicio de Machine Learning. Carga modelos preentrenados y genera predicciones probabilísticas para filtrar señales falsas.
"""
import os
import sys
import pandas as pd
from bot.config import settings

class MLService:
    def __init__(self):
        self.predictor = None
        # Solo cargar si la estrategia activa lo requiere
        if settings.STRATEGY_PARAMS.get(settings.ACTIVE_STRATEGY, {}).get('use_ml', False):
            try:
                orig_path = sys.path.copy()
                # Apuntar a la carpeta original de machine_learning para reusar los PKLs sin romper paths
                ml_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'machine_learning')
                if ml_dir not in sys.path:
                    sys.path.append(ml_dir)
                from predictor import MLPredictor
                self.predictor = MLPredictor()
                sys.path = orig_path
            except Exception as e:
                print(f"Error cargando MLPredictor: {e}")

    def predict(self, df_1h: pd.DataFrame, df_4h: pd.DataFrame, side: str):
        if not self.predictor:
            return False, 0.0
        return self.predictor.predict(df_1h, df_4h, side)
