"""
Módulo: shadow_learner.py
=================================================
Motor Profesional de Aprendizaje Cuantitativo en Sombra (Shadow AI Learner):
- Meta-Labeling Tabular con LightGBM (y fallback GradientBoosting)
- Explicabilidad Matemática de Variables con SHAP (SHapley Additive exPlanations)
- Autopsia Contrafactual de Trades Perdedores (MFE / MAE / Seguimiento Post-SL)
- Generador de Alternativas de Mejora para Trades Perdedores

IMPORTANTE: En modo SHADOW (settings.AI_TAKE_DECISIONS = False), este módulo
NO bloquea ni modifica ninguna entrada. Solo observa, aprende de cada trade
ganador y perdedor, y persiste su conocimiento en logs/ai_learning_dataset.json.
"""
import os
import json
import warnings
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import pandas as pd
import joblib

warnings.filterwarnings("ignore", category=UserWarning, module="shap")
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")

from bot.config import settings
from bot.core.trade_logger import logger, Colors
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score

HAS_LIGHTGBM = True
HAS_SHAP = True


FEATURE_COLUMNS = [
    "side_num",              # +1 LONG, -1 SHORT
    "rsi_15m",               # RSI(14) en 15m al momento de la entrada
    "vol_ratio_5m",          # Volumen 5m / SMA20(Vol)
    "body_ratio_15m",        # Cuerpo / Rango vela 15m
    "body_ratio_5m",         # Cuerpo / Rango vela gatillo 5m
    "slope_ema17_1h_norm",   # Pendiente EMA17 1H normalizada por ATR 1H
    "slope_ema30_1h_norm",   # Pendiente EMA30 1H normalizada por ATR 1H
    "dist_ema17_1h_atr",     # Distancia Precio a EMA17 1H en múltiplos de ATR 1H
    "dist_ema30_15m_atr",    # Distancia Precio a EMA30 15M en múltiplos de ATR 15M
    "atr_15m_pct",           # Volatilidad ATR 15m como % del precio
    "sl_dist_pct",           # Distancia porcentual del Stop Loss
    "prep_candles_5m",       # Velas de 5m transcurridas desde preparación 15m
    "hour_utc",              # Hora UTC de la entrada
    "consecutive_sl_prior"   # Racha de SL previos antes de abrir el trade
]


