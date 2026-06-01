from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

RiskLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str
    category: str
    unit: str
    unit_price: int
    unit_cost: int


@dataclass(frozen=True)
class InventoryRecord:
    product_id: str
    stock_on_hand: int
    reorder_point: int
    safety_stock: int


@dataclass(frozen=True)
class SalesHistory:
    product_id: str
    days: int
    daily_quantities: tuple[int, ...]

    @property
    def total_sold(self) -> int:
        return sum(self.daily_quantities)

    @property
    def average_daily_sales(self) -> float:
        if self.days == 0:
            return 0.0
        return self.total_sold / self.days


@dataclass(frozen=True)
class SupplierRule:
    product_id: str
    lead_time_days: int
    min_order_qty: int
    pack_size: int


@dataclass(frozen=True)
class SeasonalTrend:
    period_id: str
    label: str
    description: str
    category_multipliers: dict[str, float]
    product_multipliers: dict[str, float]
    promotion_categories: tuple[str, ...]


@dataclass(frozen=True)
class ToolTrace:
    thought: str
    action: str
    observation: dict[str, Any]


@dataclass(frozen=True)
class AdvisorResult:
    answer: str
    restock_items: list[dict[str, Any]]
    promotion_items: list[dict[str, Any]]
    seasonal_items: list[dict[str, Any]]
    metrics: dict[str, Any]
    trace: list[ToolTrace]
