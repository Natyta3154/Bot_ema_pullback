"""
Módulo: profiler.py
=================================================
Herramienta de perfilado de rendimiento para analizar el tiempo de ejecución de las funciones clave.
"""
import time
import functools
import os
import psutil
from bot.config import settings
from bot.core.trade_logger import logger
import pandas as pd

class Profiler:
    """
    Singleton que recolecta métricas de ejecución (tiempo y memoria).
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Profiler, cls).__new__(cls)
            cls._instance.stats = {}
            cls._instance.process = psutil.Process(os.getpid())
            cls._instance.enabled = getattr(settings, 'ENABLE_PROFILING', False)
        return cls._instance

    def _get_memory_mb(self):
        return self.process.memory_info().rss / (1024 * 1024)

    def record(self, func_name: str, category: str, exec_time: float, mem_delta: float):
        if func_name not in self.stats:
            self.stats[func_name] = {
                "category": category,
                "calls": 0,
                "total_time": 0.0,
                "min_time": float('inf'),
                "max_time": 0.0,
                "total_mem_delta_mb": 0.0
            }
        
        st = self.stats[func_name]
        st["calls"] += 1
        st["total_time"] += exec_time
        st["min_time"] = min(st["min_time"], exec_time)
        st["max_time"] = max(st["max_time"], exec_time)
        st["total_mem_delta_mb"] += mem_delta

    def generate_report(self) -> dict:
        total_pipeline_time = sum(s["total_time"] for s in self.stats.values())
        if total_pipeline_time == 0:
            total_pipeline_time = 1e-9 # Prevent division by zero
            
        report_data = []
        for func, s in self.stats.items():
            avg_time = s["total_time"] / s["calls"] if s["calls"] > 0 else 0
            time_pct = (s["total_time"] / total_pipeline_time) * 100
            
            report_data.append({
                "Function": func,
                "Category": s["category"],
                "Calls": s["calls"],
                "Total Time (s)": round(s["total_time"], 4),
                "Avg Time (ms)": round(avg_time * 1000, 4),
                "Min Time (ms)": round(s["min_time"] * 1000, 4),
                "Max Time (ms)": round(s["max_time"] * 1000, 4),
                "Time %": round(time_pct, 2),
                "Mem Delta (MB)": round(s["total_mem_delta_mb"], 4)
            })
            
        return {
            "total_time_tracked": total_pipeline_time,
            "details": report_data
        }

    def print_top_bottlenecks(self, top_n: int = 10):
        if not self.enabled or not self.stats:
            return
            
        report = self.generate_report()
        df = pd.DataFrame(report["details"])
        
        if df.empty:
            return
            
        df = df.sort_values(by="Time %", ascending=False).head(top_n)
        
        logger.info("\n" + "="*80)
        logger.info("⏱️  PROFILING REPORT: TOP BOTTLENECKS  ⏱️")
        logger.info("="*80)
        print(df[["Function", "Category", "Calls", "Total Time (s)", "Avg Time (ms)", "Time %", "Mem Delta (MB)"]].to_string(index=False))
        logger.info("="*80 + "\n")

    def reset(self):
        self.stats = {}


def profile_method(category: str = "General"):
    """
    Decorador que mide tiempo y consumo de memoria del método.
    Si ENABLE_PROFILING es False, no añade sobrecarga.
    """
    def decorator(func):
        if getattr(settings, 'ENABLE_PROFILING', False):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                profiler = Profiler()
                mem_before = profiler._get_memory_mb()
                t_start = time.perf_counter()
                
                result = func(*args, **kwargs)
                
                t_end = time.perf_counter()
                mem_after = profiler._get_memory_mb()
                
                exec_time = t_end - t_start
                mem_delta = mem_after - mem_before
                
                func_name = f"{func.__module__}.{func.__qualname__}"
                profiler.record(func_name, category, exec_time, mem_delta)
                
                return result
            return wrapper
        else:
            return func
    return decorator
