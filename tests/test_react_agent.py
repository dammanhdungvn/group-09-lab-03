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


def test_react_agent_executes_tool_and_returns_final_answer():
    tools = [
        {
            "name": "get_inventory",
            "description": "Get inventory by product_id.",
            "func": lambda product_id: {"product_id": product_id, "stock_on_hand": 24},
        }
    ]
    agent = ReActAgent(FakeProvider(), tools=tools, max_steps=3)

    answer = agent.run("Should I reorder P001?")

    assert answer == "Coca Cola needs a reorder check."
    assert len(agent.history) == 1
