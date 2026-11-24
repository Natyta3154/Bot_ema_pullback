"""Construccion de planes de entrada independientes del adaptador de ejecucion."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from bot.core.risk import RiskManager


@dataclass
class EntryOrderPlan:
    side: str
    amount: float
    price: float
    stop_loss: float
    take_profit: float = 0.0
    tp_targets: List[Dict[str, Any]] = field(default_factory=list)
    features: Dict[str, Any] = field(default_factory=dict)


class OrderPlanner:
    """Convierte una señal validada en una orden de entrada reproducible."""

    def __init__(self, risk_manager: RiskManager):
        self.risk_manager = risk_manager

    def build_entry_plan(self, signal: Dict[str, Any], balance: float) -> Optional[EntryOrderPlan]:
        side = signal.get("action")
        if side not in ("LONG", "SHORT"):
            return None

        price = float(signal.get("price", 0.0) or 0.0)
        stop_loss = float(signal.get("sl", 0.0) or 0.0)
        if price <= 0 or stop_loss <= 0:
            return None

        amount = self.risk_manager.calculate_position_size(
            price, stop_loss, float(balance), side
        )
        if amount <= 0:
            return None

        targets = []
        for raw_target in signal.get("tp_targets", []):
            target = dict(raw_target)
            pct = float(target.pop("amount_pct", 0.0) or 0.0)
            target["amount"] = round(amount * pct, 4)
            targets.append(target)

        features = dict(signal.get("features", {}))
        features.setdefault("sl_price", stop_loss)
        features.setdefault("stop_loss", stop_loss)
        features.setdefault("take_profit", float(signal.get("tp", 0.0) or 0.0))
        return EntryOrderPlan(
            side=side,
            amount=amount,
            price=price,
            stop_loss=stop_loss,
            take_profit=float(signal.get("tp", 0.0) or 0.0),
            tp_targets=targets,
            features=features,
        )

    def place_entry(self, order_manager, plan: EntryOrderPlan) -> str:
        if plan.side == "LONG":
            return order_manager.place_limit_long(
                plan.amount, plan.price, features=plan.features
            )
        return order_manager.place_limit_short(
            plan.amount, plan.price, features=plan.features
        )
