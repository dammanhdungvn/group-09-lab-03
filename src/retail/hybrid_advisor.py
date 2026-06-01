from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
from typing import Any

from dotenv import load_dotenv

from src.agent.agent import ReActAgent
from src.core.llm_provider import LLMProvider
from src.core.provider_factory import ProviderFactory, create_llm_provider
from src.retail.advisor import RetailStockAdvisor
from src.retail.models import AdvisorResult, ToolTrace
from src.retail.tools import RetailTools
from src.telemetry.logger import logger


class RetailAIError(RuntimeError):
    """Raised when the AI path cannot produce a grounded retail answer."""


class HybridRetailStockAdvisor:
    """Retail advisor with explicit base, strict LLM, and legacy hybrid modes."""

    def __init__(
        self,
        tools: RetailTools | None = None,
        deterministic_advisor: RetailStockAdvisor | None = None,
        provider_factory: ProviderFactory = create_llm_provider,
        llm: LLMProvider | None = None,
        mode: str | None = None,
        max_steps: int | None = None,
        ai_timeout_seconds: float | None = None,
    ):
        load_dotenv()
        self.tools = tools or RetailTools()
        self.deterministic_advisor = deterministic_advisor or RetailStockAdvisor(self.tools)
        self.provider_factory = provider_factory
        self._llm = llm
        self.mode = (mode or os.getenv("RETAIL_ADVISOR_MODE", "hybrid")).strip().lower()
        self.max_steps = max_steps if max_steps is not None else self._env_int("AI_MAX_STEPS", 8)
        self.ai_timeout_seconds = (
            ai_timeout_seconds
            if ai_timeout_seconds is not None
            else self._env_float("AI_TIMEOUT_SECONDS", 300.0)
        )

    def answer(
        self,
        question: str,
        category: str | None = None,
        period_id: str | None = None,
        analysis_mode: str | None = None,
    ) -> AdvisorResult:
        requested_mode = self._normalize_analysis_mode(analysis_mode)
        if requested_mode == "base" or self.mode in {"off", "rule", "rules", "deterministic"}:
            return self._answer_with_base(question, category=category, period_id=period_id)

        if requested_mode == "llm":
            return self._answer_with_llm_strict(question, category=category, period_id=period_id)

        return self._answer_with_hybrid(question, category=category, period_id=period_id)

    def _answer_with_base(
        self,
        question: str,
        category: str | None = None,
        period_id: str | None = None,
    ) -> AdvisorResult:
        result = self.deterministic_advisor.answer(question, category=category, period_id=period_id)
        return self._with_ai_metrics(
            result,
            analysis_mode="base",
            method_label="Base rules",
            rule_used=True,
            ai_enabled=False,
            ai_attempted=False,
            ai_used=False,
            fallback_used=False,
            fallback_reason=None,
            llm_steps=0,
            provider=None,
            model=None,
        )

    def _answer_with_hybrid(
        self,
        question: str,
        category: str | None = None,
        period_id: str | None = None,
    ) -> AdvisorResult:
        provider_name = os.getenv("DEFAULT_PROVIDER", "openai").strip().lower()
        configured_model = os.getenv("DEFAULT_MODEL", "").strip() or None
        agent: ReActAgent | None = None

        try:
            llm = self._get_llm()
            agent = ReActAgent(llm=llm, tools=self.tools.tool_specs(), max_steps=self.max_steps)
            prompt = self._build_prompt(question, category, period_id)
            answer = self._run_agent_with_timeout(agent, prompt)
            self._validate_ai_run(agent)

            structured = self.deterministic_advisor.answer(question, category=category, period_id=period_id)
            result = AdvisorResult(
                answer=answer,
                restock_items=structured.restock_items,
                promotion_items=structured.promotion_items,
                seasonal_items=structured.seasonal_items,
                metrics=structured.metrics,
                trace=self._trace_from_agent(agent),
            )
            logger.log_event(
                "RETAIL_AI_SUCCESS",
                {
                    "provider": llm.__class__.__name__,
                    "model": llm.model_name,
                    "llm_steps": len(agent.history),
                },
            )
            return self._with_ai_metrics(
                result,
                analysis_mode="hybrid",
                method_label="Hybrid LLM + base tables",
                rule_used=True,
                ai_attempted=True,
                ai_used=True,
                fallback_used=False,
                fallback_reason=None,
                llm_steps=len(agent.history),
                provider=llm.__class__.__name__,
                model=llm.model_name,
            )
        except Exception as exc:
            reason = f"{exc.__class__.__name__}: {exc}"
            logger.log_event(
                "RETAIL_AI_FALLBACK",
                {
                    "reason": reason,
                    "provider": provider_name,
                    "model": configured_model,
                    "llm_steps": len(agent.history) if agent else 0,
                },
            )
            fallback = self.deterministic_advisor.answer(question, category=category, period_id=period_id)
            return self._with_ai_metrics(
                fallback,
                analysis_mode="hybrid",
                method_label="Hybrid fallback to base",
                rule_used=True,
                ai_attempted=True,
                ai_used=False,
                fallback_used=True,
                fallback_reason=reason,
                llm_steps=len(agent.history) if agent else 0,
                provider=provider_name,
                model=configured_model,
            )

    def _answer_with_llm_strict(
        self,
        question: str,
        category: str | None = None,
        period_id: str | None = None,
    ) -> AdvisorResult:
        started = time.perf_counter()
        provider_name = os.getenv("DEFAULT_PROVIDER", "openai").strip().lower()
        configured_model = os.getenv("DEFAULT_MODEL", "").strip() or None
        agent: ReActAgent | None = None

        try:
            llm = self._get_llm()
            agent = ReActAgent(llm=llm, tools=self.tools.tool_specs(), max_steps=self.max_steps)
            prompt = self._build_prompt(question, category, period_id)
            answer = self._run_agent_with_timeout(agent, prompt)
            self._validate_ai_run(agent)
            trace = self._trace_from_agent(agent)
            extracted = self._extract_structured_items_from_trace(trace)
            duration_ms = int((time.perf_counter() - started) * 1000)
            metrics = self._llm_metrics(
                trace=trace,
                extracted=extracted,
                duration_ms=duration_ms,
                provider=llm.__class__.__name__,
                model=llm.model_name,
                error=None,
            )
            result = AdvisorResult(
                answer=answer,
                restock_items=extracted["restock_items"],
                promotion_items=extracted["promotion_items"],
                seasonal_items=extracted["seasonal_items"],
                metrics=metrics,
                trace=trace,
            )
            logger.log_event("RETAIL_AI_STRICT_SUCCESS", metrics)
            return result
        except Exception as exc:
            reason = f"{exc.__class__.__name__}: {exc}"
            trace = self._trace_from_agent(agent) if agent else []
            duration_ms = int((time.perf_counter() - started) * 1000)
            metrics = self._llm_metrics(
                trace=trace,
                extracted={"restock_items": [], "promotion_items": [], "seasonal_items": []},
                duration_ms=duration_ms,
                provider=provider_name,
                model=configured_model,
                error=reason,
            )
            logger.log_event("RETAIL_AI_STRICT_ERROR", metrics)
            return AdvisorResult(
                answer=f"LLM mode failed without fallback: {reason}",
                restock_items=[],
                promotion_items=[],
                seasonal_items=[],
                metrics=metrics,
                trace=trace,
            )

    def _get_llm(self) -> LLMProvider:
        if self._llm is None:
            self._llm = self.provider_factory()
        return self._llm

    def _build_prompt(self, question: str, category: str | None, period_id: str | None) -> str:
        category_text = category or "all categories"
        period_text = period_id or "none"
        return f"""
Bạn là AI agent tư vấn nhập hàng và khuyến mãi cho cửa hàng bán lẻ nhỏ.

Câu hỏi của quản lý:
{question}

Ngữ cảnh bộ lọc:
- category: {category_text}
- period_id: {period_text}

Mục tiêu:
- Kiểm tra tồn kho hiện tại bằng get_inventory.
- Dùng lịch sử bán 7/30 ngày, sell-through, stockout risk và slow-moving tools.
- Đề xuất mặt hàng nên nhập thêm, số lượng nên nhập, mặt hàng nên giảm giá/đẩy bán.
- Nếu có period_id, dùng get_seasonal_trends và recommend_seasonal_stock_plan để xét mùa vụ.

Cách làm khuyến nghị:
1. Với câu hỏi tổng quan, gọi get_inventory với category nếu có.
2. Gọi detect_slow_moving_items với category và days=30 để tìm hàng khuyến mãi.
3. Với sản phẩm có tồn kho thấp hoặc bán nhanh, gọi detect_stockout_risk và recommend_reorder_quantity.
4. Nếu có period_id, gọi recommend_seasonal_stock_plan.
5. Trả lời tiếng Việt ngắn gọn theo các nhóm: Nhập thêm, Giảm giá/đẩy bán, Mùa vụ nếu có, Cơ sở dữ liệu.

Không được tự bịa số liệu. Chỉ dùng số liệu từ Observation của tools.
""".strip()

    def _run_agent_with_timeout(self, agent: ReActAgent, prompt: str) -> str:
        if self.ai_timeout_seconds <= 0:
            return agent.run(prompt)

        result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

        def run_agent() -> None:
            try:
                result_queue.put(("answer", agent.run(prompt)))
            except Exception as exc:
                result_queue.put(("error", exc))

        thread = threading.Thread(target=run_agent, daemon=True)
        thread.start()
        thread.join(self.ai_timeout_seconds)

        if thread.is_alive():
            raise RetailAIError(f"AI timed out after {self.ai_timeout_seconds:g}s.")

        kind, value = result_queue.get()
        if kind == "error":
            raise value
        return str(value)

    @staticmethod
    def _validate_ai_run(agent: ReActAgent) -> None:
        if agent.last_status != "final_answer":
            raise RetailAIError(agent.last_error or agent.last_status or "AI did not finish with Final Answer.")
        if agent.had_tool_failure:
            raise RetailAIError(agent.last_error or "AI attempted an invalid retail tool call.")
        if not agent.history:
            raise RetailAIError("AI did not call any retail tools before answering.")

    @staticmethod
    def _trace_from_agent(agent: ReActAgent) -> list[ToolTrace]:
        trace = []
        for item in agent.history:
            content = str(item.get("thought_action", ""))
            trace.append(
                ToolTrace(
                    thought=str(item.get("thought") or HybridRetailStockAdvisor._extract_label(content, "Thought")),
                    action=str(item.get("action") or HybridRetailStockAdvisor._extract_label(content, "Action")),
                    observation=HybridRetailStockAdvisor._parse_observation(item.get("observation")),
                )
            )
        return trace

    @staticmethod
    def _extract_label(content: str, label: str) -> str:
        match = re.search(
            rf"{label}\s*:\s*(.*?)(?=\n\s*(?:Thought|Action|Observation|Final Answer)\s*:|\Z)",
            content,
            re.DOTALL,
        )
        if not match:
            return content.strip()
        return match.group(1).strip()

    @staticmethod
    def _parse_observation(raw_observation: Any) -> dict[str, Any]:
        if isinstance(raw_observation, dict):
            return raw_observation
        if raw_observation is None:
            return {}
        if isinstance(raw_observation, str):
            try:
                payload = json.loads(raw_observation)
            except json.JSONDecodeError:
                return {"raw": raw_observation}
            if isinstance(payload, dict):
                return payload
            return {"items": payload}
        return {"raw": raw_observation}

    @staticmethod
    def _extract_structured_items_from_trace(trace: list[ToolTrace]) -> dict[str, list[dict[str, Any]]]:
        risk_by_product: dict[str, dict[str, Any]] = {}
        reorder_by_product: dict[str, dict[str, Any]] = {}
        promotion_items: list[dict[str, Any]] = []
        seasonal_items: list[dict[str, Any]] = []

        for step in trace:
            observation = step.observation
            if step.action.startswith("detect_stockout_risk("):
                product_id = observation.get("product_id")
                if product_id:
                    risk_by_product[str(product_id)] = observation
            elif step.action.startswith("recommend_reorder_quantity("):
                product_id = observation.get("product_id")
                if product_id:
                    reorder_by_product[str(product_id)] = observation
            elif step.action.startswith("detect_slow_moving_items("):
                promotion_items.extend(observation.get("items", []))
            elif step.action.startswith("recommend_seasonal_stock_plan("):
                seasonal_items.extend(observation.get("items", []))
                promotion_items.extend(observation.get("promotion_candidates", []))

        restock_items = []
        for product_id, reorder in reorder_by_product.items():
            quantity = int(reorder.get("recommended_quantity") or 0)
            if quantity <= 0:
                continue
            restock_items.append({**risk_by_product.get(product_id, {}), **reorder})

        return {
            "restock_items": restock_items,
            "promotion_items": promotion_items,
            "seasonal_items": seasonal_items,
        }

    @staticmethod
    def _products_analyzed_from_trace(trace: list[ToolTrace]) -> int:
        for step in trace:
            if step.action.startswith("get_inventory("):
                observation = step.observation
                if "count" in observation:
                    return int(observation.get("count") or 0)
                if observation.get("product_id"):
                    return 1
        return 0

    @classmethod
    def _llm_metrics(
        cls,
        *,
        trace: list[ToolTrace],
        extracted: dict[str, list[dict[str, Any]]],
        duration_ms: int,
        provider: str | None,
        model: str | None,
        error: str | None,
    ) -> dict[str, Any]:
        return {
            "duration_ms": duration_ms,
            "tool_calls": len(trace),
            "products_analyzed": cls._products_analyzed_from_trace(trace),
            "restock_count": len(extracted["restock_items"]),
            "promotion_count": len(extracted["promotion_items"]),
            "seasonal_count": len(extracted["seasonal_items"]),
            "seasonal_promotion_count": 0,
            "analysis_mode": "llm",
            "method_label": "Strict LLM ReAct",
            "rule_used": False,
            "ai_enabled": True,
            "ai_attempted": True,
            "ai_used": error is None,
            "ai_provider": provider,
            "ai_model": model,
            "fallback_used": False,
            "fallback_reason": None,
            "ai_error": error,
            "llm_steps": len(trace),
        }

    @staticmethod
    def _with_ai_metrics(
        result: AdvisorResult,
        *,
        analysis_mode: str,
        method_label: str,
        rule_used: bool,
        ai_enabled: bool = True,
        ai_attempted: bool,
        ai_used: bool,
        fallback_used: bool,
        fallback_reason: str | None,
        llm_steps: int,
        provider: str | None,
        model: str | None,
    ) -> AdvisorResult:
        metrics = {
            **result.metrics,
            "analysis_mode": analysis_mode,
            "method_label": method_label,
            "rule_used": rule_used,
            "ai_enabled": ai_enabled,
            "ai_attempted": ai_attempted,
            "ai_used": ai_used,
            "ai_provider": provider,
            "ai_model": model,
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "ai_error": None,
            "llm_steps": llm_steps,
        }
        return AdvisorResult(
            answer=result.answer,
            restock_items=result.restock_items,
            promotion_items=result.promotion_items,
            seasonal_items=result.seasonal_items,
            metrics=metrics,
            trace=result.trace,
        )

    @staticmethod
    def _normalize_analysis_mode(analysis_mode: str | None) -> str:
        value = (analysis_mode or "").strip().lower()
        if value in {"base", "rule", "rules", "deterministic"}:
            return "base"
        if value in {"llm", "ai", "strict_llm", "react"}:
            return "llm"
        return "hybrid"

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        raw_value = os.getenv(name, "").strip()
        if not raw_value:
            return default
        try:
            return int(raw_value)
        except ValueError:
            logger.log_event("RETAIL_AI_CONFIG_WARNING", {"setting": name, "value": raw_value})
            return default

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        raw_value = os.getenv(name, "").strip()
        if not raw_value:
            return default
        try:
            return float(raw_value)
        except ValueError:
            logger.log_event("RETAIL_AI_CONFIG_WARNING", {"setting": name, "value": raw_value})
            return default
