import time

from src.core.llm_provider import LLMProvider
from src.retail.hybrid_advisor import HybridRetailStockAdvisor


class ScriptedProvider(LLMProvider):
    def __init__(self, responses):
        super().__init__("scripted-model")
        self.responses = list(responses)
        self.prompts = []
        self.calls = 0

    def generate(self, prompt, system_prompt=None):
        self.prompts.append(prompt)
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return {
            "content": self.responses[index],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "latency_ms": 1,
            "provider": "scripted",
        }

    def stream(self, prompt, system_prompt=None):
        yield "ok"


class SlowProvider(LLMProvider):
    def __init__(self, delay_seconds):
        super().__init__("slow-model")
        self.delay_seconds = delay_seconds

    def generate(self, prompt, system_prompt=None):
        time.sleep(self.delay_seconds)
        return {
            "content": "Final Answer: too late",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "latency_ms": int(self.delay_seconds * 1000),
            "provider": "slow",
        }

    def stream(self, prompt, system_prompt=None):
        yield "ok"


def test_hybrid_advisor_returns_ai_answer_when_react_succeeds():
    provider = ScriptedProvider(
        [
            'Thought: Need current stock first.\nAction: get_inventory({"category": "beverage"})',
            "Final Answer: AI đề xuất nhập thêm các mặt hàng có rủi ro hết hàng và giảm giá hàng tồn chậm.",
        ]
    )
    advisor = HybridRetailStockAdvisor(llm=provider, max_steps=3)

    result = advisor.answer(
        "Tuần này tôi nên nhập thêm mặt hàng nào và giảm giá mặt hàng nào?",
        category="beverage",
    )

    assert result.answer.startswith("AI đề xuất")
    assert result.metrics["ai_attempted"] is True
    assert result.metrics["ai_used"] is True
    assert result.metrics["fallback_used"] is False
    assert result.metrics["llm_steps"] == 1
    assert result.restock_items
    assert "get_inventory" in result.trace[0].action
    assert result.trace[0].observation["category"] == "beverage"


def test_hybrid_advisor_falls_back_when_provider_is_not_configured():
    def broken_provider():
        raise RuntimeError("missing provider config")

    advisor = HybridRetailStockAdvisor(provider_factory=broken_provider, max_steps=3)

    result = advisor.answer("Tuần này tôi nên nhập thêm mặt hàng nào?")

    assert result.metrics["ai_used"] is False
    assert result.metrics["ai_attempted"] is True
    assert result.metrics["fallback_used"] is True
    assert "missing provider config" in result.metrics["fallback_reason"]
    assert result.restock_items


def test_hybrid_advisor_falls_back_on_parser_error():
    provider = ScriptedProvider(["Thought: Need stock.\nAction: get_inventory(product_id=P001)"])
    advisor = HybridRetailStockAdvisor(llm=provider, max_steps=3)

    result = advisor.answer("Tôi nên nhập thêm P001 không?")

    assert result.metrics["ai_used"] is False
    assert result.metrics["fallback_used"] is True
    assert "Parser error" in result.metrics["fallback_reason"] or "RetailAIError" in result.metrics["fallback_reason"]
    assert result.restock_items


def test_hybrid_advisor_falls_back_on_hallucinated_tool():
    provider = ScriptedProvider(
        [
            'Thought: Need a fake check.\nAction: check_supplier_magic({"product_id": "P001"})',
            "Final Answer: P001 looks fine.",
        ]
    )
    advisor = HybridRetailStockAdvisor(llm=provider, max_steps=3)

    result = advisor.answer("Tôi nên nhập thêm P001 không?")

    assert result.metrics["ai_used"] is False
    assert result.metrics["fallback_used"] is True
    assert result.restock_items


def test_hybrid_advisor_can_use_seasonal_tool_path():
    provider = ScriptedProvider(
        [
            'Thought: Need seasonal demand plan.\nAction: recommend_seasonal_stock_plan({"period_id": "tet_holiday"})',
            "Final Answer: Trước Tết nên ưu tiên các mặt hàng có hệ số mùa vụ cao.",
        ]
    )
    advisor = HybridRetailStockAdvisor(llm=provider, max_steps=3)

    result = advisor.answer(
        "Trước Tết tôi nên chuẩn bị thêm mặt hàng nào?",
        period_id="tet_holiday",
    )

    assert result.metrics["ai_used"] is True
    assert result.seasonal_items
    assert "recommend_seasonal_stock_plan" in result.trace[0].action
    assert "period_id: tet_holiday" in provider.prompts[0]


def test_hybrid_advisor_falls_back_when_ai_times_out():
    advisor = HybridRetailStockAdvisor(
        llm=SlowProvider(delay_seconds=0.2),
        max_steps=3,
        ai_timeout_seconds=0.01,
    )

    result = advisor.answer("Tuần này tôi nên nhập thêm mặt hàng nào?")

    assert result.metrics["ai_used"] is False
    assert result.metrics["fallback_used"] is True
    assert "timed out" in result.metrics["fallback_reason"]
    assert result.restock_items


def test_base_mode_uses_rules_without_llm():
    provider = ScriptedProvider(["Final Answer: should not be called"])
    advisor = HybridRetailStockAdvisor(llm=provider, max_steps=3)

    result = advisor.answer("Tuần này tôi nên nhập thêm mặt hàng nào?", analysis_mode="base")

    assert provider.calls == 0
    assert result.metrics["analysis_mode"] == "base"
    assert result.metrics["rule_used"] is True
    assert result.metrics["ai_attempted"] is False
    assert result.restock_items


def test_strict_llm_mode_uses_react_trace_without_base_fallback():
    provider = ScriptedProvider(
        [
            'Thought: Need stockout risk for a candidate.\nAction: detect_stockout_risk({"product_id": "P001", "days": 7})',
            'Thought: Risk is actionable, calculate reorder quantity.\nAction: recommend_reorder_quantity({"product_id": "P001", "days": 7})',
            'Thought: Need promotion candidates.\nAction: detect_slow_moving_items({"days": 30})',
            "Final Answer: LLM recommends reordering P001 and promoting slow-moving items.",
        ]
    )
    advisor = HybridRetailStockAdvisor(llm=provider, max_steps=5)

    result = advisor.answer("Tuần này tôi nên nhập thêm gì?", analysis_mode="llm")

    assert result.metrics["analysis_mode"] == "llm"
    assert result.metrics["rule_used"] is False
    assert result.metrics["ai_used"] is True
    assert result.metrics["fallback_used"] is False
    assert result.metrics["llm_steps"] == 3
    assert result.restock_items[0]["product_id"] == "P001"
    assert result.promotion_items


def test_strict_llm_mode_reports_error_without_fallback():
    def broken_provider():
        raise RuntimeError("missing provider config")

    advisor = HybridRetailStockAdvisor(provider_factory=broken_provider, max_steps=3)

    result = advisor.answer("Tuần này tôi nên nhập thêm gì?", analysis_mode="llm")

    assert result.metrics["analysis_mode"] == "llm"
    assert result.metrics["ai_attempted"] is True
    assert result.metrics["ai_used"] is False
    assert result.metrics["fallback_used"] is False
    assert result.metrics["ai_error"]
    assert not result.restock_items
