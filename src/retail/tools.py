from __future__ import annotations

import math
from typing import Any

from src.retail.models import InventoryRecord, Product, SalesHistory
from src.retail.repositories import JsonRetailRepository, RetailRepository


class RetailTools:
    """Deterministic tools used by the retail advisor agent."""

    def __init__(self, repository: RetailRepository | None = None):
        self.repository = repository or JsonRetailRepository()

    def get_inventory(
        self,
        product_id: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        if product_id:
            product = self.repository.get_product(product_id)
            inventory = self.repository.get_inventory_record(product.product_id)
            return self._inventory_payload(product, inventory)

        rows = []
        for product in self.repository.list_products(category=category):
            inventory = self.repository.get_inventory_record(product.product_id)
            rows.append(self._inventory_payload(product, inventory))

        return {"items": rows, "count": len(rows), "category": category}

    def get_sales_history(self, product_id: str, days: int = 7) -> dict[str, Any]:
        product = self.repository.get_product(product_id)
        history = self.repository.get_sales_history(product.product_id, days)
        return self._sales_payload(product, history)

    def calculate_sell_through_rate(self, product_id: str, days: int = 30) -> dict[str, Any]:
        product = self.repository.get_product(product_id)
        history = self.repository.get_sales_history(product.product_id, days)
        inventory = self.repository.get_inventory_record(product.product_id)
        denominator = history.total_sold + inventory.stock_on_hand
        rate = 0.0 if denominator == 0 else history.total_sold / denominator
        return {
            "product_id": product.product_id,
            "name": product.name,
            "days": days,
            "total_sold": history.total_sold,
            "stock_on_hand": inventory.stock_on_hand,
            "sell_through_rate": round(rate, 4),
            "sell_through_percent": round(rate * 100, 1),
        }

    def detect_stockout_risk(self, product_id: str, days: int = 7) -> dict[str, Any]:
        product = self.repository.get_product(product_id)
        inventory = self.repository.get_inventory_record(product.product_id)
        history = self.repository.get_sales_history(product.product_id, days)
        supplier = self.repository.get_supplier_rule(product.product_id)

        average_daily_sales = history.average_daily_sales
        if average_daily_sales <= 0:
            days_until_stockout = math.inf
        else:
            days_until_stockout = inventory.stock_on_hand / average_daily_sales

        risk_window_days = supplier.lead_time_days + 2
        if days_until_stockout <= risk_window_days:
            risk_level = "high"
        elif days_until_stockout <= risk_window_days + 3:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "product_id": product.product_id,
            "name": product.name,
            "stock_on_hand": inventory.stock_on_hand,
            "average_daily_sales": round(average_daily_sales, 2),
            "lead_time_days": supplier.lead_time_days,
            "days_until_stockout": None if math.isinf(days_until_stockout) else round(days_until_stockout, 1),
            "risk_level": risk_level,
            "risk_reason": (
                "Demand will outrun stock before replenishment can safely arrive."
                if risk_level == "high"
                else "Stock is acceptable but should be watched."
                if risk_level == "medium"
                else "Stock is sufficient for the current demand window."
            ),
        }

    def detect_slow_moving_items(
        self,
        category: str | None = None,
        days: int = 30,
    ) -> dict[str, Any]:
        candidates = []
        for product in self.repository.list_products(category=category):
            inventory = self.repository.get_inventory_record(product.product_id)
            sell_through = self.calculate_sell_through_rate(product.product_id, days)
            is_overstocked = inventory.stock_on_hand >= inventory.reorder_point * 2
            is_slow = sell_through["sell_through_rate"] < 0.18
            if is_overstocked and is_slow:
                candidates.append(
                    {
                        "product_id": product.product_id,
                        "name": product.name,
                        "category": product.category,
                        "stock_on_hand": inventory.stock_on_hand,
                        "sell_through_percent": sell_through["sell_through_percent"],
                        "suggested_discount_percent": self._discount_for_sell_through(
                            sell_through["sell_through_rate"]
                        ),
                        "reason": "High stock with weak 30-day sell-through.",
                    }
                )

        return {
            "items": sorted(candidates, key=lambda item: item["sell_through_percent"]),
            "count": len(candidates),
            "category": category,
            "days": days,
        }

    def recommend_reorder_quantity(
        self,
        product_id: str,
        days: int = 7,
        cover_days: int = 14,
    ) -> dict[str, Any]:
        product = self.repository.get_product(product_id)
        inventory = self.repository.get_inventory_record(product.product_id)
        history = self.repository.get_sales_history(product.product_id, days)
        supplier = self.repository.get_supplier_rule(product.product_id)

        target_stock = math.ceil(
            history.average_daily_sales * (supplier.lead_time_days + cover_days)
            + inventory.safety_stock
        )
        raw_quantity = max(0, target_stock - inventory.stock_on_hand)
        if raw_quantity == 0:
            recommended_quantity = 0
        else:
            recommended_quantity = max(supplier.min_order_qty, raw_quantity)
            recommended_quantity = self._round_up_to_pack(recommended_quantity, supplier.pack_size)

        return {
            "product_id": product.product_id,
            "name": product.name,
            "recommended_quantity": recommended_quantity,
            "target_stock": target_stock,
            "current_stock": inventory.stock_on_hand,
            "pack_size": supplier.pack_size,
            "min_order_qty": supplier.min_order_qty,
            "reason": "Quantity covers supplier lead time, two-week demand, and safety stock.",
        }

    def get_seasonal_trends(self, period_id: str) -> dict[str, Any]:
        trend = self.repository.get_seasonal_trend(period_id)
        return {
            "period_id": trend.period_id,
            "label": trend.label,
            "description": trend.description,
            "category_multipliers": trend.category_multipliers,
            "product_multipliers": trend.product_multipliers,
            "promotion_categories": list(trend.promotion_categories),
        }

    def recommend_seasonal_stock_plan(
        self,
        period_id: str,
        category: str | None = None,
        days: int = 30,
        cover_days: int = 21,
    ) -> dict[str, Any]:
        trend = self.repository.get_seasonal_trend(period_id)
        candidates = []
        promotion_candidates = []

        for product in self.repository.list_products(category=category):
            multiplier = self._seasonal_multiplier(product.product_id, product.category, trend)
            if multiplier <= 1:
                if product.category in trend.promotion_categories:
                    inventory = self.repository.get_inventory_record(product.product_id)
                    sell_through = self.calculate_sell_through_rate(product.product_id, days)
                    promotion_candidates.append(
                        {
                            "product_id": product.product_id,
                            "name": product.name,
                            "category": product.category,
                            "stock_on_hand": inventory.stock_on_hand,
                            "sell_through_percent": sell_through["sell_through_percent"],
                            "reason": f"Category is not a demand focus for {trend.label}.",
                        }
                    )
                continue

            inventory = self.repository.get_inventory_record(product.product_id)
            history = self.repository.get_sales_history(product.product_id, days)
            supplier = self.repository.get_supplier_rule(product.product_id)
            seasonal_daily_demand = history.average_daily_sales * multiplier
            target_stock = math.ceil(
                seasonal_daily_demand * (supplier.lead_time_days + cover_days)
                + inventory.safety_stock
            )
            raw_quantity = max(0, target_stock - inventory.stock_on_hand)
            recommended_quantity = 0
            if raw_quantity > 0:
                recommended_quantity = max(supplier.min_order_qty, raw_quantity)
                recommended_quantity = self._round_up_to_pack(recommended_quantity, supplier.pack_size)

            if recommended_quantity > 0:
                candidates.append(
                    {
                        "product_id": product.product_id,
                        "name": product.name,
                        "category": product.category,
                        "period_id": trend.period_id,
                        "period_label": trend.label,
                        "demand_multiplier": round(multiplier, 2),
                        "average_daily_sales": round(history.average_daily_sales, 2),
                        "seasonal_daily_demand": round(seasonal_daily_demand, 2),
                        "current_stock": inventory.stock_on_hand,
                        "target_stock": target_stock,
                        "recommended_quantity": recommended_quantity,
                        "reason": trend.description,
                    }
                )

        return {
            "period_id": trend.period_id,
            "period_label": trend.label,
            "description": trend.description,
            "items": sorted(
                candidates,
                key=lambda item: (item["demand_multiplier"], item["recommended_quantity"]),
                reverse=True,
            ),
            "promotion_candidates": sorted(
                promotion_candidates,
                key=lambda item: item["sell_through_percent"],
            ),
            "count": len(candidates),
            "category": category,
        }

    def tool_specs(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "get_inventory",
                "description": "Get stock, reorder point, and safety stock by product_id or category.",
                "func": self.get_inventory,
            },
            {
                "name": "get_sales_history",
                "description": "Get 7/30-day sales history for one product_id.",
                "func": self.get_sales_history,
            },
            {
                "name": "calculate_sell_through_rate",
                "description": "Calculate sell-through rate from sold units and current stock.",
                "func": self.calculate_sell_through_rate,
            },
            {
                "name": "detect_stockout_risk",
                "description": "Classify a product as low, medium, or high stockout risk.",
                "func": self.detect_stockout_risk,
            },
            {
                "name": "detect_slow_moving_items",
                "description": "Find overstocked products with weak 30-day sell-through.",
                "func": self.detect_slow_moving_items,
            },
            {
                "name": "recommend_reorder_quantity",
                "description": "Recommend reorder quantity using lead time, pack size, and safety stock.",
                "func": self.recommend_reorder_quantity,
            },
            {
                "name": "get_seasonal_trends",
                "description": "Get demand multipliers for a named season or retail period.",
                "func": self.get_seasonal_trends,
            },
            {
                "name": "recommend_seasonal_stock_plan",
                "description": "Recommend pre-season reorder actions using demand multipliers.",
                "func": self.recommend_seasonal_stock_plan,
            },
        ]

    @staticmethod
    def _inventory_payload(product: Product, inventory: InventoryRecord) -> dict[str, Any]:
        return {
            "product_id": product.product_id,
            "name": product.name,
            "category": product.category,
            "unit": product.unit,
            "unit_price": product.unit_price,
            "stock_on_hand": inventory.stock_on_hand,
            "reorder_point": inventory.reorder_point,
            "safety_stock": inventory.safety_stock,
        }

    @staticmethod
    def _sales_payload(product: Product, history: SalesHistory) -> dict[str, Any]:
        return {
            "product_id": product.product_id,
            "name": product.name,
            "days": history.days,
            "daily_quantities": list(history.daily_quantities),
            "total_sold": history.total_sold,
            "average_daily_sales": round(history.average_daily_sales, 2),
        }

    @staticmethod
    def _round_up_to_pack(quantity: int, pack_size: int) -> int:
        if pack_size <= 0:
            return quantity
        return int(math.ceil(quantity / pack_size) * pack_size)

    @staticmethod
    def _discount_for_sell_through(rate: float) -> int:
        if rate < 0.08:
            return 20
        if rate < 0.12:
            return 15
        return 10

    @staticmethod
    def _seasonal_multiplier(product_id: str, category: str, trend: Any) -> float:
        product_multiplier = trend.product_multipliers.get(product_id)
        if product_multiplier is not None:
            return product_multiplier
        return trend.category_multipliers.get(category, 1.0)
