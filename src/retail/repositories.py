from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from src.retail.models import InventoryRecord, Product, SalesHistory, SeasonalTrend, SupplierRule


class RetailDataError(ValueError):
    """Raised when controlled retail data is missing or malformed."""


class RetailRepository(Protocol):
    def list_products(self, category: str | None = None) -> list[Product]:
        ...

    def get_product(self, product_id: str) -> Product:
        ...

    def get_inventory_record(self, product_id: str) -> InventoryRecord:
        ...

    def get_sales_history(self, product_id: str, days: int) -> SalesHistory:
        ...

    def get_supplier_rule(self, product_id: str) -> SupplierRule:
        ...

    def get_seasonal_trend(self, period_id: str) -> SeasonalTrend:
        ...

    def list_seasonal_trends(self) -> list[SeasonalTrend]:
        ...


class JsonRetailRepository:
    """Read-only repository backed by curated mock retail data."""

    def __init__(self, data_dir: Path | str | None = None):
        root = Path(__file__).resolve().parents[2]
        self.data_dir = Path(data_dir) if data_dir else root / "data" / "retail"
        self._products = self._load_products()
        self._inventory = self._load_inventory()
        self._sales = self._load_sales()
        self._supplier_rules = self._load_supplier_rules()
        self._seasonal_trends = self._load_seasonal_trends()

    def list_products(self, category: str | None = None) -> list[Product]:
        products = list(self._products.values())
        if category:
            normalized = category.strip().lower()
            products = [product for product in products if product.category.lower() == normalized]
        return sorted(products, key=lambda product: product.product_id)

    def get_product(self, product_id: str) -> Product:
        product = self._products.get(self._normalize_product_id(product_id))
        if product is None:
            raise RetailDataError(f"Unknown product_id: {product_id}")
        return product

    def get_inventory_record(self, product_id: str) -> InventoryRecord:
        record = self._inventory.get(self._normalize_product_id(product_id))
        if record is None:
            raise RetailDataError(f"Inventory not found for product_id: {product_id}")
        return record

    def get_sales_history(self, product_id: str, days: int) -> SalesHistory:
        if days <= 0 or days > 30:
            raise RetailDataError("days must be between 1 and 30")

        normalized_id = self._normalize_product_id(product_id)
        quantities = self._sales.get(normalized_id)
        if quantities is None:
            raise RetailDataError(f"Sales history not found for product_id: {product_id}")

        return SalesHistory(
            product_id=normalized_id,
            days=days,
            daily_quantities=tuple(quantities[-days:]),
        )

    def get_supplier_rule(self, product_id: str) -> SupplierRule:
        rule = self._supplier_rules.get(self._normalize_product_id(product_id))
        if rule is None:
            raise RetailDataError(f"Supplier rule not found for product_id: {product_id}")
        return rule

    def get_seasonal_trend(self, period_id: str) -> SeasonalTrend:
        trend = self._seasonal_trends.get(self._normalize_period_id(period_id))
        if trend is None:
            raise RetailDataError(f"Seasonal trend not found for period_id: {period_id}")
        return trend

    def list_seasonal_trends(self) -> list[SeasonalTrend]:
        return sorted(self._seasonal_trends.values(), key=lambda trend: trend.period_id)

    def _load_products(self) -> dict[str, Product]:
        rows = self._read_json("products.json")
        products = {}
        for row in rows:
            product = Product(
                product_id=str(row["product_id"]),
                name=str(row["name"]),
                category=str(row["category"]),
                unit=str(row["unit"]),
                unit_price=int(row["unit_price"]),
                unit_cost=int(row["unit_cost"]),
            )
            products[product.product_id] = product
        return products

    def _load_inventory(self) -> dict[str, InventoryRecord]:
        rows = self._read_json("inventory.json")
        return {
            str(row["product_id"]): InventoryRecord(
                product_id=str(row["product_id"]),
                stock_on_hand=int(row["stock_on_hand"]),
                reorder_point=int(row["reorder_point"]),
                safety_stock=int(row["safety_stock"]),
            )
            for row in rows
        }

    def _load_sales(self) -> dict[str, tuple[int, ...]]:
        rows = self._read_json("sales_history.json")
        return {
            str(row["product_id"]): tuple(int(value) for value in row["daily_quantities"])
            for row in rows
        }

    def _load_supplier_rules(self) -> dict[str, SupplierRule]:
        rows = self._read_json("supplier_rules.json")
        return {
            str(row["product_id"]): SupplierRule(
                product_id=str(row["product_id"]),
                lead_time_days=int(row["lead_time_days"]),
                min_order_qty=int(row["min_order_qty"]),
                pack_size=int(row["pack_size"]),
            )
            for row in rows
        }

    def _load_seasonal_trends(self) -> dict[str, SeasonalTrend]:
        rows = self._read_json("seasonal_trends.json")
        return {
            str(row["period_id"]): SeasonalTrend(
                period_id=str(row["period_id"]),
                label=str(row["label"]),
                description=str(row["description"]),
                category_multipliers={
                    str(key): float(value)
                    for key, value in row.get("category_multipliers", {}).items()
                },
                product_multipliers={
                    str(key): float(value)
                    for key, value in row.get("product_multipliers", {}).items()
                },
                promotion_categories=tuple(str(value) for value in row.get("promotion_categories", [])),
            )
            for row in rows
        }

    def _read_json(self, filename: str) -> Any:
        path = self.data_dir / filename
        if path.parent != self.data_dir:
            raise RetailDataError("Invalid data path")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RetailDataError(f"Data file not found: {filename}") from exc
        except json.JSONDecodeError as exc:
            raise RetailDataError(f"Invalid JSON file: {filename}") from exc

    @staticmethod
    def _normalize_product_id(product_id: str) -> str:
        return product_id.strip().upper()

    @staticmethod
    def _normalize_period_id(period_id: str) -> str:
        return period_id.strip().lower()