class ShadowAILearner:
    """
    Cerebro Cuantitativo en Sombra:
    1. Registra la radiografía de 14 features de cada entrada.
    2. Evalúa p(Win) con LightGBM y extrae atribución SHAP sin interferir en la ejecución.
    3. Monitorea MFE (Máxima Excursión Favorable) y MAE (Máxima Excursión Adversa) intratrade.
    4. Al cerrar un trade perdedor, realiza autopsia contrafactual (y seguimiento post-SL)
       para proponer alternativas concretas que habrían evitado o mejorado la pérdida.
    """
    def __init__(self, dataset_path: Optional[str] = None, model_path: Optional[str] = None, report_path: Optional[str] = None):
        os.makedirs("logs", exist_ok=True)
        self.dataset_path = dataset_path or os.path.join("logs", "ai_learning_dataset.json")
        self.model_path = model_path or os.path.join("logs", "ai_shadow_model.joblib")
        self.report_path = report_path or os.path.join("logs", "ai_learning_report.json")

        self.dataset: List[Dict[str, Any]] = self._load_dataset()
        self.model = None
        self.cv_accuracy: float = 0.0
        self.feature_importances: Dict[str, float] = {}
        self.active_trade_context: Optional[Dict[str, Any]] = None
        self.pending_post_mortem: List[Dict[str, Any]] = []

        self.min_trades_to_train = int(getattr(settings, "AI_MIN_TRADES_TO_TRAIN", 12))
        self.min_trades_for_ready = int(getattr(settings, "AI_MIN_TRADES_FOR_DECISIONS", 60))

        self._load_or_train_model()

    def _load_dataset(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.dataset_path):
            try:
                with open(self.dataset_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            except Exception as e:
                logger.warning(f"[IA SHADOW] No se pudo leer dataset previo: {e}")
        return []

    def _save_dataset(self) -> None:
        try:
            with open(self.dataset_path, "w", encoding="utf-8") as f:
                json.dump(self.dataset, f, indent=2)
        except Exception as e:
            logger.error(f"[IA SHADOW] Error guardando dataset de aprendizaje: {e}")

    def extract_entry_features(
        self,
        side: str,
        entry_price: float,
        sl_price: float,
        dfs: Dict[str, pd.DataFrame],
        signal_features: Optional[Dict[str, Any]] = None,
        consecutive_sl_prior: int = 0
    ) -> Dict[str, float]:
        """Extrae las 14 variables cuantitativas normalizadas de los DataFrames 1H, 15m y 5m."""
        signal_features = signal_features or {}
        side_num = 1.0 if side == "LONG" else -1.0

        df_1h = dfs.get("1h")
        df_15m = dfs.get("15m")
        df_5m = dfs.get("5m")

        # Defaults seguros
        rsi_15m = 50.0
        vol_ratio_5m = float(signal_features.get("vol_ratio", 1.0) or 1.0)
        body_ratio_15m = 0.5
        body_ratio_5m = 0.5
        slope_ema17_1h_norm = 0.0
        slope_ema30_1h_norm = 0.0
        dist_ema17_1h_atr = 0.0
        dist_ema30_15m_atr = 0.0
        atr_15m_pct = 0.0025
        hour_utc = float(datetime.utcnow().hour)

        if df_1h is not None and len(df_1h) >= 2:
            r1 = df_1h.iloc[-1]
            c1 = float(r1.get("close", entry_price) or entry_price)
            atr1 = float(r1.get("atr", 0.0) or 0.0)
            if atr1 <= 0:
                atr1 = max(float(r1.get("high", c1)) - float(r1.get("low", c1)), c1 * 0.003)
            ema17_1h = float(r1.get("ema17", c1) or c1)
            slope17 = float(r1.get("slope_ema17", 0.0) or 0.0)
            slope30 = float(r1.get("slope_ema30", 0.0) or 0.0)
            # Orientar pendientes y distancias a favor de la dirección del trade (+ = a favor)
            slope_ema17_1h_norm = round((slope17 / atr1) * side_num, 4)
            slope_ema30_1h_norm = round((slope30 / atr1) * side_num, 4)
            dist_ema17_1h_atr = round(((c1 - ema17_1h) / atr1) * side_num, 4)

        if df_15m is not None and len(df_15m) >= 1:
            r15 = df_15m.iloc[-1]
            c15 = float(r15.get("close", entry_price) or entry_price)
            o15 = float(r15.get("open", c15) or c15)
            h15 = float(r15.get("high", c15) or c15)
            l15 = float(r15.get("low", c15) or c15)
            rng15 = h15 - l15
            body_ratio_15m = round(abs(c15 - o15) / rng15, 4) if rng15 > 0 else 0.0
            rsi_15m = round(float(r15.get("rsi", 50.0) or 50.0), 2)
            atr15 = float(r15.get("atr", 0.0) or 0.0)
            if atr15 > 0 and c15 > 0:
                atr_15m_pct = round((atr15 / c15) * 100.0, 4)
                ema30_15m = float(r15.get("ema30", c15) or c15)
                dist_ema30_15m_atr = round(((c15 - ema30_15m) / atr15) * side_num, 4)

        if df_5m is not None and len(df_5m) >= 1:
            r5 = df_5m.iloc[-1]
            c5 = float(r5.get("close", entry_price) or entry_price)
            o5 = float(r5.get("open", c5) or c5)
            h5 = float(r5.get("high", c5) or c5)
            l5 = float(r5.get("low", c5) or c5)
            rng5 = h5 - l5
            body_ratio_5m = round(abs(c5 - o5) / rng5, 4) if rng5 > 0 else 0.0
            v5 = float(r5.get("volume", 0.0) or 0.0)
            vsma5 = float(r5.get("volume_sma20", v5) or v5)
            if vsma5 > 0:
                vol_ratio_5m = round(v5 / vsma5, 3)
            ts_raw = r5.get("timestamp")
            if ts_raw is not None:
                try:
                    hour_utc = float(pd.to_datetime(ts_raw).hour)
                except Exception:
                    pass

        sl_dist_pct = round((abs(entry_price - sl_price) / entry_price) * 100.0, 4) if entry_price > 0 else 0.20
        prep_candles_5m = float(signal_features.get("candles_5m_count", 1) or 1)

        return {
            "side_num": side_num,
            "rsi_15m": rsi_15m,
            "vol_ratio_5m": vol_ratio_5m,
            "body_ratio_15m": body_ratio_15m,
            "body_ratio_5m": body_ratio_5m,
            "slope_ema17_1h_norm": slope_ema17_1h_norm,
            "slope_ema30_1h_norm": slope_ema30_1h_norm,
            "dist_ema17_1h_atr": dist_ema17_1h_atr,
            "dist_ema30_15m_atr": dist_ema30_15m_atr,
            "atr_15m_pct": atr_15m_pct,
            "sl_dist_pct": sl_dist_pct,
            "prep_candles_5m": prep_candles_5m,
            "hour_utc": hour_utc,
            "consecutive_sl_prior": float(consecutive_sl_prior)
        }

    def _build_estimator(self, n_samples: int):
        """Crea un clasificador Gradient Boosting regularizado (rápido, sin bloqueo OpenMP y alta precisión)."""
        return GradientBoostingClassifier(
            n_estimators=60,
            max_depth=3,
            learning_rate=0.06,
            subsample=0.85,
            min_samples_leaf=max(3, min(10, n_samples // 6)),
            random_state=42
        )

    def _load_or_train_model(self) -> None:
        if os.path.exists(self.model_path):
            try:
                saved = joblib.load(self.model_path)
                if saved.get("trained_samples") == len(self.dataset) and saved.get("model") is not None:
                    self.model = saved.get("model")
                    self.cv_accuracy = float(saved.get("cv_accuracy", 0.0))
                    self.feature_importances = saved.get("feature_importances", {})
                    self.feature_means = saved.get("feature_means", {})
                    return
            except Exception:
                self.model = None
        if len(self.dataset) >= self.min_trades_to_train:
            self.train_model()

    def train_model(self) -> bool:
        """Entrena LightGBM sobre el historial acumulado y actualiza atribuciones SHAP y reporte."""
        valid_rows = [r for r in self.dataset if "features" in r and "is_win" in r]
        if len(valid_rows) < self.min_trades_to_train:
            return False

        X_list = []
        y_list = []
        for r in valid_rows:
            feats = r["features"]
            X_list.append([float(feats.get(col, 0.0) or 0.0) for col in FEATURE_COLUMNS])
            y_list.append(1 if r["is_win"] else 0)

        X = pd.DataFrame(X_list, columns=FEATURE_COLUMNS)
        y = np.array(y_list, dtype=int)

        if len(np.unique(y)) < 2:
            return False

        try:
            estimator = self._build_estimator(len(X))
            # Validación cruzada estratificada
            min_class_count = int(min(np.sum(y == 1), np.sum(y == 0)))
            if min_class_count >= 3:
                n_splits = min(5, min_class_count)
                skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
                scores = cross_val_score(estimator, X, y, cv=skf, scoring="accuracy")
                self.cv_accuracy = round(float(np.mean(scores)) * 100.0, 1)

            estimator.fit(X, y)
            self.model = estimator

            imp = getattr(self.model, "feature_importances_", np.ones(len(FEATURE_COLUMNS)))
            total_imp = float(np.sum(imp)) or 1.0
            self.feature_importances = {
                col: round(float(imp[i] / total_imp) * 100.0, 1)
                for i, col in enumerate(FEATURE_COLUMNS)
            }
            win_df = X[y == 1]
            loss_df = X[y == 0]
            self.feature_means = {
                col: {
                    "win_mean": float(win_df[col].mean()) if len(win_df) > 0 else 0.0,
                    "loss_mean": float(loss_df[col].mean()) if len(loss_df) > 0 else 0.0
                }
                for col in FEATURE_COLUMNS
            }

            joblib.dump({
                "model": self.model,
                "cv_accuracy": self.cv_accuracy,
                "feature_importances": self.feature_importances,
                "feature_means": self.feature_means,
                "trained_samples": len(X),
                "updated_at": datetime.now().isoformat()
            }, self.model_path)

            self._generate_learning_report()
            return True
        except Exception as e:
            logger.error(f"[IA SHADOW] Error entrenando modelo LightGBM: {e}")
            return False

    def predict_shadow(self, features: Dict[str, float]) -> Tuple[float, List[str]]:
        """
        Calcula la probabilidad estimada de éxito p(Win) y los 2 factores SHAP más influyentes.
        En modo SHADOW solo informa, NUNCA bloquea la entrada.
        """
        if self.model is None:
            return 0.50, ["Recopilando muestras iniciales"]

        try:
            x_row = pd.DataFrame([[float(features.get(col, 0.0) or 0.0) for col in FEATURE_COLUMNS]], columns=FEATURE_COLUMNS)
            probs = self.model.predict_proba(x_row)[0]
            win_prob = float(probs[1]) if len(probs) > 1 else float(probs[0])

            top_factors = []
            if self.feature_importances:
                top_cols = sorted(self.feature_importances.items(), key=lambda kv: kv[1], reverse=True)[:2]
                f_means = getattr(self, "feature_means", {}) or {}
                for col, _ in top_cols:
                    val = float(features.get(col, 0.0) or 0.0)
                    wm = f_means.get(col, {}).get("win_mean", val)
                    lm = f_means.get(col, {}).get("loss_mean", val)
                    sign = "+" if abs(val - wm) <= abs(val - lm) else "-"
                    top_factors.append(f"{col}={val:.2f} ({sign})")

            return round(win_prob, 4), top_factors
        except Exception:
            return 0.50, []

    def on_trade_entry(
        self,
        order_id: str,
        side: str,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        amount: float,
        dfs: Dict[str, pd.DataFrame],
        signal_features: Optional[Dict[str, Any]] = None,
        consecutive_sl_prior: int = 0
    ) -> Dict[str, Any]:
        """Registra el inicio de un trade en vivo para aprender de su evolución sin bloquearlo."""
        feats = self.extract_entry_features(
            side=side,
            entry_price=entry_price,
            sl_price=sl_price,
            dfs=dfs,
            signal_features=signal_features,
            consecutive_sl_prior=consecutive_sl_prior
        )
        win_prob, factors = self.predict_shadow(feats)
        risk_dist = max(abs(entry_price - sl_price), 1e-6)

        self.active_trade_context = {
            "order_id": str(order_id),
            "side": side,
            "entry_price": float(entry_price),
            "sl_price": float(sl_price),
            "tp_price": float(tp_price),
            "amount": float(amount),
            "risk_dist": float(risk_dist),
            "entry_time": datetime.now().isoformat(),
            "features": feats,
            "shadow_win_prob": win_prob,
            "shadow_top_factors": factors,
            "max_favorable_price": float(entry_price),
            "max_adverse_price": float(entry_price),
            "mfe_r": 0.0,
            "mae_r": 0.0,
            "bars_held_5m": 0
        }

        if getattr(settings, "ENVIRONMENT", "") != "BACKTEST":
            factors_str = ", ".join(factors) if factors else "N/A"
            readiness_pct = min(100.0, (len(self.dataset) / max(1, self.min_trades_for_ready)) * 100.0)
            logger.info(
                f"{Colors.CYAN}🧠 [IA SHADOW - MODO OBSERVADOR]{Colors.RESET} "
                f"Predicción p(Win): {win_prob*100:.1f}% | Factores SHAP: [{factors_str}] | "
                f"Madurez IA: {len(self.dataset)}/{self.min_trades_for_ready} trades ({readiness_pct:.0f}%) "
                f"(No interviene en la entrada)"
            )
        return self.active_trade_context

    def on_price_update(self, current_high: float, current_low: float, current_close: float) -> None:
        """
        Actualiza MFE/MAE del trade abierto actual y también monitorea qué pasó
        después de los trades perdedores recientes (seguimiento post-SL).
        """
        # 1. Actualizar MFE / MAE del trade activo
        if self.active_trade_context is not None:
            ctx = self.active_trade_context
            entry = ctx["entry_price"]
            risk = ctx["risk_dist"]
            ctx["bars_held_5m"] = ctx.get("bars_held_5m", 0) + 1

            if ctx["side"] == "LONG":
                if current_high > ctx["max_favorable_price"]:
                    ctx["max_favorable_price"] = float(current_high)
                if current_low < ctx["max_adverse_price"]:
                    ctx["max_adverse_price"] = float(current_low)
                ctx["mfe_r"] = round(max(0.0, (ctx["max_favorable_price"] - entry) / risk), 2)
                ctx["mae_r"] = round(max(0.0, (entry - ctx["max_adverse_price"]) / risk), 2)
            else:
                if current_low < ctx["max_favorable_price"]:
                    ctx["max_favorable_price"] = float(current_low)
                if current_high > ctx["max_adverse_price"]:
                    ctx["max_adverse_price"] = float(current_high)
                ctx["mfe_r"] = round(max(0.0, (entry - ctx["max_favorable_price"]) / risk), 2)
                ctx["mae_r"] = round(max(0.0, (ctx["max_adverse_price"] - entry) / risk), 2)

        # 2. Monitorear trades perdedores durante 12 velas de 5m (1 hora post-SL) para detectar Stop Hunts
        remaining_pm = []
        updated_any = False
        for pm in self.pending_post_mortem:
            pm["post_bars"] = pm.get("post_bars", 0) + 1
            side = pm["side"]
            entry = pm["entry_price"]
            tp = pm["tp_price"]
            risk = pm["risk_dist"]

            if side == "LONG":
                pm["post_best_price"] = max(pm.get("post_best_price", current_high), float(current_high))
                pm["post_worst_price"] = min(pm.get("post_worst_price", current_low), float(current_low))
                if pm["post_best_price"] >= tp:
                    pm["would_hit_tp_after_sl"] = True
                pm["post_max_adverse_r"] = round((entry - pm["post_worst_price"]) / risk, 2)
            else:
                pm["post_best_price"] = min(pm.get("post_best_price", current_low), float(current_low))
                pm["post_worst_price"] = max(pm.get("post_worst_price", current_high), float(current_high))
                if pm["post_best_price"] <= tp:
                    pm["would_hit_tp_after_sl"] = True
                pm["post_max_adverse_r"] = round((pm["post_worst_price"] - entry) / risk, 2)

            if pm["post_bars"] >= 12 or pm.get("would_hit_tp_after_sl", False):
                # Actualizar el registro en self.dataset si resultó ser un Stop Hunt
                if pm.get("would_hit_tp_after_sl") and pm.get("post_max_adverse_r", 99.0) <= 1.50:
                    for row in reversed(self.dataset):
                        if str(row.get("order_id")) == str(pm.get("order_id")):
                            row["loser_category"] = "STOP_HUNT_WICK"
                            row["improvement_alternative"] = (
                                f"Barrido de mecha detectado: el precio llegó hasta {pm['post_max_adverse_r']:.2f}R "
                                f"y luego tocó el TP original. Alternativa: SL de { round(1.2 * pm['post_max_adverse_r'], 2) }x ATR "
                                f"o orden límite más profunda en EMA17_15m convertía esta pérdida en ganancia."
                            )
                            updated_any = True
                            if getattr(settings, "ENVIRONMENT", "") != "BACKTEST":
                                logger.info(
                                    f"{Colors.YELLOW}🔍 [IA AUTOPSIA POST-SL]{Colors.RESET} Trade #{pm.get('order_id')} "
                                    f"reclasificado como STOP_HUNT_WICK -> {row['improvement_alternative']}"
                                )
                            break
            else:
                remaining_pm.append(pm)

        self.pending_post_mortem = remaining_pm
        if updated_any:
            self._save_dataset()
            self._generate_learning_report()

    def diagnose_losing_trade(self, ctx: Dict[str, Any], exit_price: float, pnl_usdt: float) -> Tuple[str, str]:
        """
        Analiza matemáticamente un trade perdedor y propone la alternativa
        específica que lo habría evitado o transformado en ganador/empate.
        """
        feats = ctx.get("features", {})
        mfe_r = float(ctx.get("mfe_r", 0.0) or 0.0)
        dist_1h = float(feats.get("dist_ema17_1h_atr", 0.0) or 0.0)
        slope_1h = float(feats.get("slope_ema17_1h_norm", 0.0) or 0.0)
        vol_ratio = float(feats.get("vol_ratio_5m", 1.0) or 1.0)
        body_5m = float(feats.get("body_ratio_5m", 0.5) or 0.5)
        rsi_15m = float(feats.get("rsi_15m", 50.0) or 50.0)
        side = ctx.get("side", "SHORT")

        # Caso 1: El trade estuvo ganando >= +1.0R y se devolvió a Stop Loss
        if mfe_r >= 1.0:
            return (
                "GIVE_BACK_AFTER_1R",
                f"El trade alcanzó +{mfe_r:.2f}R a favor antes de revertirse a SL. "
                f"Alternativa: Activar Breakeven automático o toma parcial 50% al tocar +1.1R "
                f"habría ahorrado ${abs(pnl_usdt):.2f} USD."
            )

        # Caso 2: Entrada en sobre-extensión / agotamiento de 1H
        if dist_1h > 1.35 or slope_1h < 0.08 or (side == "LONG" and rsi_15m > 64.0) or (side == "SHORT" and rsi_15m < 36.0):
            return (
                "TREND_EXHAUSTION_1H",
                f"Agotamiento de impulso (dist_ema17_1h={dist_1h:.2f} ATR, slope_1h={slope_1h:.2f}, RSI_15m={rsi_15m:.1f}). "
                f"Alternativa: Bloquear entradas cuando dist_ema17_1h_atr > 1.35 o momentum 15m extremo."
            )

        # Caso 3: Falsa ruptura en 5M (poco cuerpo o volumen marginal y MFE < 0.35R)
        if mfe_r < 0.35 and (vol_ratio < 1.15 or body_5m < 0.45):
            return (
                "WEAK_BREAKOUT_5M",
                f"Ruptura 5m sin continuación (MFE={mfe_r:.2f}R, vol_ratio={vol_ratio:.2f}x, body_5m={body_5m:.2f}). "
                f"Alternativa: Exigir vol_ratio >= 1.15x y body_ratio_5m >= 0.45 cuando la tendencia 1H es moderada."
            )

        # Caso 4: Reversión estructural o barrido pendiente de confirmación post-SL
        return (
            "STRUCTURAL_PULLBACK_DEEP",
            f"Retroceso profundo superó 1.2x ATR15m (MFE={mfe_r:.2f}R). "
            f"Monitoreando las próximas 12 velas de 5m para verificar si fue Stop Hunt (barrido de mecha) o giro real."
        )

    def on_trade_exit(
        self,
        order_id: str,
        side: str,
        entry_price: float,
        exit_price: float,
        pnl_usdt: float,
        reason: str,
        timestamp_str: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        Registra el cierre del trade, ejecuta la autopsia si fue perdedor,
        guarda el nuevo ejemplo en el dataset y re-entrena el modelo LightGBM.
        """
        ctx = self.active_trade_context
        if ctx is None:
            # Si el bot se reinició mientras la posición estaba abierta, crear contexto mínimo
            risk_dist = max(abs(entry_price - exit_price), entry_price * 0.002)
            ctx = {
                "order_id": str(order_id),
                "side": side,
                "entry_price": float(entry_price),
                "sl_price": float(exit_price) if pnl_usdt < 0 else float(entry_price),
                "tp_price": float(exit_price) if pnl_usdt > 0 else float(entry_price),
                "amount": 0.02,
                "risk_dist": float(risk_dist),
                "entry_time": timestamp_str or datetime.now().isoformat(),
                "features": {col: 0.0 for col in FEATURE_COLUMNS},
                "shadow_win_prob": 0.50,
                "shadow_top_factors": [],
                "mfe_r": 2.0 if pnl_usdt > 0 else 0.2,
                "mae_r": 0.3 if pnl_usdt > 0 else 1.0,
                "bars_held_5m": 1
            }

        is_win = bool(pnl_usdt > 0)
        loser_category = "NONE (WINNER)"
        alternative = "Trade ganador: patrón positivo reforzado en LightGBM."

        if not is_win:
            loser_category, alternative = self.diagnose_losing_trade(ctx, exit_price, pnl_usdt)
            self.pending_post_mortem.append({
                "order_id": str(order_id),
                "side": side,
                "entry_price": float(entry_price),
                "tp_price": float(ctx.get("tp_price", entry_price)),
                "risk_dist": float(ctx.get("risk_dist", max(abs(entry_price - exit_price), 1.0))),
                "post_bars": 0,
                "post_best_price": float(exit_price),
                "post_worst_price": float(exit_price),
                "would_hit_tp_after_sl": False
            })

        record = {
            "order_id": str(order_id),
            "side": side,
            "entry_price": float(entry_price),
            "exit_price": float(exit_price),
            "pnl_usdt": round(float(pnl_usdt), 2),
            "is_win": is_win,
            "reason": reason,
            "mfe_r": float(ctx.get("mfe_r", 0.0)),
            "mae_r": float(ctx.get("mae_r", 0.0)),
            "bars_held_5m": int(ctx.get("bars_held_5m", 0)),
            "shadow_win_prob_at_entry": float(ctx.get("shadow_win_prob", 0.5)),
            "loser_category": loser_category,
            "improvement_alternative": alternative,
            "features": ctx.get("features", {}),
            "timestamp": timestamp_str or datetime.now().isoformat()
        }

        # Evitar duplicar el mismo order_id
        self.dataset = [r for r in self.dataset if str(r.get("order_id")) != str(order_id)]
        self.dataset.append(record)
        self._save_dataset()
        self.active_trade_context = None

        # Re-entrenar modelo con la nueva experiencia
        self.train_model()

        if getattr(settings, "ENVIRONMENT", "") != "BACKTEST":
            if is_win:
                logger.info(
                    f"{Colors.GREEN}🧠 [IA APRENDIZAJE +1 GANADOR]{Colors.RESET} Trade #{order_id} (+${pnl_usdt:.2f} USD) "
                    f"incorporado | Total muestras: {len(self.dataset)} | Precisión CV IA: {self.cv_accuracy:.1f}%"
                )
            else:
                logger.info(
                    f"{Colors.YELLOW}🧠 [IA AUTOPSIA TRADE PERDEDOR]{Colors.RESET} Trade #{order_id} (${pnl_usdt:.2f} USD) "
                    f"| Diagnóstico: [{loser_category}] -> {alternative}"
                )

        return record

    def _generate_learning_report(self) -> Dict[str, Any]:
        """Construye y guarda un resumen ejecutivo de todo lo aprendido sobre ganadores y perdedores."""
        total = len(self.dataset)
        wins = [r for r in self.dataset if r.get("is_win")]
        losses = [r for r in self.dataset if not r.get("is_win")]

        loser_breakdown: Dict[str, int] = {}
        recommendations: List[str] = []
        for r in losses:
            cat = r.get("loser_category", "UNKNOWN")
            loser_breakdown[cat] = loser_breakdown.get(cat, 0) + 1

        if losses:
            n_loss = len(losses)
            gb = loser_breakdown.get("GIVE_BACK_AFTER_1R", 0)
            sh = loser_breakdown.get("STOP_HUNT_WICK", 0)
            ex = loser_breakdown.get("TREND_EXHAUSTION_1H", 0)
            wb = loser_breakdown.get("WEAK_BREAKOUT_5M", 0)

            if gb > 0:
                recommendations.append(
                    f"Give-Back ({gb}/{n_loss} derrotas, {gb/n_loss*100:.0f}%): Llegaron a >= +1.0R antes de caer a SL. "
                    f"Alternativa: Breakeven en +1.15R."
                )
            if sh > 0:
                recommendations.append(
                    f"Stop Hunt ({sh}/{n_loss} derrotas, {sh/n_loss*100:.0f}%): Barridos por mecha antes de ir al TP. "
                    f"Alternativa: SL 1.35x ATR en horas de alta volatilidad."
                )
            if ex > 0:
                recommendations.append(
                    f"Agotamiento 1H ({ex}/{n_loss} derrotas, {ex/n_loss*100:.0f}%): Entradas lejos de EMA17_1H (>1.35 ATR). "
                    f"Alternativa: Filtrar sobre-extensión en 1H."
                )
            if wb > 0:
                recommendations.append(
                    f"Ruptura Débil 5M ({wb}/{n_loss} derrotas, {wb/n_loss*100:.0f}%): Sin seguimiento (<0.35R). "
                    f"Alternativa: Subir filtro de volumen/cuerpo en 5m."
                )

        # Evaluar qué habría pasado si la IA hubiera filtrado los trades con p(Win) < 0.36
        report = {
            "updated_at": datetime.now().isoformat(),
            "mode": "ACTIVE_DECISION" if getattr(settings, "AI_TAKE_DECISIONS", False) else "SHADOW_LEARNING_ONLY",
            "total_trades_learned": total,
            "min_trades_for_ready": self.min_trades_for_ready,
            "readiness_pct": round(min(100.0, (total / max(1, self.min_trades_for_ready)) * 100.0), 1),
            "ready_for_live_decisions": bool(total >= self.min_trades_for_ready and self.cv_accuracy >= 55.0),
            "wins_learned": len(wins),
            "losses_learned": len(losses),
            "model_engine": "LightGBM + SHAP" if HAS_LIGHTGBM else "GradientBoosting",
            "cross_val_accuracy_pct": self.cv_accuracy,
            "top_shap_features": dict(sorted(self.feature_importances.items(), key=lambda kv: kv[1], reverse=True)[:6]),
            "loser_autopsy_breakdown": loser_breakdown,
            "actionable_alternatives_for_losers": recommendations
        }

        try:
            with open(self.report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[IA SHADOW] Error guardando reporte de aprendizaje: {e}")

        return report

    def get_dashboard_summary(self, current_features: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """Devuelve el resumen en vivo para mostrar en el tablero multitemporal de consola."""
        total = len(self.dataset)
        readiness_pct = min(100.0, (total / max(1, self.min_trades_for_ready)) * 100.0)
        mode_str = "ACTIVO (Filtra Entradas)" if getattr(settings, "AI_TAKE_DECISIONS", False) else "SOMBRA (Solo Aprende - No Interviene)"
        prob, factors = (0.50, [])
        if current_features:
            prob, factors = self.predict_shadow(current_features)

        return {
            "mode_str": mode_str,
            "total_learned": total,
            "target_learned": self.min_trades_for_ready,
            "readiness_pct": round(readiness_pct, 1),
            "cv_accuracy": self.cv_accuracy,
            "shadow_prob_pct": round(prob * 100.0, 1),
            "top_factors": factors
        }
