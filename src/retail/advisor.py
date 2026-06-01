from __future__ import annotations

import time
from typing import Any, Callable

from src.retail.models import AdvisorResult, ToolTrace
from src.retail.repositories import RetailDataError
from src.retail.tools import RetailTools
from src.telemetry.logger import logger


class RetailStockAdvisor:
    """Rule-based ReAct-style advisor grounded in controlled retail data."""

    def __init__(self, tools: RetailTools | None = None):
        self.tools = tools or RetailTools()

    def answer(
        self,
        question: str,
        category: str | None = None,
        period_id: str | None = None,
    ) -> AdvisorResult:
        started = time.perf_counter()
        trace: list[ToolTrace] = []
        tool_call_count = 0

        logger.log_event(
            "RETAIL_AGENT_START",
            {"question": question, "category": category, "period_id": period_id},
        )

        try:
            inventory = self._call_tool(
                trace,
                "Need current stock before making reorder or promotion decisions.",
                "get_inventory",
                self.tools.get_inventory,
                category=category or None,
            )
            tool_call_count += 1

            restock_items = []
            inventory_items = inventory["items"] if "items" in inventory else [inventory]
            for item in inventory_items:
                product_id = item["product_id"]
                self._call_tool(
                    trace,
                    "Need recent 7-day demand to estimate near-term stockout risk.",
                    "get_sales_history",
                    self.tools.get_sales_history,
                    product_id=product_id,
                    days=7,
                )
                tool_call_count += 1

                self._call_tool(
                    trace,
                    "Need 30-day sell-through to separate healthy demand from overstock.",
                    "calculate_sell_through_rate",
                    self.tools.calculate_sell_through_rate,
                    product_id=product_id,
                    days=30,
                )
                tool_call_count += 1

                risk = self._call_tool(
                    trace,
                    "Classify risk after combining inventory, demand, and supplier lead time.",
                    "detect_stockout_risk",
                    self.tools.detect_stockout_risk,
                    product_id=product_id,
                    days=7,
                )
                tool_call_count += 1

                if risk["risk_level"] in {"high", "medium"}:
                    reorder = self._call_tool(
                        trace,
                        "Risk is actionable, calculate an order quantity with pack-size rules.",
                        "recommend_reorder_quantity",
                        self.tools.recommend_reorder_quantity,
                        product_id=product_id,
                        days=7,
                    )
                    tool_call_count += 1
                    restock_items.append({**risk, **reorder})

            slow_moving = self._call_tool(
                trace,
                "Promotion candidates should come from overstock plus weak 30-day sell-through.",
                "detect_slow_moving_items",
                self.tools.detect_slow_moving_items,
                category=category or None,
                days=30,
            )
            tool_call_count += 1

            seasonal_items: list[dict[str, Any]] = []
            seasonal_promotions: list[dict[str, Any]] = []
            if period_id:
                self._call_tool(
                    trace,
                    "Need controlled seasonal demand multipliers before forecasting period-specific demand.",
                    "get_seasonal_trends",
                    self.tools.get_seasonal_trends,
                    period_id=period_id,
                )
                tool_call_count += 1

                seasonal_plan = self._call_tool(
                    trace,
                    "Use seasonal multipliers to recommend pre-season stock and off-season promotion actions.",
                    "recommend_seasonal_stock_plan",
                    self.tools.recommend_seasonal_stock_plan,
                    period_id=period_id,
                    category=category or None,
                )
                tool_call_count += 1
                seasonal_items = seasonal_plan["items"]
                seasonal_promotions = seasonal_plan["promotion_candidates"]

            duration_ms = int((time.perf_counter() - started) * 1000)
            metrics = {
                "duration_ms": duration_ms,
                "tool_calls": tool_call_count,
                "products_analyzed": len(inventory_items),
                "restock_count": len(restock_items),
                "promotion_count": slow_moving["count"],
                "seasonal_count": len(seasonal_items),
                "seasonal_promotion_count": len(seasonal_promotions),
            }

            answer = self._format_answer(
                restock_items,
                slow_moving["items"],
                seasonal_items,
                seasonal_promotions,
                metrics,
            )
            result = AdvisorResult(
                answer=answer,
                restock_items=sorted(
                    restock_items,
                    key=lambda item: (self._risk_rank(item["risk_level"]), item["days_until_stockout"] or 999),
                ),
                promotion_items=slow_moving["items"],
                seasonal_items=seasonal_items,
                metrics=metrics,
                trace=trace,
            )
            logger.log_event("RETAIL_AGENT_END", metrics)
            return result
        except RetailDataError as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.log_event("RETAIL_AGENT_ERROR", {"error": str(exc), "duration_ms": duration_ms})
            return AdvisorResult(
                answer=f"Không đủ dữ liệu để tư vấn: {exc}",
                restock_items=[],
                promotion_items=[],
                seasonal_items=[],
                metrics={"duration_ms": duration_ms, "tool_calls": tool_call_count, "error": str(exc)},
                trace=trace,
            )

    def _call_tool(
        self,
        trace: list[ToolTrace],
        thought: str,
        name: str,
        func: Callable[..., dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        observation = func(**kwargs)
        trace.append(
            ToolTrace(
                thought=thought,
                action=f"{name}({kwargs})",
                observation=observation,
            )
        )
        logger.log_event("RETAIL_TOOL_CALL", {"tool": name, "args": kwargs, "observation": observation})
        return observation

    @staticmethod
    def _format_answer(
        restock_items: list[dict[str, Any]],
        promotion_items: list[dict[str, Any]],
        seasonal_items: list[dict[str, Any]],
        seasonal_promotions: list[dict[str, Any]],
        metrics: dict[str, Any],
    ) -> str:
        lines = [
            "Khuyến nghị tuần này:",
            "",
            "Nhập thêm hàng:",
        ]

        if not restock_items:
            lines.append("- Chưa có mặt hàng nào cần nhập thêm ngay.")
        else:
            for item in restock_items:
                lines.append(
                    "- {name}: nhập {qty} đơn vị, rủi ro {risk}, còn khoảng {days} ngày bán.".format(
                        name=item["name"],
                        qty=item["recommended_quantity"],
                        risk=item["risk_level"],
                        days=item["days_until_stockout"],
                    )
                )

        if seasonal_items or seasonal_promotions:
            lines.extend(["", "Xu hướng theo giai đoạn:"])
            if seasonal_items:
                for item in seasonal_items:
                    lines.append(
                        "- {name}: nhu cầu x{multiplier}, nên chuẩn bị thêm {qty} đơn vị cho {period}.".format(
                            name=item["name"],
                            multiplier=item["demand_multiplier"],
                            qty=item["recommended_quantity"],
                            period=item["period_label"],
                        )
                    )
            if seasonal_promotions:
                for item in seasonal_promotions[:3]:
                    lines.append(
                        "- {name}: có thể đẩy bán nhẹ vì không thuộc nhóm nhu cầu chính của giai đoạn.".format(
                            name=item["name"],
                        )
                    )

        lines.extend(["", "Giảm giá/đẩy bán:"])
        if not promotion_items:
            lines.append("- Chưa có mặt hàng tồn chậm đủ điều kiện khuyến mãi.")
        else:
            for item in promotion_items:
                lines.append(
                    "- {name}: giảm {discount}% vì tồn {stock} và sell-through {rate}%.".format(
                        name=item["name"],
                        discount=item["suggested_discount_percent"],
                        stock=item["stock_on_hand"],
                        rate=item["sell_through_percent"],
                    )
                )

        lines.extend(
            [
                "",
                "Cơ sở phân tích: {products} sản phẩm, {calls} tool calls, {duration}ms.".format(
                    products=metrics["products_analyzed"],
                    calls=metrics["tool_calls"],
                    duration=metrics["duration_ms"],
                ),
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _risk_rank(level: str) -> int:
        return {"high": 0, "medium": 1, "low": 2}.get(level, 3)
