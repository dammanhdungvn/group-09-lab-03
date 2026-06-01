from src.agent.agent import ReActAgent
from src.core.llm_provider import LLMProvider


class FakeProvider(LLMProvider):
    def __init__(self):
        super().__init__("fake-model")
        self.calls = 0

    def generate(self, prompt, system_prompt=None):
        self.calls += 1
        if self.calls == 1:
            return {
                "content": 'Thought: Need inventory.\nAction: get_inventory({"product_id": "P001"})',
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                "latency_ms": 1,
                "provider": "fake",
            }
        return {
            "content": "Final Answer: Coca Cola needs a reorder check.",
            "usage": {"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13},
            "latency_ms": 1,
            "provider": "fake",
        }

    def stream(self, prompt, system_prompt=None):
        yield "ok"


class EarlyAnswerProvider(LLMProvider):
    def __init__(self):
        super().__init__("early-answer-model")
        self.calls = 0

    def generate(self, prompt, system_prompt=None):
        self.calls += 1
        if self.calls == 1:
            return {
                "content": "Final Answer: I think P001 needs more stock.",
                "usage": {"prompt_tokens": 7, "completion_tokens": 4, "total_tokens": 11},
                "latency_ms": 1,
                "provider": "fake",
            }
        if self.calls == 2:
            return {
                "content": 'Thought: Need real inventory first.\nAction: get_inventory({"product_id": "P001"})',
                "usage": {"prompt_tokens": 9, "completion_tokens": 5, "total_tokens": 14},
                "latency_ms": 1,
                "provider": "fake",
            }
        return {
            "content": "Final Answer: P001 should be reviewed for reorder after checking stock.",
            "usage": {"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13},
            "latency_ms": 1,
            "provider": "fake",
        }

    def stream(self, prompt, system_prompt=None):
        yield "ok"


class CombinedStepProvider(LLMProvider):
    def __init__(self):
        super().__init__("combined-step-model")
        self.calls = 0

    def generate(self, prompt, system_prompt=None):
        self.calls += 1
        if self.calls == 1:
            return {
                "content": (
                    'Thought: Need inventory first.\n'
                    'Action: get_inventory({"product_id": "P001"})\n'
                    'Observation: {"product_id": "P001", "stock_on_hand": 24}\n'
                    "Final Answer: P001 should be reordered."
                ),
                "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
                "latency_ms": 1,
                "provider": "fake",
            }
        return {
            "content": "Final Answer: P001 should be reordered.",
            "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
            "latency_ms": 1,
            "provider": "fake",
        }

    def stream(self, prompt, system_prompt=None):
        yield "ok"


def test_react_agent_executes_tool_and_returns_final_answer():
    tools = [
        {
            "name": "get_inventory",
            "description": "Get inventory by product_id.",
            "parameters": {"product_id": "required string"},
            "func": lambda product_id: {"product_id": product_id, "stock_on_hand": 24},
        }
    ]
    agent = ReActAgent(FakeProvider(), tools=tools, max_steps=3)

    answer = agent.run("Should I reorder P001?")

    assert answer == "Coca Cola needs a reorder check."
    assert len(agent.history) == 1
    assert agent.history[0]["thought"] == "Need inventory."
    assert agent.history[0]["action"] == 'get_inventory({"product_id": "P001"})'
    assert "Observation:" in agent._format_history()
    assert "Args JSON schema" in agent.get_system_prompt()


def test_react_agent_retries_when_llm_answers_before_tool_use():
    tools = [
        {
            "name": "get_inventory",
            "description": "Get inventory by product_id.",
            "parameters": {"product_id": "required string"},
            "func": lambda product_id: {"product_id": product_id, "stock_on_hand": 24},
        }
    ]
    provider = EarlyAnswerProvider()
    agent = ReActAgent(provider, tools=tools, max_steps=4)

    answer = agent.run("Should I reorder P001?")

    assert answer == "P001 should be reviewed for reorder after checking stock."
    assert provider.calls == 3
    assert len(agent.history) == 1
    assert agent.last_status == "final_answer"


def test_react_agent_executes_action_when_model_combines_action_and_final_answer():
    tools = [
        {
            "name": "get_inventory",
            "description": "Get inventory by product_id.",
            "parameters": {"product_id": "required string"},
            "func": lambda product_id: {"product_id": product_id, "stock_on_hand": 24},
        }
    ]
    provider = CombinedStepProvider()
    agent = ReActAgent(provider, tools=tools, max_steps=3)

    answer = agent.run("Should I reorder P001?")

    assert answer == "P001 should be reordered."
    assert len(agent.history) == 1
    assert agent.history[0]["action"] == 'get_inventory({"product_id": "P001"})'
