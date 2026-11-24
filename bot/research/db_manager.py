import os
import json
import uuid
from datetime import datetime
from bot.core.trade_logger import logger

class DatabaseManager:
    """
    Gestiona el almacenamiento y versionado estructurado del Research Lab.
    Mantiene la jerarquía: Experimento -> Runs.
    """
    def __init__(self, base_dir: str = None):
        if not base_dir:
            base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'research', 'db')
            
        self.base_dir = base_dir
        
        # Estructura de carpetas
        self.categories = ['experiments', 'optimizations', 'monte_carlo', 'walk_forward', 'portfolio', 'stress']
        for cat in self.categories:
            os.makedirs(os.path.join(self.base_dir, cat), exist_ok=True)
            
        # Catálogo global de experimentos
        self.catalog_file = os.path.join(self.base_dir, 'catalog.json')
        if not os.path.exists(self.catalog_file):
            self._save_catalog({})
            
    def _load_catalog(self) -> dict:
        try:
            with open(self.catalog_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
            
    def _save_catalog(self, catalog: dict):
        with open(self.catalog_file, 'w', encoding='utf-8') as f:
            json.dump(catalog, f, indent=4)
            
    def generate_id(self, prefix: str = "EXP") -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_uuid = str(uuid.uuid4())[:8]
        return f"{prefix}_{timestamp}_{short_uuid}"
        
    def save_experiment(self, experiment_id: str, metadata: dict, tags: list = None) -> str:
        """
        Registra el experimento padre.
        """
        catalog = self._load_catalog()
        
        if not tags:
            tags = []
            
        catalog[experiment_id] = {
            "created_at": datetime.now().isoformat(),
            "metadata": metadata,
            "tags": tags,
            "runs": []
        }
        self._save_catalog(catalog)
        
        # Crear directorio específico para este experimento
        exp_dir = os.path.join(self.base_dir, 'experiments', experiment_id)
        os.makedirs(exp_dir, exist_ok=True)
        
        return experiment_id
        
    def save_run(self, experiment_id: str, run_id: str, run_data: dict, run_type: str = 'single'):
        """
        Guarda una ejecución específica asociada al experimento.
        run_type puede ser: 'single', 'grid', 'walk_forward', etc.
        """
        catalog = self._load_catalog()
        if experiment_id not in catalog:
            logger.error(f"El experimento {experiment_id} no existe en el catálogo.")
            return False
            
        exp_dir = os.path.join(self.base_dir, 'experiments', experiment_id)
        
        # Guardar el JSON del run
        run_file = os.path.join(exp_dir, f"{run_id}.json")
        
        payload = {
            "run_id": run_id,
            "experiment_id": experiment_id,
            "run_type": run_type,
            "timestamp": datetime.now().isoformat(),
            "data": run_data
        }
        
        with open(run_file, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=4)
            
        # Actualizar catálogo con referencia ligera
        run_summary = {
            "run_id": run_id,
            "type": run_type,
            "timestamp": payload['timestamp'],
            "summary_metrics": run_data.get('metrics', {}) # Guardar solo métricas para búsqueda rápida
        }
        catalog[experiment_id]['runs'].append(run_summary)
        self._save_catalog(catalog)
        return True
        
    def query_experiments(self, tag: str = None, strategy: str = None) -> list:
        catalog = self._load_catalog()
        results = []
        for exp_id, data in catalog.items():
            match = True
            if tag and tag not in data.get('tags', []):
                match = False
            if strategy and data.get('metadata', {}).get('strategy') != strategy:
                match = False
            if match:
                results.append({"id": exp_id, **data})
        return results
